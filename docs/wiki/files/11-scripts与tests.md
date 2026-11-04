# 11 · 脚本与测试（scripts/ + tests/）

> 覆盖范围：`scripts/` 全部 36 个文件、`tests/` 全部 468 个 `.py`。
> 对应功能文档：[11-脚本运维与备份](../11-脚本运维与备份.md)、[12-测试体系](../12-测试体系.md)。
> 本篇是**逐文件条目**：每个脚本标注类型/入口/前置/副作用/该不该手动跑；每个测试目录与文件给出覆盖对象。

## 元信息

| 项 | 值 |
| --- | --- |
| `scripts/` 文件数 | 36（27 `.py` + 6 `.sh` + 2 `.json` + 1 `Dockerfile`） |
| `scripts/` 可执行 | 33 |
| `tests/` 文件数 | 468 个 `.py`（431 个根级 `test_*.py` + 19 ports + 11 contract + 1 compliance + 6 支撑文件） |
| 前端测试 | 536 个（见 [files/10 §15](10-前端文件.md)） |
| 统计方式 | `find scripts -type f`、`find tests -name '*.py'` |

---

## 1. `scripts/` 总览：三类东西，别混

| 类别 | 数量 | 特征 | 该不该手动跑 |
| --- | ---: | --- | --- |
| **启动器** | 3 | 长期运行/装环境 | ✅ 日常用 |
| **CI 门禁** | 11 | 命中即 exit 非 0，零容忍 | ❌ 只该 CI 跑，本地跑用来提前发现 |
| **生成 / 迁移 / 诊断** | 19 | 一次性或按需 | ⚠️ 看 §4–§7，多数有破坏性 |

混淆的后果：把 `migrate_docker_output.py` 当启动脚本跑会搬走线上数据目录；把 `lint_ee_terms.py` 加进启动流程会让服务起不来。

---

## 2. 启动器（3 个 `.sh`）

### `start-ce.sh` `[核实]`

| 项 | 内容 |
| --- | --- |
| 作用 | 本地起 CE 版 API + 打包好的前端（单进程） |
| 入口 | `bash scripts/start-ce.sh` |
| 输入 | 环境变量：`NOVELVIDEO_API_PORT`（默认 **8780**）、`ST_EDITION`、模型相关 `*_MODEL` |
| 输出 | 前台运行，日志到 stdout |
| 依赖 | `.venv`、`frontend/dist`（未构建则前端 404） |
| 副作用 | 创建/初始化 SQLite 数据目录 |
| 注意 | 端口默认 **8780**（不是 8000）；改了端口要同步 `frontend` 的 `VITE_API_BASE` 或反代配置 |

### `setup-codex.sh` `[核实]`

| 项 | 内容 |
| --- | --- |
| 作用 | 解析宿主原生的、凭据安全的 Codex 运行时 |
| 输出 | **只把路径打到 stdout**（供脚本捕获） |
| 来源 | 从 `claymorelab/codex` commit `27f7ff4d5c45...` 发布 |
| 注意 | 输出约定是「只有一行路径」，任何额外的 echo 都会破坏调用方的 `$(...)` 捕获 |

### `setup-hermes.sh` `[核实]`

| 项 | 内容 |
| --- | --- |
| 作用 | 安装或校验 DramaClaw 需要的 Hermes fork |
| 关键约束 | **不从 PyPI 装**。上游 release 与 fork 版本号相同，但会丢掉每轮凭据所依赖的 `_meta` 扩展，装了 PyPI 版会导致每一轮对话都掉凭据 |
| 注意 | 这是 [08-Agent与对话 §Hermes](../08-Agent与对话.md) 里「Hermes 走 fork」这条约束的落地脚本 |

---

## 3. CI 门禁（11 个）：命中即失败

全部为**硬零**（zero-tolerance）：不做 baseline 留存、不做「本次新增才算」，命中就 `exit 1`。

