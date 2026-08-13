# 前端 v1 对齐梳理（2026-08-13）

> 状态：**只读分析**，未修改任何代码（后端与前端均未改动）。
> 目的：在"后端同步处理中"的前提下，梳理前端构造，逐项对比"前端需要什么"与"后端能提供什么"，
> 并给出基于 context7 最佳实践与 exa 参考案例的分阶段前端对齐实施计划。
> 范围：仅前端 `frontend/src`；后端 `/backend` 不在此次修改范围内。

---

## 1. 结论摘要（TL;DR）

1. 后端已完成蓝图收敛：**当前只暴露 9 条 `/api/v1` 稳定路由 + 健康检查 + 天地图瓦片代理**，
   旧业务命令接口（`/api/sessions/...`、`/api/projects/...`）已从后端删除。
2. 前端 `planning-api.ts` 仍调用约 **18 个已不存在的遗留端点**（feedback、layer-reports、
   checkpoints、export、planning-text、rag-config、step-mode、geocode、gis-data、projects 等），
   这些调用运行时必然 404。
3. 前端当前 `npm run type-check` **失败，共 29 个 TS 错误**，全部指向契约错配：
   - `SessionStatusResponse` 与后端 `SessionProjection` 形状不一致（`gis_layout_configs`、
     `chat_history`、`gis_generation_*` 等字段缺失）；
   - `planningApi.generateGIS` 方法不存在（断链调用）；
   - `submitFeedback` 返回类型缺少 `reply / draft_feedback / dimensions`；
   - `ChatHistoryMessage` 未从 api index 导出；`GeneratePlanningTextRequest` 缺 `use_llm`。
4. SSE 存在"双协议耦合"：后端 v1 只发 6 种顶层事件（`progress / human_review / delivery_ready /
   completed / failed / resync_required`），但前端通过 `progress.data.type` 反推内部遗留事件类型
   （`dimension_start`、`layer_completed` 等），**依赖后端泄漏内部事件形状**，违反
   `docs/frontend/API_SSE_DEVELOPER_GUIDE.md` 的"前端只依赖聚合投影"约定；
   且 `delivery_ready` 后端实际从不发送（`public_event` 未映射、事件仓库无此类型）。
5. 建议：**以 `docs/contracts/openapi-v1.json` 为单一事实来源生成 TS 类型**（context7/exa 共同推荐），
   前端只消费 v1 投影；遗留功能按后端后续 v1/v2 迁移节奏逐项切换或下线（详见 §7）。

---

## 2. 前端构造梳理

### 2.1 模块地图

```text
frontend/src
├── app/                        # Next.js App Router 入口（页面只做组合）
│   ├── layout.tsx / page.tsx   # 全局壳 + 主工作台
│   ├── evaluation/page.tsx     # 质量评估页
│   ├── kg-inspection/page.tsx  # KG 巡检页
│   ├── test-gis/               # 开发期 GIS 验证页
│   └── api/dev/gis/            # 开发期 Next 路由（仅 dev）
├── features/
│   ├── planning/               # 主业务边界（会话 API/SSE 到工作台 UI）
│   │   ├── api/                # client.ts / planning-api.ts / data-api.ts / types.ts
│   │   ├── hooks/              # useSSE / useStreaming / useDelivery / useHandlers / useSessionRestore
│   │   ├── store/              # planningStore.ts（Zustand+Immer） / planning-context.tsx
│   │   ├── types/              # base / messages / events / guards / helpers
│   │   ├── utils/              # gis-normalize / session-bootstrap / session-hydrate / report-parser
│   │   ├── config/ constants/  # 阶段、维度、GIS、UI 配置
│   │   └── components/         # 工作台 / chat / gis / layout / settings / ui
│   ├── compliance/             # 合规面板（api.ts + components）
│   ├── evaluation/             # 质量评估（api.ts + hooks + components）
│   ├── suitability/            # 适宜性面板（api.ts + components）
│   └── gis-test/               # GIS 测试页 API（独立 BASE，走 /api/gis-test）
├── types/message/              # 遗留 message 类型/guard/helper（与 features/planning/types 并存）
├── styles/                     # layer-report.css 等
└── __tests__/                  # jest 单测
```

