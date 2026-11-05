# DramaClaw 项目索引

> 本索引是仓库的导航地图：先看这里定位目录/模块，再跳转到具体文件。
> 机器可读版本：[project_index.json](project_index.json)（457 个后端模块、377 个 API 端点、463 个测试文件、27 个前端路由文件）。
> 重新生成：`python scripts/build_project_index.py`（纯 AST 扫描，不导入运行时代码）。

## 1. 项目速览

| 项 | 值 |
|---|---|
| 包名 / 版本 | `supertale-ce` (DramaClaw CE) `2.1.1` |
| 定位 | 小说 → 成片的单机自托管流水线；无需 PostgreSQL / Redis |
| 后端 | Python `>=3.11,<3.13` + FastAPI，代码在 `src/novelvideo/` |
| 前端 | React 19 + TanStack Router + Vite 6，代码在 `frontend/src/` |
| 许可证 | Elastic License 2.0（见 [docs/zh/license.md](docs/zh/license.md) / [license-inventory.csv](license-inventory.csv)） |
| CLI 入口 | `novelvideo = novelvideo.cli:app`（[cli.py](src/novelvideo/cli.py)） |
| API 入口 | [api/app.py](src/novelvideo/api/app.py)，WSGI 为 [api/wsgi.py](src/novelvideo/api/wsgi.py) |
| 默认端口 | `8780`（`uv run novelvideo api --port 8780`） |
| 本地数据 | `state/<user>/<project>/data.db`（SQLite） + `output/<user>/<project>/` |
| 模型接入 | 统一经 OpenAI 兼容网关（NewAPI），配置写入 `settings.db` |

## 2. 常用命令

```bash
uv sync --group dev                  # 安装运行时 + 开发依赖
uv run novelvideo api --port 8780    # 启动本地 REST API
uv run pytest                        # 默认测试（排除 ee / e2e 标记）
uv run pytest tests/test_api_assets.py
scripts/acceptance/run.sh            # 验收检查
pre-commit run --all-files           # 仓库钩子（含 gitleaks）
```

```bash
cd frontend
pnpm dev          # Vite 开发服务器
pnpm build        # tsc -b && vite build
pnpm test         # vitest run
```

CLI 子命令：[cli.py](src/novelvideo/cli.py) —— `import-novel`、`cognee-ingest`、`cognee-profile`、`cognee-plan`、`cognee-search`、`generate-script`、`generate`、`ui`、`api`、`migrate-scene-names`、`repair-asset-names`、`backup`（子 Typer 应用）。

## 3. 顶层目录地图

| 路径 | 作用 |
|---|---|
| [src/novelvideo/](src/novelvideo/) | 后端引擎（API / agents / generators / task_backend / ports ...） |
| [frontend/](frontend/) | React Web 前端（`src/` 为源码，组件与特性按域拆分） |
| [tests/](tests/) | pytest 测试（含 `contract/`、`ports/`、`compliance/`） |
| [docs/](docs/) | 中英文档（`zh/`、`en/`，以及 changes/features/plans/reviews/wiki） |
| [scripts/](scripts/) | 运维、校验、迁移、基准与合规脚本 |
| [deploy/](deploy/) | 部署资产（Hermes sandbox、codex 相关） |
| [schemas/](schemas/) | JSON Schema（`workflow/` 等） |
| [agent-kit/](agent-kit/) | 技能 / 宿主适配清单（`manifest.json`、`skills/`） |
| [assets/](assets/) | 品牌图、架构图、内置媒体素材 |
| [readme/](readme/) | 多语言 README（zh / vi / th） |
| `state/` `output/` `runtime/` | 本地运行数据（生成物；不要提交） |
| [src/novelvideo/agent_skills/](src/novelvideo/agent_skills/) | 技能文档目录（Markdown，无运行代码） |

## 4. 后端代码地图（`src/novelvideo/`）

### 4.1 子包职责