| 脚本 | 检查什么 | 为什么必须有 | 豁免机制 |
| --- | --- | --- | --- |
| `check_dco.py` | PR 范围内每个 commit 必须带 `Signed-off-by` trailer | 合规审计要求 | 无（必须补签） |
| `check_dependency_licenses.py` | 依赖树不得出现强 copyleft（GPL / AGPL / SSPL） | 本仓以 Elastic-2.0 闭源分发，传染性许可证会波及整仓 | 弱 copyleft（LGPL 等）单独放行 |
| `lint_ee_terms.py` | 代码/注释/docstring/文档/配置中不得出现 EE 包名 | CE 仓库不能泄露 EE 边界 | 无 |
| `lint_ce_imports.py` | AST 扫描 `src/novelvideo/**/*.py`，不得 import 非本仓的模块（含顶层与惰性导入） | CE 必须能独立运行 | 无 |
| `check_ce_port_closure.py` | 端口闭合：`ST_EDITION=ce`、无 DSN 时，所有 `ports.*` 都由 `ports.local.*` 满足 | 保证 CE 不偷偷依赖外部适配器 | 无 |
| `check_dco.py`（见上） | — | — | — |
| `check_env_config.py` | 每个 `.env.example` 的键都必须被"拥有它的运行时"真实读取 | 防止文档里的变量是死变量 | 无 |
| `check_backend_i18n.py` | 后端面向用户的文案 i18n 棘轮（ratchet：只能减少不能增加） | 防止新增硬编码中文 | `scripts/backend_i18n_allowlist.json` |
| `check_frontend_i18n.py` | 前端硬编码中文文案棘轮 | 同上 | `scripts/frontend_i18n_allowlist.json` |
| `lint_banned_words.py` | 对外文本不得称本项目为「开源 / open source」 | Elastic-2.0 是 source-available，**不是**开源；错误表述有法律风险 | 无 |
| `check_workflow_agent_contracts.py` | Workflow MCP / Skills / Recipes 的**只读**端到端诊断 | 契约漂移会让 Agent 静默失效 | 无 |
| `ce_allowlist.py` | **不是门禁，是库**：统一加载 `ce-allowlist.toml` | 各 linter 的白名单收口到一处，不再各自硬编码 `SKIP_PATHS` / 行内标记 | — |

**棘轮（ratchet）语义** `[核实]`：`check_*_i18n.py` 的允许数量只能下降。你以为在「加一行豁免」，实际上是把棘轮往回放，CI 会用旧的更小值卡住你。修法只有两条——真正做完 i18n，或明确在 PR 里说明并同步收紧 allowlist。

**用法**（以 i18n 为例）

```bash
python scripts/check_backend_i18n.py            # 对照 allowlist 检查
python scripts/check_backend_i18n.py --update    # 重新生成 allowlist（会记录当前数量）
```

---

## 4. 生成 / 构建（4 个）

### `build_style_gallery.py` `[核实]`

| 项 | 内容 |
| --- | --- |
| 作用 | 把飞书导出的短剧风格素材转成 `style-gallery` 静态资源 + 风格清单 |
| 输入 | `--source`（飞书导出目录） |
| 输出 | 静态资源目录 + manifest JSON |
| 场景 | 新增风格模板时 |
| 注意 | 产物进仓库，运行前确认没有把无关素材一起带进去 |

### `generate_workflow_contract.py` `[核实]`

| 项 | 内容 |
| --- | --- |
| 作用 | 从**单一 JSON 源**生成各语言的 Workflow 契约常量 |
| 输出 | TS / Python 侧的常量文件 |
| 注意 | 生成物不要手改；改 JSON 源再重跑。手改会在下次生成时被覆盖，且两端不一致是静默错误 |

### `fetch_browser_models.py` `[核实]`

| 项 | 内容 |
| --- | --- |
| 作用 | 准备浏览器端推理（抠图、深度动作捕捉）的自托管资源目录 |
| 背景 | `transformers.js` 默认从 HuggingFace Hub 拉权重、从 jsDelivr 拉 onnxruntime wasm，国内网络基本不可用 |
| 输出 | 本地模型/wasm 目录 |
| 注意 | 体积大，不应进 git；生产需要它能被前端静态服务命中 |

### `publish_official_media_catalog.py` `[核实]`

