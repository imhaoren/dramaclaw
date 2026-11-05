"""全书结构分析与分集规划共享的数据模型。

放在独立模块是为了避免 ``story_structure`` 与 ``agents.volume_episode_planner``
之间形成导入环：前者需要把分集方案存进产物，后者需要读取分卷模型，两边都
只依赖这里的中立定义。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlannedEpisode(BaseModel):
    """分集方案中的一集。"""

    title: str = Field(default="", description="集标题，6–12 字")
    chapter_start: int = Field(default=0, description="起始章号")
    chapter_end: int = Field(default=0, description="结束章号")
    content_summary: str = Field(default="", description="本集内容摘要，50–100 字")
    main_conflict: str = Field(default="", description="本集核心冲突")
    cliffhanger: str = Field(default="", description="结尾钩子")
    key_events: list[str] = Field(default_factory=list, description="2–4 条关键事件")
    character_names: list[str] = Field(default_factory=list, description="出场角色")
    density: str = Field(default="", description="low/medium/high，情节密度")


class VolumeEpisodeOutput(BaseModel):
    """单卷分集请求的结构化输出。"""

    episodes: list[PlannedEpisode] = Field(default_factory=list)