| 子包 | py 文件数（含 `__init__.py`） | 行数 | 职责 |
|---|---:|---:|---|
| [api/](src/novelvideo/api/) | 44 | 48,663 | FastAPI 应用、REST 路由（`/api/v1`）、鉴权、SSE、上传 |
| [freezone/](src/novelvideo/freezone/) | 59 | 36,080 | 自由创作画布后端：节点任务、画布存储、工作流、Skill 导入 |
| [generators/](src/novelvideo/generators/) | 26 | 27,909 | 图片 / 视频 / TTS / 网格生成适配器与提示词构建 |
| [chat/](src/novelvideo/chat/) | 32 | 21,982 | 对话式创作运行时（Hermes / Codex / Claude 后端、会话与展示映射） |
| [task_backend/](src/novelvideo/task_backend/) | 32 | 11,462 | 任务投递、执行核心、runner 注册表、取消与限额 |
| [verification/](src/novelvideo/verification/) | 41 | 8,847 | AI 验证：草图/首帧事实核查、角色一致性、失败模式库 |
| [director_world/](src/novelvideo/director_world/) | 20 | 9,219 | DirectorWorld 持久化与 3DGS / world 场景工具 |
| [cognee/](src/novelvideo/cognee/) | 12 | 8,864 | 故事知识图谱：章节检测、事件抽取、Cognee 管线与存储 |
| [agents/](src/novelvideo/agents/) | 12 | 7,010 | 剧本 / 分集 / 资产 / 身份 / 视频提示词等智能体 |
| [utils/](src/novelvideo/utils/) | 28 | 6,655 | 路径、资产解析、媒体 IO、文本、缩略图等通用工具 |
| [seedance2_i2v/](src/novelvideo/seedance2_i2v/) | 14 | 6,229 | Seedance 2.0 图生视频集成 |
| [ports/](src/novelvideo/ports/) | 32 | 3,693 | 端口与适配器：Protocol 定义 + `ports/local/` CE 默认实现 |
| [services/](src/novelvideo/services/) | 9 | 2,494 | 风格、角色/道具参考、姿势、占位符等共享服务 |
| [skills/](src/novelvideo/skills/) | 3 | 1,303 | Director 技能目录与执行入口 |
| [workflows/](src/novelvideo/workflows/) | 3 | 1,590 | 剧本写作工作流（Cognee 版） |
| [audio/](src/novelvideo/audio/) | 3 | 862 | IndexTTS2 分 beat 配音任务、系统参考音准备 |
| [backup/](src/novelvideo/backup/) | 6 | 1,029 | 备份 CLI、WAL 迁移 |
| [storage/](src/novelvideo/storage/) | 5 | 1,122 | 媒体中继 / S3 relay / 存储预检 |
| [shared/](src/novelvideo/shared/) | 9 | 841 | 不依赖控制面的共享数据面原语（env、计费错误、provider 错误） |
| [security/](src/novelvideo/security/) | 4 | 682 | 沙箱包装（`sandbox_wrap.py`）、项目目录归属校验 |
| [export/](src/novelvideo/export/) | 2 | 126 | 字幕与剧集合成导出 |
| [render_plan/](src/novelvideo/render_plan/) | 2 | 69 | 渲染计划辅助 |
| [ui/](src/novelvideo/ui/) | 1 | 17 | 已废弃的 NiceGUI 包 |
| [prompts/](src/novelvideo/prompts/) | 1 | 6 | 基线提示词 |
| [styles/](src/novelvideo/styles/) | 0 | 0 | 风格 JSON + 预览图（`anime` / `chinese_period_drama` / `guoman_fantasy` / `post_apocalyptic` / `realistic`） |
| [agent_skills/](src/novelvideo/agent_skills/) | 0 | 0 | 技能 Markdown 文档（非运行代码） |
| [assets/](src/novelvideo/assets/) | 1 | 6 | 登录背景、片尾图等内置素材 |

### 4.2 根级核心模块（常用入口）

