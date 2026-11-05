"""全书结构分析：逐章摘要 → 分卷 → 卷大纲。

``structured_v1`` 只做确定性切分与抽取，不建图谱，因此拿不到 Cognee 那套
AI 剧情规划能力。这个模块补上「读懂整本书」这一层：只读 ``novel.txt``，
分三步归纳出全书主线、卷次划分和每卷大纲。它只产出描述性结构，不改原文、
不写 episodes 表——分集与改编后续再以它为输入。

为什么必须分层：

1. 百万字原文放不进任何一次请求。用户的书 128 万字，远超上下文窗口。
2. 按字数硬切又会在剧情中间断开，「分卷」就退化成「第 40 万字」。

所以先按章压成摘要（L1），再让模型只在摘要上判卷（L2，一轮就能看完脉络），
最后逐卷展开大纲（L3）。每层输入都在可控 token 内。

为什么按章而不是按 ``chunk_source_text`` 的切块：

分卷的边界最终要落成 ``第 a–b 章``，而切块器会把相邻短章打包成一块
（``第1章 等 3 段``），还要靠解析标签反推章号，既脆弱又不可续跑。
章节检测器本来就是结构化导入用的那一套，章号稳定且与前端预览一致，
所以这里单独按章走，摘要结果用 ``story_analysis_item_cache`` 按章内容
哈希缓存——重跑时正文没变的章节不再花钱。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Sequence

from pydantic import BaseModel, Field

logger = logging.getLogger("novelvideo.story_structure")

#: 产物在 ``story_analysis_artifacts`` 中的类型。
STORY_STRUCTURE_ARTIFACT = "story_structure"
#: 逐章摘要的单项缓存类型。
CHAPTER_DIGEST_CACHE = "chapter_digest"
#: 契约版本。prompt 或摘要字段变化时递增，旧缓存自然失效。
STORY_STRUCTURE_VERSION = "story_structure_v1"

DEFAULT_BATCH_CHAPTERS = 12
DEFAULT_CONCURRENCY = 3
#: 单章送进摘要请求的上限。网文单章多在 2000–3500 字，留余量给偶发长章。
MAX_CHARS_PER_CHAPTER = 4000
#: 分卷请求的输入上限；超出时按比例压缩每条摘要，而不是丢掉后半本。
MAX_PLAN_INPUT_CHARS = 120_000


# =============================================================================
# 数据结构
# =============================================================================


class ChapterDigest(BaseModel):
    """一章的压缩表示。"""

    number: int = Field(description="章节号，与输入保持一致")
    title: str = Field(default="", description="章节标题")
    summary: str = Field(default="", description="本章发生了什么，80–120 字")
    key_events: list[str] = Field(default_factory=list, description="2–4 条关键事件")
    characters: list[str] = Field(default_factory=list, description="本章出场的具名角色")


class DigestBatch(BaseModel):
    chapters: list[ChapterDigest] = Field(default_factory=list)


class VolumeDraft(BaseModel):
    """分卷结果中的一卷。"""

    index: int = Field(description="卷序号，从 1 连续编号")
    title: str = Field(default="", description="卷名，4–10 字")
    chapter_start: int
    chapter_end: int
    stage: str = Field(default="", description="本卷在全书中的阶段定位")
    core_conflict: str = Field(default="", description="本卷核心冲突")
    key_events: list[str] = Field(default_factory=list)
    cliffhanger: str = Field(default="", description="卷末钩子")


class VolumePlan(BaseModel):
    """分卷阶段的整体输出。"""

    logline: str = Field(default="", description="一句话说清全书故事，不超过 40 字")
    mainline: str = Field(default="", description="主线梗概，100–200 字")
    volumes: list[VolumeDraft] = Field(default_factory=list)


class VolumeOutline(BaseModel):
    """单卷大纲。"""

    outline: str = Field(default="", description="本卷起承转合，300–500 字")
    turning_points: list[str] = Field(default_factory=list)
    foreshadowing: list[str] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)


class Volume(VolumeDraft):
    """最终产物中的一卷：分卷信息 + 展开后的大纲。"""

    outline: str = ""
    turning_points: list[str] = Field(default_factory=list)
    foreshadowing: list[str] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)


class StoryStructure(BaseModel):
    """全书结构产物。"""

    version: str = STORY_STRUCTURE_VERSION
    generated_at: str = ""
    total_chapters: int = 0
    total_chars: int = 0
    logline: str = ""
    mainline: str = ""
    volumes: list[Volume] = Field(default_factory=list)


# =============================================================================
# 提示词
# =============================================================================


_DIGEST_SYSTEM_PROMPT = """你在为一部中文长篇小说做结构分析，只做摘要，不做改编。

