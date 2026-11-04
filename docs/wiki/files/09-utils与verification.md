# Utils 与 Verification（69 个）

`utils/`（28）是纯工具；`verification/`（33 + CLI 8）是质量体系。后者是这套系统里最"像科研"的部分：有失败模式库、门禁、追踪与收敛记录。

---

## A. 路径与目录（6）

#### `path_resolver.py` · 839 行 `[核实]`

**作用**：所有资源路径的**唯一计算入口**。DB 里不存路径，只存 id/name，路径在这里按规则算出。

**接口**：`PathResolver`；`canonical_portrait_path()`、`compute_scene_master_path()`、`canonical_scene_360_path()`、`compute_identity_path()`、`compute_identity_costume_path()`、`compute_prop_reference_path()`、`resolve_render_grid_path()`、`resolve_sketch_grid_path()`、`compute_beat_director_env_only_path()`。
**注意**：
- 改任何命名规则等于让历史文件"消失"（记录还在，路径对不上）；
- `compute_*` 返回"应该在哪"，`canonical_*` 返回"实际在哪（含兼容旧布局）"——两者不可互换。

#### `project_paths.py` · 238 行 `[核实]`

**作用**：项目三类目录（output/state/runtime）的统一管理与迁移。

**接口**：`ProjectPaths`，`from_context()`、`.output_dir` / `.state_dir` / `.runtime_dir`；内部有 `LEGACY_STATE_ITEMS` / `LEGACY_RUNTIME_ITEMS` 迁移清单。
**注意**：迁移会跳过 `-wal`/`-shm`（由 `VACUUM INTO` 合并），手工搬目录会丢事务。

#### `static_urls.py` · 55 行 `[核实]`

**作用**：项目静态资源 URL 生成（`/static/projects/{project}/...`）。

**接口**：`project_static_url()`。
**注意**：URL 带项目段，改前缀会让所有已保存的画布/DB 里的旧 URL 失效。

#### `state_index_files.py` · 120 行 `[核实]`

**作用**：生成物索引的 sidecar JSON 读写（原子写 + 文件锁 + 旧路径兼容）。

**接口**：`resolve_state_index_path()`、`index_file_lock()`、`write_json_atomic()`、`ensure_state_index_from_legacy()`。
**注意**：索引是缓存不是真相；损坏可重建（`rebuild_pool_index`）。

#### `asset_names.py` · 174 行 `[核实]`

**作用**：资产名的路径安全约束——同一个 `name` 同时是 DB 主键、URL 段、目录名。

**接口**：`is_path_safe_asset_name()`、`path_safe_asset_name()`、`unique_path_safe_asset_name()`、`move_asset_dir()`。
**注意**：名字里出现 `/` 会三处同时坏；已存在的不安全名字由 `repair-asset-names` 命令修。

#### `derived_scenes.py` · 44 行 `[核实]`

**作用**：派生场景命名（`base_of`）与 id 解析。

**接口**：`compose_derived_scene_name()`、`derived_scene_ids()`、`resolve_base_of()`。
**注意**：派生场景共用母场景资产，改名会断开这层关系。

---

## B. 文本与剧本（7）

#### `screenplay_scene_parser.py` · 770 行 `[核实]`

**作用**：确定性剧本场景头解析器（行式、有状态）。

**接口**：`parse_scene_blocks()`、`parse_location_header()`、`is_scene_start_line()`、`split_screenplay_lines()`、`chinese_to_int()`、`ParsedSceneBlock`。
**注意**：对格式极敏感；这是所有"场景名/时段"推断的底座，改规则要跑一批真实剧本回归。

#### `screenplay_quality.py` · 653 行 `[核实]`

**作用**：导入前的剧本质量预检：场景头是否规范、可解析行占比、常见错误。

**接口**：`check_screenplay_import_quality()`、`assess_screenplay_scene_headers()`、`build_import_format_check()`、`ScreenplayQualityReport`。
**注意**：预检是"提示"不是"阻断"，除非质量低到无法解析。

#### `document_parsers.py` · 155 行 `[核实]`

**作用**：上传文档解析（txt/docx）与计费字数统计。

**接口**：`load_novel_text()`、`decode_novel_bytes()`、`parse_docx()`、`count_billable_novel_chars()`、`count_billable_text_chars()`；异常 `DocumentParseError`。
**注意**：计费口径与 `api/chapter_preview.py` 必须一致；编码猜测失败要报错而不是乱码入库。