| 文件 | 职责 |
|---|---|
| [config.py](src/novelvideo/config.py) | 环境变量、路径、provider 预设、模型工厂 |
| [models.py](src/novelvideo/models.py) | 核心数据模型（Pydantic） |
| [sqlite_store.py](src/novelvideo/sqlite_store.py) | 项目 SQLite 存储主入口 |
| [sqlite_schema.py](src/novelvideo/sqlite_schema.py) | 跨进程 schema 初始化协调 |
| [task_state.py](src/novelvideo/task_state.py) | 任务状态持久化 |
| [project_context.py](src/novelvideo/project_context.py) | 新代码唯一的项目身份对象 |
| [project_config.py](src/novelvideo/project_config.py) | 项目配置原子读改写 |
| [egress_context.py](src/novelvideo/egress_context.py) | 请求级出口身份（不携带密钥） |
| [model_gateway_settings.py](src/novelvideo/model_gateway_settings.py) / [model_gateway_runtime.py](src/novelvideo/model_gateway_runtime.py) | 动态模型网关配置与缓存失效 |
| [newapi_provisioner.py](src/novelvideo/newapi_provisioner.py) | 在 NewAPI 中开通渠道与 relay token |
| [llm_instrumentation.py](src/novelvideo/llm_instrumentation.py) | LLM 归因上下文与 provider 埋点 |
| [story_structure.py](src/novelvideo/story_structure.py) | 全书结构：逐章摘要 → 分卷 → 卷大纲 |
| [story_analysis.py](src/novelvideo/story_analysis.py) | 结构化管线（structured_v1）的确定性分块 |
| [structured_ingest.py](src/novelvideo/structured_ingest.py) / [structured_extraction.py](src/novelvideo/structured_extraction.py) / [structured_builders.py](src/novelvideo/structured_builders.py) | 无图谱的导入、角色抽取与资产构建 |
| [prop_build.py](src/novelvideo/prop_build.py) | 全书道具批量构建 |
| [stage_asset_tasks.py](src/novelvideo/stage_asset_tasks.py) | 3GS 舞台资产子进程步骤 |
| [i18n_message.py](src/novelvideo/i18n_message.py) | 进度 / 日志 / API 的可本地化文案 |

### 4.3 任务执行链路

```
HTTP 路由 (api/routes/*.py)
  └─ task_backend/client.py  enqueue_project_task / cancel_project_task
       └─ ports/tasks.py TaskBackend (Protocol)
            └─ ports/local/tasks.py InlineTaskBackend  ← CE 默认（进程内线程）
                 └─ task_backend/consumer.py + envelope.py  信封校验 / 投递
                      └─ task_backend/run_core.py           执行核心（取消、限额、投影、计费）
                           └─ task_backend/registry.py       get_project_task_runner(task_type)
                                └─ task_backend/runners/*.py 具体任务
                                     └─ generators/ → storage/ → output/
```

关键文件：[client.py](src/novelvideo/task_backend/client.py)、[consumer.py](src/novelvideo/task_backend/consumer.py)、[run_core.py](src/novelvideo/task_backend/run_core.py)、[registry.py](src/novelvideo/task_backend/registry.py)、[limits.py](src/novelvideo/task_backend/limits.py)、[queues.py](src/novelvideo/task_backend/queues.py)。

任务类型 → runner 映射（18 个 runner 文件）：

| runner | 注册的任务类型 |
|---|---|
| [ingest.py](src/novelvideo/task_backend/runners/ingest.py) | `ingest_fast` |
| [graph_build.py](src/novelvideo/task_backend/runners/graph_build.py) | `build_characters` / `build_props` / `build_scenes` / `build_episodes` |
| [story_structure.py](src/novelvideo/task_backend/runners/story_structure.py) | 全书结构分析（无显式注册名） |
| [identity.py](src/novelvideo/task_backend/runners/identity.py) | `identity_planner` |
| [episode_assets.py](src/novelvideo/task_backend/runners/episode_assets.py) | `episode_scene_planner` / `episode_prop_planner` |
| [character_image.py](src/novelvideo/task_backend/runners/character_image.py) | `character_portrait` / `identity_image` |
| [prop_reference.py](src/novelvideo/task_backend/runners/prop_reference.py) | `prop_reference_asset` |
| [scene_reference.py](src/novelvideo/task_backend/runners/scene_reference.py) | `scene_reference_asset` |
| [script.py](src/novelvideo/task_backend/runners/script.py) | `script_writer` / `beat_video_prompt` |
| [sketch.py](src/novelvideo/task_backend/runners/sketch.py) | `sketch_generation` / `sketch_grid_generation` / `director_control_to_sketch` |
| [render.py](src/novelvideo/task_backend/runners/render.py) | `selected_regen` / `sketch_regen` / `grid_regenerate` |
| [sketch_edit_execute.py](src/novelvideo/task_backend/runners/sketch_edit_execute.py) | `sketch_edit_execute` |
| [video.py](src/novelvideo/task_backend/runners/video.py) | `single_video` / `compose_episode` / `global_optimize_video` / `freezone_video_gen` |
| [audio.py](src/novelvideo/task_backend/runners/audio.py) | 音频任务（注册在共享 helper 中） |
| [stage_asset.py](src/novelvideo/task_backend/runners/stage_asset.py) | `stage_asset` / `scene_pano_generation` / `freezone_image_to_3gs` |
| [freezone.py](src/novelvideo/task_backend/runners/freezone.py) | 23 个 `freezone_*` / `mainline_*` 任务 |
| [skill_import.py](src/novelvideo/task_backend/runners/skill_import.py) | `freezone_skill_import` |

