# Agents 与 Generators（38 个）

`agents/`（12 个，7,010 行）是「用 LLM 做决策」的地方；`generators/`（21 + 5 个，27,895 行）是「调模型产出媒体」的地方。前者输出结构化计划，后者输出文件。

---

## A. `agents/` — 智能决策层

#### `asset_compiler.py` · 1,806 行 `[核实]`

**作用**：以 SceneBlock 为单位编译本集需要的场景与道具资产，产出可执行的资产需求清单。

**接口**：`AssetCompiler`；输出模型 `DerivedSceneRequirement`、`PropRequirement`、`NarratedScenePlanOutput`、`EpisodeBaseSceneReconcileOutput`；辅助 `enrich_scene_environment_from_context()`。
**I/O**：读原文/剧本块 + 已有场景道具 → 写 `episodes.scene_menu_json` / `prop_menu_json`（经 `sqlite_store`）。
**注意**：它会**增量补充**而不是全量重建，删除菜单项要显式操作；派生场景（`base_of`）命名规则由 `utils/derived_scenes` 决定，别在这里另造规则。

#### `identity_planner.py` · 1,511 行 `[核实]`

**作用**：批量为剧集规划角色身份：预筛出场角色 → Pass A 现实主线默认身份 → 逐集身份需求 → 外貌描述。

**接口**：`IdentityPlanner`；模型 `IdentityRequirement`、`EpisodeCastList`、`AppearanceDescription`。
**I/O**：读 `episodes`/`characters` → 更新 `characters.identities_json` 与 `episodes.identity_*`。
**注意**：三段（选角/分析/外貌）可分别配模型（`IDENTITY_PLANNER_*_MODEL`），换模型会改变身份拆分粒度；身份 id 命名一旦生成就被 beat 标记引用，改规则需要全量重映射。

#### `global_video_optimizer.py` · 851 行 `[核实]`

**作用**：整集一次性优化：分析草图网格 + 角色颜色映射，为所有 beat 生成 first_frame 运动提示词。

**接口**：`GlobalVideoPromptOptimizer`、`prepare_global_optimizer_input()`、`detect_identities_by_ai()`、`create_global_video_optimizer_agent()`。
**I/O**：读整集草图 + 角色映射 → 写每个 beat 的视频提示词。
**注意**：这是**整集级**调用（一次看多图），token 消耗大；单 beat 重生成不会自动重跑它，改一个 beat 的运动描述要单独生成。

#### `episode_planner.py` · 391 行 `[核实]`

**作用**：分集规划 Agent：多轮迭代决定每集覆盖哪些章节、核心冲突与悬念。

**接口**：`EpisodePlannerAgent`、`EpisodePlan`、`create_episode_planner_agent()`。
**注意**：它依赖 Cognee 工具（legacy 管线）或结构化摘要（新管线），两条路径的输入不同，改 prompt 要分别验证。

#### `episode_reviewer.py` · 568 行 `[核实]`

**作用**：分集质量审核：叙事完整性、节奏、人物弧线、悬念强度。

**接口**：`EpisodePlanReviewer`、`EpisodePlanReport`、`EpisodePlanIssueType`。
**注意**：审核结论是**建议**，不阻断；是否重规划由 `episode_fixer` 或用户决定。

#### `episode_fixer.py` · 693 行 `[核实]`

**作用**：按审核报告生成结构化补丁修复分集规划，保留规则修复作为兜底。

**接口**：`EpisodePlanFixer`、`EpisodePatch`、`apply_patches()`。
**注意**：patch 是字段级修改，不是整集重写；应用 patch 后要重新校验集数/章节覆盖完整性。

#### `character_reviewer.py` · 111 行 `[核实]`

**作用**：角色列表审核：重复、泛称（"一个男人"）、身份错配。

**接口**：`CharacterReviewReport`、`CharacterIssue`、`create_character_reviewer_agent()`。
**注意**：它只报问题，不修；修复在 `character_fixer`。

#### `character_fixer.py` · 115 行 `[核实]`

**作用**：按审核报告修角色：合并重复、删泛称、修正身份。

**接口**：`FixAction`、`CharacterFixReport`、`create_character_fixer_agent()`。
**注意**：合并角色会改变主键（`name`），必须走 `identity_refs` 重映射，否则 beat 标记全断。

#### `video_prompt_builder.py` · 424 行 `[核实]`