| 项 | 内容 |
| --- | --- |
| 作用 | 把**不可变**的官方媒体目录与 manifest 发布到 OSS |
| 副作用 | 上传对象存储；发布后不可变（immutable） |
| 注意 | 重复发布会生成新版本而非覆盖；下线要单独处理 |

---

## 5. 一次性迁移 / 清理（5 个）：跑完就该退休

| 脚本 | 作用 | 破坏性 | 前置条件 |
| --- | --- | --- | --- |
| `convert_canvas_voice_refs.py` | 把存量画布节点里的**项目级**音色引用一次性改写为**账号级**引用（B2 §4 第 3 条：音色解析上移后，老画布仍留 `character_default` 等旧引用） | ⚠️ 改用户数据 | **先备份**；确认无旧 worker 在读 |
| `migrate_docker_output.py` | 把老 Docker 输出搬进持久化的 CE 数据卷 | ⚠️ 移动文件 | 停机；先备份目录 |
| `backfill_thumbnails.py` | 为早于缩略图特性的项目预生成缩略图变体 | 低（只增文件） | 无人访问时跑更好；请求路径**永不**按需生成（`[核实]` 设计如此） |
| `cleanup_html_artifact_exports.py` | 删除遗留的持久化 HTML 导出 ZIP | ⚠️ 删文件 | **必须等旧 worker 排空**，否则正在跑的任务会 404 |
| `bump_compose_default.py` | 改 compose 文件里某个变量的 `:-` 默认值（用法：`bump_compose_default.py <compose> <var> <value>`） | 低（改配置） | 无；但改完要 review diff |

**共同注意**：这 5 个脚本都不该出现在常驻流程里。它们没有幂等保证（`backfill_thumbnails` 相对安全），重复跑可能重复写。

---

## 6. 诊断 / 基准（6 个）

| 脚本 | 作用 | 要不要起服务 | 输出 |
| --- | --- | --- | --- |
| `analyze_hermes_requests.py` | 从 `request_dump` 文件分析 Hermes 每次调用的 token 消耗 | ❌ | 终端统计 |
| `benchmark_canvas_command_health.py` | 在大量 bridge 订阅者下压测真实 `/healthz` ASGI 中间件（**禁用 app lifespan** 以免启动副作用） | ✅ | 耗时数字 |
| `benchmark_canvas_command_watch.py` | 测本地空闲 bridge 的 IO 与事件循环延迟，**不需要**运行中的 API | ❌ | 延迟数字 |
| `benchmarks/skill_import_search.py` | 用合成的多样目录快照测有界 Recipe 检索 | ❌ | 召回/耗时 |
| `acceptance/api_coverage_report.py` | 从运行时 NDJSON trace 生成 markdown 的 API 覆盖率报告 | 需 trace | `*.md` |
| `acceptance/collect_canvas_push_evidence.py` | 收集 Linux/HTTP 灰度证据（**只读**，不记录凭据） | ✅ | 证据文件 |

`analyze_hermes_requests.py` 需要先开 tracing：设 `HERMES_DUMP_REQ...`（脚本 docstring 里给全名）才会产生 dump 文件。

---

## 7. `scripts/acceptance/`：模块验收体系

这是**手动/CI 都可跑**的验收执行器，与 `tests/` 的单测是两套东西：单测验证函数，验收验证「模块端到端可用」并留日志证据。

| 文件 | 作用 |
| --- | --- |
| `run.sh` | 验收执行器。用法 `scripts/acceptance/run.sh M01 ce` / `... M02 ee`。`ee` 模式需先起 PG/Redis 并设 `ST_CONTROL_PLANE_DSN`、`ST_REDIS_URL`。全程留日志到 `docs/oss-split/modules/` 对应的验收清单 |
| `checks/m05.sh` | M05（场景/草图/首帧）的 curl 冒烟，被 `run.sh` `source`，可用 `$MODE` / `$PORT` / `check` / `log`。对应 M05 文档 §1.5 端点归属清单与 §4 落盘检查 |
| `foss_only_e2e.sh` | M10-D FOSS_ONLY 手动闸：CE 小说 → MP4，LLM 用**真实 key**，媒体生成走 `--mock` |
| `Dockerfile.canvas-command-push` | 一次性 Linux 验收环境（**不是**应用/运行时镜像）。基础镜像为 `python:3.12-slim` 固定 digest，内含 `watchfiles`、`anyio`、`portalocker`、`rich`、`pytest`、`pytest-asyncio` |
| `api_coverage_report.py` | 见 §6 |
| `collect_canvas_push_evidence.py` | 见 §6 |

