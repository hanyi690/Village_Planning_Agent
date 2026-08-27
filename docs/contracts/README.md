# API 契约（真实产物）

| 文件 | 内容 |
|---|---|
| `openapi-v1.json` | `/api/v1` 的 OpenAPI 快照；前端 `npm run generate:api-types` 用它生成 `frontend/src/generated/v1.ts` |
| `sse-events-v1.schema.json` | SSE 事件 envelope 的 JSON Schema（`schema_version=1.0`、`seq`、`type`、`data`） |

权威来源是运行中的 `backend/app/api/v1/contracts.py` 与 `/openapi.json`；本目录的快照用于
前端类型生成和离线校验。如果快照与运行不一致，先重新导出再提交。

CI 或提交前可在 `frontend/` 执行 `npm run generate:api-types:check`。该命令只比较重新生成的
TypeScript 与已提交的 `src/generated/v1.ts`，发现快照漂移时返回失败，不会静默改写文件。

## 跨模块契约注册

领域模型仍由各自的 owner 模块维护，但只要模型跨越 LLM、artifact、API、事件或渲染边界，
必须在 `backend/app/contracts/registry.py` 注册稳定的 `contract_key`、owner、角色和版本。
LLM 调用统一经过 `run_structured_output(..., contract_key=...)`；该边界会记录 schema digest、
provider 返回形状和有限的失败码，但不会把普通文本当作 typed output。闭集候选的 descriptor、
digest 和成员校验统一由 `backend/app/contracts/llm/closed_set_contracts.py` 提供；
`backend/app/domain/validation/closed_set.py` 仅保留兼容导入。

因此新增或修改领域模型时只需要：

1. 修改 owner 模型及其本地测试；
2. 若它跨边界，更新 registry 的版本/描述和对应 schema 测试；
3. 通过 backend contract snapshot、structured runner 和 frontend generated-type check。

未注册的 boundary key 会在 runner 初始化时失败，避免模块各自拼出一套不可追踪的 prompt、
digest 或重试契约。

## Provider schema 与运行时闭集

Provider-facing schema 只包含稳定的结构和小型静态枚举：例如 `fact_type`、
`operation` 或 `status` 这类有限 discriminator 可以使用 Pydantic 的
`Annotated`/discriminated union。当前调用的 fact、relation、target、facility、parcel
或 evidence ID 不得动态编译成 `Literal`/`oneOf` 发给 provider；这些值通过 prompt 中的
候选目录和 `candidate_set_digest` 提供上下文，响应解析后由本地 validator 做精确
membership、来源和 digest 校验。

这样候选目录变化不会改变 provider contract，也不会让 schema 的大小、分支数量和
provider 编译缓存随单次输入抖动。未知 ID 必须产生 typed issue/pending，而不是被
schema failure、默认值或模糊匹配静默改写。动态 union 仅可用于本地、非 provider 的
小范围投影（例如维度内部 fact adapter）；实际外部动作仍使用 tool call，报告合成仍
使用独立的 report contract。
