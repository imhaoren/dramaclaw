# API 路由（`src/novelvideo/api/routes/`，27 个）

端点清单（方法/路径/说明）在 [06-HTTP-API参考](../06-HTTP-API参考.md)，本篇讲**每个文件怎么组织、为什么这么大、改的时候注意什么**。

`routes/` 合计 43,212 行，是全仓最大的包——其中 `freezone.py`（18,855 行）和 `generation.py`（6,447 行）占了大半。

---

#### `freezone.py` · 18,855 行 · 114 个端点 `[核实]`

**作用**：画布全部 REST 接口。图片/视频/音频/文本节点的生成、画布存取、Skill 运行、资产库、提交回主线、Agent 配置、HTML 产物之外的一切。

**结构**：单文件巨型路由，内部按 `TAG_FREEZONE_*` 常量分组（bootstrap / media / audio / image / video / text / canvas / assets / commit）。真正的纯逻辑已抽到 `freezone/route_helpers.py`（811 行），本文件保留参数解析、鉴权、任务投递、响应组装。

**I/O**：几乎每个端点都是「解析 `Freezone*Request` → `_resolve_freezone_project()` → 起任务 → 202 + `job_id`/`task_key`」；结果查询走 `.../jobs/{task_type}/{job_id}/result`。
**依赖**：`freezone/` 下 20+ 模块、`task_state`、`task_identity`、`api/schemas`、`api/upload_workers`、`api/workflow_reads`。
**注意**：
- 114 个端点里有 11 个是**不带项目前缀**的（`/freezone/skills`、`/freezone/agent-config/*`、`/freezone/hermes-workflow-skills`），其余都挂 `/projects/{project}/freezone/*`；
- 所有生成端点必须返回 202 + 可追踪 key，**不要**改成同步返回，会撞网关超时；
- 文件已 1.8 万行，新增端点前先看 `route_helpers.py` 是否已有可复用逻辑，别再往里堆；
- 跨项目媒体引用要过 `canvas_media_scope`，否则会出现"作者能看、同事 403"。

#### `generation.py` · 6,447 行 · 66 个端点 `[核实]`

**作用**：主线生成主干：草图、渲染网格、视频、音频、合成、导出，以及渲染/草图设置、图片池、视频池、背景锚点、导演控制帧。

**结构**：按「设置 → 草图 → 渲染 → 视频 → 音频 → 合成 → 导出 → 池操作」排列，函数命名即端点名（`generate_sketches`、`regenerate_grid`、`compose_video`、`export_srt`…）。

**I/O**：读 `beats`/`episodes`/`scenes` → 投递 `sketch_generation`/`grid_regenerate`/`single_video`/`compose_episode` 等任务 → 返回 `task_key`；同步端点（设置、池查询）直接读写配置与索引。
**注意**：
- 同一个 beat 的「重生成」有多个入口（`regenerate_beats` / `regenerate_sketches` / `selected_regen`），语义不同，别混用；
- `normalize_beat_indices` / `validate_beat_indices` 是越界防护，新增端点也要走；
- 导出（srt/zip/final video）是**同步**的，大项目会慢，注意超时设置。

#### `characters.py` · 2,360 行 · 34 个端点 `[核实]`

**作用**：角色与身份工作台：CRUD、身份增删改、肖像/身份图/服装图生成、音色样本、资产历史与回滚、项目级图源选择。

**I/O**：读写 `characters`（含 `identities_json`）+ `output/characters/`；生成走 `character_portrait` / `identity_image` 任务。
**注意**：
- 角色 `name` 是主键兼目录名，改名要走 `utils/identity_refs` 重映射，不能只 UPDATE；
- `list_characters` 的 `summary=true` 会跳过文件探测，前端列表页应默认带上；
- 身份 id 形如 `<角色名>_<身份名>`，改名会让所有历史标记悬空。

#### `scenes.py` · 1,847 行 · 24 个端点 `[核实]`

**作用**：场景工作台：场景 CRUD、母版/反打/全景/3GS 资产上传与生成、空间布局、导演世界（DirectorWorld）读写。

