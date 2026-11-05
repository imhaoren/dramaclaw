"""按卷分集规划 Agent。

结构化项目没有 Cognee 图谱，``EpisodePlannerAgent`` 的图谱检索工具在这里
没有输入。本 Agent 以 ``StoryStructure``（分卷 + 卷大纲 + 逐章摘要）为输入，
把每一卷切成若干集，并保证：

1. **卷边界不被跨越**：每集只落在一卷内，卷与卷之间不重叠、不留空档。
2. **集数按体量分配**：目标集数按各卷字数占比分配，每卷至少一集。
3. **情节密度优先**：模型按卷大纲里的转折点/钩子选切点；模型不可用时退化为
   按字数均衡切分，任务不会因为单卷模型失败而整体失败。
4. **可复用**：新方案按集号继承旧集的身份、场景、道具等已规划资产。

输入上限：每卷只送章节清单（章号/标题/字数）与卷大纲，不送原文；原始正文
由调用方按最终章节区间拼接，避免把百万字塞进一次请求。
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from typing import Any, Callable, Optional, Sequence

from pydantic import BaseModel

from novelvideo.story_plan_models import PlannedEpisode, VolumeEpisodeOutput

logger = logging.getLogger("novelvideo.agents.volume_episode_planner")

#: 单卷拆分请求的超时；超时后按确定性方案切分，不让整次任务卡死。
DEFAULT_VOLUME_TIMEOUT_SECONDS = 180.0
#: 单卷模型调用失败后的重试次数（不含首次）。
DEFAULT_VOLUME_RETRIES = 2
#: 未指定目标集数时，每集期望承载的字数。
DEFAULT_CHARS_PER_EPISODE = 6000
#: 单次拆分请求最多处理的集数，避免模型输出过长。
MAX_EPISODES_PER_VOLUME_REQUEST = 60


_VOLUME_SYSTEM_PROMPT = """你在把一卷中文小说切成短剧集，供后续分镜改编使用。

输入给出本卷的章节清单（章号、标题、字数）、卷大纲、转折点和关键事件。
输出本卷的每一集：
- title：6–12 字，有钩子
- chapter_start / chapter_end：必须是输入章节清单里的章号，连续覆盖本卷
- content_summary：50–100 字，只写事实（谁、在哪、做了什么、结果）
- main_conflict：本集核心矛盾
- cliffhanger：结尾钩子；本集若是本卷末集，写本卷收束后的新悬念
- key_events：2–4 条动词短语
- character_names：本集出场且有名有姓的角色
- density：low/medium/high

