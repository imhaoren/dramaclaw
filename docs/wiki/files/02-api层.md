# API 层（`src/novelvideo/api/`，16 个）

不含 `routes/`。这一层负责「进程装配、鉴权、依赖注入、上传、SSE、静态与错误出口」。

---

#### `app.py` · 550 行 `[核实]`

**作用**：独立 ASGI 应用的装配点：中间件、异常处理、路由挂载、静态媒体、启动/关闭钩子。

**接口**：`create_app()`；模块级 `app`。
**I/O**：挂 `/api/v1`（`api_router`）、`/static/projects/{project}/{file_path}`；启动时创建官方媒体轮询任务与 workflow 事件循环观察者，关闭时逐个取消。
**依赖**：`api/__init__.py`、`api/auth`、`api/routes/files`、`ports.authz`、`task_backend/limits`、`utils/upload_safety`。
**注意**：
- 静态媒体路由**带项目级鉴权**，不是公开目录；
- `/api/v1/projects/*` 路径有专门的鉴权/审计前置判断，改路径前缀会绕过它们；
- 关闭钩子按「观察者 → workflow 读线程 → 媒体轮询 → 虾导协调器 → lifecycle 端口」顺序收尾，顺序错了会卡住退出。

#### `__init__.py` · 138 行 `[核实]`

**作用**：路由聚合。`api_router = APIRouter(prefix="/api/v1")`，逐个 `include_router`；验证路由延迟注册。

**接口**：`api_router`、`register_verification_routes()`。
**注意**：验证路由（`verification/routes.py`，12 个端点）默认不在启动时注册，需要显式调用——这是为了避免循环导入，也让 EE 可以关掉它。`.endpoints.txt` 里的 387 个端点**包含**这 12 个。

#### `deps.py` · 404 行 `[核实]`

**作用**：路由共享依赖：项目路径解析、Store 构造、静态 URL 生成。

**接口**：`resolve_project_scope()`、`get_project_context_dependency()`、`make_sqlite_store_for_context()`、`make_cognee_store_for_context()`、`get_user_base_dir()`、`list_user_projects()`、`may_run_asset_repair()`、`validate_project_name()`、`make_static_url_for_context()`。
**注意**：
- 新代码一律用 `ProjectContext`，不要再用 `(username, project)` 拼路径；后者只为兼容旧脚本保留；
- `make_cognee_store()` 会拉起图谱依赖，纯 SQLite 场景用 `make_sqlite_store()`，否则慢且可能失败；
- `may_run_asset_repair()` 决定是否执行「资产名修复」这类自愈逻辑，不要绕过它。

#### `auth.py` · 279 行 `[核实]`

**作用**：凭据认证与 scope 校验的最终契约。

**接口**：`get_api_user()`、`get_api_user_or_query()`、`require_scope()`、`require_project_scope()`、`resolve_auth_cookie_from_request()`、`verify_credential_for_request()`。
**I/O**：读 `st_session` Cookie 或 `Authorization: Bearer`；调 `ports.auth` / `ports.auth_contract`。
**注意**：
- 查询参数凭据（`token` / `access_token` / `api_key`）被显式拒绝（`UNSUPPORTED_QUERY_CREDENTIALS`）；
- 长期 agent key 不能直接调业务接口，只能换会话；
- 写方法额外有 `AGENT_WRITE_SCOPES` 兜底，新增写端点时若 scope 不在集合里会被统一拦掉，需要同步这个集合。

#### `schemas.py` · 2,463 行 `[核实]`

**作用**：全部请求/响应 Pydantic 模型（100+ 个类），是前后端契约的单一来源。

**接口**：`ProjectCreate`、`IngestStart`、`BeatUpdate`、`SketchGenerateRequest`、`VideoGenerateRequest`、`FreezoneGenRequest`、`FreezoneEditRequest`、`OkResponse`、`TaskResponse`、`ErrorResponse` 等。
**注意**：
- 这里改字段名＝破坏前端，必须同步 `frontend/src/types/`；
- 画布相关请求体与 `freezone/route_helpers.py` 的默认值有耦合，改默认值要看两边。

#### `viewer_manifests.py` · 452 行 `[核实]`

**作用**：360 全景与 3GS 舞台的查看器清单构造（前端 viewer-kit 的输入）。

