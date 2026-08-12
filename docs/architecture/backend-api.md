# 当前后端 API（v1）

正式前端入口只有 `/api/v1`。API 层只做 transport 和 projection，不扫描 artifact 目录、不查询
`latest`、不重新运行图或渲染器。

## 资源

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/sessions` | multipart 创建会话并启动图 |
| GET | `/api/v1/sessions/{id}/state` | 当前 checkpoint 的公开状态 |
| GET | `/api/v1/sessions/{id}/events` | SSE 运行事件 |
| GET | `/api/v1/sessions/{id}/events/sync?after=N` | 从持久事件游标补偿 |
| GET | `/api/v1/sessions/{id}/human-review` | 当前真实 interrupt 的审查投影 |
| POST | `/api/v1/sessions/{id}/human-review` | 带 event_id 提交当前审查决定 |
| POST | `/api/v1/sessions/{id}/resume` | `mode=interrupt` 恢复当前真实 interrupt；`mode=checkpoint` 从显式历史 cursor 创建新 branch |
| GET | `/api/v1/sessions/{id}/delivery` | DeliveryManifest 投影 |
| GET | `/api/v1/sessions/{id}/map-layers` | 从 DeliverySpatialSnapshot/RenderLayers 读取图层 |
| GET | `/api/v1/sessions/{id}/artifacts/{key}` | 读取当前 checkpoint 的显式 artifact descriptor 与 payload |

支持的 artifact key 由 `app.infrastructure.artifacts.runtime.ARTIFACT_KEYS` 决定，前端不得按
文件名或目录猜测产物。artifact 响应中的身份字段是 `descriptor_digest` 和 `digest`；没有
revision/latest 语义。

## 状态与 SSE

`/state` 和 SSE 的事件都必须指向同一 session 当前 checkpoint。SSE 断线时使用 `Last-Event-ID`
或 `events/sync?after=N`，如果事件存在缺口，响应为 `resync_required=true`，前端读取 `/state`
和 `/delivery`，不得由断线逻辑触发 graph resume。

## 交付读取

前端展示规划地图只消费 DELIVER 生成的 `RenderLayers`；current、planned、change、project、
project point、facility、road、axis、land balance 和 export 的事实均来自同一个
`DeliverySpatialSnapshot`。规划 PNG 是一个双 panel 文件，HTML 才提供独立图层开关。

## 实现入口

- transport：`backend/app/api/v1/routes.py`
- 事件 replay/sync：`backend/app/application/queries/run_events.py`
- 事件持久化与在线广播：`backend/app/infrastructure/events/repository.py`、`connection_hub.py`
- 创建命令：`backend/app/api/v1/session_create.py`
- 数据摄取：`backend/app/data/ingestion/upload.py`
- projection contract：`backend/app/api/v1/contracts.py`