#### `text_utils.py` · 75 行 `[核实]`

**作用**：文本清洗（去颜色词等）。
**接口**：`strip_color_words()`。
**注意**：用于把"红衣女子"这类描述从身份名里剥离，过度剥离会丢信息。

#### `source_language.py` · 148 行 `[核实]`

**作用**：生成文案的语种策略（检测 + 给模型的指令）。

**接口**：`detect_asset_language()`、`asset_language_instruction()`、`detect_episode_asset_language()`。
**注意**：语种变了会让提示词模板整体切换，是"隐式大改"。

#### `identity_resolver.py` · 191 行 `[核实]`

**作用**：`{{}}` 标记解析（新格式 `{{身份id}}` + 旧格式 `{{角色名}}` 兼容）。

**接口**：`resolve_marker()`、`resolve_visual_description_markers()`、`build_identity_to_char_map()`、`compute_char_tag()`。
**注意**：旧格式兼容是长期包袱；新增标记语法要在这里统一。

#### `identity_refs.py` · 177 行 `[核实]`

**作用**：角色改名时，把散落各处的 `identity_id` 引用一起改。

**接口**：`remap_identity_id()`、`remap_object_field()`、`remap_id_list()`、`remap_identity_markers()`。
**注意**：`identity_id = <角色名>_<身份名>`，角色名嵌在 id 里——所以改名**必须**走这里，不能只改 `characters.name`。

---

## C. 资产、媒体与网络（8）

#### `asset_resolver.py` · 586 行 `[核实]`

**作用**：渲染期参考资产的统一解析（角色/场景/道具 → 实际文件与元数据）。

**接口**：`AssetResolver`、`ResolvedAssetRef`。
**注意**：它把"业务引用"翻成"磁盘文件"，是渲染提示词与参考图列表的来源。

#### `background_anchor.py` · 209 行 `[核实]`

**作用**：beat 级背景锚点：id 规范化、路径解析、裁剪复制。

**接口**：`background_anchor_path()`、`copy_to_beat_selected_background()`、`crop_to_beat_selected_background()`、`infer_selected_background_source()`。
**注意**：只存 anchor id，路径实时算；换锚点会让已渲染 beat 视觉跳变。

#### `thumbnails.py` · 481 行 `[核实]`

**作用**：`/static` 图片的按需缩略图（变体、并发限制、预热、拒绝策略）。

**接口**：`ensure_thumbnail()`、`thumbnail_path()`、`fresh_thumbnail()`、`normalize_variant()`、`prewarm()`、`set_render_concurrency()`。
**注意**：缩略图缓存在 `runtime/`，清空后首次访问会变慢（不是丢图）。

#### `media_io.py` · 166 行 `[核实]`

**作用**：异步安全的媒体 IO：取音频时长、裁剪图片。

**接口**：`get_audio_duration()`、`get_audio_duration_async()`、`get_audio_durations_async()`、`crop_image_to_path()`。
**注意**：同步版本会阻塞事件循环，路由里用 async 版。

#### `media_download.py` · 93 行 `[核实]`

**作用**：有界内存、原子落盘的媒体下载。

**接口**：`download_to_path()`。
**注意**：先写临时文件再 rename，避免半个文件被当成成品。

#### `oss_client.py` · 387 行 `[核实]`

**作用**：OSS 预签名与上传（Seedance 人工审核媒体等）。

**接口**：`presign_get()`、`presign_or_upload_output()`、`object_matches_local()`、`maybe_presign_static()`。
**注意**：桶懒初始化；缺配置时返回 None 而不是抛错，调用方要判空。

#### `upload_safety.py` · 109 行 `[核实]`

**作用**：上传文件名清洗与流式限额写入（防路径穿越、防超限）。

**接口**：`sanitize_upload_filename()`、`stream_to_file_with_limit()`、`create_staged_upload_file()`、`is_safe_upload_target()`；异常 `UploadTooLargeError`。
**注意**：所有上传入口都要过它，包括画布 `_uploads`。

#### `ref_image_hash.py` · 91 行 `[核实]`

**作用**：参考文件的 SHA-256（带缓存），独立于渲染管线。

**接口**：`RefImageHasher`、`file_sha256()`。
**注意**：与 `render_plan/ref_image_hash.py` 是两套（一个有缓存、一个面向渲染计划），别混用。

