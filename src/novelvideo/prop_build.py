"""全书道具构建：把「手动新建道具」升级为一次 AI 批量生成。

虾塘（资产页）里角色和场景早就有「AI 生成」入口，道具却只能一个一个手工建。
根因不在前端按钮，而在后端：``build_props_structured`` 一直是个占位实现，只
回报「道具将在分集规划时按需生成」。分集规划那条路要等项目先有剧集和剧本，
用户在资产页根本走不到。

这个模块补上的就是「从原文直接生成道具目录」这一层，并且刻意复用既有管线，
不另起一套：

- 切块：``story_analysis.chunk_source_text``，与角色/场景抽取同一套章节/场次
  感知切块，保证章节边界和 ``source_start`` 语义一致；
- 模型：``BrainClawProfile.EPISODE_PROP_PLANNING`` + 结构化输出设置，与分集
  道具规划用的是同一个模型档案，CE 自定义网关注册的别名不用再改一遍；
- 缓存：``story_analysis_item_cache`` 按「块内容 + 上下文指纹」哈希，重跑时正文
  和角色表都没变的块直接命中，不再付费；
- 落库：``SQLiteStore.add_prop``，与手工新建写的是同一张 props 表；
- 参考图：写好的 ``visual_prompt``/``scale`` 直接被
  ``generate_prop_reference`` 消费，前端点「生成参考图」即可出三视图。

为什么这里要额外喂上下文（这是与分集规划最大的差别）：

分集规划每次只看一个场景块，天然与上下文一致。全书扫描一次看几千字，模型
很容易按「一般古装剧」的想象造一把剑，跟项目里已经定稿的赛博场景、儿童角色
对不上。所以每次请求都带上项目视觉风格、已有角色表（含性别/年龄段，用于换算
尺度）、已有场景（世界观锚点）和已入库道具（避免重复），并在提示词里把
「世界观一致」「owner 只能取自已确认角色」「尺度必须给量化锚点」写成硬性要求。

失败语义（用户明确要求「妥善处理生成失败或素材缺失」）：

- 单块失败只记日志、继续跑，其余块的产出照常入库；全部失败才抛错，任务状态
  会显示为失败而不是「成功但 0 个」；
- 模型编出来的名字如果在原文里找不到，直接丢弃（不落库、不占位）；
- 一个都没抽到时返回明确的 ``message``，前端提示「可手动新增」，不是静默 0；
- 已存在的道具不覆盖：只补空字段（例如之前自动写入的占位 visual_prompt），
  用户改过的内容一律不动。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any, Callable, Optional, Sequence

from pydantic import BaseModel, Field

logger = logging.getLogger("novelvideo.prop_build")

#: ``story_analysis_item_cache`` 中单块结果的缓存类型。
PROP_REQUIREMENTS_CACHE = "prop_requirements"
#: 契约版本。提示词或输出字段变化时递增，旧缓存自然失效。
PROP_BUILD_VERSION = "prop_build_v1"

#: 抽不到道具时的用户可见说明（不是异常）。
PROP_BUILD_EMPTY_MESSAGE = "未从原文识别到需要跨镜头追踪的道具，可手动新增，或先规划分集后再按集补充"

#: 单次请求送进去的原文上限。留足提示词与上下文的余量。
DEFAULT_MAX_CALL_CHARS = 12_000
DEFAULT_CONCURRENCY = 3
#: 一次构建最多落多少个新道具。再多就不是「重要道具」而是背景清单了。
MAX_PROP_CANDIDATES = 80
MAX_NAME_CHARS = 24
MAX_CONTEXT_CHARACTERS = 40
MAX_CONTEXT_SCENES = 30
MAX_CONTEXT_PROPS = 60
#: evidence 片段长度上限，只用来校验名字确实出自原文。
MAX_EVIDENCE_CHARS = 120

PROP_TYPES = ("weapon", "accessory", "artifact", "document", "furniture", "object")


# =============================================================================
# 数据结构
# =============================================================================


class PropCandidate(BaseModel):
    """模型对单个道具的判断。"""

    name: str = Field(description="道具名，必须逐字复制自原文")
    aliases: list[str] = Field(default_factory=list, description="原文中的其他叫法")
    prop_type: str = Field(default="object", description="weapon/accessory/artifact/document/furniture/object")
    owner: str = Field(default="", description="所属角色，必须逐字取自已确认角色表；不确定留空")
    description: str = Field(default="", description="剧情用途，一句话")
    visual_prompt: str = Field(default="", description="可画的外观：形状/材质/颜色/纹样/磨损，80 字内")
    scale: str = Field(default="", description="可比较的尺寸锚点，如「全长约1.1m，约到成年男性胸口」")
    evidence: str = Field(default="", description="原文中支持该道具的连续片段")


class PropCandidateList(BaseModel):
    """单次请求的输出。"""

    props: list[PropCandidate] = Field(default_factory=list)


# =============================================================================
# 提示词
# =============================================================================


PROP_BUILD_SYSTEM_PROMPT = """# 你是长篇小说/剧本的道具资产规划师

