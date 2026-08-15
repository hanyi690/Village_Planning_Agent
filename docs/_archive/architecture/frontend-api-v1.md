# 前端稳定 API v1 对接指南

> 本文是快速联调清单。完整生命周期、TypeScript 示例、恢复算法、测试矩阵和后端
> 演进规则见 `docs/frontend/API_SSE_DEVELOPER_GUIDE.md`。

## 契约来源

- REST/OpenAPI：`docs/contracts/openapi-v1.json`
- SSE 判别联合：`docs/contracts/sse-events-v1.schema.json`
- 基础路径：`/api/v1/sessions/{session_id}`

前端只依赖聚合投影，不解析 `AgentState` 或内部 artifact payload。所有 DTO
使用 `schema_version: "1.0"`，未知字段在后端契约验证中被拒绝。

## 初始化与恢复

通过 `POST /api/v1/sessions` 提交 multipart 文件并创建会话，只保存响应中的
`session_id`。随后使用下列稳定资源：

1. 调用 `/state` 获取 `SessionProjection` 和资源链接。
2. 调用 `/delivery`；`available=false` 表示尚未到交付阶段。
3. 交付可用后调用 `/map-layers`。地图必须分别展示 current 与 planned。
4. 建立 `/events` 的 `EventSource`；服务端每条业务事件携带 SSE `id`。
5. 浏览器重连会自动发送 `Last-Event-ID`。收到 `resync_required` 后重新执行
   1–3，不从本地旧事件推断当前状态。

## 终态

`completed` 只表示工作流终止。成果状态以 `/delivery` 为准：

- `complete`：规划输出完整；是否满足法定完整性仍看 `statutory_complete`。
- `partial`：存在明确延期，但已有成果可展示。
- `diagnostic_only`：只展示诊断和人工处理入口，不标为最终成果。

延期不是 HTTP 错误。HTTP 错误统一返回 `ApiError`。

## Human Review

`GET /human-review` 返回当前 `event_id`、暂停阶段和待审项。提交时必须把同一
`event_id` 原样带回 `POST /human-review`；过期或重复决策返回冲突错误。

## 地图与事件

`MapLayerCollection.snapshot_checksum` 是本次交付空间状态的身份。前端不得把
current 与 planned 合并成一个可变图层，也不得从诊断 artifact 重建 planned。

事件按 `type` 判别：`progress`、`human_review`、`delivery_ready`、`completed`、
`failed`、`resync_required`。使用 `seq` 去重；SSE comment heartbeat 不改变状态。
