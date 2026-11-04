# Chat 与 Agent 运行时（`src/novelvideo/chat/`，32 个）

这一包把三种 Agent 后端、会话存储、事件映射、工具策略、命令回执撮合在一起。功能视角见 [08-Agent与对话](../08-Agent与对话.md)。

---

## A. 核心服务（4）

#### `service.py` · 5,858 行 `[核实]`

**作用**：对话服务门面。会话/历史/线程状态、回合编排、后端选择、流式回包、中断。

**接口**：`stream_assistant_reply()`、`generate_assistant_reply()`、`prewarm_chat_backend()`、`interrupt_chat_turn()`、`list_messages()`、`add_user_message()`、`add_assistant_message()`、`is_*_backend_available()`、`get_chat_backend_name()`、`authorize_hermes_launch()`、`force_release_chat_run_lock()`。
**I/O**：读 `chat.db`（消息/设置/事件）→ 调后端适配器 → 写消息与事件。
**依赖**：`chat/` 下几乎所有模块 + `freezone/workflow_plan` + `ports`。
**注意**：
- `_chat_backend()` **不回退**：指定 codex/hermes 不可用直接抛错，这是有意设计；
- 回合内所有异常都要保证释放锁（`finally`）；
- 文件近 6 千行，新增能力优先落到独立的 `chat/*.py`，别再往里堆。

#### `runtime_port.py` · 72 行 `[核实]`

**作用**：后端无关的运行时契约：事件、结果、线程端口。

**接口**：`ChatBackendEvent`、`ChatRunResult`、`AgentRuntimeThreadPort`。
**注意**：三个后端都要满足这个契约；新增事件类型要同时改 `runtime_event_mapper` 与前端。

#### `execution_context.py` · 84 行 `[核实]`

**作用**：一次回合的**服务端权威**身份与策略载体（用户、项目、可见工具、计费主体）。

**接口**：`AgentExecutionContext`。
**注意**：前端传的 scope 只用于定位，授权一律以这里为准；不要把前端字段直接塞进来。

#### `session_registry.py` · 457 行 `[核实]`

**作用**：会话锁与线程映射的文件化管理：谁在跑、跑了多久、心跳、闲置判定。

**接口**：`acquire_chat_run_lock()`、`release_chat_run_lock()`、`heartbeat_chat_run_lock()`、`chat_run_lock_is_active()`、`codex_scope_key()`、`load/save_agent_session_state()`、`get/set_codex_thread_id()`。
**I/O**：读写 lock 目录下的锁文件与 session state 文件。
**注意**：锁是文件锁 + 心跳，跨进程有效；**僵死锁**要等心跳超时或 `force_release_chat_run_lock`，后者会打断真实运行中的回合。

---

## B. 后端适配器（7）

#### `backend_sdk.py` · 1,975 行 `[核实]`

**作用**：Claude（SDK/CLI）与 Codex 的客户端与线程封装，以及"活跃客户端注册表"（用于中断）。

**接口**：`ClaudeSdkClient`/`ClaudeSdkThread`、`ClaudeCliClient`/`ClaudeCliThread`、`CodexClient`/`CodexThread`、`register_live_codex_turn()`、`interrupt_live_codex_turn()`、`consume_interrupted_*`。
**注意**：注册表是**进程内**的，多 worker 部署时中断只对当前进程有效——这是已知限制。

#### `codex_app_server.py` · 831 行 `[核实]`

**作用**：共享 Codex App Server 进程的生命周期管理（每 home node 一个进程）。

**接口**：`shared_codex()`、`stop_shared_codex_runtime()`、`restart_shared_codex_runtime_when_idle()`；异常 `CodexRuntimeError`。
**注意**：进程崩了影响该节点上所有项目；重启只在空闲时进行，避免打断回合。

#### `codex_app_server_windows.py` · 173 行 `[核实]`

**作用**：Windows 下的 App Server 传输：私有目录、命名管道/Unix socket 兼容、pid 存活判断。

**接口**：`connect_unix_socket()`、`private_control_root()`、`pid_alive()`、`current_user_sid()`。
**注意**：仅 Windows 分支使用；权限按 SID 隔离，换用户运行会读不到控制目录。

#### `hermes_sdk.py` · 1,580 行 `[核实]`

**作用**：Hermes 后端适配：ACP（Agent Client Protocol）over stdio，事件解析与工具调用桥接。

**接口**：`HermesSdkClient`、`HermesSdkThread`；异常 `HermesSessionUnavailableError`。
**注意**：ACP 事件形态不稳定，解析集中在 `hermes_events.py`，升级 Hermes 先看那里。