### 4.4 端口与适配器

`ports/` 定义 Protocol，CE 默认实现在 `ports/local/`；企业版在运行时注入同接口实现。核心代码不得 import 企业实现。

| 端口 | CE 默认 | EE 适配器 |
|---|---|---|
| Auth | 本地单用户、免登录 | 多租户认证 |
| ProjectRegistry | 本地 SQLite 索引 | 机群登记 / 路由 |
| ProjectAccess | owner-everywhere | 租户 RBAC |
| TaskBackend | 进程内 inline | Celery 分布式 |
| CancellationStore | 进程内 | Redis |
| UsageMeter | no-op | 计量计费 |
| Lifecycle | no-op | PG 池 / Redis |
| AuditSink | 本地 NDJSON | 审计表 |
| CreditQuote | cost = 0 | 价格表 |

入口：[ports/registry.py](src/novelvideo/ports/registry.py)、[ports/tasks.py](src/novelvideo/ports/tasks.py)、[ports/authz.py](src/novelvideo/ports/authz.py)。

### 4.5 API 路由（`/api/v1`，共 377 个端点）

| 路由文件 | 端点数 | 说明 |
|---|---:|---|
| [freezone.py](src/novelvideo/api/routes/freezone.py) | 114 | 自由画布：节点生成、工作流、Bundle、历史 |
| [generation.py](src/novelvideo/api/routes/generation.py) | 66 | 生成任务启动与状态 |
| [characters.py](src/novelvideo/api/routes/characters.py) | 34 | 角色、服装、音色 |
| [scenes.py](src/novelvideo/api/routes/scenes.py) | 24 | 场景与场景参考图 |
| [model_gateway.py](src/novelvideo/api/routes/model_gateway.py) | 23 | 模型网关配置（前缀 `/model-gateway`） |
| [chat.py](src/novelvideo/api/routes/chat.py) | 18 | 对话流、Agent 运行时 |
| [projects.py](src/novelvideo/api/routes/projects.py) | 18 | 项目 CRUD 与工作区 |
| [episodes.py](src/novelvideo/api/routes/episodes.py) | 12 | 分集、beat、设置 |
| [html_artifacts.py](src/novelvideo/api/routes/html_artifacts.py) | 11 | HTML 修订与导出（`/projects/{project}/freezone/html-artifacts`） |
| [styles.py](src/novelvideo/api/routes/styles.py) | 8 | 风格模板 |
| [tasks.py](src/novelvideo/api/routes/tasks.py) | 7 | 任务列表 / SSE 进度 / 取消 |
| [content.py](src/novelvideo/api/routes/content.py) | 6 | 内容读取 |
| [props.py](src/novelvideo/api/routes/props.py) | 6 | 道具与参考图 |
| [scripts.py](src/novelvideo/api/routes/scripts.py) | 6 | 剧本 |
| [skill_imports.py](src/novelvideo/api/routes/skill_imports.py) | 6 | 外部 Skill 导入（`/projects/{project}/freezone/skill-imports`） |
| [ingest.py](src/novelvideo/api/routes/ingest.py) | 3 | 小说导入 |
| [assets.py](src/novelvideo/api/routes/assets.py) | 2 | 资产上传 / 元数据 |
| [auth.py](src/novelvideo/api/routes/auth.py) | 2 | 登录 / 当前用户 |
| [diagnostics.py](src/novelvideo/api/routes/diagnostics.py) | 2 | 诊断 |
| [files.py](src/novelvideo/api/routes/files.py) | 2 | 文件下载 |
| [story.py](src/novelvideo/api/routes/story.py) | 2 | 故事结构 |
| [config.py](src/novelvideo/api/routes/config.py) | 1 | 运行配置 |
| [model_credits.py](src/novelvideo/api/routes/model_credits.py) | 1 | 模型额度 |
| [pipeline.py](src/novelvideo/api/routes/pipeline.py) | 1 | 管线状态 |
| [product_surfaces.py](src/novelvideo/api/routes/product_surfaces.py) | 1 | 产品面可见性（前缀 `/product-surfaces`） |
| [release_notifications.py](src/novelvideo/api/routes/release_notifications.py) | 1 | 版本更新通知 |
| [_project_audit.py](src/novelvideo/api/routes/_project_audit.py) | 0 | 审计辅助 |
| [verification/routes.py](src/novelvideo/verification/routes.py) | — | 验证路由，运行时条件注册 |

