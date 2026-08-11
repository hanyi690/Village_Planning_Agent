# ADR 006: FastAPI 0.141.1 与稳定 API 投影

## Decision

后端固定使用 `fastapi==0.141.1`。正式前端接口统一放在 `/api/v1`，使用严格
Pydantic response models、OpenAPI 3.1 和 FastAPI 原生 `EventSourceResponse` /
`ServerSentEvent`。SSE 使用 `id`、`retry` 和 `Last-Event-ID`；事件持久性仍由
应用事件日志负责。

前端消费聚合 DTO，不直接消费 LangGraph state 或内部 artifact。空间展示只
从 `DeliverySpatialSnapshot` 投影。

## Consequences

- OpenAPI 与 SSE JSON Schema 必须提交并通过漂移测试。
- 框架升级、状态收敛和旧接口删除分批验收。
- `app.frontend()` 与本项目独立前端部署无关，不采用。
- 旧 `/render-layers`、宽泛 SSE payload 和 state 字段不属于稳定契约。