---

## D. 并发、预算与安全（6）

#### `async_ops.py` · 110 行 `[核实]`

**作用**：同步阻塞调用的受控执行：元数据 IO 限流、等待任务完成、有界线程池。

**接口**：`call_blocking()`、`run_sync_bounded()`、`metadata_io_limiter()`、`wait_for_task_completion()`。
**注意**：直接 `run_in_executor` 无上限会打爆线程；统一走这里。

#### `bounded_concurrency.py` · 78 行 `[核实]`

**作用**：分批 LLM 调用的有界并发 map。

**接口**：`map_bounded()`、`default_llm_concurrency()`。
**注意**：并发上限受网关配额约束；调大要有上游依据。

#### `model_context_budget.py` · 99 行 `[核实]`

**作用**：文本模型的保守上下文预算（网关别名不告诉你上限）。

**接口**：`TextContextBudget`。
**注意**：预算超了要截断而不是报错，但截断策略要保头保尾（提示词在前、指令在后）。

#### `error_redaction.py` · 30 行 `[核实]`

**作用**：错误信息脱敏（去 key、token、URL 凭据）。

**接口**：`redact_secrets()`、`safe_exception_message()`。
**注意**：对外错误一律过这里；日志里也不要直接打原始 provider 响应。

#### `logging.py` · 390 行 `[核实]`

**作用**：工具调用日志与调试输出（Rich 控制台、结构化、统计）。

**接口**：`tool_logger()`、`log_agent_start()`、`log_llm_call()`、`set_verbose()`、`export_trace_log()`、`get_tool_stats()`。
**注意**：`set_verbose` 打开后日志量极大，别在生产常开。

#### `debug_context.py` · 203 行 `[核实]`

**作用**：AI 调用上下文快照（便于复现单次失败）。

**接口**：`create_debug_context()`、`extract_episode_from_path()`、`validate_episode_consistency()`。

---

## E. Verification 主流程（10）

#### `routes.py` · 827 行 · 12 个端点 `[核实]`

**作用**：验证 API：单 beat 核查、一致性、评分、对比、连贯性、相似度、整集总览、草图配色校验、批量草图编辑。

**注意**：这些路由**默认不注册**（`api/__init__.register_verification_routes()` 延迟调用），所以 06 的端点表里它们单列。

#### `sketch_selector.py` · 321 行 `[核实]`

**作用**：草图选择编排：T1 颜色预筛 → T2 事实核查 → T3 评分 → T4 对比 → 输出可操作摘要。

**接口**：`run_sketch_select()`、`BeatSelection`。
**注意**：四步是"流水线"，任一步失败要能降级到"人工选"，不能整体崩。

#### `sketch_select_context.py` · 438 行 `[核实]`

**作用**：为技能驱动的选择准备本地优先的上下文（候选、颜色、事实）。

**接口**：`prepare_sketch_select_context()`、`prepare_storyboard_director_context()`。

#### `sketch_color_verifier.py` · 170 行 `[核实]`

**作用**：草图颜色交叉验证（画面里是否真有该角色的颜色）。

**接口**：`verify_episode_sketch_colors()`。
**注意**：颜色相近会误判，角色配色要拉开色相。

#### `image_verifier.py` · 143 行 `[核实]`

**作用**：单 beat 草图/首帧的事实核查（元素是否与描述一致）。

**接口**：`ImageVerifier`、`resolve_verification_scene_context()`。

#### `frame_verifier.py` · 84 行 `[核实]`

**作用**：首帧渲染质量验证（对比草图：畸变、丢失、风格偏移）。

**接口**：`FrameVerifier`。

#### `consistency_verifier.py` · 183 行 `[核实]`

**作用**：跨 beat 的角色/服装一致性检查。

**接口**：`ConsistencyVerifier`。
**注意**：跨 beat 检查成本高（多图输入），通常按集批量跑。

#### `continuity_verifier.py` · 117 行 `[核实]`

**作用**：连贯性评估（相邻镜头的空间/时间连续）。

**接口**：`ContinuityVerifier`。

#### `similarity_detector.py` · 94 行 `[核实]`

**作用**：像素级草图相似度（用于发现"两 beat 画了同一张"）。

**接口**：`detect_similarity()`。

