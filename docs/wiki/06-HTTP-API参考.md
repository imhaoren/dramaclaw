# 06 HTTP API 参考

全部端点挂在 `/api/v1` 下，共 **387** 个，分布在 **28** 个路由模块。静态媒体走独立的 `/static/projects/{project}/...`（同样做项目级鉴权）。

## 1. 鉴权

三种身份，一套依赖：

| 调用方 | 凭据 | 说明 |
|---|---|---|
| 浏览器 | `st_session` HttpOnly Cookie | 登录后由服务端种下；`SameSite=Strict`，默认 `Secure`（本地 http 需 `ST_COOKIE_SECURE=0`） |
| Agent / 脚本 | `Authorization: Bearer <agent session token>` | 短期票据，由 `POST /api/v1/agent/sessions` 换取 |
| 本地调试 | `DRAMACLAW_LOCAL_AGENT_TRUST=1` + 回环地址 | 仅 `127.0.0.1` / `::1` / `localhost` 生效，生产禁用 |

**不接受** `?token=` / `?access_token=` / `?api_key=` 查询参数（`UNSUPPORTED_QUERY_CREDENTIALS` 显式拒绝）。长期有效的 agent key 只能用于换取会话，不能直接调业务接口。

路由级授权用 `require_scope("projects:write")` 这类精确 scope；写方法（POST/PUT/PATCH/DELETE）额外有一道 `AGENT_WRITE_SCOPES` 兜底，防止漏写 scope 的端点被 agent token 直接写。

## 2. 响应约定

| 场景 | 形状 |
|---|---|
| 写操作成功 | `{"ok": true, ...}`（常带 `data` 或资源字段） |
| 列表 | `{"ok": true, "data": [...]}` |
| 已接受的任务 | `{"ok": true, "task_key": "...", "job_id": "..."}` + HTTP 202 |
| 错误 | `{"ok": false, "error": "人类可读说明"}` |
| 计费/配额错误 | 在上述基础上带 `code`、`billing` 或 `retry_after` 字段 |

多数接口支持 `Accept-Language`（`zh` / `en`），错误文案由 `i18n_message.py` 生成，后端不返回已翻译死字符串。

## 3. 状态码

| 码 | 含义 | 典型来源 |
|---|---|---|
| 200 | 成功 | 读接口、同步写 |
| 202 | 已接受，异步执行 | 所有生成类接口 |
| 400 | 参数非法 | Pydantic 校验失败、泳道拼错 |
| 401 | 未认证 / 会话过期 | Cookie 失效、Bearer 过期 |
| 403 | 无权限 / 端口拒绝 | `AuthzError`、`role` 不足 |
| 404 | 项目或资源不存在 | 项目未注册、beat 越界 |
| 409 | 冲突 | 画布 `revision` 冲突、幂等键复用但载荷不同 |
| 413 | 载荷过大 | 上传超限、画布 payload 超 `FREEZONE_CANVAS_PAYLOAD_LIMIT_BYTES` |
| 422 | 语义校验失败 | 前置条件缺失（未导入小说、未建角色） |
| 429 | 配额/限流 | `ProjectTaskLimitExceeded` 等五道闸门 |
| 500 | 服务端错误 | runner 抛出未分类异常 |
| 502/504 | 上游失败/超时 | provider 或 NewAPI 网关 |

429 会带 `Retry-After`；前端按此退避，不要固定间隔重试。

## 4. 长连接

| 端点 | 协议 | 用途 |
|---|---|---|
| `GET /projects/{project}/tasks/{task_key}/stream` | SSE | 单任务进度 |
| `GET /projects/{project}/tasks/stream` | SSE | 项目任务总览 |
| `WS /chat/ws` | WebSocket | 对话双向流：Agent 事件下行、用户消息/工具结果上行 |

SSE 在进程关闭时会收到终止事件（`api/sse_shutdown.py`），客户端应视为「本次流结束」而非「任务失败」，重连前先取快照。

## 5. 端点总表

说明列取自函数文档字符串（截断），`—` 表示源码无说明。方法前的分组对应源码文件，改动时按文件定位。


### 5.1 `api/routes/projects.py`（18 个）

项目生命周期：创建/列出/更新/归档/软删/恢复/彻底清除，旁白音色，静态媒体授权

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `GET` | `/projects` | `list_projects` | List project_ids accessible to the current user. |
| `GET` | `/projects/summaries` | `list_project_summaries` | List summaries for projects accessible to the current user. |
| `POST` | `/projects` | `create_project` | 创建新项目。 |
| `GET` | `/projects/{project}` | `get_project` | 获取项目配置。 |
| `GET` | `/projects/{project}/static-auth` | `authorize_project_static_media` | — |
| `PATCH` | `/projects/{project}` | `update_project` | 更新项目配置。 |
| `GET` | `/projects/{project}/narrator-voice` | `get_narrator_voice` | 获取项目解说声线状态。 |
| `GET` | `/projects/{project}/narrator-voice/sources` | `list_narrator_voice_sources` | 列出项目内可复制为解说声线的音频。 |
| `POST` | `/projects/{project}/narrator-voice/upload` | `upload_narrator_voice` | 上传第三人称项目解说声线。 |
| `POST` | `/projects/{project}/narrator-voice/record` | `record_narrator_voice` | 保存浏览器录音为第三人称项目解说声线。 |
| `POST` | `/projects/{project}/narrator-voice/copy` | `copy_project_audio_as_narrator_voice` | 从项目内已有音频复制为第三人称项目解说声线。 |
| `POST` | `/projects/{project}/narrator-voice/trim` | `trim_narrator_voice` | 裁剪第三人称项目解说声线并写回项目声线槽位。 |
| `POST` | `/projects/{project}/narrator-voice/delete` | `delete_narrator_voice` | 移除第三人称项目解说声线。 |
| `POST` | `/projects/{project}/archive` | `archive_project` | — |
| `POST` | `/projects/{project}/unarchive` | `unarchive_project` | — |
| `POST` | `/projects/{project}/delete` | `soft_delete_project` | — |
| `POST` | `/projects/{project}/restore` | `restore_project` | — |
| `POST` | `/projects/{project}/purge` | `purge_project` | 永久删除项目目录；只允许对已进入回收站的项目执行。 |

### 5.2 `api/routes/ingest.py`（3 个）

小说上传、导入启动、知识图谱预览

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `GET` | `/projects/{project}/ingest/graph` | `get_ingest_knowledge_graph` | Return the persisted graph preview without opening Ladybug on normal r |
| `POST` | `/projects/{project}/ingest/upload` | `upload_novel` | 上传小说文件到项目的 uploads/ 目录。 |
| `POST` | `/projects/{project}/ingest/start` | `start_ingest` | 触发小说导入（构建知识图谱）。 |

### 5.3 `api/routes/episodes.py`（12 个）

