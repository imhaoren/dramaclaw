"""全书结构分析端点：分卷、主线、卷大纲。

导入只负责把原文落地并切块；「这本书讲什么、能怎么分卷」是另一件事，
由这个路由触发一次异步任务完成。产物只读不写原文，也不产生 episodes，
所以它可以随时重跑而不影响已有分集。
"""

import logging

from fastapi import APIRouter, Depends

from novelvideo.api.auth import get_api_user
from novelvideo.api.deps import (
    resolve_project_scope,
    sqlite_store_for_context_scope,
    sqlite_store_scope,
)
from novelvideo.api.schemas import StoryAnalysisRequest
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


@router.get("/projects/{project}/story/structure")
async def get_story_structure(project: str, user: dict = Depends(get_api_user)):
    """读取已生成的全书结构；没有分析过时 data 为 null。"""
    from novelvideo.story_structure import (
        STORY_STRUCTURE_ARTIFACT,
        load_story_structure,
    )
    from novelvideo.story_analysis import source_sha256
    from novelvideo.novel_source import load_imported_novel_content
    from novelvideo.project_config import load_project_config_file_from_state_dir
    from novelvideo.structured_ingest import (
        STRUCTURED_ANALYSIS_VERSION,
        STRUCTURED_SCHEMA_VERSION,
    )

    resolved = await resolve_project_scope(project, user, required_role="viewer")
    store_scope = (
        sqlite_store_for_context_scope(resolved.ctx)
        if resolved.ctx
        else sqlite_store_scope(resolved.username, resolved.project_name)
    )
    async with store_scope as store:
        # 产物挂在「同源原文 + 同一提取契约」的那次分析运行上。原文被重新导入
        # 之后哈希就变了，旧产物自然查不到——这正是我们想要的行为。
        novel_text = load_imported_novel_content(resolved.project_dir) or ""
        structure = None
        if novel_text:
            template = str(
                load_project_config_file_from_state_dir(resolved.state_dir).get(
                    "spine_template"
                )
                or "drama"
            ).strip()
            run = await store.get_reusable_analysis_run(
                source_sha256=source_sha256(novel_text),
                schema_version=STRUCTURED_SCHEMA_VERSION,
                pipeline_version=STRUCTURED_ANALYSIS_VERSION,
                spine_template=template,
            )
            if run:
                structure = load_story_structure(
                    await store.get_analysis_artifact(
                        str(run["run_id"]), STORY_STRUCTURE_ARTIFACT
                    )
                )
    return {
        "ok": True,
        "data": structure.model_dump() if structure else None,
    }