#### `episode_reviewer.py` / `sketch_scorer.py` / `sketch_comparer.py` · 174 / 79 / 103 行 `[核实]`

**作用**：T3/T4 与整集总览：内容匹配评分、候选对比排序、整集评审。
**注意**：评分尺度变化会让历史评分不可比，改 rubric 要带版本号。

---

## F. Verification 门禁与追踪（11）

#### `sketch_scorer.py` · 78 行 `[核实]`

**作用**：T3 内容匹配评分——对单个 beat 的候选草图与剧本描述做语义匹配打分。

**接口**：`SketchScorer` 类（分值为 LLM 输出的结构化结果）。
**注意**：评分与门禁（`sketch_visual_gate.py`）是两件事——门禁只判「过/不过」，评分给连续分；T4 对比需要分数可比，所以评分提示词不能随意改。

#### `sketch_comparer.py` · 102 行 `[核实]`

**作用**：T4 对比选择——把同一 beat 的多个候选放在一起比，挑出最佳。

**接口**：`SketchComparer` 类。
**注意**：对比是**相对判断**，候选集合变化会改变结论；不要拿不同批次的结果横向比较。

#### `sketch_visual_gate.py` · 535 行 `[核实]`

**作用**：VLM 驱动的视觉门禁：逐格判定候选是否可用。

**接口**：`gate_single_cell()`、`gate_candidate_cells()`、`CellVerdict`、`GateResult`、`resolve_gate_backend_for_context()`。
**注意**：门禁是"守门"不是"评分"——判否要有明确理由码，供失败模式库统计。

#### `sketch_edit_execute.py` · 702 行 `[核实]`

**作用**：执行批量草图编辑（读 teacher 产出的 `labels.jsonl`）。

**接口**：`execute_sketch_edit_batches()`、`resolve_labels_jsonl()`、`derive_audit_dir_name()`。
**注意**：批量执行耗时长且计费，必须有分批与失败隔离。

#### `sketch_edit_label_validation.py` · 135 行 `[核实]`

**作用**：标签 JSONL 的 schema 校验。

**接口**：`validate_labels_jsonl()`、`SketchEditLabelRow`；异常 `LabelsValidationError`。
**注意**：校验在执行**之前**，避免跑一半才发现格式错。

#### `sketch_edit_tasks.py` · 405 行 `[核实]`

**作用**：从项目生成"教师任务"（给编辑模型看的上下文与指令）。

**接口**：`prepare_sketch_edit_tasks()`、`build_task()`、`load_selected_sketch_paths()`。

#### `failure_registry.py` · 632 行 `[核实]`

**作用**：草图失败模式注册表：定义、命中计数、负向提示词片段。

**接口**：`ensure_seeded()`、`list_active()`、`upsert()`、`build_negative_prompt_clause()`、`load_negative_clause_for_project()`、`bump_hit()`。
**注意**：负向片段会进入生成 prompt，写得过宽会压制正常画面。

#### `global_registry_db.py` · 102 行 `[核实]`

**作用**：用户级共享 `verification.db`（失败模式定义的权威来源）。

**接口**：`open_defs_db()`、`ensure_defs_seeded()`。
**注意**：跨项目共享，删项目不应删它。

#### `training_db.py` · 332 行 `[核实]`

**作用**：用户级 `director_training.db`：训练飞轮的样本与轨迹。

**接口**：`insert_accepted_sample()`、`begin_trace()`、`finalize_trace()`、`record_reject()`、`record_override_event()`、`ensure_sketch_format_seeded()`。
**注意**：大字段不在 DB（存内容寻址文件），DB 只留哈希与路径。

#### `replay_capture.py` · 478 行 `[核实]`

**作用**：每次 beat 尝试的完整追踪（prompt/响应/门禁/覆盖）。

**接口**：`begin_trace_for_beat()`、`record_prompt_and_response()`、`record_gate()`、`finalize()`、`record_override()`、`find_traces_for_run()`。
**注意**：追踪是"证据"，字段版本要与 `version_hash` 一起落，否则历史不可比。

#### `convergence_log.py` · 115 行 `[核实]`

**作用**：每集每阶段的收敛轮次记录与趋势报告。

**接口**：`next_round_num()`、`write_round()`、`query_trend()`、`format_trend_markdown()`。
**注意**：趋势用于判断"提示词改动是否真的减少了返工"，比单次评分可靠。

---