分集列表与规划、单集详情、beats 读取、身份/场景/道具规划、手工 beat、章节检测

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `GET` | `/projects/{project}/episodes` | `list_episodes` | 获取项目分集列表。 |
| `POST` | `/projects/{project}/episodes/plan` | `plan_episodes` | 规划分集。 |
| `GET` | `/projects/{project}/episodes/{episode_num}` | `get_episode_detail` | 获取指定集的完整详情。 |
| `GET` | `/projects/{project}/episodes/{episode_num}/beats` | `get_beats` | 获取指定集数的 beats。 |
| `DELETE` | `/projects/{project}/episodes/{episode_num}/beats/{beat_number}/manual-shot` | `delete_manual_shot_route` | 删除手工插入的 beat。普通主流程 beat 不允许从这里删。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/insert-manual` | `insert_manual_shot_route` | 插入手工 beat；after_beat_number=None 表示插到第一张前。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/identities/plan` | `plan_episode_identities` | 规划单集角色身份。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/identities/plan-async` | `plan_episode_identities_async` | 兼容 1.0/旧前端的异步身份规划入口。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/scenes/plan` | `plan_episode_scenes` | 规划单集场景菜单。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/props/plan` | `plan_episode_props` | 规划单集道具菜单。 |
| `PATCH` | `/projects/{project}/episodes/{episode_num}` | `update_episode` | 编辑指定集的元数据。 |
| `GET` | `/projects/{project}/chapters` | `detect_chapters` | 检测已上传小说的章节结构。 |

### 5.4 `api/routes/scripts.py`（6 个）

剧本读取与生成、beat 编辑、视频提示词与 Seedance2 提示词生成

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `GET` | `/projects/{project}/episodes/{episode_num}/script` | `get_script` | 获取指定集数的剧本。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/script/generate` | `generate_script` | 生成指定集数的剧本。 |
| `PATCH` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}` | `update_beat` | 编辑指定 Beat。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/video-prompt/generate` | `generate_beat_video_prompt` | AI 生成 1.x 单个 Beat 的视频提示词并保存。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/seedance2-prompt/generate` | `generate_seedance2_prompt` | AI 生成单个 Beat 的 Seedance2 final_prompt 并保存回配置 JSON。 |
| `PUT` | `/projects/{project}/episodes/{episode_num}/script` | `save_script` | 保存（覆盖）指定集数的完整剧本。 |

### 5.5 `api/routes/content.py`（6 个）

原文/改写稿的读写与删除，改写任务发起

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `GET` | `/projects/{project}/episodes/{episode_num}/raw-content` | `get_raw_content` | 读取指定集的原文。 |
| `PUT` | `/projects/{project}/episodes/{episode_num}/raw-content` | `put_raw_content` | 保存指定集的原文。 |
| `GET` | `/projects/{project}/episodes/{episode_num}/adapted-content` | `get_adapted_content` | 读取指定集的改写稿。未保存时返回空串。 |
| `PUT` | `/projects/{project}/episodes/{episode_num}/adapted-content` | `put_adapted_content` | 保存指定集的改写稿。集不存在时返回 400。 |
| `DELETE` | `/projects/{project}/episodes/{episode_num}/adapted-content` | `delete_adapted_content` | 清空指定集的改写稿，回退到原文。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/rewrite/generate` | `generate_rewrite` | 同步执行“原文 → 逐行解说工作稿”，并保存到 adapted_content。 |

### 5.6 `api/routes/characters.py`（34 个）

角色 CRUD、身份（identity）管理、肖像/身份图生成、音色样本、资产历史

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `GET` | `/projects/{project}/characters` | `list_characters` | 获取角色列表；资产工作台可显式使用 summary 跳过文件探测。 |
| `POST` | `/projects/{project}/characters` | `add_character` | 手动添加单个角色（当自动提取失败时使用）。 |
| `POST` | `/projects/{project}/characters/build` | `build_characters` | 从知识图谱补充缺失角色。 |
| `GET` | `/projects/{project}/character-image-selection` | `get_project_character_image_selection` | 获取项目级角色/身份图生成源选择。 |
| `PATCH` | `/projects/{project}/character-image-selection` | `update_project_character_image_selection` | 保存项目级角色/身份图生成源选择。 |
| `GET` | `/projects/{project}/image-source-selection/{asset_kind}` | `get_project_asset_image_source_selection` | 获取项目级素材图源选择。 |
| `PATCH` | `/projects/{project}/image-source-selection/{asset_kind}` | `update_project_asset_image_source_selection` | 保存项目级素材图源选择。 |
| `GET` | `/projects/{project}/character-image-usage` | `get_project_character_image_usage` | 获取角色/身份图请求用量统计。 |
| `GET` | `/projects/{project}/characters/{name}/identities` | `get_character_identities` | 获取角色全部身份及图片。 |
| `GET` | `/projects/{project}/characters/{name}/asset-history` | `list_character_asset_history` | 列出角色资产的历史备份，用于 UI 回看和恢复。 |
| `POST` | `/projects/{project}/characters/{name}/asset-history/restore` | `restore_character_asset_history` | 把某个历史备份恢复到角色资产 canonical 槽位。 |
| `PATCH` | `/projects/{project}/characters/{name}` | `update_character` | 编辑角色基本信息。 |
| `POST` | `/projects/{project}/characters/{name}/delete` | `delete_character` | 删除角色。POST 保持与 React active UI 的兼容契约。 |
| `GET` | `/projects/{project}/characters/{name}/voice-samples` | `list_character_voice_samples` | 获取角色 IndexTTS2 声线样本插槽。 |
| `POST` | `/projects/{project}/characters/{name}/voice-samples/{slot}/upload` | `upload_character_voice_sample` | 上传角色 IndexTTS2 声线样本。 |
| `POST` | `/projects/{project}/characters/{name}/voice-samples/{slot}/record` | `record_character_voice_sample` | 保存浏览器录音为角色 IndexTTS2 声线样本。 |
| `POST` | `/projects/{project}/characters/{name}/voice-samples/{slot}/trim` | `trim_character_voice_sample` | 裁剪角色 IndexTTS2 声线样本并写回同一插槽。 |
| `POST` | `/projects/{project}/characters/{name}/voice-samples/{slot}/delete` | `delete_character_voice_sample` | 清除角色 IndexTTS2 声线样本。 |
| `POST` | `/projects/{project}/characters/{name}/identities` | `add_identity` | 为角色新增一个身份。 |
| `PATCH` | `/projects/{project}/characters/{name}/identities/{identity_id}` | `update_identity` | 编辑角色身份属性。 |
| `DELETE` | `/projects/{project}/characters/{name}/identities/{identity_id}` | `delete_identity` | 删除角色身份。 |
| `POST` | `/projects/{project}/characters/{name}/portrait-async` | `generate_single_portrait_async` | 启动单角色 Portrait 后台任务。 |
| `POST` | `/projects/{project}/characters/{name}/portrait` | `generate_single_portrait` | 为单个角色生成肖像（face close-up）。 |
| `POST` | `/projects/{project}/characters/{name}/portrait/upload` | `upload_portrait` | 上传角色肖像图片。 |
| `POST` | `/projects/{project}/characters/{name}/identities/{identity_name}/upload` | `upload_identity_image` | 上传角色身份图片。 |
| `POST` | `/projects/{project}/characters/{name}/identities/{identity_id}/image/delete` | `delete_identity_image` | — |
| `POST` | `/projects/{project}/characters/{name}/identities/{identity_id}/costume/upload` | `upload_identity_costume` | — |
| `POST` | `/projects/{project}/characters/{name}/identities/{identity_id}/costume/delete` | `delete_identity_costume` | — |
| `POST` | `/projects/{project}/characters/{name}/identities/{identity_id}/portrait/upload` | `upload_identity_portrait` | — |
| `POST` | `/projects/{project}/characters/{name}/identities/{identity_id}/portrait/generate-async` | `generate_identity_portrait_async` | — |
| `POST` | `/projects/{project}/characters/{name}/identities/{identity_id}/portrait/generate` | `generate_identity_portrait` | 同步生成身份级 portrait，供旧调用保留。新 UI 应优先使用 async。 |
| `POST` | `/projects/{project}/characters/{name}/identities/{identity_id}/generate-async` | `generate_identity_image_async` | — |
| `GET` | `/projects/{project}/characters/{name}/identities/{identity_id}/attempts` | `get_identity_attempts` | — |
| `POST` | `/projects/{project}/characters/{name}/identities/{identity_id}/generate` | `generate_identity_image` | 基于角色肖像生成身份参考图（Identity Locking）。 |