**作用**：把 beat 信息转成 I2V 模型的运动描述提示词，支持直接看首帧图理解构图。

**接口**：`VideoPromptBuilder`、`create_video_prompt_builder_agent()`。
**注意**：多模态输入会显著增加成本；纯文本路径在"首帧还没生成"时使用。

#### `keyframe_prompt_builder.py` · 327 行 `[核实]`

**作用**：首尾帧过渡提示词：分析两帧差异，描述中间运动。

**接口**：`KeyframePromptBuilder`、`create_keyframe_prompt_builder_agent()`。
**注意**：只在支持首尾帧的后端有意义；普通 I2V 后端用不到，别为此多花钱。

#### `content_rewriter.py` · 206 行 `[核实]`

**作用**：内容改写（适配解说风格/压缩篇幅）。

**接口**：`rewrite_episode_content()`、`AdaptedContentOutput`。
**注意**：改写稿与原文分表/分文件存储，互不覆盖。

#### `__init__.py` · 19 行 `[核实]`

**作用**：包声明与 Agent 导出。

---

## B. `generators/` — 媒体产出层

#### `huimengi.py` · 432 行 `[核实]`

**作用**：绘梦（HuiMeng）任务 API 的**最小**客户端封装。故意只保留通用的 task/client 部分，模型名与参数由上层生成器决定——这样新增一个绘梦模型不需要改这个文件。

**接口**：
- `HuimengiTaskClient`：提交、轮询、取结果
- 异常 `HuimengTaskFailed`
- 结果提取：`extract_huimeng_result_url()`、`extract_huimeng_result_last_frame_url()`、`extract_huimeng_result_duration()`
- 参数解析：`huimeng_video_backend_value()`、`parse_huimeng_video_backend()`、`huimeng_video_backend_options()`
- 媒体入参：`local_file_to_data_url()`、`bytes_to_data_url()`
- 下载校验：`validate_huimeng_media_download()`

**I/O**：吃本地文件/字节（转 data URL）+ 任务参数 → 吐结果 URL（图/视频/末帧/时长）。

**依赖**：被图片与视频生成器共同调用；上游是 `generators/` 的模型专属文件。

**使用场景**：接入或替换绘梦系模型时；排查"视频生成成功但拿不到结果"时先看 `extract_huimeng_result_*`。

**注意**：
1. 「末帧」是独立字段，不是从视频里抽的——`extract_huimeng_result_last_frame_url()` 拿不到时下游续接（`videoExtendClip`）会退化。
2. `validate_huimeng_media_download()` 是**外链下载的安全校验**，绕过它会引入 SSRF 面。
3. 体积类参数（`*_backend_options`）与后端能力表耦合，改一处要同步 `domain/catalogVideoModels.ts`。

#### `nanobanana_grid.py` · 7,996 行 `[核实]`

**作用**：全仓最大的生成器。NanoBananaPro 网格生成：草图的 3×3 / 渲染的 5×5，按 beat 排布、切分、配色、重生成。

**接口**：`NanoBananaGridGenerator`、`GridGenerationRequest`、`GridGenerationResult`；`pack_beats()`、`sketch_grid_split()`、`perfect_grid_split()`、`crop_sketch_panels()`、`regenerate_selected_beats()`、`build_color_map_from_character_map()`、`compute_input_fingerprint()`。
**I/O**：读 beats + 角色映射 + 参考图 → 调图模 → 存网格 PNG → 切 cell 进图片池。
**注意**：
- `compute_input_fingerprint()` 决定缓存命中，改了 prompt 组装逻辑会让所有历史网格失效；
- 网格切分对边距敏感，`perfect_grid_split` 失败时不要硬切，会切出半张脸；
- 单文件近 8 千行，新增模式优先做成 `PromptMode` 分支而不是再写一条链路。

#### `prompt_builder.py` · 3,945 行 `[核实]`

**作用**：统一的提示词模板构建器。草图 / 渲染 / 动作分镜三种策略共享核心组件。

**接口**：`UnifiedPromptBuilder`、`PromptMode`（`RENDER`/`SKETCH`/`ACTION_STORYBOARD`）、`PromptContext`、`RenderModeStrategy`、`SketchModeStrategy`。
**注意**：提示词是生成质量的第一变量；改这里要跑一组固定输入对比（`scripts/benchmarks/`），不能凭感觉。

