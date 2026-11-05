"""全书结构分析任务：逐章摘要 → 分卷 → 卷大纲。"""

from __future__ import annotations

import asyncio
from typing import Any

from novelvideo.i18n_message import MessageLike
from novelvideo.model_gateway_runtime import model_gateway_scope_for_runner
from novelvideo.project_context import ProjectContext
from novelvideo.task_backend.cancel import await_envelope_with_cancel_watch
from novelvideo.task_backend.registry import register_project_task_runner
from novelvideo.task_state import get_task_manager

TASK_TYPE = "analyze_story"


def run_analyze_story(
    envelope: dict[str, Any], ctx: ProjectContext
) -> dict[str, Any] | None:
    with model_gateway_scope_for_runner(envelope):
        return asyncio.run(
            await_envelope_with_cancel_watch(
                _run_analyze_story(envelope, ctx),
                envelope,
                task_type=TASK_TYPE,
            )
        )


async def _run_analyze_story(
    envelope: dict[str, Any], ctx: ProjectContext
) -> dict[str, Any]:
    from novelvideo.knowledge_pipeline import is_structured_pipeline
    from novelvideo.story_structure import build_story_structure

    # 结构分析只读原文，不碰图谱。Cognee 轨道走向量存储，这条路径对它没有
    # 意义，直接在入口拒绝，而不是让它跑到一半才发现拿不到章节。
    if not is_structured_pipeline(ctx.state_dir):
        from novelvideo.knowledge_pipeline import KnowledgePipelineUnsupported

        raise KnowledgePipelineUnsupported(
            "全书结构分析仅支持结构化项目；Cognee 项目请使用 AI 分集规划"
        )

    from novelvideo.sqlite_store import SQLiteStore

    payload = envelope.get("payload") or {}
    config = dict(payload.get("config") or {})

    store = SQLiteStore(
        ctx.owner_project_label,
        output_dir=str(ctx.output_dir),
        state_dir=str(ctx.state_dir),
    )
    await store.initialize()
    manager = get_task_manager()

    def update(progress: float | None, task: MessageLike) -> None:
        """落一条进度；日志消息不带进度，用 None 保持进度条不回零。"""
        manager.update_progress_for_project(
            ctx,
            TASK_TYPE,
            0,
            progress=progress,
            current_task=task,
            logs=[task],
        )

    try:
        structure = await build_story_structure(
            store,
            on_progress=update,
            on_log=lambda message: update(None, message),
            batch_size=int(config.get("batch_size") or 0) or 12,
            concurrency=int(config.get("concurrency") or 0) or 3,
            reuse=bool(config.get("reuse", True)),
        )
        return {
            "volumes": len(structure.volumes),
            "chapters": structure.total_chapters,
            "chars": structure.total_chars,
        }
    finally:
        await store.close()


register_project_task_runner(TASK_TYPE, run_analyze_story)
