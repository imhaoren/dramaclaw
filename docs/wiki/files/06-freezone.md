# Freezone 画布（`freezone/` 54 + `agent_workflows/` 5）

54 个文件、29,827 行。功能视角看 [09-画布Freezone](../09-画布Freezone.md)，这一篇按「存储 → 命令 → 节点 → Skill/Recipe → 工作流 → 提交 → 导入」分组讲文件。

---

## A. 存储、锁与版本（6）

#### `canvas_store.py` · 908 行 `[核实]`

**作用**：画布快照的持久化：版本、历史、软删、幂等、载荷上限、危险覆盖保护。

**接口**：`save_canvas()`、`save_canvas_async()`、`restore_canvas_version()`、`soft_delete_canvas()`、`list_canvases()`、`list_canvas_history()`、`load_canvas_idempotency()`、`check_dangerous_empty_overwrite()`、`prune_canvas_history()`；异常 `CanvasRevisionConflict`、`CanvasIdempotencyConflict`、`CanvasCorruptError`、`DangerousEmptyCanvasOverwrite`、`CanvasBaseRevisionRequired`。
**I/O**：读写 `freezone/canvases/*.json`、`_history/`、`_deleted/`、`_idempotency/`。
**注意**：载荷上限 5 MiB（`FREEZONE_CANVAS_PAYLOAD_LIMIT_BYTES`）；空画布覆盖非空画布会**直接拒绝**，这是防前端状态丢失后的自动清空。

#### `canvas_lock.py` · 82 行 `[核实]`

**作用**：单机画布写锁（`flock`）。

**接口**：`canvas_write_lock()`、`canvas_lock_path()`；异常 `CanvasLockBusy`。
**注意**：只在单机成立；多机必须走 `ports/canvas_mutex` 的分布式实现。

#### `history.py` · 379 行 `[核实]`

**作用**：**节点级**生成历史（不是画布版本历史）：每次生成的产物与参数。

**接口**：`append_generation_history()`、`read_generation_history()`、`read_canvas_generation_history()`、`prewarm_history_thumbnail()`、`build_node_history_record()`。
**注意**：与 `canvas_store` 的历史是两套；节点历史用于"重新选回上一次结果"。

#### `stale.py` · 33 行 `[核实]`

**作用**：stale 标记 sidecar 的读写（某 beat 的产物已过期）。

**接口**：`stale_marks_path()`、`load_stale_marks()`、`stale_marks_for_beat()`。
**注意**：stale 只标记不重生成；消费方是前端提示与批量重跑。

#### `paths.py` · 111 行 `[核实]`

**作用**：画布目录布局的唯一来源（`_uploads/`、`outputs/`、`canvases/`、`_canvas_events/`）。

**接口**：`freezone_root()`、`uploads_dir()`、`outputs_dir()`、`output_path_for_job()`、`canvas_path()`、`safe_upload_filename()`、`resolve_static_url_to_path()`。
**注意**：所有画布路径必须经它计算；`resolve_static_url_to_path` 是 URL→磁盘的唯一合法入口（含穿越防护）。

#### `canvas_static_urls.py` · 279 行 `[核实]`

**作用**：内存态 URL 迁移：把画布里指向旧项目域的地址改写成当前域。

**接口**：`migrate_canvas_static_urls_in_memory()`、`sanitize_project_local_paths_in_memory()`。
**注意**：只改内存不落盘，保存时才持久化；对跨项目 URL 不做改写（交给 `canvas_media_scope`）。

---

## B. 安全与作用域（5）

#### `canvas_media_scope.py` · 178 行 `[核实]`

**作用**：拒绝画布引用**别的项目**的媒体（否则换成其他成员打开就整片 403）。

**接口**：`scan_foreign_media_refs()`、`reject_new_foreign_media_refs()`；异常 `CanvasMediaScopeError`。
**注意**：只拒绝**新增**的跨项目引用，历史放行；跨项目粘贴要走 `asset_copy`。

#### `asset_copy.py` · 179 行 `[核实]`

**作用**：跨项目素材复制：把源项目文件复制成目标项目 `_uploads/` 下的新文件并重写 URL。