#### `video_generator.py` · 4,825 行 `[核实]`

**作用**：I2V 视频生成与多后端适配：Seedance、Seedance2、Grok、Huimeng、NewAPI、ComfyUI、Mock。

**接口**：`VideoGeneratorBase` + 各后端类；`create_video_generator()`、`newapi_video_backend_options()`、`translate_prompt_to_english()`。
**注意**：
- 后端能力差异大（时长、分辨率、参考图数量），提交前必须用 `video_duration` / `media_model_request_schema` 归一；
- 失败分类（`NewApiVideoError`、`VideoEgressError`）决定是否可重试，别一律重试；
- 这是**计费入口**，每次调用都会写 `video_request_usage`。

#### `image_generator.py` · 1,489 行 `[核实]`

**作用**：火山引擎/Seedream 图像生成与 SeedEdit 编辑（旧链路），保留 Mock 实现供测试。

**接口**：`VolcengineImageGenerator`、`MockImageGenerator`、`create_image_generator()`、`generate_character_reference_unified()`。
**注意**：新项目多数走 `nanobanana_*`；这条链路仍在用于特定模型与兼容。

#### `nanobanana_character.py` · 1,702 行 `[核实]`

**作用**：角色参考图生成，靠 Identity Locking 保证同一个角色跨集一致。

**接口**：`NanoBananaCharacterGenerator`、`create_composite_reference()`。
**注意**：参考图是"锁定"的锚，换参考图等于换脸；`create_composite_reference` 会把多张图拼成一张（用于多视角锁定）。

#### `nanobanana_prop.py` · 462 行 `[核实]`

**作用**：道具三视图参考图（正/侧/背），产品摄影风格。

**接口**：`generate_prop_reference()`、`build_prop_reference_prompt()`、`resolve_prop_reference_image_model()`。
**注意**：三视图是后续 3GS 与视频一致性的基础，模糊的参考图会导致后续全歪。

#### `scene_reference_images.py` · 754 行 `[核实]`

**作用**：场景母版/反打参考图生成。

**接口**：`generate_scene_reference_image()`、`build_scene_reference_prompt()`、`resolve_scene_reference_image_model()`。
**注意**：母版与反打必须同源（同一 `spatial layout`），否则剪辑时空间关系错乱。

#### `grid_splitter.py` · 576 行 `[核实]`

**作用**：网格图切分：去间隙、按 3×3/5×5 切、检测布局、缩放到竖屏。

**接口**：`split_grid()`、`split_grid_with_padding()`、`detect_grid_layout()`、`remove_grid_gaps()`、`resize_frames_to_portrait()`、`combine_to_grid()`。
**注意**：切分是纯图像算法，不依赖模型；改这里要配一张"已知正确切分"的夹具做回归。

#### `pool_indexer.py` · 1,063 行 `[核实]`

**作用**：图片池索引：所有候选图（1×1、3×3、5×5）统一登记，支持选帧、删格、去重、重建。

**接口**：`build_pool_index()`、`save_pool_index()`、`rebuild_pool_index()`、`select_frame_from_pool()`、`add_cell_with_dedup()`、`compute_beat_content_hash()`、`is_pool_image_stale()`。
**注意**：索引是 sidecar 文件（`utils/state_index_files`），与 DB 里的选中关系是两套；索引损坏可 `rebuild_pool_index()` 重建。

#### `video_pool_indexer.py` · 241 行 `[核实]`

**作用**：视频池索引（无网格概念，比图片池简单）。

**接口**：`load_video_pool_index()`、`add_video_to_pool()`、`assign_video_to_beat()`、`delete_video_from_pool()`。

#### `tts_generator.py` · 851 行 `[核实]`

**作用**：TTS 语音合成（Edge TTS / CosyVoice / Mock），含音频操作租约。

**接口**：`EdgeTTSGenerator`、`CosyVoiceTTSGenerator`、`create_tts_generator()`、`claim_audio_operation()`、`resolve_audio_gateway_credential()`。
**注意**：`claim_audio_operation` 是防并发重复生成的租约；不取租约直接生成会出现同一段文本两份音频。

#### `indextts2_fal.py` · 469 行 `[核实]`

**作用**：IndexTTS2 客户端（Seedance 2.0 对白音频准备）。

**接口**：`IndexTTS2FalClient`。
**注意**：音色是"参考音频 + 文本"双输入，参考音质量直接决定像不像。