**`run.sh` 的关键设计** `[核实]`：`checks/*.sh` 是被 `source` 的片段而不是子进程，因此它们共享 `$MODE`/`$PORT` 与 `check`/`log` 函数。新增一个模块的检查，应该新建 `checks/mXX.sh` 并复用这两个函数，不要自己写一套断言与日志。

`scripts/compliance/generate_p0b_artifacts.py` 生成 P0-B 的许可证与依赖合规证据文件，对应测试 `tests/compliance/test_generate_p0b_artifacts.py`，`[待补]` 具体产物清单未展开。

---

## 8. 数据文件（2 个 JSON）

| 文件 | 作用 | 谁读 |
| --- | --- | --- |
| `backend_i18n_allowlist.json` | 后端 i18n 棘轮的允许清单 | `check_backend_i18n.py` |
| `frontend_i18n_allowlist.json` | 前端 i18n 棘轮的允许清单 | `check_frontend_i18n.py` |

两者都是**生成物**（`--update` 产出），不要手写。手写会破坏计数基线，下一次 CI 直接失败。

---

## 9. `tests/` 总览

```
tests/
├── conftest.py                 # 全局 fixture
├── test_*.py                   # 431  主体单测
├── ports/                      # 19   端口适配器契约测试
├── contract/                   # 11   模块级 API 契约（M01–M09 + L014）
├── compliance/                 # 1    合规产物测试
├── support/                    # 2    egress_ledger.py 等测试基建
├── fixtures/                   # 1    foss_only_short_novel.txt
├── data/                       # 1    control-context-vectors.json
├── sandbox_linux_check.sh      # Linux 沙箱探针（shell）
├── sandbox_linux_isolation.py  # 沙箱隔离验证
└── sandbox_smoke.sh            # 沙箱冒烟
```

合计 468 个 `.py`：431 + 19 + 11 + 1 = 462 个 `test_*.py`，加 `conftest.py`（根 + contract 各 1）、`ports/__init__.py`? 与 `support/__init__.py`、`support/egress_ledger.py`、`sandbox_linux_isolation.py` 等非 `test_` 文件共 6 个。

---

## 10. 根级 431 个测试：按前缀分组

文件名前缀即覆盖域。下表列 **40 个多文件域**（合计 349 个），其余 82 个单文件域见 §10.3。

### 10.1 主要域（≥4 个文件）