### 2.2 数据流

```text
API/SSE -> hooks（useSSE/createStream）-> planningStore.handleSSEEvent
     |                                       |
     v                                       v
REST 投影（state/delivery/map-layers）   UI 状态（messages/gisLayers/dimensionProgress）
```

文档约定（`docs/architecture/frontend-api-v1.md`、`API_SSE_DEVELOPER_GUIDE.md`）：
- 前端只依赖 `/api/v1` response model、SSE 公开 envelope、`SessionProjection.links`、
  `DeliveryProjection`、`MapLayerCollection`、HTTP 状态码与 `ApiError.code`；
- 禁止依赖 AgentState、artifact payload、PlannedState、内部文件路径、内部 interrupt 格式；
- 页面刷新后应仅凭 REST 投影恢复，SSE 只做"何时重新拉取"的通知。

### 2.3 API 客户端构造（`features/planning/api/`）

| 文件 | 职责 | 关键点 |
|---|---|---|
| `client.ts` | 基础请求 | `apiRequest<T>`：JSON 头、3 次指数退避重试（仅网络错）、统一错误提取；`API_BASE_URL = NEXT_PUBLIC_API_URL 或 http://localhost:8000` |
| `planning-api.ts` | 会话/SSE/交付/审核 API | 26 个方法：10 个走 v1，16 个走遗留 `/api/sessions` |
| `data-api.ts` | 项目/跨会话报告 API | 4 个方法全部走遗留 `/api/projects`、`/api/sessions/.../reports` |
| `types.ts` | 请求/响应类型 | `APIResponse`、`SessionStatusResponse`、`RenderLayersResponse`、`DeliveryProjection`、`HumanReview*` 等（手写，与 OpenAPI 漂移） |

### 2.4 Store / Hooks 构造

- `planningStore.ts`：Zustand + Immer，`handleSSEEvent` 为约 40 个 case 的大 reducer，
  同时处理 v1 事件（`completed / delivery_ready / resync_required / human_review / error`）与
  遗留事件（`dimension_* / layer_* / tool_* / gis_* / rag_* / cascade_* / checkpoint_saved` 等）。
- `useSSE.ts`：连接生命周期 + 30ms 批量窗口 + 关键事件直通 + 重连后 `getStatus`/`syncEvents` 补同步。
- `useDelivery.ts`（`useDeliverySync`）：在终态 / `delivery_ready` / `resync_required` 时拉取
  `/delivery` + `/map-layers`，按 `snapshot_checksum` 整体替换图层（已对齐 v1 语义）。
- `useSessionRestore` / `usePlanningBootstrapStage` / `session-bootstrap.ts` / `session-hydrate.ts`：
  恢复流程，但全部基于 `getStatus`（形状错配的 `SessionStatusResponse`）。

### 2.5 SSE 现状（`createStream` 内建映射）

```text
后端 v1 事件     前端映射
progress          data.type 存在则反推遗留类型（dimension_start / layer_completed）
human_review      human_review_paused
failed            error
completed         completed（注册了双监听：直通 + 关闭连接）
resync_required   resync_required
delivery_ready    注册监听，但后端从不发送（死代码）
```
---

## 3. 后端能提供什么（契约面，证据：`backend/app/api/v1/routes/` + `openapi-v1.json`）

### 3.1 v1 路由全集（9 条）