**接口**：`copy_project_file()`、`parse_project_asset_url()`、`allocate_target_path()`；异常 `AssetCopyError`。
**注意**：是"复制"不是"引用"——文件会占双份空间，但避免了跨项目权限问题。

#### `preview_media.py` · 49 行 `[核实]`

**作用**：HTML 产物的短期预览授权（签名 + 过期）。

**接口**：`project_key()`、`signature()`、`verify()`。
**注意**：签发需要用户权限，读取只看签名；不要把签名当成长期凭据。

#### `reference_validation.py` · 256 行 `[核实]`

**作用**：生成前校验本地参考媒体是否满足模型约束（格式、尺寸、数量），避免付费后失败。

**接口**：`validate_reference_config()`、`validate_reference_media()`、`normalize_format()`。
**注意**：与 `media_model_request_schema` 互补：一个校验媒体文件，一个校验请求参数。

#### `canvas_command_watch.py` · 321 行 `[核实]`

**作用**：worker 本地的桥接监听器：目录信号触发 + 周期性对账。

**接口**：`bridge_watch_hub()`、`BridgeWatchHub`、`DirectoryState`。
**注意**：信号是**有损提示**，真相在 SQLite；丢信号只影响延迟，不影响正确性。

---

## C. 命令桥（1）

#### `canvas_command_bridge.py` · 1,173 行 `[核实]`

**作用**：Agent ↔ 前端的持久化 Inbox/Outbox。四种消息：画布命令、画布上下文、Skill 工作室事件、澄清问题。

**接口**：`put_pending_canvas_command()`、`put_or_reuse_pending_canvas_command()`、`wait_canvas_command_result()`、`resolve_canvas_command()`、`mark_bridge_message_delivered()`、`expire_bridge_messages()`、`next_bridge_deadline()`、`read_bridge_snapshot()`；以及 `canvas_context_bridge_key()` / `skill_studio_bridge_key()` / `clarification_bridge_key()`。
**I/O**：读写项目库 `canvas_command_messages`（14 列）。
**注意**：
- 幂等键由 `canvas_command_idempotency_key()` 生成，重复投递不会重复执行；
- 租约（`lease_expires_at`）+ 投递次数（`delivery_attempts`）控制重投；
- `wait_*` 会阻塞后端调用（Agent 回合），必须配合超时与取消。

---

## D. 节点逻辑（5）

#### `jobs.py` · 3,033 行 `[核实]`

**作用**：画布「单图生成/编辑」与「视频后处理」的纯异步作业实现，被 runner 与路由共用。

**接口**：`run_freezone_gen()`、`run_freezone_edit()`、`run_freezone_mask_edit()`、`run_freezone_upscale()`、`run_freezone_video_upscale()`、`run_freezone_video_compose()`、`run_freezone_video_erase()`、`run_freezone_audio_separate()`、`run_freezone_extract_frames()`、`run_freezone_analyze_shots()`、`run_freezone_video_breakdown()`。
**注意**：这些函数**不做鉴权**（调用方已鉴权），但会做出网操作，必须带 egress 上下文。

#### `video_node.py` · 1,367 行 `[核实]`

**作用**：视频节点后端逻辑：运镜模板、分辨率/时长归一、提示词组装、全能参考校验、角色素材库。

**接口**：`get_video_camera_templates()`、`build_freezone_video_prompt()`、`build_freezone_omni_video_prompt()`、`validate_omni_reference_limits()`、`resolve_freezone_video_backend()`、`load/save_video_character_library()`。
**注意**：不同后端支持的时长/分辨率集合不同（`freezone_video_duration_bounds`），提交前归一，否则"生成失败但已扣费"。

#### `audio_node.py` · 1,039 行 `[核实]`

**作用**：音频节点：语音合成、音乐生成、用户音色库。

**接口**：`generate_freezone_audio_speech()`、`generate_freezone_audio_eleven_music()`、`resolve_speech_voice()`、`list_user_audio_voices()`、`create_user_audio_voice()`；异常 `VoicePrerequisiteError`。
**注意**：音色引用有"项目级/账号级"两种，历史数据迁移见 `scripts/convert_canvas_voice_refs.py`。