### 5.7 `api/routes/scenes.py`（24 个）

场景工作台：场景 CRUD、母版/反打/全景/3GS 资产、空间布局、导演世界

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `GET` | `/projects/{project}/scenes` | `list_scenes` | — |
| `GET` | `/projects/{project}/scenes/plate-preview` | `preview_scene_plate` | — |
| `GET` | `/projects/{project}/scenes/{name}/pano/manifest` | `get_scene_pano_manifest` | — |
| `PATCH` | `/projects/{project}/scenes/{name}/pano/correction` | `update_scene_pano_correction` | — |
| `GET` | `/projects/{project}/scenes/{name}/director-stage/manifest` | `get_scene_director_stage_manifest` | — |
| `POST` | `/projects/{project}/scenes/{name}/director-stage/world` | `save_scene_director_world` | — |
| `POST` | `/projects/{project}/scenes/{name}/director-stage/world/source` | `save_scene_director_world_source` | — |
| `POST` | `/projects/{project}/scenes/{name}/director-stage/world/clear` | `clear_scene_director_world` | — |
| `POST` | `/projects/{project}/scenes` | `create_scene` | — |
| `PATCH` | `/projects/{project}/scenes/{name}` | `update_scene` | — |
| `POST` | `/projects/{project}/scenes/{name}/delete` | `delete_scene` | — |
| `POST` | `/projects/{project}/scenes/build` | `build_scenes` | — |
| `POST` | `/projects/{project}/scenes/{name}/master/upload` | `upload_scene_master` | — |
| `POST` | `/projects/{project}/scenes/{name}/master/delete` | `delete_scene_master` | — |
| `POST` | `/projects/{project}/scenes/{name}/master/generate-async` | `generate_scene_master` | — |
| `POST` | `/projects/{project}/scenes/{name}/reverse/generate-async` | `generate_scene_reverse_master` | — |
| `POST` | `/projects/{project}/scenes/{name}/pano/upload` | `upload_scene_pano` | — |
| `POST` | `/projects/{project}/scenes/{name}/pano/delete` | `delete_scene_pano` | — |
| `POST` | `/projects/{project}/scenes/{name}/custom/upload` | `upload_scene_custom_package` | — |
| `POST` | `/projects/{project}/scenes/{name}/custom/delete` | `delete_scene_custom_package` | — |
| `POST` | `/projects/{project}/scenes/{name}/3gs/master-ply/generate-async` | `generate_scene_3gs_master_ply` | — |
| `POST` | `/projects/{project}/scenes/{name}/3gs/reverse-ply/generate-async` | `generate_scene_3gs_reverse_ply` | — |
| `POST` | `/projects/{project}/scenes/{name}/3gs/pano-ply/generate-async` | `generate_scene_3gs_pano_ply` | — |
| `POST` | `/projects/{project}/scenes/{name}/pano/generate-async` | `generate_scene_pano` | — |

### 5.8 `api/routes/props.py`（5 个）

道具工作台：道具 CRUD 与三视图参考图生成

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `GET` | `/projects/{project}/props` | `list_props` | — |
| `POST` | `/projects/{project}/props` | `create_prop` | — |
| `PATCH` | `/projects/{project}/props/{name}` | `update_prop` | — |
| `POST` | `/projects/{project}/props/{name}/delete` | `delete_prop` | — |
| `POST` | `/projects/{project}/props/{name}/reference/generate-async` | `generate_prop_reference` | — |

### 5.9 `api/routes/assets.py`（2 个）

统一资产反查：某个角色/场景/道具被哪些 beat 引用

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `GET` | `/projects/{project}/assets/references` | `get_project_asset_references` | On-demand reverse index: which beats reference the named assets. |
| `GET` | `/projects/{project}/assets/{asset_type}/{asset_id}/references` | `get_asset_references` | Return beat references for a character identity, scene, or prop asset. |

### 5.10 `api/routes/generation.py`（66 个）