#### `hermes_pool.py` · 1,348 行 `[核实]`

**作用**：每用户每 agent profile 至多一个 Hermes 客户端，会话在其上复用；网关指纹变化时重建。

**接口**：`HermesPool`、`is_hermes_backend_available()`、`canvas_bridge_dir_for_profile()`、`gateway_origin_fingerprint()`；异常 `HermesDrainingError`、`GatewayOriginMismatch`。
**注意**：`GatewayOriginMismatch` 是"改了网关配置"的直接信号；改配置后必须重开会话。

#### `hermes_workspace.py` · 1,418 行 `[核实]`

**作用**：幂等物化 `state/<user>/.hermes/`：插件、技能、hook 目录、网关指纹。

**接口**：`ensure_user_hermes_workspace()`、`sync_freezone_hermes_workflow_skills()`、`effective_gateway_fingerprint()`。
**注意**：工作区是"幂等重建"而非增量，手改里面的文件会在下次被覆盖。

#### `hermes_fork_requirement.py` · 158 行 `[核实]`

**作用**：强制 DramaClaw 与 Hermes fork 成对安装。

**接口**：`require_hermes_fork()`、`hermes_fork_is_installed()`；异常 `HermesForkMissing`。
**注意**：硬错误，不是警告；缺 fork 时 Hermes 后端起不来。

#### `hermes_egress.py` · 245 行 `[核实]`

**作用**：为每个 Hermes 回合申请出网授权并构造子进程环境（凭据不落盘）。

**接口**：`authorize_credentialed_hermes()`、`build_hermes_child_env()`、`HermesTurnAuthorization`。
**注意**：授权按回合发放，跨回合复用会失效；子进程环境变量里含模型凭据，不要打日志。

#### `hermes_operation.py` · 140 行 `[核实]`

**作用**：回合结束时关闭出网操作（成功/失败/未知三种处置）。

**接口**：`TurnOperationFinalizer`、`disposition_for()`。
**注意**：`unknown` 是有意义的状态（外部可能已执行），不能当成失败处理，否则会重复调用。

#### `hermes_events.py` · 127 行 `[核实]`

**作用**：ACP 事件形状知识：工具调用 id、生命周期更新、瞬时失败判定。

**接口**：`session_update_kind()`、`tool_call_id()`、`is_transient_tool_failure()`、`contains_freezone_canvas_bridge_result()`。
**注意**：只有 Hermes 适配器该依赖它；其他地方别直接解析 ACP 原始结构。

---

## C. 存储（3）

#### `store.py` · 1,236 行 `[核实]`

**作用**：作用域化对话持久化（React WS 与旧 NiceGUI 共用）。

**接口**：`ChatStore`、`ChatScope`；按 scope 解析 `chat.db` 路径（home / project / canvas / surface）。
**I/O**：读写 `chat_messages`、`chat_settings`、`chat_ui_events`。
**注意**：删项目不自动删 home 会话；画布会话按 `canvas_id` 分库，画布删了库还在（需清理脚本）。

#### `message_repository.py` · 208 行 `[核实]`

**作用**：旧版项目聊天库的读写与迁移。

**接口**：`migrate_legacy_chat_db()`、`append_message()`、`replace_trace_messages()`、`history_contents()`、`get_setting()`/`set_setting()`。
**注意**：新旧两套存储并存，迁移函数只跑一次；混用会导致消息"时有时无"。

#### `live_events.py` · 68 行 `[核实]`

**作用**：服务端主动消息的实时扇出（注册 WS、广播事件）。

**接口**：`register_chat_websocket()`、`broadcast_project_chat_event()`。
**注意**：best-effort，失败不重试；关键状态必须落库，不能只靠广播。

---

## D. 事件、呈现与证据（8）

#### `runtime_event_mapper.py` · 86 行 `[核实]`

**作用**：把后端事件映射成对话流的公共形状（只构造 payload，不做 IO）。

**接口**：`lifecycle_event()`、`progress_event()`、`sdk_tool_event()`。
**注意**：前端依赖这些形状，改字段等于改协议。

#### `presentation_mapping.py` · 512 行 `[核实]`

**作用**：工具结果 → UI spec 的纯映射与变换。

**接口**：模块级映射函数（按工具名分派）。
**注意**：纯函数，最容易单测；新增工具要在这里加映射，否则前端只能显示原始 JSON。

#### `presentation.py` · 320 行 `[核实]`

