"""全书结构人工修正与导出的单元测试。"""

from __future__ import annotations

import pytest

from novelvideo.story_plan_models import PlannedEpisode
from novelvideo.story_structure import (
    StoryStructure,
    Volume,
    apply_manual_volume_edits,
    story_structure_markdown,
)


def _chapter(number: int) -> dict:
    return {"number": number, "title": f"第{number}章", "word_count": 1000, "content": ""}


def _volume(index: int, start: int, end: int, title: str = "") -> Volume:
    return Volume(
        index=index,
        title=title or f"第{index}卷",
        chapter_start=start,
        chapter_end=end,
        characters=["秦", "赵"],
    )


def _structure() -> StoryStructure:
    return StoryStructure(
        logline="一句话故事",
        mainline="主线",
        volumes=[_volume(1, 1, 5), _volume(2, 6, 10)],
    )


def test_manual_edit_reindexes_and_recomputes_characters():
    chapters = [_chapter(n) for n in range(1, 11)]
    structure = _structure()
    edited = [
        _volume(3, 1, 3, "卷一"),
        Volume(index=9, title="卷二", chapter_start=4, chapter_end=7, characters=["林"]),
        Volume(index=5, title="卷三", chapter_start=8, chapter_end=10, characters=["秦"]),
    ]

    updated = apply_manual_volume_edits(structure, edited, chapters)

    assert [volume.index for volume in updated.volumes] == [1, 2, 3]
    assert [volume.title for volume in updated.volumes] == ["卷一", "卷二", "卷三"]
    assert updated.characters == ["秦", "赵", "林"]


def test_manual_edit_rejects_gap_overlap_and_missing_edges():
    chapters = [_chapter(n) for n in range(1, 11)]

    with pytest.raises(ValueError, match="漏掉"):
        apply_manual_volume_edits(
            _structure(), [_volume(1, 1, 4), _volume(2, 6, 10)], chapters
        )
    with pytest.raises(ValueError, match="重叠"):
        apply_manual_volume_edits(
            _structure(), [_volume(1, 1, 6), _volume(2, 5, 10)], chapters
        )
    with pytest.raises(ValueError, match="第 1 章"):
        apply_manual_volume_edits(
            _structure(), [_volume(1, 2, 5), _volume(2, 6, 10)], chapters
        )
    with pytest.raises(ValueError, match="第 10 章"):
        apply_manual_volume_edits(
            _structure(), [_volume(1, 1, 5), _volume(2, 6, 9)], chapters
        )


def test_manual_edit_uses_chapter_positions_for_non_contiguous_numbers():
    chapters = [_chapter(n) for n in (1, 3, 7, 9, 12)]
    structure = StoryStructure(volumes=[_volume(1, 1, 7), _volume(2, 9, 12)])
    edited = [_volume(1, 1, 7), _volume(2, 9, 12)]

    updated = apply_manual_volume_edits(structure, edited, chapters)

    assert len(updated.volumes) == 2
    assert updated.volumes[0].chapter_start == 1
    assert updated.volumes[-1].chapter_end == 12


def test_markdown_export_contains_mainline_volumes_and_episodes():
    structure = _structure()
    structure.episode_plan = [
        PlannedEpisode(
            title="开局",
            chapter_start=1,
            chapter_end=2,
            content_summary="主角登场",
        )
    ]

    markdown = story_structure_markdown(structure)

    assert "# 全书结构" in markdown
    assert "## 主线" in markdown
    assert "## 核心人物" in markdown
    assert "### 第 1 卷 · 第1卷" in markdown
    assert "## 分集方案" in markdown
    assert "| 1 | 开局 | 1–2 | 主角登场 |" in markdown