生成主干：草图/渲染网格/视频/音频/合成/导出，含渲染设置与图片池

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `GET` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/seedance2-status` | `get_seedance2_beat_status` | Return NiceGUI-aligned read-only Seedance 2.0 status for one Beat. |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/seedance2/assets/upload` | `upload_seedance2_asset` | Upload a manual Seedance 2.0 reference asset. |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/seedance2/assets/delete` | `delete_seedance2_asset` | Remove a manually attached Seedance 2.0 reference asset. |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/seedance2/assets/crop` | `crop_seedance2_asset` | Crop an existing Seedance 2.0 image reference into a manual reference. |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/seedance2/assets/audio-trim` | `trim_seedance2_audio_asset` | Trim an existing Seedance 2.0 audio reference into a 3-5 second clip. |
| `GET` | `/projects/{project}/video-backends` | `get_video_backend_options` | Return video backend options shared with the NiceGUI render workbench. |
| `GET` | `/projects/{project}/render-settings` | `get_render_settings` | Return Render-stage image model and sizing settings for React. |
| `PATCH` | `/projects/{project}/render-settings` | `update_render_settings` | Persist Render-stage image model and sizing settings. |
| `GET` | `/projects/{project}/sketch-settings` | `get_sketch_settings` | Return Sketch-stage image model settings for React. |
| `PATCH` | `/projects/{project}/sketch-settings` | `update_sketch_settings` | Persist Sketch-stage image model settings. |
| `GET` | `/projects/{project}/episodes/{episode_num}/sketch-regen-queue` | `get_sketch_regen_queue` | Return the persisted React sketch regeneration dispatch queue. |
| `PUT` | `/projects/{project}/episodes/{episode_num}/sketch-regen-queue` | `update_sketch_regen_queue` | Persist the React sketch regeneration dispatch queue per episode. |
| `GET` | `/projects/{project}/episodes/{episode_num}/sketch-image-usage` | `get_sketch_image_usage` | Return NiceGUI-style Sketch image request usage summary. |
| `GET` | `/projects/{project}/episodes/{episode_num}/image-generation-guard` | `get_image_generation_guard` | Return per-scope image generation guard status used before dispatch. |
| `POST` | `/projects/{project}/episodes/{episode_num}/image-generation-guard/verify-password` | `verify_image_generation_guard_password` | Verify the same operator password NiceGUI requires after repeated imag |
| `POST` | `/projects/{project}/episodes/{episode_num}/videos/compose` | `compose_video` | 合成成片。 |
| `GET` | `/projects/{project}/episodes/{episode_num}/final` | `get_final_video` | 读取 episode 成片状态，供 supertale-fe compose 页刷新 hydration。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/tts/generate` | `generate_tts` | Legacy TTS endpoint removed after IndexTTS2 cutover. |
| `POST` | `/projects/{project}/tts/preview` | `preview_tts` | Legacy TTS preview endpoint removed after IndexTTS2 cutover. |
| `GET` | `/projects/{project}/tts/voices` | `list_tts_voices` | Legacy voice listing endpoint removed after IndexTTS2 cutover. |
| `POST` | `/projects/{project}/episodes/{episode_num}/sketches/generate` | `generate_sketches` | 生成草图。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/audio/system-voices/prepare` | `prepare_system_voices_for_agent` | Prepare missing system voice references for the outer Hermes assistant |
| `POST` | `/projects/{project}/episodes/{episode_num}/audio/billing-quote` | `audio_generation_billing_quote` | Quote the exact set of Beat audio model calls for an audio action. |
| `POST` | `/projects/{project}/episodes/{episode_num}/audio/generate` | `generate_audio` | 批量生成语音（IndexTTS2）。 |
| `GET` | `/projects/{project}/episodes/{episode_num}/optimize/video-global/billing-quote` | `global_optimize_video_billing_quote` | Return the number of Beat prompt generations the batch action can run. |
| `POST` | `/projects/{project}/episodes/{episode_num}/optimize/video-global` | `global_optimize_video` | 全局视频提示词优化（草图 → AI 自由决策每个 beat 的 i2v/k2v 模式）。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/grids/{grid_index}/regenerate` | `regenerate_grid` | 重新生成单个网格。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/render/plan` | `render_plan` | Return the server-authoritative render plan for selected beats. |
| `POST` | `/projects/{project}/episodes/{episode_num}/render/execute` | `render_execute` | Validate and dispatch a render plan through the current selected-regen |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/regenerate` | `regenerate_beats` | 选中 Beats 再生画面。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/sketches/regenerate` | `regenerate_sketches` | 选中 Beats 再生草图。 |
| `GET` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/pano-background/manifest` | `get_beat_pano_background_manifest` | Return the typed 360 viewer manifest for Beat selected-background capt |
| `GET` | `/projects/{project}/director-stage/palette` | `get_default_director_stage_palette` | Return the shared director-stage palette used by local/freezone worlds |
| `GET` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/director-stage/manifest` | `get_beat_director_stage_manifest` | Return the typed 3GS director-stage manifest for Beat-level capture. |
| `GET` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/director-stage/overlay` | `get_beat_director_stage_overlay` | Load the current Beat 3GS overlay, or inherit the previous same-scene |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/director-stage/overlay` | `save_beat_director_stage_overlay` | Persist the current Beat 3GS overlay to director_blockings/epNNN/beat_ |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/director-stage/control-frame` | `export_beat_director_stage_control_frame` | Persist Director Render control-frame PNG layers and frame_meta.json. |
| `GET` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/background-anchors` | `get_beat_background_anchors` | Return NiceGUI-compatible single-beat background anchor options. |
| `PATCH` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/background-anchor` | `update_beat_background_anchor` | Persist the single-beat background anchor selection. |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/background-anchor/crop` | `crop_beat_background_anchor` | Crop a source background into the beat-owned render background slot. |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/background-anchor/upload` | `upload_beat_background_anchor` | Upload an external render-background reference for a single Beat. |
| `GET` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/director-control-frame` | `get_director_control_frame_status` | Return the NiceGUI director control frame status for one beat. |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/director-control-to-sketch` | `director_control_to_sketch` | Start the existing Direct Render combined.png -> canonical sketch task |
| `GET` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/sketch/pose-editor` | `get_sketch_pose_editor` | Return NiceGUI-compatible pose editor payload for a canonical sketch. |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/sketch/pose-editor` | `save_sketch_pose_editor` | Persist pose editor strokes/skeletons back to the canonical sketch. |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/sketch/crop` | `crop_current_sketch` | Crop and overwrite the canonical sketch, matching NiceGUI current-imag |
| `POST` | `/projects/{project}/episodes/{episode_num}/sketches/generate-missing-manual` | `generate_missing_manual_sketches` | Dispatch sketch regen only for manually inserted beats missing sketche |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/video` | `generate_single_video` | 单 Beat 视频再生。 |
| `GET` | `/projects/{project}/episodes/{episode_num}/video-pool` | `list_video_pool` | — |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/video-pool-select` | `select_video_pool` | — |
| `GET` | `/projects/{project}/episodes/{episode_num}/grids` | `list_grids` | 查看网格预览和图片池。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/grids/rebuild-pool` | `rebuild_grids_pool_index` | Rebuild the episode image pool index using the same helper as NiceGUI. |
| `GET` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/sketch-candidates` | `get_beat_sketch_candidates` | Return sketch pool candidates for a beat without treating them as the |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/pool-select` | `select_pool_image` | 选择 pool 图片，按类型设为 beat 首帧或草图。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/sketch/upload` | `upload_beat_sketch` | Upload a beat sketch, store the canonical sketch file, and add it to t |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/render/upload` | `upload_beat_render` | Upload a beat render first frame, promote it, and add it to the pool. |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/audio` | `regenerate_beat_audio` | 重新生成单个 beat 的 IndexTTS2 语音。 |
| `GET` | `/projects/{project}/episodes/{episode_num}/export/srt` | `export_srt` | 导出 SRT 字幕文件。 |
| `GET` | `/projects/{project}/episodes/{episode_num}/export/video` | `export_final_video` | Download the composed final episode video. |
| `POST` | `/projects/{project}/episodes/{episode_num}/grids/{grid_index}/upload` | `upload_grid` | 上传单张网格整图并更新 pool index 中同 scope 的 grid_path。 |
| `GET` | `/projects/{project}/episodes/{episode_num}/grids/{grid_index}/prompt` | `export_grid_prompt` | 读取 pool index 中记录的单张网格 prompt 文本。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/grids/{grid_index}/sketch-preview` | `sketch_grid_preview` | Return the same sketch-thumbnail preview NiceGUI shows for planned gri |
| `POST` | `/projects/{project}/episodes/{episode_num}/grids/{grid_index}/cut` | `cut_grid` | 将网格切割为单个 beat 图片入池。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/export/zip` | `export_zip` | 打包指定集的所有资源为 ZIP 文件下载。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/sketches/assign-colors` | `assign_sketch_colors` | 为本集出场身份和全局道具分配共享颜色。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/sketches/detect-identities` | `detect_sketch_identities` | AI 视觉识别草图中出现的身份/道具颜色标记。 |

### 5.11 `api/routes/tasks.py`（7 个）

任务列表、详情、SSE 流、取消、清理已完成任务、配额查询

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `GET` | `/projects/{project}/tasks` | `list_project_tasks` | 列出单个项目的任务。生产多节点路径由 OpenResty 路由到项目 home node。 |
| `GET` | `/projects/{project}/tasks/limits` | `get_project_task_limits` | 查询单个项目各队列的项目池和当前用户额度。 |
| `DELETE` | `/projects/{project}/tasks/completed` | `clear_project_completed_tasks` | 删除单个项目的已完成任务记录。 |
| `GET` | `/projects/{project}/tasks/{task_type}/{episode}` | `get_project_task` | 查询单个项目内指定任务的状态。 |
| `GET` | `/projects/{project}/tasks/stream` | `stream_project_tasks` | 项目级 SSE 任务流。OpenResty 可按 project_id 路由到 home node。 |
| `GET` | `/projects/{project}/tasks/{task_type}/{episode}/stream` | `stream_project_task` | 项目级单任务 SSE 端点。 |
| `DELETE` | `/projects/{project}/tasks/{task_type}/{episode}` | `cancel_project_task_route` | 终止一个项目任务。 |

### 5.12 `api/routes/freezone.py`（114 个）

画布：图片/视频/音频/文本节点生成、Skill 运行、画布存储、资产库、提交回主线

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `GET` | `/freezone/skills` | `freezone_skills` | — |
| `POST` | `/freezone/agent-config/bundles:validate` | `validate_freezone_agent_bundle` | — |
| `POST` | `/freezone/agent-config/bundles:install` | `install_freezone_agent_bundle` | — |
| `POST` | `/freezone/agent-config/bundles:export` | `export_freezone_agent_bundle` | — |
| `GET` | `/freezone/agent-config/{kind}` | `list_freezone_agent_config` | — |
| `GET` | `/freezone/hermes-workflow-skills` | `list_freezone_hermes_skills` | — |
| `POST` | `/freezone/agent-config/{kind}` | `save_freezone_agent_config_item` | — |
| `DELETE` | `/freezone/agent-config/{kind}/{item_id}` | `delete_freezone_agent_config_item` | — |
| `POST` | `/freezone/recipes/compile` | `compile_freezone_recipe` | Compile an effective user Recipe without returning its internal defini |
| `POST` | `/freezone/recipes/compile-batch` | `compile_freezone_recipe_batch` | Compile several independent node prompts without one failure cancellin |
| `POST` | `/freezone/recipes/generate-text` | `generate_freezone_recipe_text` | Compile and execute one catalog-backed text node. |
| `POST` | `/projects/{project}/freezone/upload` | `freezone_upload` | 把外部资源上传保存到 `freezone/_uploads/`。 |
| `POST` | `/projects/{project}/freezone/reference-file-upload` | `freezone_reference_file_upload` | 保存视频模型参考文件，并限制为不超过 100 MB。 |
| `POST` | `/projects/{project}/freezone/assets/copy` | `freezone_copy_assets_from_project` | 跨项目粘贴：把源项目的素材拷进本项目的 `freezone/_uploads/`。 |
| `POST` | `/projects/{project}/freezone/three-d-viewer/screenshot` | `freezone_three_d_viewer_screenshot` | 保存内置 3D viewer 普通截图到 Freezone 输出目录。 |
| `POST` | `/projects/{project}/freezone/gen` | `freezone_gen` | 图片处理：启动文生图任务，返回可供 SSE 追踪的 `task_key`。 |
| `POST` | `/projects/{project}/freezone/sketch-from-context` | `freezone_sketch_from_context` | 主线上下文：从 Beat / 背景 / 导演合成图生成草图候选。 |
| `POST` | `/projects/{project}/freezone/frame-from-context` | `freezone_frame_from_context` | 主线上下文：从草图和可选背景生成分镜候选。 |
| `POST` | `/projects/{project}/freezone/scene-360` | `freezone_scene_360` | 图片处理：基于场景 master 源图生成 2:1 的 360 全景候选图。 |
| `POST` | `/projects/{project}/freezone/ai-staging-prop` | `freezone_ai_staging_prop` | — |
| `POST` | `/projects/{project}/freezone/skills/{skill_id}/run` | `freezone_skill_run` | — |
| `POST` | `/projects/{project}/freezone/multi-view` | `freezone_multi_view` | 图片处理：基于单张源图做多角度重构 / 机位重定位。 |
| `POST` | `/projects/{project}/freezone/relight` | `freezone_relight` | 图片处理：打光。基于源图和打光参考图的光照重塑接口。 |
| `POST` | `/projects/{project}/freezone/template-edit` | `freezone_template_edit` | 图片处理：九宫格下拉菜单统一编辑接口。 |
| `GET` | `/projects/{project}/freezone/image/camera-options` | `freezone_image_camera_options` | 图片处理：返回摄像机参数选项列表。 |
| `GET` | `/projects/{project}/freezone/image/style-templates` | `freezone_image_style_templates` | 图片处理：返回风格模板列表(默认内置清单,可用 STYLE_GALLERY_MANIFEST 覆盖)。 |
| `POST` | `/projects/{project}/freezone/image-to-3gs` | `freezone_image_to_3gs` | 图片处理：把 Freezone 图片节点作为 SHARP 输入，生成 Freezone 3GS PLY。 |
| `POST` | `/projects/{project}/freezone/upscale` | `freezone_upscale` | 图片处理：高清放大接口。 |
| `POST` | `/projects/{project}/freezone/outpaint` | `freezone_outpaint` | 图片处理：扩图接口。 |
| `POST` | `/projects/{project}/freezone/redraw` | `freezone_redraw` | 图片处理：重绘接口。 |
| `POST` | `/projects/{project}/freezone/extract-frames` | `freezone_extract_frames` | 视频处理：从视频中抽取关键帧，返回任务 `task_key`。 |
| `POST` | `/projects/{project}/freezone/analyze-shots` | `freezone_analyze_shots` | 视频处理：分析一组关键帧的镜头内容，返回任务 `task_key`。 |
| `POST` | `/projects/{project}/freezone/analyze-video-story` | `freezone_analyze_video_story` | 视频处理：抽帧并解析视频故事，返回任务 `task_key`。 |
| `POST` | `/projects/{project}/freezone/video-breakdown` | `freezone_video_breakdown` | 视频处理：逐帧拉片，把一条视频拆成分镜 / 动态 / 音乐参考，返回任务 `task_key`。 |
| `POST` | `/projects/{project}/freezone/text/generate` | `freezone_text_generate` | 文本节点：根据用户要求生成可继续编辑的自由文本。 |
| `POST` | `/projects/{project}/freezone/text/translate` | `freezone_text_translate` | 文本工具：中英文互译，供各类节点编写提示词时直接调用。 |
| `GET` | `/projects/{project}/freezone/audio/references` | `freezone_audio_references` | 获取 Freezone 音频节点可用的账号级音色、项目解说人与角色参考音频。 |
| `POST` | `/projects/{project}/freezone/audio/voices` | `create_freezone_audio_voice` | 创建账号级“我的音色”。 |
| `GET` | `/projects/{project}/freezone/audio/voices/{voice_id}/media` | `get_freezone_audio_voice_media` | — |
| `POST` | `/projects/{project}/freezone/text/story-script` | `freezone_story_script_generate` | 文本工具：根据上传剧本内容生成结构化故事脚本表。 |
| `GET` | `/projects/{project}/freezone/video/camera-templates` | `freezone_video_camera_templates` | 视频处理：返回文生视频运镜模板库。 |
| `GET` | `/projects/{project}/freezone/video/models` | `freezone_video_models` | 视频处理：返回和 NovelVideo 视频模型下拉一致的可见模型。 |
| `GET` | `/projects/{project}/freezone/image/models` | `freezone_image_models` | 图片处理：返回和 NovelVideo 图片模型下拉一致的可见模型。 |
| `POST` | `/projects/{project}/freezone/marks/detect` | `freezone_mark_detect` | 图片处理：识别单张图片中点击点或框选区域的局部元素标记。 |
| `POST` | `/projects/{project}/freezone/image/reverse-prompt` | `freezone_image_reverse_prompt` | 图片处理：异步反推图片提示词。 |
| `GET` | `/projects/{project}/freezone/video/character-library` | `freezone_video_character_library` | 视频处理：获取文生视频角色素材库。 |
| `POST` | `/projects/{project}/freezone/video/character-library` | `freezone_add_video_character_library_item` | 视频处理：把上传好的素材登记到资产库（图片/视频/音频）。 |
| `GET` | `/projects/{project}/freezone/video/asset-library/folders` | `freezone_asset_library_folders` | 视频处理：列出用户自建的资产库文件夹（系统文件夹由前端按保留 key 生成）。 |
| `POST` | `/projects/{project}/freezone/video/asset-library/folders` | `freezone_add_asset_library_folder` | 视频处理：新建一个资产库文件夹。 |
| `PATCH` | `/projects/{project}/freezone/video/asset-library/folders/{folder_id}` | `freezone_update_asset_library_folder` | 视频处理：给资产库文件夹改名或换封面。系统文件夹没有实体记录，一律 404。 |
| `DELETE` | `/projects/{project}/freezone/video/asset-library/folders/{folder_id}` | `freezone_delete_asset_library_folder` | 视频处理：删掉一个自建文件夹，柜内素材条目一并从资产库移除。 |
| `POST` | `/projects/{project}/freezone/video/asset-library/sync-from-mainline` | `freezone_sync_asset_library_from_mainline` | 视频处理：把主线的人物/场景/道具参考图与人物语音幂等同步进资产库。 |
| `PATCH` | `/projects/{project}/freezone/video/character-library/{item_id}` | `freezone_rename_video_character_library_item` | 视频处理：给资产库条目改名。 |
| `DELETE` | `/projects/{project}/freezone/video/character-library/{item_id}` | `freezone_delete_video_character_library_item` | 视频处理：删除角色素材库条目。 |
| `POST` | `/projects/{project}/freezone/video/gen` | `freezone_video_gen` | 视频处理：文生视频。 |
| `POST` | `/projects/{project}/freezone/image/animate` | `freezone_image_animate` | 将当前项目的画布图片作为锁定首帧，生成固定规格的动态图。 |
| `POST` | `/projects/{project}/freezone/image/vectorize` | `freezone_image_vectorize` | 将当前项目的图片节点异步转换为 SVG。 |
| `POST` | `/projects/{project}/freezone/image/animate-gif` | `freezone_image_animate_gif` | — |
| `POST` | `/projects/{project}/freezone/video/i2v` | `freezone_video_i2v` | 视频处理：图片驱动视频。 |
| `POST` | `/projects/{project}/freezone/video/keyframes` | `freezone_video_keyframes` | 视频处理：关键帧视频。 |
| `POST` | `/projects/{project}/freezone/video/omni-gen` | `freezone_video_omni_gen` | 视频处理：全能参考文生视频。 |
| `POST` | `/projects/{project}/freezone/video/video-edit` | `freezone_video_edit` | 视频处理：视频编辑。 |
| `POST` | `/projects/{project}/freezone/video/video-extend` | `freezone_video_extend` | 视频处理：从一个源视频的结尾继续生成指定时长。 |
| `POST` | `/projects/{project}/freezone/video/erase` | `freezone_video_erase` | 视频处理：智能去字幕 / 框选擦除。 |
| `POST` | `/projects/{project}/freezone/video/upscale/quote` | `freezone_video_upscale_quote` | — |
| `POST` | `/projects/{project}/freezone/video/upscale` | `freezone_video_upscale` | 视频处理：目录驱动的视频超分、慢放与补帧流水线。 |
| `GET` | `/projects/{project}/freezone/video/upscale/probe` | `freezone_video_upscale_probe` | 读取源视频参数，供增强面板过滤无效的目标档位。 |
| `POST` | `/projects/{project}/freezone/video/audio-separate` | `freezone_audio_separate` | 视频处理：音视频分离。 |
| `POST` | `/projects/{project}/freezone/audio/speech` | `freezone_audio_speech` | Freezone 音频节点：文本生成语音。 |
| `POST` | `/projects/{project}/freezone/audio/eleven-music` | `freezone_audio_eleven_music` | Freezone 音频节点：文本生成音乐。 |
| `POST` | `/projects/{project}/freezone/video/compose` | `freezone_video_compose` | 视频处理：按时间线描述异步导出成片。 |
| `POST` | `/projects/{project}/freezone/edit` | `freezone_edit` | 图片处理：启动图生图 / 图编辑任务，返回 `task_key`。 |
| `GET` | `/projects/{project}/freezone/jobs/{task_type}/{job_id}/result` | `freezone_job_result` | 任务完成后，通过这个接口解析最终产物 URL。 |
| `GET` | `/projects/{project}/freezone/skills/runs/{run_id}/result` | `freezone_skill_run_result` | — |
| `POST` | `/projects/{project}/freezone/canvases:from-preset` | `create_canvas_from_preset` | 根据项目上下文创建一个预填充画布。 |
| `POST` | `/projects/{project}/freezone/projections:build-from-preset` | `build_projection_from_preset` | — |
| `POST` | `/projects/{project}/freezone/canvases/{canvas_id}/projections:from-preset` | `project_canvas_from_preset` | — |
| `POST` | `/projects/{project}/freezone/canvases/{canvas_id}/projections:remove` | `remove_canvas_projection` | — |
| `POST` | `/projects/{project}/freezone/canvases/{canvas_id}/projections:status` | `projection_status` | — |
| `GET` | `/projects/{project}/freezone/canvases` | `list_canvases` | — |
| `GET` | `/projects/{project}/freezone/canvases/{canvas_id}/revision` | `get_canvas_revision` | Read only the revision used to detect external direct-MCP writes. |
| `GET` | `/projects/{project}/freezone/canvases/{canvas_id}` | `get_canvas` | — |
| `GET` | `/projects/{project}/freezone/canvases/{canvas_id}/history` | `list_canvas_history` | — |
| `GET` | `/projects/{project}/freezone/workflow-capabilities` | `get_workflow_capabilities` | — |
| `POST` | `/projects/{project}/freezone/canvases/{canvas_id}/workflow-drafts` | `create_canvas_workflow_draft` | — |
| `GET` | `/projects/{project}/freezone/canvases/{canvas_id}/workflow-drafts/{draft_id}` | `get_canvas_workflow_draft` | — |
| `POST` | `/projects/{project}/freezone/canvases/{canvas_id}/workflow-drafts/{draft_id}/cancel` | `cancel_canvas_workflow_draft` | — |
| `PATCH` | `/projects/{project}/freezone/canvases/{canvas_id}/workflow-drafts/{draft_id}` | `patch_canvas_workflow_draft` | — |
| `POST` | `/projects/{project}/freezone/agent-product-operations` | `begin_agent_product_operation` | Admit and reserve one model-produced product before generation starts. |
| `GET` | `/projects/{project}/freezone/agent-product-operations/{operation_id}` | `get_agent_product_operation` | — |
| `GET` | `/projects/{project}/freezone/agent-generation-sessions/{generation_session_id}` | `get_agent_generation_session` | — |
| `PUT` | `/projects/{project}/freezone/agent-generation-sessions/{generation_session_id}` | `put_agent_generation_session` | — |
| `POST` | `/projects/{project}/freezone/agent-product-operations/{operation_id}/finish` | `complete_agent_product_operation` | — |
| `POST` | `/projects/{project}/freezone/canvases/{canvas_id}/workflow-drafts/{draft_id}/claim` | `claim_canvas_workflow_draft` | — |
| `POST` | `/projects/{project}/freezone/canvases/{canvas_id}/workflow-drafts/{draft_id}/finish` | `finish_canvas_workflow_draft` | — |
| `POST` | `/projects/{project}/freezone/canvases/{canvas_id}/workflow-runs` | `create_canvas_workflow_run` | — |
| `GET` | `/projects/{project}/freezone/canvases/{canvas_id}/workflow-runs` | `get_canvas_workflow_runs` | — |
| `GET` | `/projects/{project}/freezone/canvases/{canvas_id}/workflow-runs/{run_id}` | `get_canvas_workflow_run` | — |
| `PATCH` | `/projects/{project}/freezone/canvases/{canvas_id}/workflow-runs/{run_id}` | `patch_canvas_workflow_run` | — |
| `POST` | `/projects/{project}/freezone/canvases/{canvas_id}/restore` | `restore_canvas_history` | — |
| `GET` | `/projects/{project}/freezone/canvases/{canvas_id}/nodes/{node_id}/generation-history` | `get_node_generation_history` | Return backend-side generation attempts recorded for one canvas node. |
| `DELETE` | `/projects/{project}/freezone/canvases/{canvas_id}/nodes/{node_id}/generation-history` | `delete_node_generation_history_record` | Remove one entry from the history browser without deleting its media. |
| `GET` | `/projects/{project}/freezone/canvases/{canvas_id}/generation-history` | `get_canvas_generation_history` | Return every node's recorded generation attempts for a whole canvas. |
| `PUT` | `/projects/{project}/freezone/canvases/{canvas_id}` | `put_canvas` | — |
| `DELETE` | `/projects/{project}/freezone/canvases/{canvas_id}` | `delete_canvas` | — |
| `POST` | `/projects/{project}/freezone/impact` | `freezone_impact` | — |
| `GET` | `/projects/{project}/freezone/director-capture` | `freezone_director_capture_manifest` | 返回某个 beat 当前的 3GS director capture 状态。 |
| `POST` | `/projects/{project}/freezone/director-capture/sync-background` | `freezone_director_capture_sync_background` | Mirror env_only.png → selected_background.png (idempotent). |
| `GET` | `/projects/{project}/freezone/scene-assets-for-beat` | `freezone_scene_assets_for_beat` | Lazy thumbnail/source pool for a beat's "selected_background" slot. |
| `POST` | `/projects/{project}/freezone/push` | `freezone_push` | 把 Freezone candidate 媒体写回主流程 canonical slot。 |
| `GET` | `/projects/{project}/freezone/assets` | `list_freezone_assets` | 列出当前项目作用域下可供 Freezone 使用的 canonical assets。 |
| `GET` | `/projects/{project}/freezone/assets/beat-context` | `list_freezone_beat_context_assets` | 列出 default/project 画布可用的 novelvideo Beat 上下文资产。 |
| `POST` | `/projects/{project}/freezone/assets/identities` | `freezone_create_identity_asset` | 从选中的 Freezone 图片创建一个新的角色 identity。 |
| `POST` | `/projects/{project}/freezone/init` | `init_freezone` | 懒创建 Freezone 目录树，可重复调用且幂等。 |

### 5.13 `api/routes/model_gateway.py`（23 个）

CE 模型网关配置：官方/自定义/BrainClaw 模式、渠道、媒体模型映射、Embedding

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `GET` | `/config` | `get_model_gateway_config` | — |
| `GET` | `/official/media-catalog` | `get_official_media_catalog_status` | — |
| `POST` | `/official/media-catalog/preferences` | `save_official_media_catalog_preferences` | — |
| `POST` | `/official/media-catalog/check` | `check_official_media_catalog` | — |
| `POST` | `/official/enable` | `enable_official_gateway` | — |
| `POST` | `/custom/enable` | `enable_custom_gateway` | — |
| `POST` | `/hybrid/enable` | `enable_hybrid_gateway` | — |
| `POST` | `/official/config` | `save_official_gateway_config` | — |
| `POST` | `/agent/config` | `save_agent_gateway_config` | Save the CE Agent route independently from media gateway selection. |
| `POST` | `/custom/brainclaw/config` | `save_custom_brainclaw_config` | Save the BrainClaw endpoint for Custom mode (does not switch the activ |
| `POST` | `/custom/brainclaw/enable` | `enable_custom_brainclaw` | — |
| `POST` | `/custom/llm-mode` | `save_custom_llm_routing_mode` | — |
| `POST` | `/media-relay/config` | `save_media_relay_settings` | — |
| `POST` | `/custom/newapi/init` | `init_custom_newapi` | — |
| `POST` | `/custom/newapi/provider-channels` | `save_custom_newapi_provider_channels` | — |
| `DELETE` | `/custom/newapi/comfyui` | `clear_custom_newapi_comfyui` | — |
| `GET` | `/custom/newapi/channel-types` | `get_custom_newapi_channel_types` | — |
| `POST` | `/custom/newapi/provider-channel/models` | `get_custom_newapi_provider_channel_models` | — |
| `POST` | `/custom/newapi/provider-channel/sync` | `sync_custom_newapi_provider_channel` | — |
| `POST` | `/custom/newapi/channels` | `create_custom_newapi_channel` | — |
| `POST` | `/custom/newapi/channels/batch` | `create_custom_newapi_channels_batch` | — |
| `POST` | `/custom/newapi/embedding-model` | `save_custom_newapi_embedding_model` | — |
| `POST` | `/custom/newapi/media-models` | `save_custom_newapi_media_models` | — |

### 5.14 `api/routes/model_credits.py`（1 个）

生成前的积分报价查询

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `GET` | `/generation-credit-cost` | `get_generation_credit_cost` | Return display-ready credit cost for one generation action or model. |

### 5.15 `api/routes/styles.py`（8 个）

风格列表、预览、创建、分析、上传预览图

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `GET` | `/styles` | `list_styles` | 列出所有风格（预设 + 自定义）。 |
| `GET` | `/styles/{style_id}` | `get_style` | 获取风格详情。 |
| `GET` | `/styles/{style_id}/preview` | `get_style_preview` | 返回预设风格的参考预览图。 |
| `POST` | `/styles` | `create_style` | 创建自定义风格。 |
| `DELETE` | `/styles/{style_id}` | `delete_style` | 删除自定义风格。 |
| `POST` | `/styles/{style_id}/preview` | `preview_style` | 使用指定风格生成预览图。 |
| `POST` | `/projects/{project}/styles/analyze` | `analyze_style` | 上传参考图片，AI 分析并提取风格参数。 |
| `POST` | `/projects/{project}/styles/preview-upload` | `upload_style_preview` | 立即保存自定义风格参考图，不等待 AI 风格分析。 |

### 5.16 `api/routes/pipeline.py`（1 个）

流水线聚合状态（一次拿到 ingest→plan→script→…各阶段进度）

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `GET` | `/projects/{project}/pipeline/status` | `pipeline_status` | — |

### 5.17 `api/routes/files.py`（2 个）

文件下载与预览（带路径穿越防护）

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `GET` | `/projects/{project}/files/{file_path:path}` | `download_file` | 下载项目内的生成文件。 |
| `GET` | `/projects/{project}/media/{file_path:path}` | `preview_file` | 预览项目内媒体文件。 |

### 5.18 `api/routes/html_artifacts.py`（11 个）

画布 HTML 产物的版本化存取、历史、导出。路由前缀 `/projects/{project}/freezone/html-artifacts`，下表路径相对于该前缀。

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `POST` | `/` | `create` | 创建产物（首版） |
| `GET` | `/` | `list_artifacts` | 列出项目下所有产物 |
| `GET` | `/creation-lookup` | `find_creation` | — |
| `GET` | `/{artifact_id}` | `get` | — |
| `PUT` | `/{artifact_id}` | `update` | — |
| `GET` | `/{artifact_id}/versions` | `versions` | — |
| `POST` | `/{artifact_id}/restore` | `restore` | — |
| `GET` | `/{artifact_id}/preview` | `preview` | — |
| `GET` | `/{artifact_id}/preview-media/{expires}/{token}/{file_path:path}` | `preview_resource` | — |
| `GET` | `/{artifact_id}/export` | `export` | — |
| `POST` | `/{artifact_id}/node-history` | `record_node_history` | — |

### 5.19 `api/routes/skill_imports.py`（6 个）

外部 Skill 转换任务的提交、轮询、重试、安装。路由前缀 `/projects/{project}/freezone/skill-imports`，下表路径相对于该前缀。

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `POST` | `/` | `submit` | 提交转换任务 |
| `GET` | `/` | `listing` | 列出本项目转换任务 |
| `GET` | `/{import_id}` | `detail` | — |
| `POST` | `/{import_id}/retry` | `retry` | — |
| `POST` | `/{import_id}/install` | `install` | — |
| `POST` | `/{import_id}/validate` | `validate_draft` | — |

### 5.20 `api/routes/chat.py`（19 个）

WebSocket 对话、会话清除、取消回合、画布命令回执、工具结果回填

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `POST` | `/chat/cancel` | `cancel_chat_turn` | Best-effort cancellation for the active agent turn. |
| `POST` | `/chat/clear` | `clear_chat_scope` | Clear one conversation and start a fresh Codex context for that scope. |
| `GET` | `/projects/{project}/chat/director-auto` | `get_director_auto_run` | — |
| `POST` | `/projects/{project}/chat/director-auto/start` | `start_director_auto_run` | — |
| `POST` | `/projects/{project}/chat/director-auto/pause` | `pause_director_auto_run` | — |
| `POST` | `/projects/{project}/chat/director-auto/suspend` | `suspend_director_auto_run` | — |
| `POST` | `/projects/{project}/chat/director-auto/resume` | `resume_director_auto_run` | — |
| `POST` | `/chat/notifications` | `append_chat_notification` | — |
| `POST` | `/chat/ui-events` | `append_chat_ui_event` | — |
| `POST` | `/chat/permission-result` | `resolve_agent_permission` | — |
| `POST` | `/chat/freezone-canvas-agents` | `list_freezone_canvas_agents` | — |
| `POST` | `/chat/canvas-command-tool-result` | `resolve_canvas_command_tool_result` | — |
| `POST` | `/chat/canvas-context-tool-result` | `resolve_canvas_context_tool_result` | — |
| `POST` | `/chat/skill-studio-tool-result` | `resolve_skill_studio_tool_result` | — |
| `GET` | `/chat/agent-capability-price-reference` | `agent_capability_price_reference` | Return the user-facing scope of Agent-only billing, excluding NewAPI m |
| `POST` | `/chat/clarification-tool-result` | `resolve_clarification_tool_result` | — |
| `POST` | `/chat/pending-canvas-commands` | `list_pending_canvas_commands` | — |
| `GET` | `/chat/canvas-commands/stream` | `stream_canvas_commands` | — |
| `WEBSOCKET` | `/chat/ws` | `chat_ws` | — |

### 5.21 `api/routes/auth.py`（2 个）

登出与当前用户

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `POST` | `/auth/logout` | `logout` | Best-effort revoke the session and always clear the browser cookie. |
| `GET` | `/auth/me` | `me` | — |

### 5.22 `api/routes/config.py`（1 个）

前端运行时配置（公开、无敏感信息）

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `GET` | `/config` | `get_runtime_config` | — |

### 5.23 `api/routes/diagnostics.py`（2 个）

证据面计数与画布命令推送计数的只读诊断

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `GET` | `/diagnostics/canvas-command-push` | `get_canvas_command_push_counters` | Worker-local counters only; never expose directory or project identiti |
| `GET` | `/diagnostics/evidence` | `get_evidence_counters` | Return shared evidence-plane counters and any halting outcomes. |

### 5.24 `api/routes/release_notifications.py`（1 个）

版本更新通知流

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `GET` | `/release-notifications` | `get_release_notifications` | — |

### 5.25 `api/routes/product_surfaces.py`（1 个）

当前用户可见的功能面

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `GET` | `/me` | `current_product_surface_access` | — |

### 5.26 `api/routes/routes.py`（12 个）

验证系统（草图事实核查、一致性、相似度、评分、整集总览）

| 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/verify` | `verify_beat` | 验证单个 beat 的草图/首帧是否匹配描述。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/verify/sketch-edit-execute/start` | `start_sketch_edit_execute` | 启动 episode 级 sketch edit execute 后台任务。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/verify/consistency` | `verify_consistency` | 检查整集跨 beat 的角色/服装一致性。支持 verify_type="sketch"(默认) 或 "frame"。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/verify-frame` | `verify_frame` | 验证单个 beat 的首帧渲染质量（对比草图）。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/score` | `score_beat` | T3: 对单个 beat 的草图进行内容匹配评分。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/score-batch` | `score_batch` | T3 批量: 对指定 beat 的所有候选草图打分。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/beats/{beat_num}/compare` | `compare_beat` | T4: 对比多张候选草图，选择最佳。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/verify/continuity` | `verify_continuity` | T6: 检查相邻 beat 之间的叙事连贯性。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/verify/similarity` | `verify_similarity` | T7: 像素级草图相似度检测（零 LLM 成本）。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/verify/sketch-select` | `sketch_select` | 编排端点: 一站式草图择优 — 加载候选 → T1/T2 淘汰 → T3 评分 → T4 对比 → 输出选择。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/verify/episode-overview` | `verify_episode_overview` | T8: 导演视角全局分镜审片 — 整集草图拼网格图，一次 LLM 调用评估整体表现。 |
| `POST` | `/projects/{project}/episodes/{episode_num}/verify/sketch-colors` | `verify_sketch_colors` | Step 12.4: 草图颜色交叉验证 — 检测草图中角色颜色是否与剧本预期一致。 |

