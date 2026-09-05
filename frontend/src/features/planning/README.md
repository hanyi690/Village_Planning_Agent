# planning feature

> 本 README 以 `frontend/src/features/planning/` 实际代码为准（核验日期 2026-08-15）。

规划 feature 是前端主业务边界：把后端 `/api/v1` 会话 API / SSE 事件流转换为工作台可消费
的 UI 状态，并呈现规划文本、GIS 图层、报告、检查点与 HITL 审核。前端状态是**可丢弃的 UI
投影**；断线重连通过 `/events/sync` + `/state` + `/delivery` 恢复，不以浏览器内存为 SSOT。

## 目录职责

| 目录 | 职责 | 关键文件 |
|---|---|---|
| `api/` | 后端 HTTP 客户端 | `client.ts`（`apiRequest`/`API_BASE_URL`）、`planning-api.ts`（`planningApi`：startPlanning/createStream/state/delivery/map-layers/human-review/resume/artifacts）、`types.ts`、`v1-types.ts`、`index.ts` |
| `store/` | 状态容器 | `planningStore.ts`（Zustand + Immer，约 93KB：消息/事件 reducer、SSE 事件处理、GIS 图层、报告、审核状态）、`planning-context.tsx`（`PlanningProvider`/`usePlanningActions`/`usePlanningStore`）、`index.ts` |
| `hooks/` | 副作用 | `useSSE.ts`（SSE 连接/重连/batch，`Last-Event-ID` + `sync` 补偿）、`useSessionRestore.ts`、`useStreaming.ts`/`utils/useStreamingRender.ts`（流式文本渲染）、`useHandlers.ts`、`useDelivery.ts`（delivery 同步）、`useApprovalActions.ts`（HITL）、`usePlanningBootstrapStage.ts`、`useSelectors.ts`、`useAnalysisCompletion.ts`、`useActiveAnalysisFocus.ts` |
| `types/` | 消息/事件/状态类型与 guard | `messages.ts`、`events.ts`、`guards.ts`、`helpers.ts`、`base.ts`、`index.ts` |
| `components/` | UI | `PlanningWorkbenchPage.tsx`（主工作台）、`chat/*`（MessageList/MessageBubble/MessageContent/ProgressPanel/ToolStatusPanel/StreamingText/CheckpointMarker/GisResultCard/KnowledgeSliceCard/FileViewerSidebar）、`gis/*`（MapView/LayerTogglePanel/LegendPanel/ValidationPanel）、`layout/*`（AnalysisSidePanel/ReportViewer/PlanningBootstrapPanel/OverviewGuidePanel）、`settings/SettingsPanel`、`ui/*`（MarkdownRenderer/ImagePreview）、`CascadePanel`/`CascadeNotificationBanner`、`IntermediateArtifactsPanel`、`DeliveryStatusBanner`、`ExportDialog`、`VillageInputForm`、`ChatInput`、`MessagePanel`、`PlanningTextViewer`、`DimensionCard`、`LlmStatusBanner`、`artifact-keys.ts` |
| `config/` | 阶段/维度配置 | `phases.ts`、`planning.ts` |
| `constants/` | GIS/阶段/UI 常量 | `gis.ts`（图层常量 23KB）、`index.ts`、`workbench-icons.tsx` |
| `utils/` | 纯函数 | `gis-normalize.ts`（v1 图层归一化）、`report-parser.ts`、`session-report-loader.ts`、`chat-messages.ts`、`message-helpers.ts`、`markdown-table-captions.ts`、`coord-transform.ts`、`download.ts`、`offline-basemap.ts`、`road-map-style.ts`、`session-bootstrap.ts`、`session-hydrate.ts`、`session-url.ts`、`throttle.ts`、`workbench-nav.ts`、`format.ts`、`logger.ts`、`cn.ts`、`index.ts` |

## 数据流

```text
VillageInputForm（MIME/扩展名分类；非 GIS 附件交给 MinerU 预处理）→ planningApi.startPlanning(POST /api/v1/sessions, multipart)
  → 后端 MinerU → UTF-8 Markdown artifact → DATA catalog
  → useSSE 连接 GET /api/v1/sessions/{id}/events（Last-Event-ID + sync 补偿）
  → planningStore 事件 reducer（progress / dimension_* / gis_layer_update / tool_* /
    human_review / delivery_ready / completed / failed / resync_required）
  → hooks（useSelectors/useDelivery/useApprovalActions）→ components
HITL：POST /api/v1/sessions/{id}/human-review（event_id 乐观锁）
Resume：POST /api/v1/sessions/{id}/resume（mode: interrupt | checkpoint）
交付：GET /delivery + /map-layers（snapshot_checksum 变化时整体替换图层）
```

## 与后端契约的对应

- `types/events.ts` / `store/planningStore.ts` 消费 `contracts.py` 定义的 public event
  envelope（`schema_version=1.0`、`seq`、`type`、`data`）。
- 地图图层以 `/map-layers` 的 `DeliverySpatialSnapshot` 投影为准；
  `utils/gis-normalize.ts` 做 v1 词汇 → 内部渲染词汇映射。
- `/source-layers` 必须携带当前 `session_id`，只投影该会话已准入 DATA catalog 的 normalized
  现状图层；没有 session 或 catalog 时返回空上下文和诊断，不得跨会话复用任何固定村庄数据。
  它不替代会话交付，也不会自动注入规划结果。规划图层必须来自该会话的
  `DeliverySpatialSnapshot`。
- v1 只呈现当前会话的报告与证据；跨会话报告和版本历史没有前端兼容 API，避免把已下线
  的端点伪装成可用能力。
- `partial` / `diagnostic_only` / `statutory_complete=false` 由 `DeliveryStatusBanner`
  显著展示，不显示为法定完整成果。

## 测试

- `src/__tests__/store/planningStore.chat.test.ts`、`planningStore.delivery.test.ts`
- `src/__tests__/hooks/useStreamingRender.test.ts`、`useStreamingText.test.ts`
- `src/__tests__/api/client.test.ts`、`src/__tests__/components/*`、`src/__tests__/utils/*`
- E2E：`frontend/e2e/v1-contract.spec.ts`（Playwright；只验证稳定 v1 契约）