#### `text_node.py` · 744 行 `[核实]`

**作用**：文本节点：中英互译、自由文本生成、故事脚本生成（含视觉版）。

**接口**：`translate_freezone_text()`、`generate_freezone_text()`、`generate_freezone_story_script()`、`generate_freezone_story_script_with_vision()`、`bind_story_script_assets()`。
**注意**：视觉版会读参考图，成本更高；`bind_story_script_assets` 把脚本与画布资产绑定，改名会使绑定失效。

#### `mark_node.py` · 179 行 `[核实]`

**作用**：标记识别：识别画布图上用户框选/标记的意图。

**接口**：`detect_freezone_mark()`、`crop_mark_focus_image()`、`build_mark_detection_task()`。
**注意**：裁剪区域决定识别质量，框太小会看不清。

#### `image_node.py` · 78 行 `[核实]`

**作用**：图片节点唯一职责：反推提示词（图生文）。

**接口**：`reverse_prompt_from_image()`、`build_image_reverse_prompt_task()`。

#### `image_outputs.py` · 100 行 `[核实]`

**作用**：本地图像格式转换（GIF 转码、SVG 矢量化），可取消。

**接口**：`transcode_gif()`、`vectorize_image()`。

#### `video_slowdown.py` · 11 行 `[核实]`

**作用**：视频慢放倍率的共享常量，保证"报价"与"执行"用同一组倍率。

**接口**：`slowdown_factor()`。
**注意**：改倍率要同时影响计费与执行，改动前确认两边都读这里。

---

## E. Skill 与 Recipe（11）

#### `skill_registry.py` · 613 行 `[核实]`

**作用**：Skill 注册表与运行契约 schema。

**接口**：`SkillDefinition`、`SkillInputSpec`、`SkillRunRequest/Response`、`CanvasGraphPatch`、`list_skills()`、`get_skill()`。
**注意**：`CanvasGraphPatch` 是 Skill 改画布的唯一合法形式（增节点/增边/设参数），不允许直接改节点内容。

#### `recipe_runtime.py` · 842 行 `[核实]`

**作用**：把 catalog 里的 Recipe 编译成可执行节点 prompt（可批量、可并发、带超时）。

**接口**：`compile_recipe_prompt()`、`compile_recipe_prompt_batch()`、`generate_recipe_text()`、`compose_deterministic_prompt()`、`get_recipe_for_runtime()`。
**注意**：编译结果与 operation id 绑定（审计/计费）；编译失败要保留原因，不要静默回退到默认 prompt。

#### `agent_config_store.py` · 312 行 `[核实]`

**作用**：用户级 agent 配置存储（内置 catalog + 用户覆盖 + 项目覆盖）。

**接口**：`list_user_agent_config_items()`、`save_user_agent_config_item()`、`delete_user_agent_config_item()`、`builtin_agent_catalog_dir()`、`project_agent_catalog_dir()`。
**注意**：三层覆盖顺序（内置 < 用户 < 项目）；删除用户项会回落到内置，不是"消失"。

#### `agent_catalog_schema.py` · 336 行 `[核实]`

**作用**：catalog 的 Skill/Recipe schema 校验（触发条件、输入参数、评分、评审项）。

**接口**：`validate_agent_config_item()`、`validate_agent_skill_config()`、`validate_agent_recipe_config()`。
**注意**：schema 变更要让旧 catalog 继续通过校验，否则用户配置全废。

#### `agent_catalog_security.py` · 71 行 `[核实]`

**作用**：catalog 导入路径的共享安全检查（危险内容扫描）。

**接口**：`scan_agent_catalog_payload_for_unsafe_content()`。
**注意**：所有导入入口（bundle、skill import、用户配置）都要过它。

#### `agent_bundle_schema.py` · 156 行 `[核实]`

**作用**：社区 Skill Bundle 的 schema 与 semver 校验、许可证字段。

**接口**：`AgentSkillBundle`、`normalize_agent_bundle()`、`parse_semver()`。
**注意**：许可证是必填项（`AgentBundleLicense`），缺了不允许安装。

#### `agent_bundle_store.py` · 287 行 `[核实]`