输入是同一部作品的若干连续片段，外加这个项目已有的角色、场景、已入库道具和
视觉风格。任务：找出需要作为「同一个物体」跨镜头持续追踪的道具，并写出可画的
视觉设定——这些设定会直接用于生成道具三视图参考图。

## 什么算道具（判定标准与分集道具规划一致）
一个物体值得入册，当且仅当：
- 它是独立的、可移动的物理实体
- 它被角色拿取/递交/操作，或在多个片段中反复出现
- 后续镜头需要画出「同一个东西」来保持视觉连续性

## 什么不是道具
- 场景固定设施：门、窗、墙、灯、招牌、巨幕、大屏、门锁、挂钟
- 环境陈设：桌子、椅子、床、柜子、栏杆——除非被角色明确拿起或长时间操作
- 屏幕显示内容：字幕、LOGO、弹窗、广告文案
- 特效/虚拟元素：光效、粒子、透明的手
- 一次性食品与消耗品：易拉罐、面碗、筷子
- 只被提到一次、之后再不出现的背景点缀

## 与既有资产保持一致（硬性要求，违反即作废）
1. **世界观**：道具的年代、技术层级、材质与工艺必须与「已有角色」「已有场景」
   和项目视觉风格相容。不要引入设定里不存在的技术或器物。
2. **归属**：owner 只能从「已有角色」里逐字选择；角色表里没有就留空，禁止编造人名。
3. **命名**：name 必须逐字来自原文，不要改写、泛化或同义替换。原文写「青铜虎符」，
   就不要写「虎符」或「兵符」。
4. **尺度**：scale 必须给出可比较的量化锚点，参照人的身体部位或常见物体，例如
   「全长约1.1m，约到成年男性胸口」「约成人手掌大小，18cm」「高约30cm，单手可握」。
   禁止「很大」「很小」「巨大」这类无法量化的描述；尺度要与归属角色的年龄段相称。
5. **风格**：visual_prompt 使用与场景描述相同的风格语言（题材、时代、质感、色调），
   80 字以内，只写外观（形状/材质/颜色/纹样/磨损），不写镜头、人物、动作、情绪、
   文字内容。

## 输出规则
- props 必须是对象数组，每项含 name / aliases / prop_type / owner / description /
  visual_prompt / scale / evidence