纪律：
1. 只依据给定的卷大纲与章节清单，不得虚构剧情、人物或设定
2. 每集至少覆盖 1 章；集与集必须连续覆盖本卷全部章节，不得留空档或重叠
3. **切点优先落在转折点/冲突爆发处**，不要机械按章节数量均分
4. 输出集数必须与要求的集数完全一致"""


def _build_agent(output_type: type[BaseModel]):
    from pydantic_ai import Agent

    from novelvideo.brainclaw_contract import BrainClawProfile
    from novelvideo.config import (
        get_newapi_structured_output_model_settings,
        get_pydantic_model,
    )

    return Agent(
        get_pydantic_model(brainclaw_profile=BrainClawProfile.EPISODE_STORY_PLANNING),
        system_prompt=_VOLUME_SYSTEM_PROMPT,
        output_type=output_type,
        model_settings=get_newapi_structured_output_model_settings(),
        output_retries=2,
        name="按卷分集规划",
    )


def _log(on_log: Optional[Callable[[str], None]], message: str) -> None:
    logger.info("volume episode planner: %s", message)
    if on_log:
        on_log(message)


def _volume_chapter_items(
    volume: Any, chapter_map: dict[int, dict]
) -> list[dict]:
    """按章号升序返回本卷章节元数据。"""

    return [
        chapter_map[number]
        for number in sorted(chapter_map)
        if int(volume.chapter_start) <= int(number) <= int(volume.chapter_end)
    ]


def _largest_remainder_allocation(weights: Sequence[int], total: int) -> list[int]:
    """按权重把 ``total`` 分成若干份，每份至少 1，总和精确等于 total。"""

    count = len(weights)
    if count == 0:
        return []
    total = max(total, count)
    normalized = [max(0, int(w)) for w in weights]
    if sum(normalized) <= 0:
        normalized = [1] * count
    shares = [total * w / sum(normalized) for w in normalized]
    floors = [max(1, int(math.floor(share))) for share in shares]
    # 至少 1 集/卷后可能已经超过 total；把多出来的从最大份额里扣回去。
    while sum(floors) > total:
        index = max(range(count), key=lambda i: floors[i])
        if floors[index] <= 1:
            break
        floors[index] -= 1
    remainder = total - sum(floors)
    if remainder > 0:
        fractions = sorted(
            range(count),
            key=lambda i: (shares[i] - math.floor(shares[i]), weights[i]),
            reverse=True,
        )
        for index in fractions[:remainder]:
            floors[index] += 1
    return floors


def allocate_episode_counts(
    volumes: Sequence[Any],
    chapter_map: dict[int, dict],
    *,
    target_episodes: int | None = None,
    chars_per_episode: int | None = None,
    episode_counts: Sequence[int] | None = None,
) -> list[int]:
    """给每卷分配集数。

    优先级：人工指定的 ``episode_counts`` > ``target_episodes`` 按字数占比 >
    ``chars_per_episode``（每集期望字数）。任何情况下每卷至少 1 集。
    """

    if not volumes:
        return []
    if episode_counts is not None:
        counts = [max(1, int(value)) for value in episode_counts]
        if len(counts) != len(volumes):
            raise ValueError(
                f"episode_counts 长度 {len(counts)} 与卷数 {len(volumes)} 不一致"
            )
        return counts

    weights = [max(1, sum(
        int(ch.get("word_count") or 0) for ch in _volume_chapter_items(volume, chapter_map)
    )) for volume in volumes]

    if target_episodes and int(target_episodes) > 0:
        return _largest_remainder_allocation(weights, int(target_episodes))

    per = int(chars_per_episode or DEFAULT_CHARS_PER_EPISODE)
    if per <= 0:
        per = DEFAULT_CHARS_PER_EPISODE
    return [max(1, int(round(weight / per))) for weight in weights]


def _chapter_index_map(
    chapter_map: dict[int, dict], volume: Any
) -> tuple[list[int], list[int]]:
    """返回本卷章号列表与对应字数列表。"""

    numbers = [
        int(number)
        for number in sorted(chapter_map)
        if int(volume.chapter_start) <= int(number) <= int(volume.chapter_end)
    ]
    weights = [max(1, int(chapter_map[number].get("word_count") or 0)) for number in numbers]
    return numbers, weights


def _snap_to_chapter(value: int, numbers: Sequence[int]) -> int:
    """把任意章号吸附到本卷最近的章号，避免模型写到区间外。"""

    if not numbers:
        return value
    if value <= numbers[0]:
        return numbers[0]
    if value >= numbers[-1]:
        return numbers[-1]
    return min(numbers, key=lambda number: abs(number - value))


def _fallback_split(
    volume: Any, chapter_map: dict[int, dict], count: int
) -> list[PlannedEpisode]:
    """确定性兜底：按字数累计切分，保证连续覆盖与每集至少 1 章。"""

    numbers, weights = _chapter_index_map(chapter_map, volume)
    if not numbers:
        return []
    count = max(1, min(int(count), len(numbers)))
    total = sum(weights)
    prefix = [0]
    for weight in weights:
        prefix.append(prefix[-1] + weight)

    episodes: list[PlannedEpisode] = []
    start = 0
    for episode_index in range(count):
        remaining_episodes = count - episode_index - 1
        # 给剩余每集至少留 1 章。
        max_end = len(numbers) - 1 - remaining_episodes
        target = total * (episode_index + 1) / count
        end = start
        while end < max_end and prefix[end + 1] < target:
            end += 1
        end = max(start, min(end, max_end))
        chapter_start = numbers[start]
        chapter_end = numbers[end]
        body = "".join(
            str(chapter_map[number].get("content") or "") for number in numbers[start : end + 1]
        )
        summary = re.sub(r"\s+", " ", body).strip()[:120]
        if len(summary) == 120:
            summary += "…"
        episodes.append(
            PlannedEpisode(
                # 标题留空，由 _renumber 按全书集号补齐，避免每卷都从第 1 集重新编号。
                title="",
                chapter_start=chapter_start,
                chapter_end=chapter_end,
                content_summary=summary,
                main_conflict=str(getattr(volume, "core_conflict", "") or ""),
                cliffhanger=str(getattr(volume, "cliffhanger", "") or "")
                if episode_index + 1 == count
                else "",
                key_events=[],
                character_names=list(getattr(volume, "characters", []) or [])[:6],
                density="",
            )
        )
        start = end + 1
    return episodes


def _normalize_volume_episodes(
    candidates: Sequence[PlannedEpisode],
    volume: Any,
    chapter_map: dict[int, dict],
    expected: int,
) -> Optional[list[PlannedEpisode]]:
    """校验模型切分；不满足「集数一致 + 连续覆盖本卷」就返回 None 走兜底。"""

    numbers, _ = _chapter_index_map(chapter_map, volume)
    if not numbers or len(candidates) != expected:
        return None
    if expected > len(numbers):
        return None

    starts: list[int] = []
    ordered: list[PlannedEpisode] = []
    for candidate in candidates:
        start = _snap_to_chapter(int(candidate.chapter_start or 0), numbers)
        starts.append(numbers.index(start))
    if len(set(starts)) != expected:
        return None

    ordered = [c for _, c in sorted(zip(starts, candidates), key=lambda item: item[0])]
    sorted_starts = sorted(starts)
    sorted_starts[0] = 0
    for index in range(1, len(sorted_starts)):
        sorted_starts[index] = max(sorted_starts[index], sorted_starts[index - 1] + 1)
    if sorted_starts[-1] >= len(numbers):
        return None

    result: list[PlannedEpisode] = []
    for index, candidate in enumerate(ordered):
        start_index = sorted_starts[index]
        end_index = (
            sorted_starts[index + 1] - 1
            if index + 1 < len(sorted_starts)
            else len(numbers) - 1
        )
        result.append(
            candidate.model_copy(
                update={
                    "chapter_start": numbers[start_index],
                    "chapter_end": numbers[end_index],
                    "character_names": list(candidate.character_names)
                    or list(getattr(volume, "characters", []) or [])[:6],
                }
            )
        )
    return result


def _volume_prompt(volume: Any, chapter_map: dict[int, dict], count: int) -> str:
    numbers, weights = _chapter_index_map(chapter_map, volume)
    total_chars = sum(weights)
    lines = [
        f"本卷：第 {volume.index} 卷《{volume.title or ''}》"
        f"（第 {volume.chapter_start}–{volume.chapter_end} 章，共 {len(numbers)} 章，约 {total_chars:,} 字）",
        f"阶段：{getattr(volume, 'stage', '') or '—'}",
        f"核心冲突：{getattr(volume, 'core_conflict', '') or '—'}",
        f"卷大纲：{getattr(volume, 'outline', '') or '—'}",
        "转折点：" + ("；".join(getattr(volume, "turning_points", []) or []) or "—"),
        "关键事件：" + ("；".join(getattr(volume, "key_events", []) or []) or "—"),
        "主要角色：" + ("、".join(getattr(volume, "characters", []) or []) or "—"),
        "",
        f"请把本卷切成 **{count} 集**。章节清单（章号｜标题｜字数）：",
    ]
    for number, weight in zip(numbers, weights):
        title = str(chapter_map[number].get("title") or "")
        lines.append(f"{number}｜{title}｜{weight}")
    return "\n".join(lines)


async def _plan_one_volume(
    agent: Any,
    volume: Any,
    chapter_map: dict[int, dict],
    count: int,
    *,
    timeout: float,
    retries: int,
) -> list[PlannedEpisode]:
    """请求单卷分集；超时/重试都失败时返回空列表，由调用方兜底。"""

    if agent is None:
        return []
    prompt = _volume_prompt(volume, chapter_map, count)
    attempts = max(0, retries) + 1
    for attempt in range(1, attempts + 1):
        try:
            result = await asyncio.wait_for(agent.run(prompt), timeout=timeout)
            normalized = _normalize_volume_episodes(
                result.output.episodes, volume, chapter_map, count
            )
            if normalized:
                return normalized
            logger.warning(
                "volume %s episode split invalid (attempt %s/%s)",
                getattr(volume, "index", "?"),
                attempt,
                attempts,
            )
        except Exception as exc:
            logger.warning(
                "volume %s episode split failed (attempt %s/%s): %s",
                getattr(volume, "index", "?"),
                attempt,
                attempts,
                exc,
            )
            if attempt < attempts:
                await asyncio.sleep(min(2 ** attempt, 8))
    return []


def plan_structure_episodes_sync(
    structure: Any,
    chapter_map: dict[int, dict],
    *,
    target_episodes: int | None = None,
    chars_per_episode: int | None = None,
    episode_counts: Sequence[int] | None = None,
) -> list[PlannedEpisode]:
    """同步兜底：只按字数均分，不调模型。测试与离线环境使用。"""

    counts = allocate_episode_counts(
        structure.volumes,
        chapter_map,
        target_episodes=target_episodes,
        chars_per_episode=chars_per_episode,
        episode_counts=episode_counts,
    )
    planned: list[PlannedEpisode] = []
    for volume, count in zip(structure.volumes, counts):
        planned.extend(_fallback_split(volume, chapter_map, count))
    return _renumber(planned)


def _renumber(planned: Sequence[PlannedEpisode]) -> list[PlannedEpisode]:
    return [
        episode.model_copy(update={"title": episode.title or f"第{number}集"})
        for number, episode in enumerate(planned, start=1)
    ]


async def plan_structure_episodes(
    structure: Any,
    chapter_map: dict[int, dict],
    *,
    target_episodes: int | None = None,
    chars_per_episode: int | None = None,
    episode_counts: Sequence[int] | None = None,
    concurrency: int = 3,
    timeout: float = DEFAULT_VOLUME_TIMEOUT_SECONDS,
    retries: int = DEFAULT_VOLUME_RETRIES,
    on_progress: Optional[Callable[[float, str], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> list[PlannedEpisode]:
    """按卷生成分集方案。

    模型调用按卷并发；某卷超时或多次失败时，该卷退化为确定性切分。整次任务
    因此不会因为单卷失败而失败，返回的集数始终等于分配方案。
    """

    counts = allocate_episode_counts(
        structure.volumes,
        chapter_map,
        target_episodes=target_episodes,
        chars_per_episode=chars_per_episode,
        episode_counts=episode_counts,
    )
    if not structure.volumes:
        return []
    if sum(counts) < (target_episodes or 0):
        _log(
            on_log,
            f"目标 {target_episodes} 集少于卷数 {len(structure.volumes)}，每卷至少保留 1 集",
        )

    try:
        agent = _build_agent(VolumeEpisodeOutput)
    except Exception as exc:
        # 模型未配置/网关不可达时仍应完成任务：所有卷走确定性切分。
        _log(on_log, f"分集模型不可用，改用按字数均衡切分：{exc}")
        agent = None
    semaphore = asyncio.Semaphore(max(1, concurrency))
    done = 0
    total = len(structure.volumes)
    planned: list[PlannedEpisode] = []

    async def run_one(volume: Any, count: int) -> list[PlannedEpisode]:
        nonlocal done
        count = max(1, min(int(count), MAX_EPISODES_PER_VOLUME_REQUEST, len(
            _volume_chapter_items(volume, chapter_map)
        )))
        if count <= 0:
            done += 1
            return []
        async with semaphore:
            episodes = await _plan_one_volume(
                agent, volume, chapter_map, count, timeout=timeout, retries=retries
            )
        if not episodes:
            _log(
                on_log,
                f"第 {volume.index} 卷模型分集不可用，按字数均衡切分 {count} 集",
            )
            episodes = _fallback_split(volume, chapter_map, count)
        done += 1
        if on_progress:
            on_progress(
                0.1 + 0.75 * (done / total),
                f"已规划 {done}/{total} 卷分集",
            )
        return episodes

    results = await asyncio.gather(
        *(run_one(volume, count) for volume, count in zip(structure.volumes, counts)),
        return_exceptions=True,
    )
    for volume, count, result in zip(structure.volumes, counts, results):
        if isinstance(result, BaseException):
            _log(on_log, f"第 {volume.index} 卷分集异常，使用兜底方案：{result}")
            planned.extend(_fallback_split(volume, chapter_map, count))
        else:
            planned.extend(result)

    return _renumber(planned)


def to_novel_episodes(
    planned: Sequence[PlannedEpisode],
    chapter_map: dict[int, dict],
    *,
    existing: Sequence[Any] = (),
) -> list[Any]:
    """把分集方案转成 ``NovelEpisode``，按集号继承已有的已规划资产。"""

    from novelvideo.models import NovelEpisode

    by_number = {int(episode.number): episode for episode in existing}
    episodes: list[NovelEpisode] = []
    for number, plan in enumerate(planned, start=1):
        raw_content = "".join(
            str(chapter_map[chapter_number].get("content") or "")
            for chapter_number in sorted(chapter_map)
            if int(plan.chapter_start) <= int(chapter_number) <= int(plan.chapter_end)
        )
        episode = NovelEpisode(
            number=number,
            title=plan.title or f"第{number}集",
            chapter_start=int(plan.chapter_start),
            chapter_end=int(plan.chapter_end),
            raw_content=raw_content,
            content_summary=plan.content_summary,
            main_conflict=plan.main_conflict,
            cliffhanger=plan.cliffhanger,
            key_events=list(plan.key_events),
            character_names=list(plan.character_names),
        )
        old = by_number.get(number)
        if old is not None:
            episode.identity_ids = list(getattr(old, "identity_ids", []) or [])
            episode.scene_menu_json = getattr(old, "scene_menu_json", "[]") or "[]"
            episode.prop_menu_json = getattr(old, "prop_menu_json", "[]") or "[]"
            episode.identity_default_map_json = (
                getattr(old, "identity_default_map_json", "{}") or "{}"
            )
            episode.sketch_colors_json = getattr(old, "sketch_colors_json", "{}") or "{}"
        episodes.append(episode)
    return episodes