## 6. 典型调用

### 6.1 建项目 → 传小说 → 启动导入

```bash
BASE=http://localhost:8780/api/v1
# 1) 建项目
curl -s -X POST "$BASE/projects" -H 'Content-Type: application/json' \
  -d '{"name":"demo","title":"演示项目"}' -b cookies.txt

# 2) 上传小说（multipart）
curl -s -X POST "$BASE/projects/demo/ingest/upload" -b cookies.txt \
  -F "file=@novel.txt"

# 3) 启动导入，拿 task_key
curl -s -X POST "$BASE/projects/demo/ingest/start" -b cookies.txt \
  -H 'Content-Type: application/json' -d '{"pipeline":"structured_v1"}'
# → {"ok":true,"task_key":"..."}

# 4) 追进度
curl -N "$BASE/projects/demo/tasks/<task_key>/stream" -b cookies.txt
```

### 6.2 生成单 beat 视频

```bash
curl -s -X POST "$BASE/projects/demo/episodes/1/beats/3/video" -b cookies.txt \
  -H 'Content-Type: application/json' -d '{"backend":"seedance2"}'
```

### 6.3 画布生成（Freezone）

```bash
curl -s -X POST "$BASE/projects/demo/freezone/gen" -b cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{"node_id":"n1","prompt":"雨夜霓虹街道","aspect_ratio":"16:9"}'
# → {"ok":true,"job_id":"...","task_key":"..."}
```

## 7. 三个容易误用的端点

| 端点 | 误用 | 正确做法 |
|---|---|---|
| `POST /projects/{p}/episodes/plan` | 反复调用期待「重新分集」 | 它是全量重规划，会覆盖既有 beats；只想改一集用 `PATCH /episodes/{n}` |
| `POST /projects/{p}/freezone/*` | 当前端同步接口用，等返回结果 | 一律 202 + job_id，结果要轮询 `.../jobs/{task_type}/{job_id}/result` 或订阅 SSE |
| `DELETE /projects/{p}` | 以为删了目录 | 默认软删（`status=deleted`）；彻底清除是 `purge`，且需要 `projects:purge` scope |