| 前缀 | 数量 | 覆盖对象 | 对应文档 |
| --- | ---: | --- | --- |
| `freezone` | 49 | 画布：存储、锁、命令桥、节点后端、技能、工作流、媒体作用域 | [09](../09-画布Freezone.md) / [files/06](06-freezone.md) |
| `api` | 46 | HTTP 端点：资产、音频、鉴权、角色、导出、配置、项目、风格… | [06](../06-HTTP-API参考.md) / [files/03](03-api路由.md) |
| `task` | 30 | 任务：后端、队列、信封、状态机、取消、超时、配额、结算 | [05](../05-任务系统.md) / [files/07](07-运行时与端口.md) |
| `chat` | 16 | 对话：WS、会话注册表、事件映射、错误持久化、作用域、预热 | [08](../08-Agent与对话.md) / [files/05](05-chat.md) |
| `project` | 12 | 项目：生命周期、ID 路由、名称校验、作用域、静态鉴权、依赖 | [04](../04-数据模型与SQLite表.md) |
| `seedance2` | 12 | Seedance2 视频：配置、模型、请求、提示词、音色、面板 | [files/08](08-领域与集成.md) |
| `workflow` | 12 | 工作流：计划、草案、预检、事务、观察、MCP、语义、稳定契约 | [09](../09-画布Freezone.md) |
| `hermes` | 10 | Hermes 后端：事件、fork 配对、池、workspace、操作账本、插件 | [08](../08-Agent与对话.md) |
| `canvas` | 8 | 画布横切：命令推送/流/桥、媒体作用域、场景引用、写回执兼容 | [09](../09-画布Freezone.md) |
| `media` | 8 | 媒体：归档、IO 探针、模型请求、读授权、中转、预检、缩略图 | [files/08](08-领域与集成.md) |
| `scene` | 8 | 场景：解析、构建续跑、环境契约、名称迁移、参考提示词、360 | [07](../07-生成流水线.md) |
| `skill` / `skill_import` | 8 | 技能导入：预算、能力、压缩分析、证据、质量、检索、基准 | [09 §Skill](../09-画布Freezone.md) |
| `brainclaw` | 7 | BrainClaw：能力签发、契约、控制上下文、端点密钥边界、运行时 | [files/01 §E](01-核心顶层模块.md) |
| `render` | 7 | 渲染：身份守卫、多视图参考、修复上下文、场景锚点、比例 | [07](../07-生成流水线.md) |
| `agent` | 6 | Agent：画布 revision 契约、目录搜索、执行上下文、kit、LLM 配置、产品操作 | [08](../08-Agent与对话.md) |
| `cognee` | 6 | Cognee：配置、episode 更新合并、失败契约、LLM 刷新、并发、store 关闭 | [files/08](08-领域与集成.md) |
| `video` | 6 | 视频：归档投递、计费、合成结果契约、池静态 URL、处理请求、提示词语言 | [07](../07-生成流水线.md) |
| `backup` | 5 | 备份：日常 DB、文件同步、恢复 CLI、作用域、WAL 迁移 | [11](../11-脚本运维与备份.md) |
| `episode` | 5 | 分集：资产绑定、runner、菜单归一、调色板 | [07](../07-生成流水线.md) |
| `newapi` | 5 | new-api 网关：渠道模型、上下文预算、图片/文本网关、provider 同步 | [files/01 §B](01-核心顶层模块.md) |
| `ce` | 4 | CE 守栏：allowlist、import lint、迁移测试棘轮、端口闭合 | 本篇 §3 |
| `character` | 4 | 角色：年龄组、提升服务、重命名级联、音色存储 | [07](../07-生成流水线.md) |
| `director` | 4 | 导演：auto、staging 形状预设、world 服务、staging prop AI | [files/08](08-领域与集成.md) |
| `html` | 4 | HTML 产物：预览媒体、工作流、意图 | [09 §HTML](../09-画布Freezone.md) |
| `identity` | 4 | 身份：规划器外观校验、角色提升、语言、runner 结果 | [07](../07-生成流水线.md) |
| `sqlite` | 4 | SQLite：pragma、schema 初始化、store、indextts2 迁移 | [04](../04-数据模型与SQLite表.md) |

### 10.2 次要域（2–3 个文件，合计 52）

| 前缀（数量） | 含义 |
| --- | --- |
| `asset`(3) `billing`(3) `codex`(3) `image`(3) `indextts2`(3) `org`(3) `pool`(3) `stage`(3) `structured`(3) | 资产编译器、计费、Codex App Server、图片、IndexTTS2、组织、资源池、阶段、结构化构建 |
| `authz`(2) `batch`(2) `cli`(2) `control`(2) `dramaclaw`(2) `feature`(2) `graph`(2) `p0`(2) `product`(2) `reference`(2) `sandbox`(2) `screenplay`(2) `sketch`(2) `wysiwyg`(2) | 授权、批处理、CLI、控制面、MCP/技能契约、feature 模型、图谱、P0 灰度、产品面、参考素材、沙箱、剧本、草图、所见即所得一致性 |

### 10.3 单文件域（82 个）

其余 82 个前缀各 1 个文件，是**点状回归测试**——每个都对应一次具体事故或一条硬约束。命名即说明：