| Method | Path | 响应模型 | 说明 |
|---|---|---|---|
| POST | `/api/v1/sessions` | `SessionCreated` | 创建会话（multipart），201 |
| POST | `/api/v1/sessions/{id}/resume` | `ResumeAccepted` | 中断/检查点恢复 |
| GET | `/api/v1/sessions/{id}/state` | `SessionProjection` | 页面恢复基线 |
| GET | `/api/v1/sessions/{id}/events` | SSE `text/event-stream` | 事件流（`seq` 单调，`Last-Event-ID` 续传） |
| GET | `/api/v1/sessions/{id}/events/sync?after=N` | `EventSyncResponse` | 补拉事件 |
| GET | `/api/v1/sessions/{id}/human-review` | `HumanReviewProjection` | 待审项 |
| POST | `/api/v1/sessions/{id}/human-review` | `dict` | 提交决策（`event_id` 乐观锁，409 冲突） |
| GET | `/api/v1/sessions/{id}/delivery` | `DeliveryProjection` | 交付结论 |
| GET | `/api/v1/sessions/{id}/map-layers` | `MapLayerCollection` | 权威空间快照 |
| GET | `/api/v1/sessions/{id}/artifacts/{key}` | artifact model | 读取特定 artifact（按 key） |

另有 `/api/health`、`/api/tiles/tianditu/{layer_proj}/{z}/{y}/{x}`、`/health`、`/`。

### 3.2 公开 DTO（`backend/app/api/v1/contracts.py`，`extra='forbid', strict=True`）

- `SessionProjection`：`schema_version / session_id / status(pending|running|paused|reviewing|revising|completed|failed) / active_stage / phase / progress(0..100) / human_review_pending / delivery_status / statutory_complete / last_event_seq / links`
- `DeliveryProjection`：`schema_version / session_id / available / delivery_status / statutory_complete / snapshot_checksum / deferral_summary / diagnostic_summary / deliverables / downloads`
- `MapLayer`：`layer_type(current|planned|overlay|constraint) / layer_name / crs / checksum / feature_count / geojson`
- `MapLayerCollection`：`schema_version / session_id / snapshot_checksum / delivery_status / layers[]`
- `HumanReviewProjection`：`schema_version / session_id / pending / event_id / paused_stage / items[]`
- `HumanReviewDecision`：`event_id / action(approve|retry|reject) / decisions`
- `ResumeRequest`：`mode(interrupt|checkpoint) / event_id / action / feedback / checkpoint_id / replay_from_stage`
- `ResumeAccepted`：`schema_version / session_id / mode / status / checkpoint_id / branch_id / resume_plan`
- `SessionCreated`：`session_id / stream_url / status`
- `ApiError`：`schema_version / code / message / request_id / retryable / details`
- SSE 判别联合：`ProgressEvent / HumanReviewEvent / DeliveryReadyEvent / CompletedEvent / FailedEvent / ResyncRequiredEvent`

### 3.3 蓝图进行中（不影响本次只读梳理）

- `docs/superpowers/plans/2026-08-12-accelerated-blueprint-convergence.md` Task 3 将扩展
  `map-layers` 元数据（`layer_id / layer_type / layer_name / feature_count / geojson / style /
  legend / default_visible` + 快照 checksum）。前端 `getRenderLayers` 适配层需在元数据落库后跟进，
  **当前 `MapLayer` 尚无 `layer_id/style/legend/default_visible`**。

---

## 4. 前端需要 vs 后端提供（对齐矩阵）

> 图例：已对齐 / 端点存在但契约错配 / 端点后端已删除（前端调用会 404） / 死代码或断链

### A. v1 端点（后端提供）

| 前端函数 | 端点 | 消费方 | 判定 | 说明 |
|---|---|---|---|---|
| `startPlanning` | POST /api/v1/sessions | planning-context | OK | multipart 字段与 OpenAPI 一致 |
| `createStream` | GET /events (SSE) | useSSE | MISMATCH | 依赖 `progress.data.type` 反推内部类型 |
| `syncEvents` | GET /events/sync?after=N | bootstrap/hydrate/useSSE | OK | 形状匹配 `EventSyncResponse` |
| `getStatus` | GET /state | 8 处 | MISMATCH | 类型写成 `SessionStatusResponse`，实为 `SessionProjection` |
| `getRenderLayers` | GET /map-layers | useDelivery | MISMATCH | 丢 `crs/checksum/feature_count`；待 Task3 元数据 |
| `getDelivery` | GET /delivery | useDelivery | OK | `DeliveryProjection` 一致 |
| `getHumanReview` | GET /human-review | useApprovalActions/context | MISMATCH | 包装成旧 `HumanReviewListResponse(post_l3_status)` |
| `resolveHumanReview` | POST /human-review | useApprovalActions/context | OK | `event_id + action + decisions` 一致 |
| `resumeSession` | POST /resume | planning-context | OK | `ResumeRequest` 一致 |
| `getArtifact` | GET /artifacts/{key} | 无 | DEAD | 已实现但无消费方；响应形状需与后端 model 核对 |