路由装配入口：[api/\_\_init\_\_.py](src/novelvideo/api/__init__.py)（`api_router = APIRouter(prefix="/api/v1")`）。

## 5. 前端代码地图（`frontend/src/`）

| 目录 | 作用 |
|---|---|
| [routes/](frontend/src/routes/) | 文件式路由（27 个文件，TanStack Router 生成 `routeTree.gen.ts`） |
| [features/](frontend/src/features/) | 按域拆分的特性模块：`freezone`（71 文件）、`canvas`（383 文件）、`superchat`、`html-artifacts`、`viewer-kit` 等 |
| [components/](frontend/src/components/) | 通用 UI 组件 |
| [api/](frontend/src/api/) | 后端 API 客户端 |
| [stores/](frontend/src/stores/) | 状态存储 |
| [task-center/](frontend/src/task-center/) | 任务中心 |
| [pipeline-import/](frontend/src/pipeline-import/) | 导入管线 UI |
| [i18n/](frontend/src/i18n/) | 国际化资源 |
| [hooks/](frontend/src/hooks/) | 复用 hooks |
| [lib/](frontend/src/lib/) | 工具函数 |

路由树要点：

```
routes/
├─ __root.tsx, _app.tsx           # 根布局 / 登录后布局
├─ login.tsx, checkout.tsx, recharge.tsx, watch.$work.tsx
└─ _app/
   ├─ index.tsx, credits.tsx, payment-return.tsx, access-unavailable.tsx
   └─ projects.$project/
      ├─ assistant.tsx, characters.lazy.tsx, ingest.tsx, styles.tsx, tasks.tsx, episodes.tsx, freezone.lazy.tsx
      └─ episodes.$episode/
         ├─ index.lazy.tsx, overview.lazy.tsx, script.lazy.tsx, beats.lazy.tsx
         ├─ sketches.lazy.tsx, video.lazy.tsx, audio.lazy.tsx, compose.lazy.tsx
```

入口：[main.tsx](frontend/src/main.tsx)、[index.css](frontend/src/index.css)（设计变量，规范见 [DESIGN.md](DESIGN.md)）。

## 6. 测试与质量门