- prop_type 只能是 weapon / accessory / artifact / document / furniture / object
- evidence 放原文中 10–30 字的连续片段，逐字复制，用于校验该道具确实出现
- 同一物体只输出一次；「已入库道具」里有的不要再输出
- 本批没有符合条件的道具就返回空数组，宁可少也不要凑数
"""


def _build_agent(output_type: type[BaseModel] = PropCandidateList):
    """构造走网关的 PydanticAI Agent。

    能力档案与 ``AssetCompiler`` 的分集道具规划保持一致，CE 自定义网关下解析
    到的模型别名因此不需要额外配置。
    """
    from pydantic_ai import Agent

    from novelvideo.brainclaw_contract import BrainClawProfile
    from novelvideo.config import (
        get_newapi_structured_output_model_settings,
        get_pydantic_model,
    )

    return Agent(
        get_pydantic_model(brainclaw_profile=BrainClawProfile.EPISODE_PROP_PLANNING),
        system_prompt=PROP_BUILD_SYSTEM_PROMPT,
        output_type=output_type,
        model_settings=get_newapi_structured_output_model_settings(),
        output_retries=2,
        name="道具构建",
    )


# =============================================================================
# 上下文
# =============================================================================


class _ProjectContext:
    """一次性读好的项目上下文，供每个请求复用。"""

    def __init__(
        self,
        *,
        style: str,
        characters: Sequence[Any],
        scenes: Sequence[Any],
        props: Sequence[Any],
    ) -> None:
        self.style = style
        self.characters = list(characters)
        self.scenes = list(scenes)
        self.props = list(props)
        self.roster = {
            str(getattr(item, "name", "") or "").strip()
            for item in self.characters
            if str(getattr(item, "name", "") or "").strip()
        }
        # 别名也认，模型有时照着原文写绰号而不是正名。
        self.roster_aliases = {
            str(alias or "").strip()
            for item in self.characters
            for alias in (getattr(item, "aliases", None) or [])
            if str(alias or "").strip()
        }

    @property
    def fingerprint(self) -> str:
        """上下文指纹：风格或角色表变了，块缓存就该失效。"""
        payload = json.dumps(
            {
                "version": PROP_BUILD_VERSION,
                "style": self.style,
                "characters": sorted(self.roster | self.roster_aliases),
                "scenes": sorted(
                    str(getattr(item, "name", "") or "") for item in self.scenes
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def prompt_block(self) -> str:
        lines: list[str] = ["## 项目视觉风格", self.style.strip() or "（项目未指定，按原文题材判断）", ""]

        lines.append("## 已有角色（owner 只能从这里选）")
        if self.characters:
            for character in self.characters[:MAX_CONTEXT_CHARACTERS]:
                name = str(getattr(character, "name", "") or "").strip()
                if not name:
                    continue
                bits = [name]
                gender = str(getattr(character, "gender", "") or "").strip()
                age = str(getattr(character, "age_group", "") or "").strip()
                if gender:
                    bits.append(gender)
                if age:
                    bits.append(age)
                if getattr(character, "is_main", False):
                    bits.append("主角")
                lines.append("- " + "｜".join(bits))
        else:
            lines.append("（暂无角色，owner 一律留空）")

        lines.append("")
        lines.append("## 已有场景（世界观锚点）")
        if self.scenes:
            for scene in self.scenes[:MAX_CONTEXT_SCENES]:
                name = str(getattr(scene, "name", "") or "").strip()
                if not name:
                    continue
                scene_type = str(getattr(scene, "scene_type", "") or "").strip()
                hint = str(
                    getattr(scene, "environment_prompt", "")
                    or getattr(scene, "description", "")
                    or ""
                ).strip()
                suffix = f"｜{scene_type}" if scene_type else ""
                if hint:
                    suffix += f"｜{hint[:60]}"
                lines.append(f"- {name}{suffix}")
        else:
            lines.append("（暂无场景，按原文自行判断年代与质感）")

        lines.append("")
        lines.append("## 已入库道具（不要重复输出）")
        if self.props:
            for prop in self.props[:MAX_CONTEXT_PROPS]:
                name = str(getattr(prop, "name", "") or "").strip()
                if not name:
                    continue
                aliases = [
                    str(alias or "").strip()
                    for alias in (getattr(prop, "aliases", None) or [])
                    if str(alias or "").strip()
                ]
                lines.append(
                    f"- {name}（别名：{'、'.join(aliases)}）" if aliases else f"- {name}"
                )
        else:
            lines.append("（暂无）")
        return "\n".join(lines)


async def _load_context(store: Any) -> _ProjectContext:
    from novelvideo.project_config import load_project_config_file_from_state_dir

    config = load_project_config_file_from_state_dir(store.state_dir)
    style = str(config.get("visual_style") or config.get("project_style") or "").strip()

    characters = await _maybe_await(store.list_characters())
    scenes = await _maybe_await(store.list_scenes())
    props = await _maybe_await(store.list_props())
    return _ProjectContext(
        style=style, characters=characters or [], scenes=scenes or [], props=props or []
    )


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


# =============================================================================
# 切块
# =============================================================================


class _Batch:
    """一次请求覆盖的若干原文块。"""

    def __init__(self, chunks: Sequence[Any]) -> None:
        self.chunks = list(chunks)
        self.text = "\n\n".join(
            f"=== 片段 {index + 1}｜{getattr(chunk, 'section_label', '') or '未命名'} ===\n"
            f"{getattr(chunk, 'text', '')}"
            for index, chunk in enumerate(self.chunks)
        )

    def cache_key(self, fingerprint: str) -> str:
        payload = f"{PROP_BUILD_VERSION}\x00{fingerprint}\x00{self.text}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:40]


def _chunk_batches(
    chunks: Sequence[Any], *, max_chars: int
) -> list[_Batch]:
    """把块打包成请求批次，不拆分单块（块内是完整章节/场次）。"""
    batches: list[_Batch] = []
    current: list[Any] = []
    current_chars = 0
    for chunk in chunks:
        length = len(getattr(chunk, "text", "") or "")
        if current and current_chars + length > max_chars:
            batches.append(_Batch(current))
            current = []
            current_chars = 0
        current.append(chunk)
        current_chars += length
    if current:
        batches.append(_Batch(current))
    return batches


# =============================================================================
# 抽取
# =============================================================================


def _run_prompt(context: _ProjectContext, batch: _Batch) -> str:
    return "\n\n".join(
        [
            context.prompt_block(),
            "",
            "## 待分析原文",
            "请只依据下面的原文提取道具；原文没写的不要补。",
            "",
            batch.text,
        ]
    )


async def _extract_batches(
    store: Any,
    context: _ProjectContext,
    batches: Sequence[_Batch],
    *,
    concurrency: int,
    agent: Any,
    on_progress: Optional[Callable[[float, str], None]],
    on_log: Optional[Callable[[str], None]],
) -> tuple[list[tuple[PropCandidate, int]], list[BaseException]]:
    """跑所有批次，返回 (候选 + 出现块序号, 失败列表)。

    单批失败不中断整次构建：其余批次的产出仍然有效，用户拿到的是「部分成功」
    而不是全盘重来。是否算整体失败由调用方按失败比例判断。
    """
    cache_type = PROP_REQUIREMENTS_CACHE
    keys = [batch.cache_key(context.fingerprint) for batch in batches]
    cached_raw: dict[str, str] = {}
    if hasattr(store, "get_analysis_item_cache"):
        cached_raw = await store.get_analysis_item_cache(cache_type, keys)

    results: dict[int, list[PropCandidate]] = {}
    pending: list[tuple[int, _Batch, str]] = []
    for index, (batch, key) in enumerate(zip(batches, keys)):
        blob = cached_raw.get(key)
        if blob:
            try:
                results[index] = list(
                    PropCandidateList.model_validate(json.loads(blob)).props
                )
                continue
            except Exception:
                # 缓存坏了就当没命中，重新算一次。
                pass
        pending.append((index, batch, key))

    if len(results) < len(batches):
        _log(
            on_log,
            "复用已缓存道具结果 %d/%d 块" % (len(results), len(batches)),
        )
    elif batches:
        _log(on_log, "全部 %d 块命中道具缓存，未产生模型调用" % len(batches))

    failures: list[BaseException] = []
    if pending:
        semaphore = asyncio.Semaphore(max(1, concurrency))
        done = 0
        total = len(pending)

        async def run_one(index: int, batch: _Batch, key: str) -> None:
            nonlocal done
            try:
                async with semaphore:
                    result = await agent.run(_run_prompt(context, batch))
                candidates = list(getattr(result.output, "props", []) or [])
                results[index] = candidates
                if hasattr(store, "save_analysis_item_cache"):
                    await store.save_analysis_item_cache(
                        cache_type,
                        {
                            key: json.dumps(
                                {"props": [c.model_dump() for c in candidates]},
                                ensure_ascii=False,
                            )
                        },
                    )
            except Exception as exc:  # noqa: BLE001 - 单批失败要能继续跑
                failures.append(exc)
                _log(on_log, f"第 {index + 1}/{len(batches)} 块道具抽取失败：{exc}")
            finally:
                done += 1
                if on_progress:
                    on_progress(
                        0.05 + 0.8 * (done / total),
                        f"已分析 {done}/{total} 块原文",
                    )

        await asyncio.gather(
            *(run_one(index, batch, key) for index, batch, key in pending)
        )

    tagged: list[tuple[PropCandidate, int]] = []
    for index in sorted(results):
        for candidate in results[index]:
            tagged.append((candidate, index))
    return tagged, failures


# =============================================================================
# 归一与合并
# =============================================================================


def _is_background(name: str) -> bool:
    from novelvideo.agents.asset_compiler import (
        BACKGROUND_PROP_DENYLIST,
        NON_PROP_KEYWORDS,
    )

    if any(token in name for token in NON_PROP_KEYWORDS):
        return True
    # 只挡「整名就是一件陈设」的情况：原文里的「密室铜门」是道具，
    # 而光秃秃的「门」几乎一定是场景的一部分。
    return name in BACKGROUND_PROP_DENYLIST


def _clean_name(raw: str) -> str:
    from novelvideo.utils.asset_names import path_safe_asset_name

    name = str(raw or "").strip()
    if not name:
        return ""
    name = path_safe_asset_name(name).strip()
    if len(name) > MAX_NAME_CHARS:
        return ""
    # 纯符号/纯数字的「名字」不可能是道具名。
    if not any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in name):
        return ""
    return name


def _attested(name: str, batch_text: str) -> bool:
    """名字必须真的出自原文，否则多半是模型自己造的。"""
    return bool(name) and name in batch_text


def _resolve_owner(owner: str, context: _ProjectContext) -> str:
    owner = str(owner or "").strip()
    if not owner:
        return ""
    if owner in context.roster:
        return owner
    if owner in context.roster_aliases:
        for character in context.characters:
            aliases = [
                str(alias or "").strip()
                for alias in (getattr(character, "aliases", None) or [])
            ]
            if owner in aliases:
                return str(getattr(character, "name", "") or "").strip()
    # 角色表里没有：宁可留空也不要写一个不存在的角色名。
    return ""


def _normalize_type(value: str) -> str:
    value = str(value or "").strip().lower()
    return value if value in PROP_TYPES else "object"


def _merge_candidates(
    tagged: Sequence[tuple[PropCandidate, int]],
    *,
    batch_texts: Sequence[str],
    context: _ProjectContext,
    on_log: Optional[Callable[[str], None]],
) -> list[PropCandidate]:
    """把多次请求的结果合成一份目录。

    同一道具在不同块里被重复识别很常见（一把剑贯穿全书）。合并规则偏保守：
    名字或别名能对上就算同一个，保留信息最全的那条，其余只贡献别名的并集。
    另外把「已入库道具」的别名也算进匹配，避免再造一个同物异名的重复条目。
    """
    existing_alias: dict[str, str] = {}
    for prop in context.props:
        canonical = str(getattr(prop, "name", "") or "").strip()
        if not canonical:
            continue
        existing_alias[canonical] = canonical
        for alias in getattr(prop, "aliases", None) or []:
            alias_text = str(alias or "").strip()
            if alias_text:
                existing_alias[alias_text] = canonical

    merged: dict[str, PropCandidate] = {}
    mentions: dict[str, set[int]] = {}
    dropped_unattested = 0
    dropped_background = 0
    cleared_owner = 0

    for candidate, batch_index in tagged:
        name = _clean_name(candidate.name)
        if not name:
            continue
        batch_text = batch_texts[batch_index] if batch_index < len(batch_texts) else ""
        if not _attested(name, batch_text):
            dropped_unattested += 1
            continue
        if _is_background(name):
            dropped_background += 1
            continue

        owner = _resolve_owner(candidate.owner, context)
        if candidate.owner and not owner:
            cleared_owner += 1

        canonical = existing_alias.get(name, name)
        # 别名也参与归并：模型有时在 A 块写正名、B 块写绰号。
        aliases = [
            cleaned
            for cleaned in (_clean_name(alias) for alias in candidate.aliases)
            if cleaned and cleaned != canonical
        ]
        for alias in aliases:
            existing_alias.setdefault(alias, canonical)

        normalized = PropCandidate(
            name=canonical,
            aliases=aliases,
            prop_type=_normalize_type(candidate.prop_type),
            owner=owner,
            description=str(candidate.description or "").strip(),
            visual_prompt=str(candidate.visual_prompt or "").strip(),
            scale=str(candidate.scale or "").strip(),
            evidence=str(candidate.evidence or "").strip()[:MAX_EVIDENCE_CHARS],
        )

        mentions.setdefault(canonical, set()).add(batch_index)
        current = merged.get(canonical)
        if current is None:
            merged[canonical] = normalized
            continue
        merged[canonical] = _merge_two(current, normalized)

    if dropped_unattested:
        _log(on_log, f"丢弃 {dropped_unattested} 条原文中不存在的道具名")
    if dropped_background:
        _log(on_log, f"跳过 {dropped_background} 条场景陈设/非道具条目")
    if cleared_owner:
        _log(on_log, f"清空 {cleared_owner} 条不存在的归属角色")

    # 出现块数越多越可能是主线道具；同样多时先取信息更完整的那条。
    ordered = sorted(
        merged.values(),
        key=lambda item: (-len(mentions.get(item.name, ())), -len(item.visual_prompt), item.name),
    )
    if len(ordered) > MAX_PROP_CANDIDATES:
        _log(on_log, f"候选 {len(ordered)} 个，按重要性保留前 {MAX_PROP_CANDIDATES} 个")
        ordered = ordered[:MAX_PROP_CANDIDATES]
    return ordered


def _merge_two(base: PropCandidate, extra: PropCandidate) -> PropCandidate:
    """合并同一条道具的两次识别，只补空、不覆盖更具体的信息。"""
    aliases = list(dict.fromkeys([*base.aliases, *extra.aliases]))
    return PropCandidate(
        name=base.name,
        aliases=aliases,
        prop_type=base.prop_type if base.prop_type != "object" else extra.prop_type,
        owner=base.owner or extra.owner,
        description=base.description or extra.description,
        visual_prompt=(
            base.visual_prompt
            if len(base.visual_prompt) >= len(extra.visual_prompt)
            else extra.visual_prompt
        ),
        scale=base.scale or extra.scale,
        evidence=base.evidence or extra.evidence,
    )


# =============================================================================
# 落库
# =============================================================================


async def _publish(
    store: Any,
    candidates: Sequence[PropCandidate],
    *,
    on_log: Optional[Callable[[str], None]],
) -> tuple[int, int, int]:
    """写入 props 表，返回 (新增, 补空, 跳过)。

    「已存在」不等于「什么都不做」：早期自动写入的条目可能只有名字和一个占位
    visual_prompt，直接跳过会永远留着占位。所以只补空字段，用户写过的内容不动。
    """
    from novelvideo.models import NovelProp

    added = 0
    filled = 0
    skipped = 0
    for candidate in candidates:
        existing = await _maybe_await(store.get_prop(candidate.name))
        if existing is None:
            await _maybe_await(
                store.add_prop(
                    NovelProp(
                        name=candidate.name,
                        aliases=list(candidate.aliases),
                        prop_type=candidate.prop_type,
                        visual_prompt=candidate.visual_prompt,
                        description=candidate.description,
                        owner=candidate.owner,
                        scale=candidate.scale,
                    )
                )
            )
            added += 1
            continue

        updates: dict[str, Any] = {}
        if not str(getattr(existing, "visual_prompt", "") or "").strip() and candidate.visual_prompt:
            updates["visual_prompt"] = candidate.visual_prompt
        if not str(getattr(existing, "description", "") or "").strip() and candidate.description:
            updates["description"] = candidate.description
        if not str(getattr(existing, "owner", "") or "").strip() and candidate.owner:
            updates["owner"] = candidate.owner
        if not str(getattr(existing, "scale", "") or "").strip() and candidate.scale:
            updates["scale"] = candidate.scale
        if updates and hasattr(store, "update_prop"):
            await _maybe_await(store.update_prop(candidate.name, **updates))
            filled += 1
        else:
            skipped += 1

    if added or filled or skipped:
        _log(
            on_log,
            f"道具入库：新增 {added}，补齐空字段 {filled}，已有且完整 {skipped}",
        )
    return added, filled, skipped


# =============================================================================
# 入口
# =============================================================================


def _log(on_log: Optional[Callable[[str], None]], message: str) -> None:
    logger.info("prop build: %s", message)
    if on_log:
        on_log(message)


async def build_props_from_novel(
    store: Any,
    *,
    on_progress: Optional[Callable[[float, str], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    max_call_chars: int = DEFAULT_MAX_CALL_CHARS,
    agent: Any = None,
) -> dict[str, Any]:
    """从 ``novel.txt`` 批量生成道具目录。

    Args:
        store: SQLiteStore（或暴露同样 project_dir / state_dir / props 接口的对象）。
        on_progress: ``(进度 0–1, 阶段说明)``。
        on_log: 纯日志回调。
        concurrency: 并发请求数。
        max_call_chars: 单次请求的原文上限。
        agent: 测试注入用的假 Agent；为空时按项目配置构造。

    Returns:
        ``{"props": 识别数, "added_props": 新增, "filled_props": 补空,
        "skipped_props": 跳过, "mode": "novel_sweep", "message": 可选说明}``。
    """
    from novelvideo.novel_source import require_imported_novel
    from novelvideo.project_config import load_project_config_file_from_state_dir
    from novelvideo.story_analysis import chunk_source_text

    def report(progress: float, task: str) -> None:
        if on_progress:
            on_progress(progress, task)

    novel_text = require_imported_novel(store.project_dir)
    template = str(
        load_project_config_file_from_state_dir(store.state_dir).get("spine_template")
        or "drama"
    ).strip()

    report(0.02, "切分原文…")
    chunks = chunk_source_text(novel_text, template)
    if not chunks:
        raise RuntimeError("原文为空或无法切分，无法提取道具")
    batches = _chunk_batches(chunks, max_chars=max(2000, max_call_chars))
    _log(on_log, f"共 {len(chunks)} 块原文，合并为 {len(batches)} 次请求")

    context = await _load_context(store)
    _log(
        on_log,
        f"上下文：角色 {len(context.characters)}、场景 {len(context.scenes)}、"
        f"已入库道具 {len(context.props)}",
    )

    if agent is None:
        agent = _build_agent()

    tagged, failures = await _extract_batches(
        store,
        context,
        batches,
        concurrency=concurrency,
        agent=agent,
        on_progress=on_progress,
        on_log=on_log,
    )
    if failures and len(failures) >= len(batches):
        # 全部失败：不能报「成功但 0 个」，否则用户以为是书里没道具。
        raise RuntimeError(f"道具抽取全部失败：{failures[0]}") from failures[0]

    report(0.87, "归并同一道具的不同写法…")
    batch_texts = [batch.text for batch in batches]
    candidates = _merge_candidates(
        tagged, batch_texts=batch_texts, context=context, on_log=on_log
    )

    if not candidates:
        report(1.0, "未识别到道具")
        _log(on_log, PROP_BUILD_EMPTY_MESSAGE)
        return {
            "props": 0,
            "added_props": 0,
            "filled_props": 0,
            "skipped_props": 0,
            "mode": "novel_sweep",
            "failed_batches": len(failures),
            "message": PROP_BUILD_EMPTY_MESSAGE,
        }

    report(0.92, f"写入 {len(candidates)} 个道具…")
    added, filled, skipped = await _publish(store, candidates, on_log=on_log)

    report(1.0, f"完成：新增 {added} 个道具")
    return {
        "props": len(candidates),
        "added_props": added,
        "filled_props": filled,
        "skipped_props": skipped,
        "mode": "novel_sweep",
        "failed_batches": len(failures),
        # 任务结果会被 json.dumps 进 result_json，只能是普通字符串，
        # 不能把 LocalizableMessage 塞进来。
        "message": f"已生成 {added} 个道具",
    }


__all__ = [
    "PROP_BUILD_EMPTY_MESSAGE",
    "PROP_REQUIREMENTS_CACHE",
    "PROP_BUILD_VERSION",
    "PropCandidate",
    "PropCandidateList",
    "build_props_from_novel",
]
