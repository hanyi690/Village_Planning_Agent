# Contracts 契约层

> 本 README 以 `backend/app/contracts/` 实际代码为准（核验日期 2026-08-15）。

## 定位

跨边界类型契约：阶段间、模块间、API 与工作流之间交换的对象全部是 Pydantic 模型或
Protocol。`contracts/` 是底层的“共享语言”，不依赖 API、UI 或 provider 具体实现；
上层通过这里声明的类型保证“artifact ref 指向的内容可被解析为已知类型”。

## 目录职责

| 目录 | 内容 |
|---|---|
| `artifacts/` | `ArtifactDescriptor`、`ArtifactRef`、`ContractMeta`、`ClassificationRef`/`ClassificationDecision`、`DeliveryManifest`、`DeferralLedger`、`ReconciliationReport`、`ValidationReport`、`Provenance` 等 artifact 载荷契约 |
| `domain/` | 认知层与领域决策契约：`l1_contracts`（L1Snapshot/AnalysisReport）、`l2_contracts`、`l3_contracts`（PlanningClaim/PlanningClaimSet）、`planning_semantics`、`road_planning`、`selection_contracts`（SiteSelectionDecision/PortfolioDecision）、`custom_zone_contracts` |
| `spatial/` | 空间契约：`constraint_contracts`、`context_contracts`、`grounding_contracts`、`parcel_change_contracts`、`planned_state_contracts`、`spatial_delivery_contracts`、`spatial_reference_contracts`、`global_zone/site_allocation_contracts`、`land_balance_contracts`、`terrain_evidence` |
| `workflow/` | 工作流契约：`execution_plan_contracts`、`human_interrupt_contracts`、`parse_contracts`/`parse_result_contracts`/`parsing_contracts`、`repair`/`repair_directive_contracts`、`resume_contracts`、`review_contracts`、`target_binding_contracts`、`workflow_contracts`、`dispatch` |
| `evidence/` | `evidence_contracts`：EvidenceBundle/EvidenceSource/ExplorationRequest 等 |
| `ports/` | 依赖倒置端口（Protocol）：`context`、`gazetteer`、`place_resolution`、`semantic_query`、`spatial`/`spatial_query`、`workers`、`zone_allocator`、`road_planner`、`external_search`、`media_evidence`、`bundle_assembly`、`nomenclature_registry`、`adjustment`、`planning_ports`、`context_ref_contracts` |
| `events.py` | `SSEEventType`：SSE 事件类型唯一来源（全系统共享） |
| `program.py` | `PlanningClaim`/`PlanningClaimSet`（L3 输入；空间目标统一由 `PlanningIntervention` 承载） |
| `public/` | 公开 API 契约（当前由 `api/v1/contracts.py` 承载） |

## 关键约定

- `ContractMeta`（`artifacts/contract_meta.py`）给阶段产物提供 schema_version、artifact_id、
  producer、created_at 等公共元数据。
- 产物 key 到契约类型的映射权威来源是
  `workflow/stage_adapter.py::_KEY_BY_TYPE`（见 `docs/design/00_SYSTEM_DESIGN.md`）。
- `contracts/ports/*` 是 Protocol 边界：实现方在 `infrastructure/` 或 `spatial/`，
  消费方在 `domain/`/`workflow/`，保证领域层不反向依赖外部系统。