## G. Verification 基础设施（12）

#### `artifact_store.py` · 85 行 `[核实]`

**作用**：内容寻址的大对象存储（prompt、模型响应、门禁结果）。

**接口**：`ArtifactRef`、`write_bytes()`、`write_text()`、`write_json_gz()`、`resolve_path()`、`compute_sha256()`。
**注意**：同一内容只存一份；删除要按引用计数，不能按文件删。

#### `trace_ids.py` · 87 行 `[核实]`

**作用**：可读的稳定 id 工厂（trace/sample/reject/event）。

**接口**：`make_trace_id()`、`make_sample_id()`、`make_reject_id()`、`make_event_id()`。
**注意**：id 里嵌上下文（项目/集/beat），换格式会让历史 id 无法解析。

#### `version_hash.py` · 77 行 `[核实]`

**作用**：注册表版本、提示词版本的哈希（每次 trace 必须带）。

**接口**：`compute_registry_version()`、`compute_prompt_version_from_artifact()`。

#### `sanitize.py` · 61 行 `[核实]`

**作用**：提示词输入消毒（移除可能的注入指令）。

**接口**：`sanitize_prompt_input()`。
**注意**：消毒会改变原文，别用它处理需要保真的剧本正文。

#### `models.py` · 259 行 `[核实]`

**作用**：验证系统的数据模型（核查结果、一致性报告、评分、对比、整集总览）。

**接口**：`VerificationResult`、`ConsistencyResult`、`ColorVerifyResult`、`ObjectiveScore`、`CompareResult`、`EpisodeOverviewResult`。
**注意**：这些模型直接映射到 API 响应，改字段等于改协议。

#### `report_formatter.py` · 216 行 `[核实]`

**作用**：验证报告格式化与持久化（Markdown/JSON）。

**接口**：`format_verification_report()`、`format_consistency_report()`、`save_verify_report()`。

#### `prompts.py` · 210 行 `[核实]`

**作用**：验证系统提示词集中管理。
**注意**：改这里会同时影响所有验证结果的可比性。

#### `task_services.py` · 151 行 `[核实]`

**作用**：验证系统的任务辅助（整集草图选择的异步执行）。

**接口**：`run_sketch_select_episode()`。

#### `render_repair_context.py` · 280 行 `[核实]`

**作用**：渲染修复的本地上下文：哪些 beat 需要重生成、如何分组。

**接口**：`build_render_repair_context()`、`split_bad_beats_into_regen_groups()`、`prepare_render_regen_task_plan()`。

#### `utils.py` · 88 行 `[核实]`

**作用**：验证工具：图片压缩、beat 读取、草图/首帧查找。

**接口**：`compress_image()`、`load_all_beats()`、`find_active_sketch_for_beat()`、`safe_resolve_under()`。
**注意**：`safe_resolve_under` 是路径穿越防护，别用裸 `Path`。

#### `schemas.py` · 67 行 `[核实]`

**作用**：验证 API 的请求模型（`VerifyRequest`、`SketchSelectRequest` 等）。

#### `__init__.py` · 26 行 `[核实]`

**作用**：包说明（草图/首帧事实核查 + 一致性 + 渲染质量）。

---

## H. `verification/cli/`（8）

| 文件 | 行数 | 用途 | 注意 |
|---|---:|---|---|
| `migrate_to_global_shared.py` | 267 | 把各用户 `_shared/` 迁到全局 `state/_shared/` | 一次性；先备份 |
| `run_gate.py` | 175 | 对最新 `sketch_edit_execute_summary` 跑视觉门禁 | 需存在 summary 文件 |
| `copy_back_passed.py` | 168 | 只把门禁通过的候选复制回正式草图 | 覆盖前会备份 |
| `register_failure_mode.py` | 167 | 注册/更新失败模式到用户共享库 | 负向片段要窄 |
| `seed_mirror_once.py` | 167 | 把旧项目 `sketch_failure_modes` 镜像到共享库 | 一次性 |
| `emit_human_override.py` | 103 | 记录人工推翻门禁（按 trace 或按 beat） | 用于训练飞轮 |
| `show_trend.py` | 63 | 打印收敛轮次 Markdown 表 | 需要 `convergence_rounds` 有数据 |
| `__init__.py` | 2 | 包声明 | — |

CLI 统一入口：`uv run python -m novelvideo.verification.cli.<name>`。