### B. 遗留端点（后端已删除，前端仍调用）

| 前端函数 | 遗留端点 | 消费方 |
|---|---|---|
| `submitFeedback` / `sendChatMessage` | POST /api/sessions/{id}/feedback | ReportViewer:627、planning-context:423 |
| `getLayerReports` | GET /api/sessions/{id}/layer/{layer}/reports | useHandlers:79、session-report-loader:82 |
| `getDimensionReport` | GET /api/sessions/{id}/reports/{dim_key} | （api 定义，无直接消费方） |
| `deleteSession` | DELETE /api/sessions/{id} | planning-context:347,380 |
| `getCheckpoints` | GET /api/sessions/{id}/checkpoints | session-hydrate:89 |
| `exportLayerFormat/Docx/Json/Md` | POST /api/sessions/{id}/export | ExportDialog、PlanningTextViewer |
| `exportPlanningTextDocx` | POST /api/sessions/{id}/export?planning_text=true | PlanningTextViewer:433 |
| `getPlanningText/Versions/generatePlanningText` | /api/sessions/{id}/planning-text* | PlanningTextViewer |
| `updateRagConfig` | PATCH /api/sessions/{id}/rag-config | SettingsPanel:105 |
| `updateStepMode` | PATCH /api/sessions/{id}/step-mode | SettingsPanel:123、Workbench:1588 |
| `geocodeVillage` | GET /api/sessions/{id}/geocode | planning-context:136 |
| `uploadGisData` | POST /api/sessions/{id}/gis-data | （api 定义，无直接消费方） |
| `dataApi.listVillages` | GET /api/projects | planning-context:263 |
| `dataApi.getVillageSessions` | GET /api/projects/{name}/sessions | planning-context:266、evaluation/api.ts |
| `dataApi.getCrossSessionReport` | GET /api/projects/{name}/reports/{dim_key} | ReportViewer:477 |
| `dataApi.getDimensionVersions` | GET /api/sessions/{id}/reports/{dim_key}/versions | ReportViewer:448 |

### C. 类型契约错配（`npm run type-check` 实测 29 错，抽样）

| 错误位置 | 问题 |
|---|---|
| session-bootstrap.ts:50,54 / session-hydrate.ts:117-136 / planningStore.ts:2277 | `SessionStatusResponse` 无 `gis_layout_configs`、`chat_history` |
| ReportViewer.tsx:238-261 | `SessionStatusResponse` 无 `gis_generation_id/status/error` |
| ReportViewer.tsx:595 | `planningApi.generateGIS` 不存在（断链） |
| ReportViewer.tsx:635 / Workbench:1701-1705 | `submitFeedback` 返回类型缺 `reply/draft_feedback/dimensions` |
| chat-messages.ts / 测试 | `ChatHistoryMessage` 未从 api index 导出 |
| PlanningTextViewer.tsx:384 | `GeneratePlanningTextRequest` 缺 `use_llm` |

### D. SSE 协议错配

