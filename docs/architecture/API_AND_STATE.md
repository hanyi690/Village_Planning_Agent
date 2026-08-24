# API and State

> Status: CURRENT
> Authority: Current HTTP/SSE/state ownership map. Generated schemas and Pydantic models are the field-level contract.

## 1. Contract sources

HTTP 字段和路径以 [`docs/contracts/openapi-v1.json`](../contracts/openapi-v1.json) 为准；SSE 的稳定外部 schema 以 [`docs/contracts/sse-events-v1.schema.json`](../contracts/sse-events-v1.schema.json) 为准。本文不复制 endpoint 或事件字段清单。

FastAPI router 由 [`backend/app/api/routes.py`](../../backend/app/api/routes.py) 和 [`backend/app/api/v1/routes/__init__.py`](../../backend/app/api/v1/routes/__init__.py) 聚合。当前资源类别包括 session、state、events、human review、delivery、map/source layers、artifacts、dependency graph、evidence、history 和 trace；实际路径以生成 OpenAPI 为准。

## 2. Application boundary

API route 通过 `backend/app/application/commands/` 执行 create/resume/human decision，通过 `backend/app/application/queries/` 读取 state、checkpoint、artifacts、delivery、evidence、events 和 layers，通过 `backend/app/application/projections/` 形成外部视图。运行时调用集中在 [`PlanningRuntimeService`](../../backend/app/infrastructure/runtime/planning_runtime_service.py)。

route 不应直接解释领域 artifact 或重跑规划；projection 不是新的事实源。目标新增契约在实现后先进入 Pydantic，再更新生成 schema，禁止手工编辑 OpenAPI。

## 3. SSE ownership

内部事件词汇定义在 [`backend/app/contracts/events.py`](../../backend/app/contracts/events.py)，事件持久化和在线发布分别位于 [`backend/app/infrastructure/events/repository.py`](../../backend/app/infrastructure/events/repository.py) 与 [`sse_publisher.py`](../../backend/app/infrastructure/events/sse_publisher.py)。API events route 只负责连接和投影。

外部 envelope 与内部丰富事件词汇必须区分：新增内部事件不自动等于稳定外部 API 变更。断线恢复以持久事件/checkpoint 为事实，不能只依赖进程内连接 hub。事件需要关联 session/run/stage/artifact；SSE 文本不得替代 artifact payload。

## 4. WorkflowState ownership

[`backend/app/workflow/state.py`](../../backend/app/workflow/state.py) 的 `WorkflowState` 是 LangGraph 控制面：阶段、路由、checkpoint、轻量 runtime projection、artifact refs、gate/interrupt/terminal refs 和诊断事件。完整业务结果应存为 typed artifact，由 `ArtifactRef` 定位；state 中的自由 dict 不应成为第二套业务数据库。

当前 reducers 对 artifact refs、控制字段和失败事件有专门合并规则。`scoped_grounding_problem`、`ScenarioSet`、`ApprovedExecutionInput` 和 `ValidationCertificate` 已作为 typed artifact ref 接入；scoped problem 通过 parent fingerprint 和 deferred target IDs 保持问题收敛 lineage。仍需保持单一 producer，不得把完整方案数组或二进制地图塞入 state。

## 5. Resume and human review

人工暂停由 hitl segment 和 typed interrupt artifacts 表达。应用 command 在 `backend/app/application/commands/` 中提交 decision，`PlanningRuntimeService.resume_from_interrupt` 校验 expected event 并使用 LangGraph `Command(resume=...)`。重复消费、过期 interrupt 和内容漂移应返回冲突，而不是重启整条工作流。

当前完整 ScenarioSet recommendation 可由 SELECT 产生自动批准输入；SELECT 的 HUMAN approve/resume 会先把显式延期目标写入 `DeferralLedger`，再回到 SELECT 生成 scoped problem/set，并在新 problem/scenario lineage 上生成 human-approved `ApprovedExecutionInput`。其他阶段的 HITL 路径仍在迁移中。普通 resume payload 不能自行拼装或篡改它。批准后的 problem/scenario/baseline fingerprint 变化必须使执行输入失效。

## 6. Delivery projection

delivery、map layers 和 export 是 typed artifacts 的外部投影。当前 query/projection 位于 `backend/app/application/queries/` 和 `backend/app/application/projections/delivery.py`，manifest 契约位于 [`backend/app/contracts/artifacts/delivery_manifest_contracts.py`](../../backend/app/contracts/artifacts/delivery_manifest_contracts.py)。

正式交付目标要求 projection 只读取同一 run-root、相同 snapshot lineage 且已通过证书的 artifacts。当前 DELIVER 已读取 `ValidationCertificate` 并将其状态写入诊断摘要；正式 scenario 缺失证书或证书不可对账时强制 `END_DIAGNOSTIC`，带明确延期且证书为 partial 时才允许 partial manifest。EXECUTE 已有 `ExecutionStaging` 与 L4 快照回滚，但 one-worker-fails/replay、统一入口证书生成和完整 lineage replay 仍为 `PARTIAL`，不能从 API 返回成功就推断目标交付已完成。

## 7. Verification

```powershell
rg -n "include_router" backend/app/api backend/app/main.py -g '*.py'
pytest -q -o addopts='' backend/tests/contracts backend/tests/core
```

OpenAPI 变化应由应用重新生成并比较，不得手工修改 `docs/contracts/openapi-v1.json`。
