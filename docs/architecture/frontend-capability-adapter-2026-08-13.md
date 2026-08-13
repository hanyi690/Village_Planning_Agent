# 前端能力 × 后端 v1 适配分析（2026-08-13）

> 目标：前端每个能力都对齐"现在的后端"（v1 稳定契约），形成可运行、可验证的实现闭环。
> 分析口径：
> - 后端事实来源：`backend/app/api/v1/routes/*`（9 条路由）、`backend/app/api/v1/contracts.py`、
>   `backend/app/infrastructure/artifacts/runtime.py`（ARTIFACT_KEYS）、真实后端冒烟测试（2026-08-13）。
> - 适配原则：前端只消费 v1 真实产出；遗留端点一律不调用；后端尚不提供的能力显式登记并给出恢复条件。
> - 规划文本能力**暂不恢复**（另行确认）。

---

## 1. 能力适配矩阵（总表）

| # | 前端能力 | 后端 v1 提供 | 适配方案 | 状态 |
|---|---|---|---|---|
| 1 | 会话创建（VillageInputForm/startPlanning） | POST /api/v1/sessions（multipart） | 表单字段与后端严格一致（project_name/village_name/区划/规划期限/step_mode/rag_*/文件） | 已闭环 |
| 2 | SSE 实时进度与报告流 | GET /events（SSE）+ /events/sync | 只监听 6 种 v1 顶层事件；`progress.data.type` 透传真实维度/图层事件 | 已闭环 |
| 3 | L1/L2/L3 报告查看（ReportViewer） | 报告由 SSE dimension_complete 事件累积 | store 累积 + 刷新事件重放恢复；不再调用 /layer/reports | 已闭环 |
| 4 | GIS 地图（MapView/map-layers） | GET /map-layers（权威快照） | 按 snapshot_checksum 整体替换；delivery 前 404 兜底 | 已闭环 |
| 5 | 中间产物显示 | GET /artifacts/{key}（24 个 ARTIFACT_KEYS） | IntermediateArtifactsPanel 轮询展示；404 显示未产出 | 已闭环（可增强） |
| 6 | 人工审核（useApprovalActions） | GET/POST /human-review | event_id 乐观锁 + approve/reject/retry；409 冲突刷新 | 已闭环 |
| 7 | 检查点分叉恢复（rollback） | POST /resume（mode=checkpoint） | checkpoint_id 分叉；检查点列表从 SSE checkpoint_saved 事件累积 | 已闭环 |
| 8 | 会话历史列表 | （无 /api/projects） | 本地会话历史 + localStorage 删除标记 | 已本地化 |
| 9 | 对话（chat） | （无 chat 端点） | 本地回显"v1 暂不可用"，不发起网络 | 已本地化 |
| 10 | 质量评估页（/evaluation） | （无 /api/evaluation） | 列表返回空、其余抛"已下线" | 已本地化 |
| 11 | 交付结论展示（DeliveryStatusBanner） | GET /delivery | complete/partial/diagnostic_only + statutory_complete + deferral/diagnostic 摘要 | 已闭环（可增强） |
| 12 | 导出（ExportDialog） | （无下载端点） | 显示"导出暂不可用"，等待 /delivery.downloads 服务 | 需后端 |
| 13 | RAG/step-mode 运行时配置 | （无配置端点；创建时支持 step_mode/rag_*） | stub 抛错；配置仅在创建会话时传入 | 需后端 |
| 14 | 跨会话报告对比 | （无报告资源） | compare 降级为空 | 需后端 |
| 15 | 规划文本（PlanningTextViewer） | （无规划文本端点） | **暂不恢复** | 暂不恢复 |

---

## 2. 已闭环能力（实现机制）

### 2.1 会话创建（能力 1）
- 实现：`planning-api.startPlanning` → POST /api/v1/sessions，multipart 字段与 `backend/app/api/v1/session_create.py` 表单参数逐一对应。
- 已验证：冒烟测试 201 返回 `SessionCreated{session_id, stream_url, status}`；缺 village_data 返回结构化 `ApiError`。

### 2.2 SSE 实时进度与报告流（能力 2）
- 实现：`planning-api.createStream` 只注册 6 种 v1 顶层事件；`parseEvent` 对 `progress.data.type` 透传真实维度/图层事件（后端 `public_event` 将内部事件放入 progress.data）。
- 恢复：`syncEvents(sessionId, after)` 按 seq 补拉；`bootstrapPlanningSession`/`hydrateSessionSnapshot` 在刷新时重放事件重建报告与进度。

### 2.3 报告查看（能力 3）
- 数据源：SSE `dimension_complete`（data.full_content）累积进 `store.reports[layer][dimKey]`；刷新后由事件重放重建。
- `useHandlers.fetchLayerReportsFromBackend` 已改为读 store（无网络）；Workbench 轮询不再调用 /layer/reports。

### 2.4 GIS 地图（能力 4）
- 实现：`useDeliverySync` 在 delivery_ready/终态/resync 时拉取 /delivery + /map-layers；`normalizeV1MapLayers` 将 v1 `current|planned|overlay|constraint` 图层映射为内部渲染词汇；`applyMapLayers` 按 `snapshot_checksum` 整体替换。
- 交付前 /map-layers 404 → `.catch(() => null)` 兜底。