**作用**：Bundle 的安装与导出（用户级）。

**接口**：`validate_agent_bundle()`、`install_agent_bundle()`、`export_agent_bundle()`、`current_dramaclaw_version()`。
**注意**：安装是"解包到用户目录"，同名会覆盖；导出带版本约束，跨大版本可能不兼容。

#### `skill_import.py` · 180 行 `[核实]`

**作用**：外部 Skill 来源的登记与转换检查点（来源只作为数据，不执行）。

**接口**：`create_record()`、`convert_record()`、`validate_analysis()`、`bind_task()`、`public_record()`。
**注意**：来源文件**永不执行**；转换过程落检查点，可断点续。

#### `skill_import_quality.py` · 463 行 `[核实]`

**作用**：转换质量流水线：结构审查、schema 校验、catalog 补水、门禁。

**接口**：`run_quality_pipeline()`、`gate()`、`review_schema()`、`normalize_generated_bundle()`。
**注意**：门禁失败要保留诊断（`append_diagnostic`），否则用户不知道哪一步不过。

#### `skill_import_retrieval.py` · 446 行 `[核实]`

**作用**：候选检索：从现有 catalog 里找可复用 Recipe，避免重复造。

**接口**：`find_candidates()`、`resolve_task_recipes()`、`recipe_summaries()`、`validate_recipe_verdict()`。
**注意**：检索只是候选，最终以完整定义为准（避免"摘要看起来像，实际不兼容"）。

#### `skill_import_capabilities.py` · 175 行 `[核实]`

**作用**：离线能力快照与候选工作流的非执行校验。

**接口**：`snapshot_capabilities()`、`validate_candidate_plan()`。
**注意**：校验不执行模型调用，只做契约层面判断。

#### `skill_import_contracts.py` · 149 行 `[核实]`

**作用**：导入过程的内部契约（审计产物，不是运行时 Skill）。

**接口**：`RecipeDecision`、`ConversionDesign`、`BundleReview`、`validate_bundle_review()`、`content_hash()`。
**注意**：这些模型只用于审计与断点，不要当运行时数据结构用。

#### `skill_import_evidence.py` · 113 行 `[核实]`

**作用**：来源分析的无损证据（原文片段 + 引用回填）。

**接口**：`segment_source()`、`hydrate_segment_quotes()`、`SourceSegment`。
**注意**：证据用于回溯"这个 Skill 是从哪段文档推出来的"，不要裁剪原文。

#### `skill_import_budget.py` · 130 行 `[核实]`

**作用**：单次导入的模型调用预算（次数/token），超限抛 `ImportBudgetExceeded`。

**接口**：`ImportBudget`、`is_transient_model_error()`。
**注意**：预算是"防跑飞"的硬闸，不要为了提高成功率无限调大。

---

## F. 工作流（12）

#### `workflow_schema.py` · 912 行 `[核实]`

**作用**：可移植的 Workflow JSON Schema（前后端/多 Agent 共享的稳定 envelope）。

**接口**：`workflow_plan_json_schema()`、`workflow_intent_json_schema()`、`normalize_workflow_tool_arguments()`、`workflow_plan_schema_diagnostics()`。
**注意**：schema 是契约，改它要跑 `scripts/generate_workflow_contract.py` 重新生成两端常量。

#### `workflow_contract_generated.py` · 89 行 `[核实]`

**作用**：从 `schemas/workflow/v1/stable-contract.json` 生成的常量。
**注意**：**不要手改**，改源 JSON 后重新生成。

#### `workflow_plan.py` · 1,002 行 `[核实]`

**作用**：Agent 编写的 WorkflowPlan 的严格校验（步骤、参数类型、文本边规则）。

**接口**：`validate_workflow_plan()`。
**注意**：校验失败要给出可修复的诊断，而不是"invalid plan"。

#### `workflow_semantics.py` · 72 行 `[核实]`

**作用**：稳定文本边规则（哪些节点输出能连到哪些输入），供计划校验与命令编译共用。

**接口**：`text_edge_error()`。
**注意**：这里是"同一规则两处使用"的唯一实现，不要在别处复制判断。

#### `workflow_preflight.py` · 1,163 行 `[核实]`