| 项 | 现状 | 问题 |
|---|---|---|
| 顶层事件 | 后端只发 progress/human_review/completed/failed/resync_required | 前端还注册 `delivery_ready`，后端从不发送 |
| progress.data | `dict(event)` 含 `type` 等内部字段 | 前端依赖 `data.type` 反推内部类型，违反契约 |
| human_review | 后端 `data={pending,event_id,paused_stage,items}` | 前端映射为 `human_review_paused` 旧形状再消费 |
| failed | 后端 `data=ApiError` | 前端映射为 `error`，store 再读 `code/message`（可用但绕） |
| 重连 | 浏览器自动 `Last-Event-ID` + 前端 `syncEvents` | 逻辑存在，但依赖 `getStatus` 的错配类型 |
---

## 5. context7 最佳实践对比（结论到建议）

| 主题 | context7 最佳实践 | 本项目现状 | 建议 |
|---|---|---|---|
| OpenAPI 到 TS 类型 | FastAPI 官方：`@hey-api/openapi-ts` 从 openapi 生成 SDK；openapi-typescript 生成类型，CI 强制重新生成，契约漂移在编译期暴露 | 前端手写 `api/types.ts`，与 OpenAPI 已漂移（29 个 tsc 错误） | **引入 `openapi-typescript`（或 @hey-api）以 `docs/contracts/openapi-v1.json` 生成类型**，删除手写 v1 DTO |
| SSE 生命周期 | 连接对象由 middleware/store 持有；`useEffect` cleanup 关闭闭包内实例（非 ref），StrictMode 双挂载对称创建/销毁；onerror 不 close（交给浏览器重试） | `useSSE.ts` 已实现 create/close 对称；`createStream` 内自定义重连 | 保持，补：稳定 URL（useMemo）、onError 回调用 ref 防 stale |
| SSE 幂等/去重 | 单调 `seq`/`id` 去重（LRU 有界）；重连缺口超阈值先 REST 快照再续流；批量用 rAF 合并渲染 | 已有 `seq` 去重（`lastProcessedSeq`）与 30ms 批量窗口 | 保持；补：缺口检测时强制 REST 重拉（已有 `resync_required` 语义） |
| Store 外部订阅 | Zustand：`getState/subscribe/setState` 可在 React 外使用；事件到 action 路由在 store 内 | `handleSSEEvent` 大 reducer 路由约 40 种事件 | 按 v1 收敛为 6 种顶层事件 + `progress.data.type` 白名单透传 |
| 类型安全 | 生成类型 + 关键端点 Zod 运行时校验 | 无运行时校验 | 对 `map-layers`/`state` 增加轻量运行时 guard |
| API 版本化 | v1/v2 并存、deprecation/sunset 头、先测再删 | 后端已删遗留端点，前端仍在调用 | 前端立即停止调用已删端点；遗留功能列入后端迁移队列 |

## 6. exa 参考案例

