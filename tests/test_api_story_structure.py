"""全书结构人工修正/导出与按卷分集前置校验的接口级测试。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from novelvideo.api.schemas import (
    EpisodePlanRequest,
    StoryStructureUpdate,
    StoryVolumeEdit,
)
from novelvideo.story_structure import StoryStructure, Volume


class _FakeStore:
    def __init__(self, structure: StoryStructure | None = None):
        self.structure = structure
        self.saved: list[tuple[str, str, str]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def save_analysis_artifact(self, run_id: str, name: str, blob: str):
        self.saved.append((run_id, name, blob))


def _resolved(tmp_path: Path):
    return SimpleNamespace(
        ctx=SimpleNamespace(project_id="proj_demo"),
        username="admin",
        project_name="demo",
        project_dir=tmp_path,
        output_dir=str(tmp_path),
        state_dir=str(tmp_path),
        runtime_dir=str(tmp_path),
    )


def _structure() -> StoryStructure:
    return StoryStructure(
        total_chapters=6,
        total_chars=6000,
        logline="一句话故事",
        mainline="主线",
        volumes=[
            Volume(index=1, title="卷一", chapter_start=1, chapter_end=3),
            Volume(index=2, title="卷二", chapter_start=4, chapter_end=6),
        ],
    )


def _patch_scope(monkeypatch, module, tmp_path, structure, store):
    async def resolve_project_scope(project, user, required_role="viewer"):
        return _resolved(tmp_path)

    async def resolve_run(_store, _novel_text):
        return "run_1", structure

    monkeypatch.setattr(module, "resolve_project_scope", resolve_project_scope)
    monkeypatch.setattr(module, "has_imported_novel", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(module, "is_structured_pipeline", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(module, "_store_scope_for", lambda _resolved: store, raising=False)
    monkeypatch.setattr(
        module, "sqlite_store_for_context_scope", lambda _ctx: store, raising=False
    )
    import novelvideo.story_structure as story_structure

    monkeypatch.setattr(story_structure, "resolve_story_structure_run", resolve_run)


@pytest.mark.asyncio
async def test_update_structure_rejects_gap_before_persisting(tmp_path, monkeypatch):
    from novelvideo.api.routes import story

    store = _FakeStore()
    _patch_scope(monkeypatch, story, tmp_path, _structure(), store)
    import novelvideo.api.chapter_preview as chapter_preview

    monkeypatch.setattr(
        chapter_preview,
        "build_chapter_preview",
        lambda _text: {"chapters": [
            {"number": n, "title": f"第{n}章", "word_count": 1000, "content": ""}
            for n in range(1, 7)
        ]},
    )

    body = StoryStructureUpdate(
        volumes=[
            StoryVolumeEdit(index=1, title="卷一", chapter_start=1, chapter_end=2),
            StoryVolumeEdit(index=2, title="卷二", chapter_start=4, chapter_end=6),
        ]
    )
    response = await story.update_story_structure(
        "demo", body, user={"username": "admin"}
    )

    assert response["ok"] is False
    assert response["code"] == "STORY_STRUCTURE_INVALID"
    assert "漏掉" in response["error"]
    assert store.saved == []


@pytest.mark.asyncio
async def test_update_structure_persists_and_returns_reindexed_volumes(
    tmp_path, monkeypatch
):
    from novelvideo.api.routes import story

    store = _FakeStore()
    _patch_scope(monkeypatch, story, tmp_path, _structure(), store)
    import novelvideo.api.chapter_preview as chapter_preview

    monkeypatch.setattr(
        chapter_preview,
        "build_chapter_preview",
        lambda _text: {"chapters": [
            {"number": n, "title": f"第{n}章", "word_count": 1000, "content": ""}
            for n in range(1, 7)
        ]},
    )

    body = StoryStructureUpdate(
        volumes=[
            StoryVolumeEdit(index=9, title="新卷一", chapter_start=1, chapter_end=4),
            StoryVolumeEdit(index=3, title="新卷二", chapter_start=5, chapter_end=6),
        ],
        mainline="新的主线",
    )
    response = await story.update_story_structure(
        "demo", body, user={"username": "admin"}
    )

    assert response["ok"] is True
    assert [volume["index"] for volume in response["data"]["volumes"]] == [1, 2]
    assert response["data"]["mainline"] == "新的主线"
    assert len(store.saved) == 1
    saved = json.loads(store.saved[0][2])
    assert saved["volumes"][0]["chapter_start"] == 1
    assert saved["volumes"][1]["chapter_end"] == 6


@pytest.mark.asyncio
async def test_export_structure_returns_markdown_attachment(tmp_path, monkeypatch):
    from novelvideo.api.routes import story

    store = _FakeStore()
    _patch_scope(monkeypatch, story, tmp_path, _structure(), store)

    response = await story.export_story_structure(
        "demo", format="markdown", user={"username": "admin"}
    )

    assert response.status_code == 200
    assert "# 全书结构" in response.body.decode("utf-8")
    assert "attachment" in response.headers["content-disposition"]
    assert "demo-story-structure.md" in response.headers["content-disposition"]


@pytest.mark.asyncio
async def test_update_structure_reports_missing_structure(tmp_path, monkeypatch):
    from novelvideo.api.routes import story

    store = _FakeStore()
    _patch_scope(monkeypatch, story, tmp_path, None, store)

    response = await story.update_story_structure(
        "demo",
        StoryStructureUpdate(volumes=[StoryVolumeEdit(chapter_start=1, chapter_end=1)]),
        user={"username": "admin"},
    )

    assert response == {
        "ok": False,
        "code": "STORY_STRUCTURE_NOT_FOUND",
        "error": "尚未生成全书结构，请先运行结构分析",
    }


@pytest.mark.asyncio
async def test_volume_planning_requires_existing_structure(tmp_path, monkeypatch):
    from novelvideo.api.routes import episodes

    store = _FakeStore()
    _patch_scope(monkeypatch, episodes, tmp_path, None, store)

    response = await episodes.plan_episodes(
        "demo",
        EpisodePlanRequest(target_episodes=8, planning_mode="volumes"),
        user={"username": "admin"},
    )

    assert response == {
        "ok": False,
        "code": "STORY_STRUCTURE_NOT_FOUND",
        "error": "请先生成全书结构，再按卷规划分集",
    }
