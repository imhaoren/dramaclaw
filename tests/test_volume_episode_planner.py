"""按卷分集规划的单元测试：分配算法、确定性兜底、产物转换。"""

from __future__ import annotations

import pytest

from novelvideo.agents.volume_episode_planner import (
    _normalize_volume_episodes,
    allocate_episode_counts,
    plan_structure_episodes_sync,
    to_novel_episodes,
)
from novelvideo.models import NovelEpisode
from novelvideo.story_plan_models import PlannedEpisode
from novelvideo.story_structure import StoryStructure, Volume


def _volume(index: int, start: int, end: int, title: str = "") -> Volume:
    return Volume(index=index, title=title or f"第{index}卷", chapter_start=start, chapter_end=end)


def _chapter(number: int, chars: int, title: str | None = None) -> dict:
    return {
        "number": number,
        "title": title or f"第{number}章",
        "word_count": chars,
        "content": f"第{number}章正文。" * max(1, chars // 8),
    }


def _structure(volumes: list[Volume]) -> StoryStructure:
    return StoryStructure(volumes=volumes, total_chapters=sum(1 for _ in volumes))


def test_allocation_is_proportional_and_each_volume_gets_one_episode():
    volumes = [_volume(1, 1, 10), _volume(2, 11, 30), _volume(3, 31, 60)]
    chapter_map = {
        number: _chapter(number, 1000)
        for number in range(1, 61)
    }

    counts = allocate_episode_counts(volumes, chapter_map, target_episodes=12)

    assert counts == [2, 4, 6]
    assert sum(counts) == 12


def test_allocation_keeps_one_episode_when_target_is_smaller_than_volume_count():
    volumes = [_volume(1, 1, 1), _volume(2, 2, 2), _volume(3, 3, 3)]
    chapter_map = {1: _chapter(1, 100), 2: _chapter(2, 100), 3: _chapter(3, 100)}

    assert allocate_episode_counts(volumes, chapter_map, target_episodes=2) == [1, 1, 1]


def test_manual_episode_counts_win_and_must_match_volume_count():
    volumes = [_volume(1, 1, 2), _volume(2, 3, 4)]
    chapter_map = {n: _chapter(n, 500) for n in range(1, 5)}

    assert allocate_episode_counts(volumes, chapter_map, episode_counts=[3, 1]) == [3, 1]
    with pytest.raises(ValueError, match="长度"):
        allocate_episode_counts(volumes, chapter_map, episode_counts=[3])


def test_sync_plan_covers_every_chapter_without_gaps_or_overlap():
    volumes = [_volume(1, 1, 4), _volume(2, 5, 8)]
    chapter_map = {number: _chapter(number, 800) for number in range(1, 9)}
    structure = _structure(volumes)

    planned = plan_structure_episodes_sync(
        structure, chapter_map, episode_counts=[3, 2]
    )

    assert len(planned) == 5
    assert planned[0].chapter_start == 1
    assert planned[-1].chapter_end == 8
    # 相邻集必须紧邻：要么同卷内 +1，要么正好跨过卷边界。
    for left, right in zip(planned, planned[1:]):
        assert right.chapter_start == left.chapter_end + 1
    for episode in planned:
        assert 1 <= episode.chapter_start <= episode.chapter_end <= 8
    # 卷内集数符合人工分配。
    assert sum(1 for ep in planned if ep.chapter_end <= 4) == 3
    assert sum(1 for ep in planned if ep.chapter_start >= 5) == 2


def test_sync_plan_handles_non_contiguous_chapter_numbers():
    """网文常见跳号/缺章：按章节位置而不是章号数值校验覆盖。"""

    volumes = [_volume(1, 1, 5), _volume(2, 7, 11)]
    chapter_map = {
        number: _chapter(number, 600)
        for number in (1, 2, 5, 7, 9, 11)
    }

    planned = plan_structure_episodes_sync(
        _structure(volumes), chapter_map, episode_counts=[2, 1]
    )

    assert [ep.title for ep in planned] == ["第1集", "第2集", "第3集"]
    assert planned[0].chapter_start == 1
    assert planned[-1].chapter_end == 11
    used = [
        number
        for episode in planned
        for number in range(episode.chapter_start, episode.chapter_end + 1)
        if number in chapter_map
    ]
    assert used == [1, 2, 5, 7, 9, 11]


def test_sync_plan_keeps_every_volume_non_empty_even_for_uneven_char_counts():
    volumes = [_volume(1, 1, 2), _volume(2, 3, 6)]
    chapter_map = {
        1: _chapter(1, 10),
        2: _chapter(2, 10),
        3: _chapter(3, 9000),
        4: _chapter(4, 9000),
        5: _chapter(5, 9000),
        6: _chapter(6, 9000),
    }

    planned = plan_structure_episodes_sync(
        _structure(volumes), chapter_map, target_episodes=4
    )

    # 第一卷只有 1 集，必须覆盖它的全部 2 章；第二卷 3 集从第 3 章起。
    assert (planned[0].chapter_start, planned[0].chapter_end) == (1, 2)
    assert planned[1].chapter_start == 3
    assert planned[-1].chapter_end == 6


def test_normalize_model_episodes_forces_full_volume_coverage():
    volume = _volume(1, 1, 4)
    chapter_map = {n: _chapter(n, 500) for n in range(1, 5)}
    candidates = [
        PlannedEpisode(title="开局", chapter_start=1, chapter_end=2),
        PlannedEpisode(title="反转", chapter_start=4, chapter_end=4),
    ]

    normalized = _normalize_volume_episodes(candidates, volume, chapter_map, 2)

    # 模型给的起点（第 1、4 章）保留，中间缺口由前一集吸收，保证全覆盖。
    assert normalized is not None
    assert [(ep.chapter_start, ep.chapter_end) for ep in normalized] == [(1, 3), (4, 4)]


def test_normalize_rejects_wrong_episode_count_and_duplicate_boundaries():
    volume = _volume(1, 1, 4)
    chapter_map = {n: _chapter(n, 500) for n in range(1, 5)}

    assert _normalize_volume_episodes(
        [PlannedEpisode(chapter_start=1, chapter_end=4)], volume, chapter_map, 2
    ) is None
    assert _normalize_volume_episodes(
        [
            PlannedEpisode(chapter_start=1, chapter_end=1),
            PlannedEpisode(chapter_start=1, chapter_end=2),
        ],
        volume,
        chapter_map,
        2,
    ) is None


def test_to_novel_episodes_concatenates_source_and_keeps_planned_assets():
    chapter_map = {
        1: _chapter(1, 200, title="入宫"),
        2: _chapter(2, 200, title="交锋"),
    }
    existing = NovelEpisode(
        number=1,
        title="旧第一集",
        identity_ids=["秦_青年"],
        scene_menu=[{"scene_id": "宫门"}],
        prop_menu=[{"prop_id": "玉佩"}],
    )
    planned = [
        PlannedEpisode(
            title="入宫",
            chapter_start=1,
            chapter_end=2,
            content_summary="主角入宫并与守门人交锋",
            main_conflict="身份暴露",
            cliffhanger="玉佩落在地上",
            key_events=["入宫", "交锋"],
            character_names=["秦"],
        )
    ]

    episodes = to_novel_episodes(planned, chapter_map, existing=[existing])

    assert len(episodes) == 1
    assert episodes[0].number == 1
    assert episodes[0].title == "入宫"
    assert "第1章正文" in episodes[0].raw_content
    assert "第2章正文" in episodes[0].raw_content
    assert episodes[0].identity_ids == ["秦_青年"]
    assert episodes[0].scene_menu[0].scene_id == "宫门"
    assert episodes[0].prop_menu[0].prop_id == "玉佩"
    assert episodes[0].main_conflict == "身份暴露"