| 案例 | 参考点 |
|---|---|
| [server-sent-events.com – State-Management Integration](https://www.server-sent-events.com/frontend-consumption-client-patterns/state-management-integration/) | SSE 到 Zustand/Redux 模式：事件到 action 路由、LRU 去重、rAF 批量、缺口超阈值先 REST 快照、单一多路复用端点 |
| [souyang/sse-demo](https://github.com/souyang/sse-demo) | Next.js 14 App Router + SSE 进度流：指数退避重连、心跳、cancel/retry/reset、TS strict |
| [zircon-tech/sse](https://github.com/zircon-tech/sse) | Next.js 客户端 + 服务端 SSE：进度条/表格/toast 多事件类型消费 |
| [opengig/next-nest-sse-template](https://github.com/opengig/next-nest-sse-template) | TanStack Query + SSE 模板：查询层与连接层分离 |
| [alexanderkasten/use-next-sse](https://github.com/alexanderkasten/use-next-sse) | `useSSE` hook + `createSSEHandler`：`lastEventId` 续传、reconnect 配置、`connectionState` |
| [ibuzzardo/forge](https://github.com/ibuzzardo/forge) | Next.js 14 全栈 SSE：heartbeat + reconnect-safe `id` replay + 断线后 REST 重取 + Zod 校验 |
| [FastAPI – Generating SDKs](https://fastapi.tiangolo.com/advanced/generate-clients/) | 从 OpenAPI 生成 TS 客户端（@hey-api/openapi-ts），后端变更自动反映到前端 |
| [openreplay – Type-Safe API Clients](https://blog.openreplay.com/type-safe-openapi-typescript-client/) | openapi-typescript/openapi-fetch/Orval：CI 自动再生成、Zod 运行时兜底 |

---

## 7. 分阶段前端对齐实施计划（仅前端，后端零改动）

> **执行状态（2026-08-13）**：Phase 0/1/2 已完成并验证
> （`npm run type-check` 0 错误、`npm run lint` 通过、`npm test` 11 suites/92 tests 全绿）。
> 遗留端点退役明细见 `docs/audits/frontend-legacy-endpoints-2026-08-13.md`。
> Phase 3 部分完成（SSE 仅监听 6 种 v1 顶层事件；`delivery_ready` 监听保留待后端实际发送）。
> Phase 4 等待后端蓝图 Task 3 落库后跟进；Phase 5 文档已完成、e2e 待跑。

> 原则：以 `docs/contracts/openapi-v1.json` + `sse-events-v1.schema.json` 为事实来源；
> 不新增后端路由；对已删遗留端点一律前端兜底（停用 UI 入口或改走 v1 等价物），不再依赖 404。

### Phase 0（准备，约 0.5 天）
- [x] 引入 openapi-typescript 并从 `docs/contracts/openapi-v1.json` 生成 `src/generated/v1.ts`；新增 `src/features/planning/api/v1-types.ts` re-export。
- [x] 完成（v1-types.ts 已建立，v1 类型与手写遗留类型分离）。

### Phase 1（修复编译红，约 1 天）——先让 `npm run type-check` 变绿
- [x] `SessionStatusResponse` 补齐 v1 字段（含 `links` 语义）并将遗留字段标为可选；`syncBackendState` 优先消费 v1 字段；恢复流程不再读取 legacy 报告/聊天/GIS 字段。
- [x] 29 个 tsc 错误全部修复（type-check 0 错误）；`generateGIS` 断链改为等待 v1 delivery 投影；`ChatHistoryMessage` 导出；`use_llm` 补齐。
- [x] `resolveHumanReview` 已直出 v1 形状；`getHumanReview` 保留旧包装字段但 v1 字段透传（store 已消费 v1 `humanReview`）。

### Phase 2（遗留端点下线，约 2 天）
- [x] 全部遗留端点已停止调用（stub 抛错/本地化/UI 禁用），退役清单已登记：
  `feedback / layer-reports / dimension-report / delete / checkpoints / export / planning-text / rag-config / step-mode / geocode / gis-data / projects / cross-session-reports`。
- [x] `dataApi` 4 方法 stub 抛错；`planning-api` 15 个遗留方法 stub 抛错（保留签名）；`getArtifact`（v1）保留待接入。
- [x] `useHandlers` 报告改读 store（SSE dimension_complete 累积）；`ReportViewer` GIS 改等 delivery 投影。

### Phase 3（SSE 契约收敛，约 1.5 天）
- [x] `createStream` 只注册 6 种 v1 顶层事件；`progress.data.type` 透传真实工作流进度（dimension/layer 事件）。
- [x] 保留 `delivery_ready` 监听并注释说明：后端 `public_event` 目前未发送该类型，属未来兼容。
- [x] `useDeliverySync` 在 `resync_required`/终态/`delivery_ready` 时重拉 `/delivery` + `/map-layers`；恢复流程为 `/state` + 事件重放 + delivery/map-layers。
- [ ] 按 React 最佳实践补：URL 用 `useMemo` 稳定、onError/onReconnect 存 ref、cleanup 关闭闭包内实例。

### Phase 4（map-layers 元数据对齐，跟随蓝图 Task 3，约 1 天）
- [ ] 蓝图 Task 3 落库 `layer_id/style/legend/default_visible` 后，更新 `getRenderLayers` 适配层与 `gis-normalize.ts`，透传元数据到 `LayerTogglePanel/LegendPanel`。

### Phase 5（测试与文档，约 1 天）
- [ ] `npm run type-check`、`npm run lint`、`npm test` 全绿。
- [ ] 更新 `docs/architecture/frontend-api-v1.md`、`API_SSE_DEVELOPER_GUIDE.md` 第 14 节（遗留端点退役矩阵）。
- [ ] e2e 最小链路（创建会话到 state 到 SSE 到 delivery 到 map-layers）通过；`planningStore` 单测覆盖 v1 事件。

---

## 8. 验收标准

1. `npm run type-check` 0 错误、`npm run lint` 通过、`npm test` 通过。
2. 前端不再调用任何已删除的遗留端点（代码扫描 `api/sessions/`、`api/projects/` 仅剩"待后端 v2 迁移"的显式清单项）。
3. `getStatus` 消费的是后端 `SessionProjection`；SSE 只依赖 6 种公开顶层事件；未知 `progress.data.type` 不改变状态。
4. 页面刷新仅凭 `state + delivery + map-layers` 可恢复；`resync_required` 触发全量 REST 重拉。
5. map-layers 元数据（Task 3 后）完整透传到图层面板。

---

## 9. 闭环验证（2026-08-13 真实后端冒烟测试）

启动 `uvicorn app.main:app` 后，以真实后端逐一验证前端所依赖的 v1 端点：

| 端点 | 结果 |
|---|---|
| GET /api/health | 200 ready（database/checkpointer/langgraph ready） |
| POST /api/v1/sessions（缺 village_data） | 422 风格 v1 ApiError：`REQUEST_REJECTED · 村庄数据不能为空或过短` |
| POST /api/v1/sessions（含 village_data） | 201 `SessionCreated{session_id, stream_url, status}` |
| GET /state | `SessionProjection`（status=running, active_stage=L1, phase=layer1, progress=15, last_event_seq 递增, links） |
| GET /events/sync?after=0 | 真实工作流事件流：`progress.data.type` 携带 layer_started / dimension_start / dimension_delta（含 LLM 生成内容） |
| GET /delivery | `DeliveryProjection`（available=false 交付前） |
| GET /map-layers | 交付前 404（前端 `.catch(() => null)` 兜底） |
| GET /human-review | `HumanReviewProjection`（pending=false） |
| GET /artifacts/l1_snapshot | 未产出时 v1 ApiError 404 `NOT_FOUND` |

结论：前端 createStream/syncEvents 消费的 `progress.data.type` 与后端真实事件一致；
中间产物面板（`IntermediateArtifactsPanel`）通过 `getArtifact` 消费真实 artifact，404 显示"未产出"。

## 10. 中间产物显示（新增组件）

- `frontend/src/features/planning/components/IntermediateArtifactsPanel.tsx`：展示后端真实全流程中间产物。
- artifact key 清单 `artifact-keys.ts` 与 `backend/app/infrastructure/artifacts/runtime.py` 的
  ARTIFACT_KEYS 完全一致（l1_snapshot / grounding_result / execution_plan / parcel_changeset /
  planned_state / validation_report / reconciliation_report / delivery_manifest / render_layers / delivery_spatial_snapshot 等 24 个）。
- 已接入工作台右侧栏（实体浏览器之下），按阶段分组、8 秒轮询、404 显示"未产出"。
- 面板数据完全来自 `GET /api/v1/sessions/{id}/artifacts/{key}`，无任何遗留端点调用。

## 附：本次梳理证据

- 后端路由全集：`backend/app/api/v1/routes/*.py`、`backend/app/api/routes.py`（仅 health/tiles + v1）。
- 契约：`docs/contracts/openapi-v1.json`（9 条 path）、`docs/contracts/sse-events-v1.schema.json`。
- SSE 投影：`backend/app/application/projections/events.py`（public_event 映射）。
- 事件源：`backend/app/application/queries/run_events.py`、`backend/app/infrastructure/events/event_factory.py`。
- 前端类型错误：`npm run type-check`（29 错，2026-08-13 实测）。