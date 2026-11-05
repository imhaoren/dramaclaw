"""全书道具构建：抽取、归并与落库规则。

这里测的都是「会花钱且会写资产表」的判定：名字是否真出自原文、归属角色是否
存在、同一道具跨块是否只落一行、部分请求失败时其余结果是否照常入库。
模型本身用假 Agent 替代，不联网。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from novelvideo.knowledge_pipeline import (
    KNOWLEDGE_PIPELINE_KEY,
    KNOWLEDGE_PIPELINE_STRUCTURED,
)
from novelvideo.models import NovelCharacter, NovelProp, NovelScene
from novelvideo.prop_build import (
    PROP_BUILD_EMPTY_MESSAGE,
    PropCandidate,
    PropCandidateList,
    build_props_from_novel,
)
from novelvideo.sqlite_store import SQLiteStore

SOURCE = """第一章 夜探

林默推开库房的门，从木架上取下青铜虎符，握在掌心还有余温。
他把虎符塞进怀里，提着一盏旧油灯沿密道往里走。

第二章 对峙

苏晴伸手拦住他，目光落在他怀里的青铜虎符上。
她从桌上拿起一卷未拆封的密信，扔进火盆。
"""


def _padded(body: str) -> str:
    """把一章撑到单独成块，方便构造多批次场景。"""
    return body + "\n" + "夜色沉了下去。" * 400 + "\n"


MULTI_BATCH_SOURCE = (
    "第一章 夜探\n\n" + _padded("林默从木架上取下青铜虎符，握在掌心还有余温。")
    + "\n第二章 对峙\n\n" + _padded("苏晴伸手拦住他，目光落在他怀里的青铜虎符上。")
)


def _candidate(name: str, **overrides) -> PropCandidate:
    data = {
        "name": name,
        "prop_type": "artifact",
        "owner": "",
        "description": "",
        "visual_prompt": "",
        "scale": "",
        "evidence": "",
    }
    data.update(overrides)
    return PropCandidate(**data)


class FakeAgent:
    """按提示词内容返回预设结果的假 Agent，并记录每次请求。"""

    def __init__(self, responder):
        self._responder = responder
        self.prompts: list[str] = []

    async def run(self, prompt: str):
        self.prompts.append(prompt)
        output = self._responder(prompt)
        if isinstance(output, BaseException):
            raise output
        return SimpleNamespace(output=PropCandidateList(props=list(output)))


@pytest.fixture
async def prop_store(tmp_path):
    state_dir = tmp_path / "user" / "props"
    state_dir.mkdir(parents=True)
    (state_dir / "project_config.json").write_text(
        json.dumps(
            {
                KNOWLEDGE_PIPELINE_KEY: KNOWLEDGE_PIPELINE_STRUCTURED,
                "spine_template": "narrated",
                "visual_style": "赛博武侠，冷蓝主色",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (state_dir / "novel.txt").write_text(SOURCE, encoding="utf-8")
    store = SQLiteStore(
        "user/props", output_dir=str(state_dir), state_dir=str(state_dir)
    )
    await store.initialize()
    await store.load_graph_state()
    try:
        yield store, state_dir
    finally:
        await store.close()


async def test_build_publishes_props_with_style_scale_and_owner(prop_store):
    store, state_dir = prop_store
    await store.add_character(NovelCharacter(name="林默", role="lead", is_main=True, gender="male", age_group="youth"))
    await store.add_scene(NovelScene(name="库房", scene_type="interior", environment_prompt="潮湿的石砌库房，油灯昏黄"))

    agent = FakeAgent(
        lambda _prompt: [
            _candidate(
                "青铜虎符",
                owner="林默",
                description="调兵信物，林默随身携带",
                visual_prompt="青铜铸造的虎形兵符，虎首回望，背有错金铭文，边角磨损发暗",
                scale="长约9cm，约成人手掌三分之二",
                evidence="从木架上取下青铜虎符",
            )
        ]
    )

    result = await build_props_from_novel(store, agent=agent)

    assert result["mode"] == "novel_sweep"
    assert result["props"] == 1
    assert result["added_props"] == 1
    prop = await store.get_prop("青铜虎符")
    assert prop is not None
    assert prop.owner == "林默"
    assert prop.scale.startswith("长约9cm")
    assert "虎首" in prop.visual_prompt
    # 风格与既有资产必须进到提示词里，否则模型会按「一般古装」自由发挥。
    prompt = agent.prompts[0]
    assert "赛博武侠，冷蓝主色" in prompt
    assert "林默" in prompt
    assert "库房" in prompt


async def test_names_absent_from_source_are_dropped(prop_store):
    store, _ = prop_store
    agent = FakeAgent(
        lambda _prompt: [
            _candidate("青龙偃月刀", visual_prompt="长柄大刀"),
            _candidate("青铜虎符", visual_prompt="青铜虎形兵符"),
        ]
    )

    result = await build_props_from_novel(store, agent=agent)

    assert result["added_props"] == 1
    assert await store.get_prop("青龙偃月刀") is None
    assert await store.get_prop("青铜虎符") is not None


async def test_owner_outside_the_roster_is_cleared(prop_store):
    store, _ = prop_store
    agent = FakeAgent(
        lambda _prompt: [
            _candidate("青铜虎符", owner="不存在的角色", visual_prompt="青铜虎形兵符")
        ]
    )

    await build_props_from_novel(store, agent=agent)

    prop = await store.get_prop("青铜虎符")
    assert prop is not None and prop.owner == ""


async def test_background_furniture_is_skipped(prop_store):
    store, _ = prop_store
    # 原文里确实出现「门」，但它不是需要跨镜头追踪的故事道具。
    agent = FakeAgent(
        lambda _prompt: [_candidate("门", visual_prompt="一扇木门")]
    )

    result = await build_props_from_novel(store, agent=agent)

    assert result["props"] == 0
    assert await store.get_prop("门") is None


async def test_same_prop_across_batches_is_merged_into_one_row(prop_store):
    store, state_dir = prop_store
    (state_dir / "novel.txt").write_text(MULTI_BATCH_SOURCE, encoding="utf-8")

    def responder(prompt: str):
        if "第二章" in prompt:
            return [_candidate("青铜虎符", visual_prompt="青铜虎形兵符，错金铭文，虎尾残缺")]
        return [_candidate("青铜虎符", visual_prompt="青铜虎形兵符")]

    agent = FakeAgent(responder)
    result = await build_props_from_novel(store, agent=agent, max_call_chars=2000)

    props = await store.list_props()
    assert [prop.name for prop in props] == ["青铜虎符"]
    assert "虎尾残缺" in props[0].visual_prompt
    assert result["props"] == 1


async def test_existing_prop_keeps_user_edits_and_only_fills_blanks(prop_store):
    store, state_dir = prop_store
    (state_dir / "novel.txt").write_text(SOURCE, encoding="utf-8")
    await store.add_prop(
        NovelProp(
            name="青铜虎符",
            visual_prompt="用户自己写的设定",
            description="用户描述",
        )
    )
    await store.add_prop(NovelProp(name="密信", visual_prompt=""))

    agent = FakeAgent(
        lambda _prompt: [
            _candidate("青铜虎符", visual_prompt="模型写的设定", description="模型描述", scale="长约9cm"),
            _candidate("密信", visual_prompt="未拆封的绢帛密信，火漆封印"),
        ]
    )

    result = await build_props_from_novel(store, agent=agent)

    kept = await store.get_prop("青铜虎符")
    assert kept is not None
    assert kept.visual_prompt == "用户自己写的设定"
    assert kept.description == "用户描述"
    # 空字段可以补，用户写过的字段一律不动。
    assert kept.scale == "长约9cm"
    filled = await store.get_prop("密信")
    assert filled is not None and filled.visual_prompt.startswith("未拆封")
    assert result["added_props"] == 0
    assert result["filled_props"] == 2


async def test_a_failed_batch_does_not_discard_the_rest(prop_store):
    store, state_dir = prop_store
    (state_dir / "novel.txt").write_text(MULTI_BATCH_SOURCE, encoding="utf-8")

    def responder(prompt: str):
        if "第二章" in prompt:
            return RuntimeError("gateway 502")
        return [_candidate("青铜虎符", visual_prompt="青铜虎形兵符")]

    agent = FakeAgent(responder)
    result = await build_props_from_novel(store, agent=agent, max_call_chars=2000)

    assert result["failed_batches"] >= 1
    assert result["added_props"] == 1
    assert await store.get_prop("青铜虎符") is not None


async def test_every_batch_failing_raises_instead_of_reporting_zero(prop_store):
    store, _ = prop_store
    agent = FakeAgent(lambda _prompt: RuntimeError("401 Invalid token"))

    with pytest.raises(RuntimeError, match="道具抽取全部失败"):
        await build_props_from_novel(store, agent=agent)

    assert await store.list_props() == []


async def test_no_candidates_returns_an_explicit_message(prop_store):
    store, _ = prop_store
    agent = FakeAgent(lambda _prompt: [])

    result = await build_props_from_novel(store, agent=agent)

    assert result["props"] == 0
    assert result["message"] == PROP_BUILD_EMPTY_MESSAGE


async def test_second_run_reuses_chunk_cache(prop_store):
    store, _ = prop_store
    calls = {"n": 0}

    def responder(_prompt: str):
        calls["n"] += 1
        return [_candidate("青铜虎符", visual_prompt="青铜虎形兵符")]

    await build_props_from_novel(store, agent=FakeAgent(responder))
    assert calls["n"] == 1

    await build_props_from_novel(store, agent=FakeAgent(responder))
    # 正文与上下文都没变，第二次不该再请求模型。
    assert calls["n"] == 1


async def test_legacy_props_table_gains_scale_column(tmp_path):
    """老项目升级后 props 表必须自动长出 scale 列，旧数据不能丢。"""
    import sqlite3

    state_dir = tmp_path / "user" / "legacy"
    state_dir.mkdir(parents=True)
    legacy = sqlite3.connect(state_dir / "data.db")
    legacy.executescript(
        """
        CREATE TABLE props (
            name          TEXT PRIMARY KEY,
            aliases_json  TEXT DEFAULT '[]',
            prop_type     TEXT DEFAULT 'object',
            visual_prompt TEXT DEFAULT '',
            description   TEXT DEFAULT '',
            owner         TEXT DEFAULT '',
            notes         TEXT DEFAULT '',
            created_at    TEXT DEFAULT '',
            updated_at    TEXT DEFAULT ''
        );
        """
    )
    legacy.execute(
        "INSERT INTO props (name, visual_prompt) VALUES ('旧道具', '旧设定')"
    )
    legacy.commit()
    legacy.close()

    store = SQLiteStore(
        "user/legacy", output_dir=str(state_dir), state_dir=str(state_dir)
    )
    await store.initialize()
    try:
        existing = await store.get_prop("旧道具")
        assert existing is not None
        assert existing.visual_prompt == "旧设定"
        assert existing.scale == ""

        await store.add_prop(NovelProp(name="新道具", scale="长约9cm"))
        added = await store.get_prop("新道具")
        assert added is not None and added.scale == "长约9cm"
    finally:
        await store.close()


async def test_missing_novel_is_reported_as_import_required(tmp_path):
    state_dir = tmp_path / "user" / "empty"
    state_dir.mkdir(parents=True)
    store = SQLiteStore(
        "user/empty", output_dir=str(state_dir), state_dir=str(state_dir)
    )
    await store.initialize()
    try:
        from novelvideo.novel_source import NovelImportRequiredError

        with pytest.raises(NovelImportRequiredError):
            await build_props_from_novel(store, agent=FakeAgent(lambda _p: []))
    finally:
        await store.close()