**接口**：`build_pano_viewer_manifest()`、`build_director_stage_manifest()`、`default_director_stage_palette()`、`asset_url()`。
**I/O**：读 `director_world/paths.py` 的产物路径 + 场景记录 → 输出 JSON 清单（URL、相机、调色板、修正参数）。
**注意**：清单里的 URL 是**带项目鉴权域的静态地址**；直接拼磁盘路径会导致前端 403。

#### `egress_binding.py` · 164 行 `[核实]`

**作用**：在 HTTP/WS 请求入口把「出网身份」绑定到当前请求作用域。

**接口**：`build_request_egress_context()`、`request_egress_scope()`。
**注意**：绑定发生在鉴权之后、路由之前；漏绑会让下游 `ModelGatewayEgressError` 或把请求记到错误主体上。

#### `workflow_reads.py` · 218 行 `[核实]`

**作用**：把工作流读取的同步阻塞操作放到有界线程池，避免阻塞事件循环。

**接口**：`WorkflowReadExecutor`、`workflow_read_stage()`、`workflow_read_maintenance()`、`shutdown_workflow_reads()`、`observe_workflow_event_loop()`；异常 `WorkflowReadBusy`。
**注意**：池满时抛 `WorkflowReadBusy`（映射成 503/429），**不要**无界扩容；`observe_workflow_event_loop()` 负责在事件循环延迟升高时告警。

#### `chapter_preview.py` · 161 行 `[核实]`

**作用**：章节预览的公共载荷构造（上传前后都能用）。

**接口**：`build_chapter_preview()`、`decode_novel_bytes()`、`load_novel_text()`、`count_billable_novel_chars()`。
**注意**：`count_billable_novel_chars` 是计费口径，和 `utils/document_parsers` 里的同名逻辑必须保持一致。

#### `upload_workers.py` · 89 行 `[核实]`

**作用**：把阻塞的上传处理（落盘、解码、缩略图）放到有界线程，并给每类上传独立限流。

**接口**：`run_asset_upload_operation()`、`asset_upload_limiter()`、`scene_ply_upload_limiter()`、`asset_resource_lock()`、`scene_upload_lock()`。
**注意**：同一资产的并发上传用 `asset_resource_lock` 串行化，否则会出现"后写的被先写的覆盖"。

#### `asset_metadata.py` · 79 行 `[核实]`

**作用**：资产业务的元信息（更新时间）计算，用于缓存与"是否有新产物"判断。

**接口**：`utc_iso()`、`path_updated_at()`、`newest_updated_at()`、`newest_path_updated_at()`、`tree_updated_at()`。
**注意**：`tree_updated_at` 会遍历目录，列表页大量调用时要配合 `summary=true`。

#### `sse_shutdown.py` · 67 行 `[核实]`

**作用**：让 SSE 响应在进程关闭时**优雅结束**，而不是被硬断。

**接口**：`shutdown_aware_sse_response()`、`wait_interval_or_shutdown()`。
**注意**：客户端收到终止事件应视为"流结束"，不是"任务失败"；不这么处理会导致无限重连。

#### `gunicorn_worker.py` · 110 行 `[核实]`

**作用**：自定义 Gunicorn worker，回收时先让 SSE 流结束再退出。

**接口**：`GracefulUvicornWorker`、`install_sse_shutdown_bridge()`。
**注意**：生产用 `-k novelvideo.api.gunicorn_worker.GracefulUvicornWorker`；用默认 `UvicornWorker` 会截断长连接。

#### `task_start_errors.py` · 54 行 `[核实]`

**作用**：把任务启动阶段的类型化异常（配额、计费、授权）转成正确的 HTTP 响应。

**接口**：`handle_task_start_runtime_error()`。
**注意**：新增配额异常类必须在这里登记，否则会退化成 500。

#### `responses.py` · 18 行 `[核实]`

**作用**：带「临时文件所有权」语义的响应类——发送后删除临时文件。

**接口**：`TemporaryFileResponse`。
**注意**：只用于 `runtime/` 下的临时产物；对 `output/` 里的正式文件用它会把文件删掉。

#### `wsgi.py` · 8 行 `[核实]`

**作用**：ASGI 入口，暴露 `application` 供 uvicorn/gunicorn 引用。

**接口**：`application`。
**注意**：`uvicorn novelvideo.api.wsgi:application` 与 `novelvideo api` 等价，后者多了 CLI 参数处理。