**作用**：运行前确定性预检：模型是否可用、参数是否兼容、是否需要澄清。

**接口**：`evaluate_workflow_preflight()`、`resolve_generation_recommendations()`、`preflight_failure_blocker()`、`generation_clarification_request()`。
**注意**：预检要"宁可多问一句"——错误参数跑到计费阶段损失更大。

#### `workflow_runs.py` · 1,745 行 `[核实]`

**作用**：工作流运行账本：创建、认领、续租、动作状态、错误分类、对账、裁剪。

**接口**：`create_workflow_run()`、`claim_workflow_media_action()`、`renew_workflow_media_claim()`、`update_workflow_run()`、`classify_workflow_error()`、`reconcile_workflow_runs_with_tasks()`、`interrupt_stale_workflow_runs()`；异常 `WorkflowRunLeaseConflict`、`WorkflowRunIdempotencyConflict`。
**注意**：`classify_workflow_error()` 的 `retryable` 决定是否自动重试；不要把 provider 计费错误标成可重试。

#### `workflow_run_actions` 相关（同文件）

**作用**：每个 (run, node, action) 的状态机：`pending → running → succeeded/failed`，含 `retry_count`、`error_fingerprint`。
**注意**：`error_fingerprint` 用于聚合重复失败，改算法会让历史聚合断层。

#### `workflow_drafts.py` · 723 行 `[核实]`

**作用**：工作流草稿（用户确认前不执行）。

**接口**：`create_workflow_draft()`、`patch_workflow_draft()`、`claim_workflow_draft_confirmation()`、`finish_workflow_draft_confirmation()`、`prune_expired_workflow_drafts()`。
**注意**：草稿确认是**一次性认领**（claim），并发确认只有一个成功。

#### `workflow_transactions.py` · 539 行 `[核实]`

**作用**：无模型调用、无画布写入的确定性准备/修订（绑定输入、改步骤）。

**接口**：`bind_workflow_inputs()`、`update_workflow_steps()`、`prepare_workflow_source()`、`revise_workflow_source()`；异常 `WorkflowOperationError`。
**注意**：这一层必须保持"纯"，否则重放会不一致。

#### `workflow_observation.py` · 101 行 `[核实]`

**作用**：运行进度摘要与保守恢复决策（不给执行权）。

**接口**：`summarize_workflow_run()`。
**注意**：恢复决策偏保守（宁可重跑一步），避免跳过依赖。

#### `workflow_external_inputs.py` · 84 行 `[核实]`

**作用**：把声明的外部输入解析到已鉴权的画布快照上。

**接口**：`resolve_external_image_inputs()`。
**注意**：解析要过 `canvas_media_scope`，否则会引入跨项目媒体。

#### `workflow_planning.py` · 22 行 `[核实]`

**作用**：把"规划"与"Recipe 执行"分开的提示词/指令常量。
**注意**：只有常量，但它是"Agent 先规划后执行"策略的落点。

#### `clarifications.py` · 55 行 `[核实]`

**作用**：服务端拥有的澄清载荷（如视频模型约束调整），API 与 MCP 共用。
**注意**：文案与选项在服务端生成，前端只渲染。

---

## G. 提交回主线（1）

#### `slots.py` · 509 行 `[核实]`

**作用**：22 个正式资产槽位的定义与提交流程（校验 → 备份 → 写入 → 同步索引 → 标记 stale）。

**接口**：`slot_target_path()`、`validate_source_for_slot()`、`backup_slot_if_exists()`、`sync_slot_after_write()`、`compute_slot_impact()`、`record_slot_stale_marks()`、`slot_asset_key()`；22 个 `*Target` 类。
**注意**：
- `PushTargetKind`（前端 19 个可推送类型）必须与这里同步；
- 提交是**覆盖式**的，所以先备份；
- `compute_slot_impact` 不自动重生成，只标 stale——这是成本控制的关键。

---

## H. 其他（5）

#### `presets.py` · 5,318 行 `[核实]`

**作用**：预设画布构建器：按项目/集/beat/资产上下文生成预填充画布（含节点、连线、参考图）。

