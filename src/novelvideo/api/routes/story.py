"""全书结构分析端点：分卷、主线、卷大纲。

导入只负责把原文落地并切块；「这本书讲什么、能怎么分卷」是另一件事，
由这个路由触发一次异步任务完成。产物只读不写原文，也不产生 episodes，
所以它可以随时重跑而不影响已有分集。
"""

import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, PlainTextResponse

from novelvideo.api.auth import get_api_user
from novelvideo.api.deps import (
    resolve_project_scope,
    sqlite_store_for_context_scope,
    sqlite_store_scope,
)
from novelvideo.api.schemas import StoryAnalysisRequest, StoryStructureUpdate
from novelvideo.knowledge_pipeline import is_structured_pipeline
from novelvideo.novel_source import has_imported_novel, novel_import_required_response
from novelvideo.ports import get_task_backend
from novelvideo.task_identity import project_task_state_key

logger = logging.getLogger("novelvideo.api.story")

router = APIRouter()

TASK_TYPE = "analyze_story"


@router.post("/projects/{project}/story/analyze")
async def analyze_story(
    project: str, body: StoryAnalysisRequest | None = None, user: dict = Depends(get_api_user)
):
    """入队一次全书结构分析（逐章摘要 → 分卷 → 卷大纲）。"""
    payload = body or StoryAnalysisRequest()
    resolved = await resolve_project_scope(project, user, required_role="editor")
    ctx = resolved.ctx
    if ctx is None:
        return {"ok": False, "error": "该项目不在当前节点，无法分析"}

    if not has_imported_novel(resolved.project_dir):
        return novel_import_required_response()

    # 这条路径按章节读原文，Cognee 项目的章节在向量库里而不在 novel.txt 的
    # 章节标记上；与其让它跑到一半失败，不如在入队前就说清楚。
    if not is_structured_pipeline(resolved.state_dir):
        return {
            "ok": False,
            "code": "KNOWLEDGE_PIPELINE_UNSUPPORTED",
            "error": "全书结构分析仅支持结构化项目",
        }

    logger.info("[%s] analyze_story: reuse=%s", project, payload.reuse)
    queued = await get_task_backend().enqueue_project_task(
        ctx,
        product_surface="mainline",
        task_type=TASK_TYPE,
        queue_kind="default",
        episode=0,
        payload={
            "config": payload.model_dump(exclude_none=True),
            "output_dir": str(resolved.output_dir),
            "state_dir": str(resolved.state_dir),
        },
    )
    return {
        "ok": True,
        "task_type": TASK_TYPE,
        "task_id": queued.task_state.task_id,
        "task_key": project_task_state_key(TASK_TYPE, ctx.project_id, 0),
        "backend": queued.backend,
        "queue": queued.queue,
    }


def _store_scope_for(resolved):
    return (
        sqlite_store_for_context_scope(resolved.ctx)
        if resolved.ctx
        else sqlite_store_scope(resolved.username, resolved.project_name)
    )


@router.get("/projects/{project}/story/structure")
async def get_story_structure(project: str, user: dict = Depends(get_api_user)):
    """读取已生成的全书结构；没有分析过时 data 为 null。"""
    from novelvideo.novel_source import load_imported_novel_content
    from novelvideo.story_structure import resolve_story_structure_run

    resolved = await resolve_project_scope(project, user, required_role="viewer")
    async with _store_scope_for(resolved) as store:
        # 产物挂在「同源原文 + 同一提取契约」的那次分析运行上。原文被重新导入
        # 之后哈希就变了，旧产物自然查不到——这正是我们想要的行为。
        novel_text = load_imported_novel_content(resolved.project_dir) or ""
        _, structure = await resolve_story_structure_run(store, novel_text)
    return {
        "ok": True,
        "data": structure.model_dump() if structure else None,
    }


@router.put("/projects/{project}/story/structure")
async def update_story_structure(
    project: str,
    body: StoryStructureUpdate,
    user: dict = Depends(get_api_user),
):
    """保存人工修正后的分卷结构。

    只允许「连续覆盖全部章节」的编辑：少一章、叠一章都会被拒绝并给出具体
    位置，避免下游按章节区间取原文时出现空洞。
    """
    from novelvideo.api.chapter_preview import build_chapter_preview
    from novelvideo.novel_source import load_imported_novel_content
    from novelvideo.story_structure import (
        STORY_STRUCTURE_ARTIFACT,
        Volume,
        apply_manual_volume_edits,
        resolve_story_structure_run,
    )

    resolved = await resolve_project_scope(project, user, required_role="editor")
    if not has_imported_novel(resolved.project_dir):
        return novel_import_required_response()
    if not is_structured_pipeline(resolved.state_dir):
        return {
            "ok": False,
            "code": "KNOWLEDGE_PIPELINE_UNSUPPORTED",
            "error": "全书结构修正仅支持结构化项目",
        }

    novel_text = load_imported_novel_content(resolved.project_dir) or ""
    async with _store_scope_for(resolved) as store:
        run_id, structure = await resolve_story_structure_run(store, novel_text)
        if not structure:
            return {
                "ok": False,
                "code": "STORY_STRUCTURE_NOT_FOUND",
                "error": "尚未生成全书结构，请先运行结构分析",
            }
        chapters = build_chapter_preview(novel_text)["chapters"]
        volumes = [Volume(**volume.model_dump()) for volume in body.volumes]
        try:
            updated = apply_manual_volume_edits(
                structure,
                volumes,
                chapters,
                logline=body.logline,
                mainline=body.mainline,
            )
        except ValueError as exc:
            return {
                "ok": False,
                "code": "STORY_STRUCTURE_INVALID",
                "error": str(exc),
            }
        await store.save_analysis_artifact(
            run_id,
            STORY_STRUCTURE_ARTIFACT,
            json.dumps(updated.model_dump(), ensure_ascii=False),
        )
    return {"ok": True, "data": updated.model_dump()}


@router.get("/projects/{project}/story/structure/export")
async def export_story_structure(
    project: str,
    format: Literal["json", "markdown"] = "markdown",
    user: dict = Depends(get_api_user),
):
    """导出全书结构（含分集方案）。"""
    from novelvideo.novel_source import load_imported_novel_content
    from novelvideo.story_structure import (
        resolve_story_structure_run,
        story_structure_markdown,
    )

    resolved = await resolve_project_scope(project, user, required_role="viewer")
    async with _store_scope_for(resolved) as store:
        novel_text = load_imported_novel_content(resolved.project_dir) or ""
        _, structure = await resolve_story_structure_run(store, novel_text)
    if not structure:
        return JSONResponse(
            status_code=404,
            content={
                "ok": False,
                "code": "STORY_STRUCTURE_NOT_FOUND",
                "error": "尚未生成全书结构",
            },
        )
    if format == "json":
        content = json.dumps(structure.model_dump(), ensure_ascii=False, indent=2)
        media_type = "application/json"
        filename = f"{resolved.project_name}-story-structure.json"
    else:
        content = story_structure_markdown(structure)
        media_type = "text/markdown; charset=utf-8"
        filename = f"{resolved.project_name}-story-structure.md"
    return PlainTextResponse(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
