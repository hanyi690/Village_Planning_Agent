# API 契约（真实产物）

| 文件 | 内容 |
|---|---|
| `openapi-v1.json` | `/api/v1` 的 OpenAPI 快照；前端 `npm run generate:api-types` 用它生成 `frontend/src/generated/v1.ts` |
| `sse-events-v1.schema.json` | SSE 事件 envelope 的 JSON Schema（`schema_version=1.0`、`seq`、`type`、`data`） |

权威来源是运行中的 `backend/app/api/v1/contracts.py` 与 `/openapi.json`；本目录的快照用于
前端类型生成和离线校验。如果快照与运行不一致，先重新导出再提交。