**作用**：供应商无关的 UI-spec 处理：解析（容忍尾部截断）、规范化、合并、去重、从文本中拆分。

**接口**：`canonicalize_ui_spec()`、`merge_ui_specs()`、`split_ui_specs_from_text()`、`json_loads_with_trailing_repair()`。
**注意**：`json_loads_with_trailing_repair` 是给"模型输出被截断"兜底的，不要用它掩盖真实的格式错误。

#### `presentation_text.py` · 253 行 `[核实]`

**作用**：文本呈现：增量拼接、去重、截断、占位符替换。
**注意**：流式增量可能出现重复片段，去重逻辑在这里而不是前端。

#### `media_presentation.py` · 263 行 `[核实]`

**作用**：对话里媒体链接的规范化与去重（同一素材只展示一张卡片）。

**接口**：模块级 `media_*` 辅助。
**注意**：依赖 `utils/static_urls`，URL 规则变了这里要同步。

#### `display_fallback.py` · 825 行 `[核实]`

**作用**：模型没给结构化结果时，从权威数据重建展示（读 DB/文件补全画面信息）。

**注意**：这是"兜底展示"，不是数据源；它读 DB 意味着可能比对话内容更新，注意时间语义。

#### `runtime_event_evidence.py` · 551 行 `[核实]`

**作用**：从运行时事件里归一化「这次工具调用是否真的成功」的证据判定。

**注意**：判定规则变严会让 `HALTING` 计数上升，属预期；不要为了"绿灯"放宽。

#### `evidence_metrics.py` · 132 行 `[核实]`

**作用**：证据面计数器（`evidence_counters` 表）+ 报告格式化。

**接口**：`observe()`、`counters()`、`halting_counts()`、`format_report()`。
**注意**：`HALTING` 集合必须恒为 0，非零代表"不可信证据/越界出网"。

#### `canvas_outcome.py` · 178 行 `[核实]`

**作用**：画布操作的最终回复契约：必须带 receipt 才能声称完成。

**接口**：`receipt_reference()`、`finalize_canvas_reply()`、`needs_canvas_format_repair()`。
**注意**：这是防"Agent 假装画好了"的闸门，绕过它会产生空画布却显示成功。

---

## E. 工具、MCP 与策略（4）

#### `tool_policy.py` · 184 行 `[核实]`

**作用**：按 surface 与 agent profile 裁剪工具集。

**接口**：`tool_mode_for_surface()`、`surface_context_has_freezone_canvas()`、`freezone_canvas_execution_mode_from_context()`、`allows_mainline_media_ui_specs()`、`is_hidden_chat_tool_event()`。
**注意**：工具先裁剪再给模型，不是"给了让模型自己克制"；新增危险工具必须在这里加限制。

#### `dramaclaw_mcp.py` · 944 行 `[核实]`

**作用**：DramaClaw 工具的 MCP 服务器（给 Claude/Codex 等通用客户端）。

**接口**：`list_tools()`、`call_tool()`、`list_resources()`、`read_resource()`、`main()`。
**注意**：工具 schema 从 `_agent_tools()` 生成，scope 过滤在生成时完成；Hermes 不走这里（它用插件目录）。

#### `workflow_mcp.py` · 578 行 `[核实]`

**作用**：共享 Workflow Skill / Recipe 的 MCP 服务器，**只读 + 编译**。

**接口**：`list_tools()`、`call_tool()`、`read_resource()`。
**注意**：刻意不给执行权——执行由前端画布完成，避免 Agent 直接改用户画布。

#### `runtime_history.py` · 120 行 `[核实]`

**作用**：解析 Codex 历史条目（不依赖 chat 存储与媒体查询）。

**接口**：`parse_codex_history_item()`。
**注意**：用于重建上下文；解析失败要降级为纯文本，不能整段丢弃。

---

## F. 自动模式（1）

#### `director_auto.py` · 1,067 行 `[核实]`

**作用**：虾导整集自动模式的持久化协调器：按阶段推进、等任务完成、可暂停/恢复。

**接口**：`DirectorAutoCoordinator`、`DirectorAutoStore`、`DirectorAutoRun`；表 `director_auto_runs`。
**I/O**：读写 `state/<user>/director_auto.db`；查询 `task_states` 判断阶段完成。
**注意**：
- 状态落库才能跨进程重启续跑，别改成内存状态；
- 遇到需要人工决策的步骤会挂起（不替用户选），这是设计而非卡住；
- `handled_task_ids` 是去重关键，重复处理会导致重复计费。

#### `__init__.py` · 3 行 `[核实]`

**作用**：包声明。