对输入的每一章输出：
- number：原样返回输入的章号，不得改动
- title：章节标题
- summary：本章发生了什么，80–120 字。只写事实（谁、在哪、做了什么、结果如何），
  不写"引人入胜""情节紧凑"这类评价
- key_events：2–4 条动词短语，如"主角在演武场击败外门弟子"
- characters：本章出场且**有名有姓**的角色，不要写"路人""众人"

纪律：
1. 只依据给定原文，不得补充原文没有的剧情、人物或设定
2. 信息不足时只写清"发生了什么"，不要推测
3. 每一章都必须有一条输出，即使内容很短"""


_PLAN_SYSTEM_PROMPT = """你在为一部中文长篇小说划分卷次，并提炼全书主线。

划分依据，按优先级：
1. **舞台跃迁**：主角所处的环境、势力、地域发生不可逆变化时开新卷
   （如"宗门外门 → 内门""地方 → 王城"）
2. **核心冲突更替**：主要对手或核心目标被替换时开新卷
3. 不要按章节数量机械均分，剧情节奏比平均更重要

输出：
- logline：一句话说清全书故事，不超过 40 字
- mainline：主线梗概 100–200 字，说明主角成长路径与核心矛盾
- volumes：每卷给出 index（从 1 连续编号）、title（4–10 字）、chapter_start、
  chapter_end、stage、core_conflict、key_events（2–5 条）、cliffhanger

纪律：
1. 各卷必须**连续覆盖**全书章节，不得留空档、不得重叠
2. 每卷 15–60 章为宜；超出说明分卷粒度不对
3. 只能使用给定摘要里出现的信息，不得虚构剧情、人物或设定"""


_OUTLINE_SYSTEM_PROMPT = """你在为一卷小说写大纲，供后续改编使用。

输入包含全书主线与本卷的逐章摘要。输出：
- outline：本卷大纲 300–500 字，写清起（如何进入）、承（冲突如何升级）、
  转（转折点）、合（本卷收束到什么状态）
- turning_points：本卷转折点，2–5 条
- foreshadowing：本卷埋下或回收的伏笔，1–5 条；没有就给空数组
- characters：本卷主要角色