`acceptance` `ai`（identity detector）`async`（路由存储）`auth`（契约快照）`background`（锚点服务）`block`（world 节点不可用）`build`（style gallery）`bump`（compose 默认值）`channel`（任务上限错误面）`compose`（episode audio source）`confirmed`（创意输入）`content`（adapter）`convert`（canvas voice refs 脚本）`dependency`（许可证门）`detected`（空标记）`display`（fallback 用 episode）`docker`（持久化配置）`ee`（术语 lint）`egress`（分发泄漏可诊断性）`env`（配置棘轮）`evidence`（指标）`fanout`（部分派发）`fetch`（browser models）`fish`（speech prompt 移除）`format`（check copy）`frontend`（i18n 扫描器）`global`（prop 标记颜色）`history`（资产模型模式）`ingest`（进度）`knowledge`（双轨流水线）`literal`（script writing audio type）`llm`（instrumentation 日志）`local`（运行时依赖隔离）`m10`（最终闸）`manual`（shots）`mcp`（CE owner）`migrate`（docker output 脚本）`model`（网关设置）`narrator`（主语义 / voice）`no`（nicegui 导入禁止）`openapi`（版本契约）`openresty`（上传上限）`pano`（sharp da2 加载）`path`（安全资产名）`prompt`（风格族群分层）`publish`（official media catalog）`queue`（kind 字面 lane）`recipe`（运行时）`ref`（image hash）`release`（feed）`request`（egress 绑定）`running`（任务授权不确定）`runtime`（env）`s3`（媒体中转）`setup`（codex）`source`（语言）`spa`（静态服务）`start`（CE codex 运行时）`storyboard`（提示词视觉权威）`style`（模板 manifest）`superpower`（模型配置）`system`（音色设置）`tasks`（stream list）`tool`（policy 契约）`transport`（重试禁用）`trusted`（任务结算解析）`undelivered`（退款结果）`upload`（消毒）`worker`（stderr 排空）`workspace`（不持网关密钥）`p0b`/`p0g4a…p0g4t`（灰度分片，13 个）

其中 `p0g4a`–`p0g4t` 是 **P0 灰度分片**：`model_core`、`image_egress`、`media_relay_handoff`、`video_egress`、`audio_egress`、`cognee_concurrent_egress`、`storage_control`、`ambient_egress_fallback`、`org_denial_refund_invariant`、`freezone_leaf_classification`、`egress_handle_kind_contract`、`grid_family_image_egress`、`scene_360_subprocess_egress`、`service_operation_exclusion`。这些名字连起来就是**出网（egress）治理的完整边界**。

---

## 11. `tests/ports/`（19）· 端口适配器契约

验证「端口 + 本地实现」这一对是否满足契约。这是 CE 能独立运行的证明。

| 文件 | 验证的端口 |
| --- | --- |
| `test_registry.py` / `test_registry_isolation.py` | 端口注册表、端口间隔离 |
| `test_access_local.py` / `test_project_access.py` / `test_product_surface_access.py` | 访问控制（项目/功能面） |
| `test_auth_local.py` / `test_authz.py` | 鉴权与授权 |
| `test_cancel_memory.py` / `test_tasks.py` / `test_task_projection_port.py` | 任务取消、任务端口、投影 |
| `test_credit_quote.py` / `test_usage_meter.py` / `test_usage_noop.py` | 积分报价、用量计量、空实现 |
| `test_egress.py` / `test_egress_operations.py` | 出网通道与操作 |
| `test_media_model_catalog_scope.py` / `test_model_credentials.py` | 媒体模型目录作用域、模型凭据 |
| `test_project_local_uniqueness.py` / `test_project_registry.py` | 项目本地唯一性、项目注册表 |

**注意**：这 19 个文件不只是单测，它们是 `_EE_REQUIRED_PORTS`（18 个 EE 必填端口，见 [02 §端口](../02-架构与分层.md)）的**行为规格**。新增端口必须同时在这里加契约测试，否则 CE 是否真能跑没有证据。

---

## 12. `tests/contract/`（11）· 模块级 API 契约

按模块里程碑（M01–M09）组织的路由契约测试，验证「端点的形状、状态码、错误体」不漂移。