**I/O**：`scenes` 表 + `output/scenes/` + `output/director_worlds/<scene>/v1/`。
**注意**：
- 派生场景共用母场景资产，删母场景会影响变体；
- 3GS 生成是子进程任务（`stage_asset`），超时与磁盘占用都大；
- 场景前置错误（`ScenePlanningPrerequisiteError` 等）要映射成 422/409，不要 500。

#### `episodes.py` · 778 行 · 12 个端点 `[核实]`

**作用**：分集列表、全量规划、单集详情、beats 读取、单集身份/场景/道具规划、手工 beat 插删、章节检测。

**注意**：`POST /episodes/plan` 是**全量重规划**，会覆盖既有 beats；单集微调用 `PATCH /episodes/{n}`。

#### `scripts.py` · 802 行 · 6 个端点 `[核实]`

**作用**：剧本读取/生成、beat 编辑、视频提示词与 Seedance2 提示词生成。

**注意**：2.0 起剧本状态**只在 SQLite**，不再读写 `scripts/epXXX_script.json`；老脚本还在写文件的话会读到过期数据。

#### `content.py` · 247 行 · 6 个端点 `[核实]`

**作用**：原文与改写稿的读写、删除，以及改写任务发起。

**注意**：改写稿是独立产物，不覆盖原文；删改写稿不影响 beats。

#### `ingest.py` · 472 行 · 3 个端点 `[核实]`

**作用**：小说上传、启动导入、图谱预览。

**注意**：上传只落 `_uploads`，不解析；解析在 `ingest_fast` 任务里。`graph` 端点读的是持久化预览（`graph_preview.py`），不是实时查图。

#### `projects.py` · 1,205 行 · 18 个端点 `[核实]`

**作用**：项目生命周期（创建/列出/更新/归档/软删/恢复/彻底清除）+ 旁白音色 + 静态媒体授权。

**注意**：
- 删除默认软删（`status=deleted`），`purge` 才是真删且需 `projects:purge`；
- purge 前必须过 `security/project_storage.py` 的归属校验，防误删他人目录；
- 项目创建时决定知识管线，之后无法切换。

#### `tasks.py` · 689 行 · 7 个端点 `[核实]`

**作用**：任务列表/详情/SSE 流/取消/清理已完成/配额查询。

**注意**：流式端点用 `sse_shutdown` 的优雅关闭；`clear_project_completed_tasks` 只清终态，不要用它清活跃任务。

#### `model_gateway.py` · 1,554 行 · 23 个端点 `[核实]`

**作用**：CE 模型网关配置：模式切换（官方/自定义/混合/BrainClaw）、官方与自定义渠道、媒体模型映射、Embedding、媒体 relay。

**注意**：
- 保存后需要让运行期缓存失效（`refresh_model_gateway_runtime`），否则"改了不生效"；
- 管理类操作在 CE 下要求额外权限（`require_ce_gateway_management`）；
- 返回的 key 一律 mask。

#### `model_credits.py` · 964 行 · 1 个端点 `[核实]`

**作用**：生成前的积分报价（按节点类型/模型/时长算价）。

**注意**：报价与实际扣费必须同源，改价规则要同时改这里与 EE 结算侧。

#### `styles.py` · 477 行 · 8 个端点 `[核实]`

**作用**：风格列表/详情/预览/创建/删除/分析/上传预览图。

**注意**：`StyleService` 是风格的单一事实源（系统预设只读 + 项目自定义可写），路由不要绕过它直接写文件。

#### `pipeline.py` · 328 行 · 1 个端点 `[核实]`

**作用**：流水线聚合状态，一次返回各阶段进度（导入→分集→剧本→资产→草图→渲染→视频→音频→合成）。

**注意**：这是"总览页"的数据源，聚合逻辑较重，不要在高频轮询里调。

#### `files.py` · 278 行 · 2 个端点 `[核实]`

**作用**：文件下载与预览，带路径穿越防护。

**注意**：只允许项目目录内路径；`TemporaryFileResponse` 只用于临时文件。

