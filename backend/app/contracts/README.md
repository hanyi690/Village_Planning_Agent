# Contracts 契约层

> 本 README 以 `backend/app/contracts/` 实际代码为准（核验日期 2026-08-28）。

## 定位

跨边界类型契约：阶段间、模块间、API 与工作流之间交换的对象全部是 Pydantic 模型或
Protocol。`contracts/` 是底层的“共享语言”，不依赖 API、UI 或 provider 具体实现；
上层通过这里声明的类型保证“artifact ref 指向的内容可被解析为已知类型”。

## 目录职责

| 目录 | 内容 |
|---|---|
| `artifacts/` | `ArtifactDescriptor`、`ArtifactRef`、`ContractMeta`、`ClassificationRef`/`ClassificationDecision`、`DeliveryManifest`、`DeferralLedger`、`FinalManifest`、`ValidationReport`、`ValidationCertificate`、`ExecutionStaging`、`Provenance` 等 artifact 载荷契约 |
| `l1/`、`l2/`、`l3/` | L1ObservationSnapshot、L2 strategy/planning semantics、L3 claim 与 PlanningProgram 等阶段契约 |
| `target_projection/` | PlanningProgram 到 GroundingRequest 的目标、意图、关系、解析和任务图契约 |
| `ground/` | 空间引用、候选、约束、关系参数、GroundingResult 与 GroundedPlanningProblem 契约 |
| `select/` | ScenarioSet、solver、readiness、approval 及全局分配契约 |
| `execute/` | ApprovedExecutionInput、ExecutionPlan/Result、PlannedState（含通用 `ScenarioFeature`）与执行 staging 契约；`ParcelChangeSet` 仅为显式 BSM 兼容类型 |
| `spatial/` | 仍需跨阶段共享的空间基础契约：`context_contracts`、`query_ast`、`terrain_evidence` |
| `workflow/` | 工作流控制面契约：human interrupt、repair、resume、review、gate、dispatch；不再承载业务阶段契约 |
| `evidence/` | EvidenceBundle/EvidenceSource/ExplorationRequest、EvidenceRequirement、RelationEvidence 等跨边界证据契约 |
| `base.py` | `StrictContractModel` 与 JSON-compatible 基础类型；由 contracts 持有，infrastructure 只能依赖它 |
| `ports/` | 依赖倒置端口（Protocol）：`context`、`gazetteer`、`place_resolution`、`semantic_query`、`spatial`/`spatial_query`、`zone_allocator`、`road_planner`、`external_search`、`media_evidence`、`bundle_assembly`、`nomenclature_registry`、`adjustment`、`planning_ports`、`context_ref_contracts` |
| `events.py` | `SSEEventType`：SSE 事件类型唯一来源（全系统共享） |
| `l3/program.py` | `PlanningClaim`/`PlanningClaimSet`（L3 输入；空间目标统一由 `PlanningIntervention` 承载） |
| `public/` | 公开 API 契约（当前由 `api/v1/contracts.py` 承载） |

## 关键约定

- `ContractMeta`（`artifacts/contract_meta.py`）给阶段产物提供 schema_version、artifact_id、
  producer、created_at 等公共元数据。
- 产物 key 到契约类型的映射权威来源是
  `workflow/stage_adapter.py::_KEY_BY_TYPE`（见 `docs/design/00_SYSTEM_DESIGN.md`）。
- `contracts/ports/*` 是 Protocol 边界：实现方在 `infrastructure/` 或 `spatial/`，
  消费方在 `modules/`/`workflow/`，保证业务层不反向依赖外部系统。