纪律：只依据给定摘要，不得虚构摘要中没有的事件或人物。"""


# =============================================================================
# 模型调用
# =============================================================================


def _build_agent(output_type: type[BaseModel], system_prompt: str):
    """构造走网关的 PydanticAI Agent。

    与 ``episode_planner`` 使用同一能力档案和结构化输出设置，保证 CE 自定义
    网关下解析出的模型与既有 Agent 一致。
    """
    from pydantic_ai import Agent

    from novelvideo.brainclaw_contract import BrainClawProfile
    from novelvideo.config import (
        get_newapi_structured_output_model_settings,
        get_pydantic_model,
    )

    return Agent(
        get_pydantic_model(brainclaw_profile=BrainClawProfile.EPISODE_STORY_PLANNING),
        system_prompt=system_prompt,
        output_type=output_type,
        model_settings=get_newapi_structured_output_model_settings(),
        output_retries=3,
        name="全书结构分析",
    )


def _chunk(items: Sequence, size: int) -> list[list]:
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def _clip(text: str, limit: int) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n……（本章后文略）"


def _digest_cache_key(chapter: dict) -> str:
    """按章内容哈希。正文没变的章节重跑时直接命中缓存。"""
    payload = (
        f"{STORY_STRUCTURE_VERSION}\x00{chapter.get('title', '')}\x00"
        f"{chapter.get('content', '')}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:40]


# =============================================================================
# L1 逐章摘要
# =============================================================================


def _digest_prompt(batch: Sequence[dict]) -> str:
    parts = [
        "下面是小说中的若干章原文，请逐章摘要。",
        "共 %d 章，章号依次为：%s" % (len(batch), "、".join(str(ch["number"]) for ch in batch)),
        "",
    ]
    for chapter in batch:
        parts.append(f"=== 第 {chapter['number']} 章 {chapter.get('title', '')} ===")
        parts.append(_clip(chapter.get("content", ""), MAX_CHARS_PER_CHAPTER))
        parts.append("")
    return "\n".join(parts)


def _coerce_batch(
    output: DigestBatch, expected: Sequence[int]
) -> list[ChapterDigest]:
    """把模型返回的章号对齐到输入章号。

    模型偶尔写错章号或写成批内序号。数量能对上时按位置回填；对不上就只保留
    章号确实匹配的那些，宁缺勿错——错章的摘要会污染全书的卷划分。
    """
    produced = [d for d in output.chapters if d.number in expected]
    if len(produced) == len(expected):
        return produced
    if len(output.chapters) == len(expected):
        for number, digest in zip(expected, output.chapters):
            digest.number = number
        return list(output.chapters)
    return produced


async def _digest_chapters(
    store: Any,
    chapters: Sequence[dict],
    *,
    batch_size: int,
    concurrency: int,
    on_progress: Optional[Callable[[float, str], None]],
    on_log: Optional[Callable[[str], None]],
) -> list[ChapterDigest]:
    keys = [_digest_cache_key(chapter) for chapter in chapters]
    cached_raw = await store.get_analysis_item_cache(
        CHAPTER_DIGEST_CACHE, [k for k in keys if k]
    )

    digests: dict[int, ChapterDigest] = {}
    pending: list[tuple[dict, str]] = []
    for chapter, key in zip(chapters, keys):
        blob = cached_raw.get(key)
        if blob:
            try:
                digests[int(chapter["number"])] = ChapterDigest.model_validate(
                    json.loads(blob)
                )
                continue
            except Exception:
                # 缓存条目坏了就当没命中，重新算一次即可。
                pass
        pending.append((chapter, key))

    if cached_raw:
        _log(on_log, f"复用已缓存摘要 {len(digests)} 章")

    if pending:
        agent = _build_agent(DigestBatch, _DIGEST_SYSTEM_PROMPT)
        semaphore = asyncio.Semaphore(max(1, concurrency))
        batches = _chunk(pending, max(1, batch_size))
        done = 0
        total = len(pending)
        new_cache: dict[str, str] = {}

        async def run_batch(batch: Sequence[tuple[dict, str]]) -> None:
            nonlocal done
            expected = [int(item[0]["number"]) for item in batch]
            async with semaphore:
                result = await agent.run(_digest_prompt([item[0] for item in batch]))
            for digest in _coerce_batch(result.output, expected):
                digests[digest.number] = digest
                # 只在章号确实属于本批时缓存，避免把错位的摘要写进别人的键。
                for chapter, key in batch:
                    if int(chapter["number"]) == digest.number:
                        new_cache[key] = json.dumps(
                            digest.model_dump(), ensure_ascii=False
                        )
                        break
            if new_cache:
                # 每批落盘：中途失败重跑时，已完成的章节不必再付一次钱。
                await store.save_analysis_item_cache(CHAPTER_DIGEST_CACHE, dict(new_cache))
            done += len(batch)
            if on_progress:
                on_progress(0.08 + 0.62 * (done / total), f"已摘要 {done}/{total} 章")

        results = await asyncio.gather(
            *(run_batch(batch) for batch in batches), return_exceptions=True
        )
        failures = [r for r in results if isinstance(r, BaseException)]
        if failures:
            _log(on_log, f"{len(failures)} 批摘要失败")
            if len(failures) == len(batches):
                raise RuntimeError(f"章节摘要全部失败：{failures[0]}") from failures[0]

    missing = [int(ch["number"]) for ch in chapters if int(ch["number"]) not in digests]
    if missing:
        preview = "、".join(str(n) for n in missing[:10])
        tail = "…" if len(missing) > 10 else ""
        raise RuntimeError(f"以下章节未能生成摘要：{preview}{tail}")

    return [digests[int(ch["number"])] for ch in chapters]


# =============================================================================
# L2 分卷
# =============================================================================


def _plan_prompt(digests: Sequence[ChapterDigest]) -> str:
    lines = [f"全书共 {len(digests)} 章，逐章摘要如下：", ""]
    total = sum(len(d.summary) + 24 for d in digests)
    per_chapter = 240
    if total > MAX_PLAN_INPUT_CHARS:
        # 压缩摘要长度而不是丢章，否则后半本会被判卷时看不见。
        per_chapter = max(48, int(MAX_PLAN_INPUT_CHARS / max(1, len(digests))) - 24)
    for digest in digests:
        events = "；".join(digest.key_events[:3])
        line = f"{digest.number}. {digest.title}｜{_clip(digest.summary, per_chapter)}"
        lines.append(line + (f"｜{events}" if events else ""))
    return "\n".join(lines)


def _normalize_volumes(
    drafts: Sequence[VolumeDraft], chapters: Sequence[dict]
) -> list[VolumeDraft]:
    """把模型给出的卷边界修成连续、完整、单调的一组区间。

    模型的边界常有一两章偏差或相邻卷重叠。与其带着瑕疵进产物，不如按起点
    排序后重排：保留每卷起点与文字描述，终点顺延到下一卷起点前，最后一卷
    收在全书末章。这样产出的永远是一份可用的连续划分。
    """
    if not drafts:
        return []
    numbers = [int(ch["number"]) for ch in chapters]
    first, last = numbers[0], numbers[-1]

    ordered = sorted(drafts, key=lambda d: (d.chapter_start, d.index))
    fixed: list[VolumeDraft] = []
    cursor = first
    for position, draft in enumerate(ordered, start=1):
        start = min(max(max(draft.chapter_start, first), cursor), last)
        fixed.append(
            VolumeDraft(
                index=position,
                title=draft.title or f"第{position}卷",
                chapter_start=start,
                chapter_end=start,
                stage=draft.stage,
                core_conflict=draft.core_conflict,
                key_events=list(draft.key_events),
                cliffhanger=draft.cliffhanger,
            )
        )
        cursor = start + 1
    for i, volume in enumerate(fixed):
        if i + 1 < len(fixed):
            volume.chapter_end = max(volume.chapter_start, fixed[i + 1].chapter_start - 1)
        else:
            volume.chapter_end = last
    return fixed


# =============================================================================
# L3 卷大纲
# =============================================================================


def _outline_prompt(
    volume: VolumeDraft, mainline: str, digests: Sequence[ChapterDigest]
) -> str:
    lines = [
        f"全书主线：{mainline}",
        "",
        f"本卷：第 {volume.index} 卷《{volume.title}》"
        f"（第 {volume.chapter_start}–{volume.chapter_end} 章）",
        f"本卷阶段：{volume.stage}",
        f"本卷核心冲突：{volume.core_conflict}",
        "",
        "本卷逐章摘要：",
    ]
    lines.extend(f"{d.number}. {d.summary}" for d in digests)
    return "\n".join(lines)


async def _outline_volumes(
    volumes: Sequence[VolumeDraft],
    digests: Sequence[ChapterDigest],
    *,
    mainline: str,
    concurrency: int,
    on_progress: Optional[Callable[[float, str], None]],
    on_log: Optional[Callable[[str], None]],
) -> list[Volume]:
    by_number = {d.number: d for d in digests}
    agent = _build_agent(VolumeOutline, _OUTLINE_SYSTEM_PROMPT)
    semaphore = asyncio.Semaphore(max(1, concurrency))
    done = 0
    total = len(volumes)

    async def run_one(volume: VolumeDraft) -> Volume:
        nonlocal done
        chapter_digests = [
            by_number[n]
            for n in range(volume.chapter_start, volume.chapter_end + 1)
            if n in by_number
        ]
        outline = VolumeOutline()
        if chapter_digests:
            try:
                async with semaphore:
                    result = await agent.run(
                        _outline_prompt(volume, mainline, chapter_digests)
                    )
                outline = result.output
            except Exception as exc:
                # 单卷大纲失败不该让整次分析作废：其余卷仍然可用，
                # 缺的那卷在产物里是空 outline，重跑时可单独补。
                _log(on_log, f"第 {volume.index} 卷大纲生成失败：{exc}")
        done += 1
        if on_progress:
            on_progress(0.84 + 0.14 * (done / total), f"已展开 {done}/{total} 卷大纲")
        return Volume(
            **volume.model_dump(),
            outline=outline.outline,
            turning_points=list(outline.turning_points),
            foreshadowing=list(outline.foreshadowing),
            characters=list(outline.characters),
        )

    return list(await asyncio.gather(*(run_one(v) for v in volumes)))


# =============================================================================
# 读取
# =============================================================================


def load_story_structure(blob: str | None) -> StoryStructure | None:
    """解析已存产物；缺失或损坏时返回 None。"""
    if not blob:
        return None
    try:
        return StoryStructure.model_validate(json.loads(blob))
    except Exception:
        logger.warning("stored story structure is unreadable", exc_info=True)
        return None


# =============================================================================
# 入口
# =============================================================================


def _log(on_log: Optional[Callable[[str], None]], message: str) -> None:
    logger.info("story structure: %s", message)
    if on_log:
        on_log(message)


async def build_story_structure(
    store: Any,
    *,
    on_progress: Optional[Callable[[float, str], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    batch_size: int = DEFAULT_BATCH_CHAPTERS,
    concurrency: int = DEFAULT_CONCURRENCY,
    reuse: bool = True,
) -> StoryStructure:
    """对整本书做分层结构分析并落库。

    Args:
        store: SQLiteStore（或暴露同样 project_dir / 缓存 / 产物接口的对象）。
        on_progress: ``(进度 0–1, 阶段说明)``。
        on_log: 纯日志回调。
        batch_size: 每批摘要的章节数。
        concurrency: 并发请求数。
        reuse: 命中同源产物时直接返回，不重新分析。
    """
    from novelvideo.api.chapter_preview import build_chapter_preview
    from novelvideo.novel_source import require_imported_novel
    from novelvideo.project_config import load_project_config_file_from_state_dir
    from novelvideo.story_analysis import source_sha256
    from novelvideo.structured_ingest import (
        STRUCTURED_ANALYSIS_VERSION,
        STRUCTURED_SCHEMA_VERSION,
    )

    def report(progress: float, task: str) -> None:
        if on_progress:
            on_progress(progress, task)

    novel_text = require_imported_novel(store.project_dir)
    template = str(
        load_project_config_file_from_state_dir(store.state_dir).get("spine_template")
        or "drama"
    ).strip()

    run = await store.get_reusable_analysis_run(
        source_sha256=source_sha256(novel_text),
        schema_version=STRUCTURED_SCHEMA_VERSION,
        pipeline_version=STRUCTURED_ANALYSIS_VERSION,
        spine_template=template,
    )
    run_id = str(run["run_id"]) if run else ""
    if run_id and reuse:
        existing = load_story_structure(
            await store.get_analysis_artifact(run_id, STORY_STRUCTURE_ARTIFACT)
        )
        if existing and existing.volumes:
            _log(on_log, "已有同源分析产物，直接复用")
            report(1.0, "复用已有全书分析")
            return existing

    report(0.03, "切分章节…")
    preview = build_chapter_preview(novel_text)
    chapters = list(preview.get("chapters") or [])
    if not chapters:
        raise RuntimeError("未识别到章节，无法做结构分析")

    total_chars = sum(int(ch.get("word_count") or 0) for ch in chapters)
    _log(on_log, f"共 {len(chapters)} 章，约 {total_chars:,} 字")

    digests = await _digest_chapters(
        store,
        chapters,
        batch_size=batch_size,
        concurrency=concurrency,
        on_progress=on_progress,
        on_log=on_log,
    )

    report(0.72, "按剧情阶段分卷…")
    plan_agent = _build_agent(VolumePlan, _PLAN_SYSTEM_PROMPT)
    plan = (await plan_agent.run(_plan_prompt(digests))).output
    volumes = _normalize_volumes(plan.volumes, chapters)
    if not volumes:
        _log(on_log, "模型未给出有效分卷，退化为单卷")
        volumes = [
            VolumeDraft(
                index=1,
                title="全书",
                chapter_start=int(chapters[0]["number"]),
                chapter_end=int(chapters[-1]["number"]),
                stage="全书",
            )
        ]
    _log(on_log, f"划分出 {len(volumes)} 卷")

    outlined = await _outline_volumes(
        volumes,
        digests,
        mainline=plan.mainline,
        concurrency=concurrency,
        on_progress=on_progress,
        on_log=on_log,
    )

    structure = StoryStructure(
        version=STORY_STRUCTURE_VERSION,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        total_chapters=len(chapters),
        total_chars=total_chars,
        logline=plan.logline,
        mainline=plan.mainline,
        volumes=outlined,
    )
    if run_id:
        await store.save_analysis_artifact(
            run_id,
            STORY_STRUCTURE_ARTIFACT,
            json.dumps(structure.model_dump(), ensure_ascii=False),
        )
    report(1.0, f"完成：{len(outlined)} 卷")
    return structure