| 区域 | 内容 |
|---|---|
| 后端单测 | `tests/` 463 个 `test_*.py`；`tests/contract/`（13）、`tests/ports/`（19）、`tests/compliance/`（1） |
| 前端单测 | `frontend/src/**/*.test.ts(x)` 565 个，`pnpm test`（Vitest） |
| pytest 配置 | `asyncio_mode=auto`；默认 `-m 'not ee and not e2e'`（见 [pyproject.toml](pyproject.toml#L172-L186)） |
| 质量脚本 | [scripts/check_backend_i18n.py](scripts/check_backend_i18n.py)、[scripts/check_frontend_i18n.py](scripts/check_frontend_i18n.py)、[scripts/lint_ce_imports.py](scripts/lint_ce_imports.py)、[scripts/lint_ee_terms.py](scripts/lint_ee_terms.py)、[scripts/check_workflow_agent_contracts.py](scripts/check_workflow_agent_contracts.py) |
| 验收 | [scripts/acceptance/](scripts/acceptance/)、`tests/support/` |

## 7. 数据与运行时目录

| 路径 | 内容 |
|---|---|
| `state/<user>/<project>/data.db` | 项目结构化数据（SQLite） |
| `state/<user>/<project>/` | 项目状态、索引 sidecar |
| `output/<user>/<project>/` | 成片、图片、音频等产物 |
| `runtime/` | API 日志等临时运行文件 |
| `settings.db` | CE 模型网关配置（网页「设置 → 模型配置」写入） |

环境变量权威全集见 [.env.example](.env.example)，归类说明见 [docs/zh/reference/environment-variables.md](docs/zh/reference/environment-variables.md)。

## 8. 文档索引

| 入口 | 内容 |
|---|---|
| [docs/README.md](docs/README.md) | 文档总入口（中英切换） |
| [docs/zh/README.md](docs/zh/README.md) / [docs/en/README.md](docs/en/README.md) | 简中 / 英文文档 |
| [docs/zh/concepts/architecture.md](docs/zh/concepts/architecture.md) | 架构与端口说明 |
| [docs/zh/concepts/features.md](docs/zh/concepts/features.md) | 能力总览 |
| [docs/zh/getting-started/quickstart.md](docs/zh/getting-started/quickstart.md) | 快速开始 |
| [docs/zh/guides/self-hosting.md](docs/zh/guides/self-hosting.md) | 自托管手册 |
| [docs/zh/reference/environment-variables.md](docs/zh/reference/environment-variables.md) | 环境变量 |
| [llms.txt](llms.txt) | 给 LLM/Agent 的项目摘要 |
| [AGENTS.md](AGENTS.md) | 仓库协作规范（结构、命令、测试、沙箱约束） |

## 9. 机器可读索引（`project_index.json`）

结构（`schema = dramaclaw-project-index@1`）：

| 字段 | 内容 |
|---|---|
| `project` | 名称、版本、Python 版本、许可证、CLI 入口 |
| `layout` | 顶层目录、docs、scripts、deploy、schemas、agent-kit 文件清单 |
| `backend.packages` | 每个子包的模块数 / 行数 / 文档首行 |
| `backend.modules[]` | 文件路径、模块名、docstring、行数、顶层 `classes` / `functions`（含行号）、内部 import 依赖 |
| `api.routes` | 按路由文件分组的 `method` / `path` / `handler` / `line` |
| `task_backend.runners` | runner 文件 → 注册的 task_type 与说明 |
| `frontend` | 框架版本、目录统计、路由文件、features 统计 |
| `tests.files[]` | 测试文件路径与测试函数名 |

查询示例：

```bash
# 找某个函数/类定义在哪个文件
python -c "import json;d=json.load(open('project_index.json',encoding='utf-8'));[print(m['path']) for m in d['backend']['modules'] if any(f['name']=='enqueue_project_task' for f in m['functions'])]"

# 列出 freezone 的所有端点
python -c "import json;d=json.load(open('project_index.json',encoding='utf-8'));[print(r['method'],r['path']) for r in d['api']['routes']['freezone.py']]"

# 某模块直接依赖了哪些内部模块
python -c "import json;d=json.load(open('project_index.json',encoding='utf-8'));[print(m['imports']) for m in d['backend']['modules'] if m['path'].endswith('task_backend/run_core.py')]"
```

## 10. 索引维护

- 新增/删除模块、路由、runner 后运行 `python scripts/build_project_index.py` 刷新 JSON。
- 本文件（`INDEX.md`）是人工维护的导航层；结构性数字（模块数、端点数）以 JSON 为准。
- 前端路由由 TanStack Router 依据 `frontend/src/routes/` 自动生成，`routeTree.gen.ts` 不要手改。