| 文件 | 覆盖 |
| --- | --- |
| `test_m01_auth.py` | M01 鉴权 |
| `test_m02_projects.py` | M02 项目 |
| `test_m03_episodes_scripts_content.py` | M03 分集/剧本/内容 |
| `test_m03_task_completion.py` | M03 任务完成 |
| `test_m04_route_contracts.py` | M04 路由契约 |
| `test_m05_route_contracts.py` | M05 场景/草图/首帧 |
| `test_m06_route_contracts.py` | M06 路由契约 |
| `test_m07_tasks.py` | M07 任务 |
| `test_m08_chat_agent.py` | M08 对话/Agent |
| `test_m09_route_contracts.py` | M09 路由契约 |
| `test_l014_inline_task_backend_concurrency.py` | L014 内联任务后端并发 |

**契约测试与普通单测的区别** `[核实]`：契约测试断言**对外形状**（字段名、可空性、状态码），不关心内部实现。改内部实现时它会通过；改 API 形状时它必须一起改——这是有意的摩擦。

---

## 13. 支撑文件

| 文件 | 作用 | 注意 |
| --- | --- | --- |
| `tests/conftest.py` | 全局 fixture（临时项目目录、store、mock 网关、egress 账本） | 改它影响 431 个测试 |
| `tests/contract/conftest.py` | 契约测试专用 fixture | — |
| `tests/support/egress_ledger.py` | 出网账本测试基建（记录/断言出网调用） | egress 相关测试的公共依赖 |
| `tests/support/__init__.py` | 包标记 | — |
| `tests/fixtures/foss_only_short_novel.txt` | FOSS_ONLY 端到端用的短篇小说 | `foss_only_e2e.sh` 消费 |
| `tests/data/control-context-vectors.json` | 控制上下文测试向量（BrainClaw） | 改协议要同步更新 |
| `tests/sandbox_linux_isolation.py` | Linux 沙箱隔离验证 | 需要 Linux |
| `tests/sandbox_linux_check.sh` / `tests/sandbox_smoke.sh` | 沙箱探针与冒烟 | 需要 Linux，macOS/Windows 会 skip |

---

## 14. 「我改了 X → 跑什么」速查

| 改动位置 | 最小验证集 |
| --- | --- |
| `api/routes/freezone.py` | `pytest tests/test_freezone_*.py tests/test_canvas_*.py` |
| 任何路由文件 | `pytest tests/test_api_*.py tests/contract/` |
| 任务 runner | `pytest tests/test_task_*.py tests/test_freezone_*_backend.py` |
| `task_backend/` | `pytest tests/test_task_backend_*.py tests/test_queue_*.py` |
| `chat/` | `pytest tests/test_chat_*.py tests/test_hermes_*.py` |
| SQLite schema | `pytest tests/test_sqlite_*.py tests/test_project_lifecycle_storage.py` |
| `ports/` | `pytest tests/ports/ tests/test_ce_port_closure.py` |
| `utils/path_resolver.py` | `pytest tests/test_path_safe_asset_names.py tests/test_freezone_paths.py` |
| 计费 | `pytest tests/test_billing_*.py tests/test_*credit*.py` |
| `scripts/` 任一 linter | `pytest tests/test_ce_*.py tests/test_ee_terms_lint.py tests/test_dependency_license_gate.py` |
| 前端 | `npm test`（见 [files/10 §15](10-前端文件.md)） |
| 不确定 | `pytest tests/ -x -q`（全量，约需数分钟） |

---

## 15. 本篇的边界

1. **未逐个展开 431 个测试的断言内容**——只到「文件名 → 覆盖对象」粒度。单个测试内部想表达什么，读文件本身最快（本仓测试命名与 docstring 质量足够）。
2. **未统计用例数**（只统计文件数）。用例数随参数化变化，跑一次 `pytest --collect-only -q` 才是准确值。
3. **`scripts/compliance/` 与 `docs/oss-split/modules/` 的产物清单**未展开，标 `[待补]`。
4. **运行时长、覆盖率数字**未记录——依赖机器与数据，写死的数字会过期。