**接口**：`build_canvas_payload_from_context()`、`build_beat_preset_context()`、`build_episode_preset_context()`、`build_asset_preset_context()`、`prepare_freezone_vision_egress()`。
**注意**：文件巨大但逻辑是"拼装"，不调模型（视觉 egress 除外）；`PresetRef.role` 与 `PushTargetKind` 是两套枚举，别混。

#### `route_helpers.py` · 811 行 `[核实]`

**作用**：从 `routes/freezone.py` 抽出的纯辅助：提示词拼装、尺寸解析、任务启动、路径推断。

**接口**：`build_camera_prompt()`、`merge_prompt_with_style_and_camera()`、`start_freezone_gen_job()`、`resolve_upscale_dimensions()`、`infer_scene_id_from_master_path()`。
**注意**：这里**不应有**鉴权与 DB 事务，保持"可单测"。

#### `agent_product_operations.py` · 778 行 `[核实]`

**作用**：Agent 触发的可计费产物的 operation 账本（幂等、绑定任务、结算、取消）。

**接口**：`create_agent_product_operation()`、`finish_agent_product_operation()`、`cancel_pending_agent_product_operation()`、`terminalize_undelivered_agent_product_task()`；异常 `AgentProductSettlementPending`。
**注意**：结算未完成时**不能返回成功**，否则会出现"生成成功但没扣费"。

#### `html_artifacts.py` · 723 行 `[核实]`

**作用**：HTML 产物的原子发布、版本、历史与本地导出。

**接口**：`ArtifactStore`；异常 `ArtifactConflict`、`PreviewTooLarge`。
**注意**：产物是**不可变文件**（每次新 revision），恢复是切指针而不是改文件。

#### `vision_gateway.py` · 266 行 `[核实]`

**作用**：画布视觉理解任务的共享 NewAPI 传输（图片 → 描述/标记）。

**接口**：`call_freezone_vision_model()`、`load_compact_vision_inputs()`、`resolve_freezone_vision_model()`。
**注意**：输入图片会压缩（`load_compact_vision_inputs`），过小会看不清细节。

#### `style_templates.py` · 137 行 `[核实]`

**作用**：短剧风格模板清单加载与兜底（正文在 `style_templates.json`，随包发布）。

**接口**：`load_style_templates()`、`get_style_manifest_version()`、`reset_style_template_cache()`；异常 `StyleManifestError`。
**注意**：运维换风格库通过 `STYLE_GALLERY_MANIFEST` 指向新清单。

#### `__init__.py` · 6 行 `[核实]`

**作用**：包声明。

---

## I. `freezone/agent_workflows/`（5）

#### `catalog.py` · 5,102 行 `[核实]`

**作用**：Workflow Skill 目录解析与 Agent 计划校验：标准阶段、阶段边、Recipe 规范化、模板同构判定。

**接口**：`get_workflow_skill()`、`compile_workflow_intent()`、`validate_agent_workflow_plan()`、`standard_skill_stages()`、`template_isomorphism()`。
**注意**：这是"计划 → 可执行"的判定核心；`skill_stage_blockers()` 的拒绝理由要能指导修复。

#### `graph.py` · 915 行 `[核实]`

**作用**：把工作流图计划编译成前端画布命令。

**接口**：`build_workflow_graph_commands()`、`validate_workflow_graph_commands()`。
**注意**：编译产物要满足前端 `canvasCommandValidator` 的约束，改格式要两端同改。

#### `drafts.py` · 149 行 `[核实]`

**作用**：Agent 无关的草稿补丁与公开视图。

**接口**：`build_workflow_draft_patch()`、`public_workflow_draft()`。
**注意**：`public_*` 会裁剪敏感字段，别用它做内部用途。

#### `registry.py` · 140 行 `[核实]`

**作用**：Agent 无关的 Skill/Recipe 检索（按关键词/标签）。

**接口**：`search_catalog()`、`search_catalog_items()`、`get_catalog_item()`、`CatalogSearch`。
**注意**：检索结果可能为空（未安装 catalog），调用方要能降级。

#### `__init__.py` · 6 行 `[核实]`

**作用**：包声明（说明这些模块被 API/MCP/前端共享）。