### 2.5 中间产物（能力 5）
- 实现：`IntermediateArtifactsPanel` 通过 `getArtifact(sessionId, key)` 读取 24 个真实 ARTIFACT_KEYS；按阶段分组、8s 轮询、404 显示"未产出"；GeoJSON 显示要素数与属性、列表显示图层名、对象显示关键字段。

### 2.6 人工审核（能力 6）
- 实现：`useApprovalActions.resolveWithDecision` 读取当前 event_id（store.humanReview 或 GET /human-review）后提交 `resolveHumanReview`（POST /human-review，action + feedback）；409 冲突由调用方刷新 /state 与 /human-review。

### 2.7 检查点（能力 7）
- 检查点列表：SSE `checkpoint_saved` 事件 → store.checkpoints 累积（key/regular、layer、phase）。
- 分叉恢复：`rollback(checkpointId)` → POST /resume `{mode:'checkpoint', checkpoint_id}`，随后 syncBackendState 刷新。

### 2.8 会话历史（能力 8）
- `loadVillagesHistory` 只保留本地会话历史（本会话内新建 + localStorage 删除标记）；`deleteSession`/`clearAllHistory` 仅本地生效，不再调用已删除的 DELETE /sessions。

### 2.9 对话（能力 9）
- `sendChatMessage` 本地回显："对话功能在 v1 暂不可用（后端未提供 chat 端点）"，不发起网络。

### 2.10 质量评估页（能力 10）
- `evaluationApi` 列表返回空、其余方法抛"已下线"；页面显示"暂无会话"。

### 2.11 交付结论（能力 11）
- `DeliveryStatusBanner` 展示 delivery_status 与 statutory_complete 的组合语义；partial/diagnostic_only 明确标注不可作为法定完整成果；展示 deferral/diagnostic 摘要。

---

## 3. 本轮推进的适配

### 3.1 交付成果文件清单（能力 11 增强）
- 已实现（2026-08-13）：`DeliveryStatusBanner` 重构为统一布局，交付可用时列出 `delivery.deliverables`（描述/类型、格式、deliverable_id），并注明"下载端点（/delivery.downloads）待后端提供后启用"。

### 3.2 中间产物详情展开（能力 5 增强）
- 已实现（2026-08-13）：点击条目展开/收起 payload JSON 详情（截断 4000 字符 + 提示），便于核对每个中间产出的真实内容。

### 3.3 会话创建表单字段兜底（能力 1 核对）
- 已核对：前端未传 `enable_review/stream_mode/need_human_review/input_mode`，与后端表单严格一致；`StartPlanningRequest` 中这些可选字段保留供后续 v1 扩展。

---

## 4. 需后端 v1/v2 提供的能力（登记，恢复条件）

| 能力 | 当前处理 | 后端需提供 | 前端恢复动作 |
|---|---|---|---|
| 导出/下载 | ExportDialog 显示"暂不可用" | /delivery.downloads（或 artifacts 的下载端点）服务 deliverables.path | ExportDialog 改为从 /delivery.downloads 下载；移除 stub |
| map-layers 样式元数据 | 图层无 color/style/legend/default_visible | 蓝图 Task 3：MapLayer 增加 layer_id/style/legend/default_visible | getRenderLayers 透传；normalizeV1MapLayers 应用样式 |
| RAG/step-mode 运行时配置 | stub 抛错 | v1 配置端点（PATCH /sessions/{id}/…） | SettingsPanel 恢复 |
| 跨会话报告对比 | compare 降级为空 | v1 报告/版本资源 | ReportViewer compare 恢复 |
| 会话删除 | 仅本地删除 | v1 DELETE /sessions | planning-context deleteSession 恢复后端删除 |

## 5. 暂不恢复

- 规划文本（PlanningTextViewer / getPlanningText / generatePlanningText / exportPlanningTextDocx）：后端无对应端点，暂不恢复；如后续需要，应以后端 v1 规划文本资源为前提（UI 入口当前仍显示"已下线"错误提示）。

### 3.4 地图样式/图例透传（能力 4 增强）
- 已实现（2026-08-13）：`useDeliverySync` 同步拉取 `render_layers` artifact（v1 `getArtifact`），
  `gis-normalize.applyRenderLayerStyles` 按 v1 layer_name 合并后端 DELIVER 真实产出的
  `color / style / default_visible` 到 `GISLayerConfig`（MapView 原生消费 layer.color/style）。
  颜色/样式来自后端真实产出，非前端重建分类颜色。
- 单测：`gis-normalize.test.ts` 新增 `applyRenderLayerStyles` 用例（jest 94 tests）。

### 3.5 e2e v1 契约冒烟测试（闭环固化）
- 新增 `frontend/e2e/v1-contract.spec.ts`：直连真实后端验证
  `create -> state -> events/sync -> delivery -> human-review -> map-layers -> artifacts` 全部按契约响应，
  并断言遗留端点 `/api/projects` 已下线（404）。
- 已验证：`BACKEND_URL=http://127.0.0.1:8000 npx playwright test e2e/v1-contract.spec.ts` → 2 passed（约 2s）。
- 测试发现并固化两个真实契约细节：`SessionCreated` 不含 `schema_version`；会话创建后首个检查点异步落库
  （`/state` 需轮询等待，与前端行为一致）。

## 6. 后续动作

- 交付物清单与中间产物详情本轮实现。
- 后端 Task 3（map-layers 元数据）落库后，更新 `getRenderLayers`/`normalizeV1MapLayers` 透传样式。
- 后端提供下载端点后，`ExportDialog` 恢复为真实下载。