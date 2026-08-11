# API / SSE 正式切换与退役说明

前端稳定读取面统一为 `/api/v1`。会话创建、状态恢复、事件流、人工审核、地图和
交付结果不得再读取 LangGraph checkpoint 或 Artifact Store 的内部 payload。

| 能力 | 正式端点 | 已删除兼容端点 |
|---|---|---|
| 创建会话 | `POST /api/v1/sessions` | `POST /api/sessions` |
| 状态 | `GET /api/v1/sessions/{id}/state` | `GET /api/sessions/{id}/status` |
| SSE | `GET /api/v1/sessions/{id}/events` | `GET /api/sessions/{id}/stream` |
| 事件补偿 | `GET /api/v1/sessions/{id}/events/sync?after=N` | `GET /api/sessions/{id}/sync?from_seq=N` |
| 人工审核 | `GET/POST /api/v1/sessions/{id}/human-review` | `/api/human-review/{id}[/resolve]` |
| 地图 | `GET /api/v1/sessions/{id}/map-layers` | `GET /api/sessions/{id}/render-layers` |
| 交付 | `GET /api/v1/sessions/{id}/delivery` | 直接读取 DeliveryManifest artifact |
| Artifact | 不公开；使用聚合资源 | `/api/sessions/{id}/artifacts/**` |

报告、反馈、检查点、规划文本、GIS 上传和文件导出尚无 v1 替代，本次继续作为
业务命令端点存在。

## SSE 规则

公开事件只有 `progress`、`human_review`、`delivery_ready`、`completed`、
`failed`、`resync_required`。每条事件携带 `id`、`seq`、`session_id`、
`occurred_at` 和 `data`。

- 使用原生 `EventSource`；浏览器通过 `Last-Event-ID` 自动重连。
- 客户端按 `seq` 去重。
- 收到 `resync_required` 后重新请求 state、delivery、map-layers。
- `completed` 只代表工作流终止，成果完整性读取 delivery。
- heartbeat 是 SSE comment，不进入业务 Store。

前端 adapter 会在客户端边界把 `progress.data.type` 转成 UI 现有细粒度事件；后端
公开 schema 不重新暴露历史事件联合。

## 交付物

- `docs/contracts/openapi-v1.json`
- `docs/contracts/sse-events-v1.schema.json`
- `docs/architecture/frontend-api-v1.md`
- `docs/architecture/backend-state-contract.md`

CI 至少执行后端契约快照、legacy route absence 和前端 `tsc --noEmit`。