#### `video_composer.py` · 849 行 `[核实]`

**作用**：FFmpeg/MoviePy 合成：片段拼接、Ken Burns 动效、时长对齐。

**接口**：`VideoComposer`、`MoviePyComposer`、`create_video_composer()`、`adjust_video_duration()`、`get_video_duration()`。
**注意**：合成是 CPU/IO 密集，跑在 `ffmpeg` 泳道（默认全局 2 槽）；磁盘不足时失败信息不直观，先看 `df -h`。

#### `sketch_color_detector.py` · 265 行 `[核实]`

**作用**：检测草图上实际出现的调色板颜色，用于过滤不存在的角色、导出标注。

**接口**：`detect_sketch_colors()`、`detect_sketch_colors_per_panel()`、`annotate_sketch_with_identities()`。
**注意**：颜色检测是启发式（阈值 + 连通域），同色系角色容易混；给角色分配颜色时要拉开色相。

#### `episode_optimizer.py` · 152 行 `[核实]`

**作用**：2.0 里只剩草图配色分配（`assign_sketch_colors`）与 `EpisodeOptimizer`。
**注意**：配色逻辑影响后续所有颜色检测，改分配算法要重跑已生成的草图检测。

#### `style_analyzer.py` · 150 行 `[核实]`

**作用**：从参考图提取风格预设（色调、质感、构图倾向）。

**接口**：`StyleAnalyzer`、`StyleAnalysisResult`。
**注意**：分析结果写进项目风格配置，是"建议值"，可被用户覆盖。

#### `voxel_restyle.py` · 209 行 `[核实]`

**作用**：把体素世界截图按项目视觉风格重绘，使 3D 场景与 2D 画风统一。

**接口**：`render_voxel_shot_styled()`。
**注意**：重绘会改变像素，若要用于严格空间对齐（如控制帧），不要走重绘。

#### `scene_world.py` · 79 行 `[核实]`

**作用**：轻量场景世界清单（场景参考资产的显式声明），**不是** DirectorWorld。

**接口**：`validate_scene_world_file()`、`ensure_scene_world_file()`。
**注意**：名字容易与 `director_world/` 混，两者用途不同，别合并。

#### `render_identity_guard.py` · 55 行 `[核实]`

**作用**：渲染前的前置检查：是否已做草图 AI 身份检测。

**接口**：`RenderIdentityDetectionRequired`、`render_ai_detection_error()`。
**注意**：这是防"渲染用了错误角色"的闸门，跳过它会产出整批错图。

#### `__init__.py` · 128 行 `[核实]`

**作用**：生成器包的导出与说明（含各生成器的一句话注释）。

---

## C. `generators/scene_voxel/`（5）

#### `__init__.py` · 164 行 `[核实]`

**作用**：体素世界生成流水线入口：`master.png + reverse_master.png` → 调色板 → AI 写 build script → 体素模型 → glb。

**接口**：`generate_scene_voxel_world()`、`voxel_world_output_dir()`。
**注意**：需要 Node 与 vengi-voxconvert，属可选能力。

#### `codegen_agent.py` · 383 行 `[核实]`

**作用**：VLM Agent：看两张参考图，写一段可执行的 `build_script.py` 来搭建场景。

**接口**：`generate_build_script()`。
**注意**：生成的是**代码**，执行前要按白名单校验（只允许 primitives API），不能直接 `exec` 任意代码。

#### `palette.py` · 370 行 `[核实]`

**作用**：从两张参考图提取 24–32 色调色板（Lab 空间 K-means）。

**接口**：`extract_palette()`、`find_closest_color()`、`find_color_family()`、`pick_global_anchor()`。
**注意**：调色板决定体素"像不像"，比 build script 更影响观感。

#### `primitives.py` · 223 行 `[核实]`

**作用**：给 AI 生成的 build script 用的体素原语 API（盒子、柱、坡道、随机种子等）。

**接口**：`VoxelScene`、`make_rng()`。
**注意**：这是 codegen 的"安全边界"，新增原语要同步 prompt 说明，否则模型不会用。

#### `voxconvert.py` · 88 行 `[核实]`

**作用**：`.vox` → `.glb` 的转换封装（定位 vengi-voxconvert 二进制）。

**接口**：`is_available()`、`vox_to_glb()`。
**注意**：二进制缺失时只返回不可用，不抛错——调用方要自己判断。