#### `html_artifacts.py` · 234 行 · 11 个端点 `[核实]`

**作用**：画布 HTML 产物的版本化存取、历史、恢复、预览、导出。

**注意**：路由前缀是 `/projects/{project}/freezone/html-artifacts`（在 `APIRouter(prefix=...)` 里定义），所以 06 里的路径是相对前缀的；预览走签名 URL（`preview_media.py`），签发要权限、读取只看签名。

#### `skill_imports.py` · 194 行 · 6 个端点 `[核实]`

**作用**：外部 Skill 转换任务的提交、列表、详情、重试、安装、草稿校验。

**注意**：转换是后台任务（`skill_import` runner），与会话生命周期解耦；来源内容是**数据不是代码**，会被安全扫描。

#### `chat.py` · 4,584 行 · 19 个端点（含 1 个 WebSocket） `[核实]`

**作用**：`WS /chat/ws` 双向对话 + 取消/清除会话 + 画布命令回执 + 工具结果回填 + 虾导自动模式控制 + 权限确认。

**注意**：
- WebSocket 与 REST 混在一个文件，前半是 REST 辅助，`chat_ws()` 是主入口；
- 每个回执类端点都对应一个后端阻塞等待（`wait_*_result`），没回执会让 Agent 回合卡死；
- 事件形状变化要同步 `chat/runtime_event_mapper.py` 与前端 `task-center/stream-client.ts`。

#### `assets.py` · 199 行 · 2 个端点 `[核实]`

**作用**：资产反查——某个角色/场景/道具被哪些 beat 引用。

**注意**：实现是扫 `beats` 的 JSON 字段，数据量大时会慢；前端应缓存。

#### `props.py` · 403 行 · 5 个端点 `[核实]`

**作用**：道具 CRUD + 三视图参考图生成。

**注意**：道具名同样是路径安全约束对象（`utils/asset_names`）。

#### `auth.py` · 91 行 · 2 个端点 `[核实]`

**作用**：登出（撤销会话并清 Cookie）、当前用户信息。

**注意**：登出是 best-effort，失败也清 Cookie——否则用户会卡在"退不出去"。

#### `config.py` · 76 行 · 1 个端点 `[核实]`

**作用**：前端运行时配置（版本、edition、功能开关），**不含敏感信息**。

**注意**：`start-ce.sh` 用它做健康检查，改路径会影响启动脚本。

#### `diagnostics.py` · 65 行 · 2 个端点 `[核实]`

**作用**：只读诊断：证据面计数、画布命令推送计数。

**注意**：`HALTING` 计数非零意味着该停线排查，不是普通指标。

#### `release_notifications.py` · 32 行 · 1 个端点 `[核实]`

**作用**：版本更新通知流（按 locale 过滤）。

**注意**：依赖 `release_notes.parse()`；release notes 格式坏了这里会返回空而不是报错。

#### `product_surfaces.py` · 26 行 · 1 个端点 `[核实]`

**作用**：当前用户可见的产品面（用于前端隐藏入口）。

**注意**：判定来自 `ports.product_surface_access`，CE 默认全开。

#### `_project_audit.py` · 28 行 · 0 个端点 `[核实]`

**作用**：项目审计事件发射的共享辅助（`emit_project_audit`）。

**注意**：不是路由文件；审计走 `ports.audit`，CE 是 NoOp。

#### `__init__.py` · 2 行 `[核实]`

**作用**：包声明。

---

## 改路由时的四条硬规则

1. **鉴权先行**：新端点必须带 `Depends(get_api_user)` 或 `require_scope`；漏了会被 CI 的 `AGENT_WRITE_SCOPES` 兜底拦下（但那是兜底，不是设计）。
2. **生成类必须异步**：返回 202 + `task_key`，同步执行会撞网关/代理超时。
3. **错误要分类**：422（前置条件）、409（冲突）、429（配额）、503（依赖不可用）。把业务错误统一抛 500 是最常见的退步。
4. **契约测试同步**：改路径/字段必须改 `tests/contract/test_m*_route_contracts.py`，否则 CI 红。
