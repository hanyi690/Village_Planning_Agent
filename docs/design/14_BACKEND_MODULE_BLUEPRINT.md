# 后端模块蓝图：可并行落地版

> 状态：`TARGET DESIGN`
> 更新时间：2026-08-12
> 目标：把后端拆成边界清晰、可以并行开发、可以独立验收的模块。
> 当前实现以 [10_IMPLEMENTATION_STATUS.md](10_IMPLEMENTATION_STATUS.md) 为准；本文件只定义目标边界、契约和落地顺序。

## 1. 先看结论

后端采用以下依赖方向，依赖只能从上到下：

```text
API / SSE
    -> Application commands / queries
        -> Workflow orchestration
            -> Domain services
                -> Data / Spatial / Evidence ports
                    <- Infrastructure adapters
```

规划主链：

```text
SessionDataSnapshot
  -> AssessmentSnapshot
  -> ObjectivePortfolio
  -> DemandPortfolio
  -> SuitabilityResult
  -> PortfolioDecision
  -> ExecutionPlan
  -> ExecutionResult
  -> ValidationReport
  -> ReconciliationReport
  -> DeliverySpatialSnapshot
```

核心原则只有四条：

1. 一个业务事实只有一个 owner；下游通过不可变 artifact ref 读取。
2. Workflow 只负责编排、路由、暂停和恢复，不实现规划算法。
3. LLM 只能生成带证据的 claim 或建议，不能直接写空间事实、分类、选址或执行任务。
4. 所有输出都从权威 artifact 重新投影；报告、SSE、地图、导出包不能反向成为规划真相。

### 1.1 认知视图与业务主链

L1/L2/L3 是面向分析、审查和报告的认知视图，不应与 KG 的数据层级混用；它们仍然保留，但不再承担“文本直接变成可执行规划”的职责：

| 认知视图 | 权威产物 | 在业务主链中的作用 |
|---|---|---|
| L1 OBSERVE | `L1Snapshot` / `AssessmentSnapshot` | 现状事实、问题、约束和证据缺口 |
| L2 STRATEGIZE | `L2Strategy` / `ObjectivePortfolio` | 目标、定位、策略和冲突 |
| L3 PLAN | `PlanningClaimSet`、`ProgramProposal`、`PlanningProgram` | 需求、干预候选和规划程序 |

规划程序经过 `Demand -> Suitability -> Allocation -> Materialize` 的确定性领域链，才会成为可执行空间结果。这样既保留 L1/L2/L3 的专业分析价值，也避免把 Markdown、JSON 或 LLM 输出直接当作规划事实。

### 当前状态提醒

当前分支已经具备 `WorkflowState`、CAS artifact、事件仓库、规划阶段和 `DeliverySpatialSnapshot` 的部分实现；Application、数据/空间统一契约、地点证据闭环、自动修复、多模态和外部搜索仍有 `PARTIAL/GAP`。不要因为目录或单测存在就标记模块完成。

本蓝图吸收现有设计文档的稳定结论；实现状态、历史审计和任务清单不在这里重复维护。文档取舍见第 11 节。

## 2. 模块拆分

每个模块都应有独立 owner、独立 contract tests 和一个明确的产物。模块之间只通过 contracts、ports 和 artifact refs 通信。

| 编号 | 模块 | 目录 | 唯一职责 | 输入 → 输出 | 可并行性 |
|---|---|---|---|---|---|
| M0 | Contracts & Artifact | `contracts/`, `infrastructure/artifacts/` | 冻结 Pydantic 契约、schema、digest、parent refs 和 CAS | payload → `ArtifactDescriptor` / named ref | 先行基础 |
| M1 | Data Snapshot | `data/` | 摄取文件、CRS/schema/BSM、质量检查、冻结资料快照 | 文件/Bundle → `SessionDataSnapshot` | 依赖 M0 |
| M2 | Spatial Kernel | `spatial/` | 几何、空间查询、面积、拓扑、overlay、距离和空间质量 | `SpatialWorkspace` → typed spatial result | 依赖 M1，可与 M3 并行 |
| M3 | Evidence & KG | `evidence/` | 本地证据、KG、地点语义、证据溯源和 EXPLORE | request + refs → `EvidenceBundle` / resolution | 依赖 M0/M1，可与 M2 并行 |
| M4 | Planning Domain | `domain/` | 需求、适宜性、分配、分类、规划对象组装 | typed inputs → planning artifacts | 依赖 M1/M2/M3 |
| M5 | Workflow | `workflow/` | 阶段编排、路由、gate、interrupt、resume、dispatch | refs + control → `WorkflowState` patch | 依赖 M0/M4 的接口，可提前搭骨架 |
| M6 | Execution Workers | `domain/materialization/`, `spatial/allocation/` | 项目、分区、设施、道路、轴线执行和合并 | `ExecutionPlan` → `ExecutionResult` | 依赖 M2/M4；worker 可并行 |
| M7 | Validate & Reconcile | `domain/validation/`, `workflow/stages/validate.py`, `reconcile.py` | 检查、归因、对账、有限自动修复 | execution refs → reports / adjustments | 依赖 M6，可先冻结契约 |
| M8 | Delivery | `domain/delivery/`, `spatial/delivery/`, `infrastructure/rendering/`, `export/` | 从唯一空间快照生成地图、报告、HTML、PNG、GeoJSON、manifest | validated refs → `DeliverySpatialSnapshot` / outputs | 依赖 M2/M6/M7 |
| M9 | Application & API | `application/`, `api/v1/` | 用例、查询投影、HTTP/SSE、认证和生命周期 | public request → projection/event | 依赖 M0/M5/M8，可与 M2/M3 并行 |
| M10 | Infrastructure Adapters | `infrastructure/` | DB、checkpoint、LLM、GIS、KG、RAG、搜索、媒体适配器 | ports → provider calls | 按 port 独立并行 |

### 2.1 目标目录结构

以下目录是并行开发和依赖检查的目标边界。目录本身不是业务契约，但每个目录必须只承载对应模块职责；移动代码前先冻结 contract，避免只换目录、不换依赖。

```text
backend/app/
├── api/
│   └── v1/
│       ├── routes/
│       │   ├── sessions.py
│       │   ├── state.py
│       │   ├── events.py
│       │   ├── human_review.py
│       │   ├── delivery.py
│       │   ├── map_layers.py
│       │   └── artifacts.py
│       ├── contracts/
│       └── dependencies.py
├── application/
│   ├── commands/
│   │   ├── create_session.py
│   │   ├── start_planning.py
│   │   ├── submit_human_decision.py
│   │   ├── resume_checkpoint.py
│   │   ├── retry_delivery.py
│   │   └── delete_session.py
│   ├── queries/
│   │   ├── workflow_state.py
│   │   ├── run_events.py
│   │   ├── human_review.py
│   │   ├── delivery.py
│   │   └── map_layers.py
│   ├── projections/
│   └── unit_of_work.py
├── workflow/
│   ├── root_graph.py
│   ├── state.py
│   ├── runtime_adapter.py
│   ├── stage_adapter.py
│   ├── routing.py
│   ├── dispatch.py
│   ├── interrupts.py
│   ├── terminal.py
│   ├── stage_audit.py
│   └── stages/
│       ├── target_projection.py
│       ├── ground.py
│       ├── select.py
│       ├── execute.py
│       ├── validate.py
│       ├── reconcile.py
│       ├── deliver.py
│       └── support.py
├── domain/
│   ├── assessment/
│   ├── objectives/
│   ├── demand/
│   ├── program/
│   │   └── target_projection/
│   ├── suitability/
│   ├── allocation/
│   ├── materialization/
│   ├── validation/
│   ├── scenario/
│   └── delivery/
├── data/
│   ├── model/
│   ├── ingestion/
│   ├── catalog/
│   ├── snapshots/
│   └── ports/
├── spatial/
│   ├── model/
│   ├── query/
│   ├── grounding/
│   ├── allocation/
│   ├── network/
│   ├── change/
│   ├── validation/
│   └── delivery/
├── evidence/
│   ├── model/
│   │   ├── l1_location_fact.py
│   │   ├── relation_evidence.py
│   │   ├── place_resolution.py
│   │   ├── image_artifact.py
│   │   ├── image_evidence.py
│   │   ├── visual_fact.py
│   │   ├── visual_review.py
│   │   └── external_search.py
│   ├── retrieval/
│   │   ├── explore_service.py
│   │   ├── place_evidence_index.py
│   │   └── external_search_policy.py
│   └── kg/
│       ├── base_facts.py
│       ├── derived_relations.py
│       └── reverse_relation_index.py
├── contracts/
│   ├── artifacts/
│   ├── workflow/
│   │   ├── dispatch.py
│   │   ├── repair.py
│   │   └── resume.py
│   ├── public/
│   │   └── v1/
│   └── ports/
│       ├── context.py
│       ├── place_evidence.py
│       ├── external_search.py
│       ├── media_evidence.py
│       ├── spatial.py
│       └── workers.py
├── infrastructure/
│   ├── persistence/
│   ├── artifacts/
│   ├── events/
│   ├── checkpoints/
│   ├── llm/
│   ├── gis/
│   ├── kg/
│   ├── rag/
│   ├── search/
│   │   └── exa_adapter.py
│   ├── media/
│   ├── rendering/
│   └── export/
└── bootstrap/
    ├── composition.py
    └── lifespan.py
```

### 2.2 目录迁移规则

- `app/agent/` 只作为迁移期 workflow 代码来源，不再新增业务算法；迁移完成后由 `workflow/` 和 `domain/` 接管。
- `app/services/`、`app/tools/`、宽泛 `app/modules/` 不作为最终能力容器；对应能力迁移完成后删除空目录和旧生产入口。
- `modules/schema` 的稳定契约逐步归并到 `contracts/`；在调用方未切换前不得直接删除旧契约文件。
- `modules/spatial_ops/road/` 的 staged planner 是唯一正式道路实现；旧 local planner 只能显式标记为 degraded，不能作为静默 fallback。
- `domain/` 不依赖 `workflow`、`api` 或具体 adapter；`workflow/stages` 通过 `stage_adapter` 调用 domain service。
- `infrastructure/` 只实现 `contracts/ports`；provider SDK、凭证、重试和序列化不能上浮到 domain/workflow。

### 模块边界规则

- `api/` 不得实例化 graph、artifact store、数据库或 SSE history。
- `application/` 只编排用例和事务，不放规划算法。
- `workflow/` 不读取裸 GeoJSON、文件路径、`latest artifact`，不直接发 SSE。
- `domain/` 不依赖 FastAPI、LangGraph、Exa、具体数据库或 provider response。
- `data/` 是原始资料、CRS、schema、BSM 和数据完整性的 owner。
- `spatial/` 只消费 typed workspace，不自行刷新数据源。
- `evidence/` 只能提供事实、关系、证据、置信度和 provenance，不能生成规划决定。
- `infrastructure/` 只能实现 ports，不向上层泄漏 provider-specific 类型。

## 3. 唯一状态与 artifact

| 状态/产物 | Owner | 允许保存的内容 | 禁止保存的内容 |
|---|---|---|---|
| `SessionDataSnapshot` | Data | 原始资料 manifest、collection、CRS、schema、BSM、质量报告 | 可变运行状态 |
| `WorkflowState` | Workflow checkpoint | run/thread/branch、当前阶段、gate、interrupt、artifact refs | 裸 GIS、长文本、可变业务事实 |
| `StageArtifact` | 对应 Domain/Evidence 模块 | 阶段业务结果、schema、parents、provenance | 覆盖历史版本 |
| `RunEvent` | Event Repository | 追加事件、`session_id + seq`、artifact refs | 业务真相副本 |
| `PublicProjection` | Application | 面向前端的查询 DTO | 作为下游输入的权威事实 |
| `DeliverySpatialSnapshot` | Delivery | current/planned/change/project/facility/road/axis、土地平衡、渲染输入 | 反向修改规划结果 |

所有 artifact 必须至少包含：`schema_version`、`digest`、`parents`、`producer`、`run_id`、`branch_id`、`provenance`。blob 只允许 create-if-absent；named ref 只允许 compare-and-set；resume 必须创建新 branch，不能覆盖历史。

### 3.1 单一 PlanningContext

所有 stage 使用同一版本化上下文，只通过引用传递：

```text
PlanningContext
├── session_id
├── village_bundle_ref + version
├── kg_snapshot_ref + version
├── report_snapshot_ref
├── evidence_bundle_ref
├── planning_artifact_refs
├── context_fingerprint
└── active_gate
```

同一 session 的 Bundle、KG、报告和 artifact 必须版本一致；外部数据刷新必须显式生成新 snapshot，不得在读取期间偷偷刷新。

### 3.2 ResumePlan

LangGraph checkpoint 只表示“从哪里继续”，不表示“哪些业务产物还能复用”。Application 必须先生成可审计的 `ResumePlan`：

```text
ResumePlan
├── mode: resume_checkpoint | resume_interrupt | rerun_from_stage | completed | blocked
├── resume_from
├── reuse_refs
├── rerun_stages
├── reason
├── context_fingerprint
├── input_checksums
└── output_checksums
```

判定优先级：pending interrupt → context identity → artifact parent/checksum → 最早失效阶段 → 终态。HUMAN checkpoint 只能通过同一 interrupt channel 的 `Command(resume=...)` 恢复，不能把 `snapshot.next` 当作普通续跑。

## 4. 工作流与阶段契约

### 4.1 主图

```text
INGEST
  -> ASSESS / L1 OBSERVE
  -> OBJECTIVES / L2 STRATEGIZE -- HUMAN OBJECTIVE GATE
  -> PROGRAM / L3 PLAN
  -> TARGET_PROJECTION
  -> GROUND
  -> DEMAND
  -> SUITABILITY
  -> ALLOCATION -- HUMAN PORTFOLIO GATE
  -> MATERIALIZE / EXECUTE
  -> VALIDATE
  -> RECONCILE
  -> DELIVER
```

`EXPLORE` 是横向能力，不是固定主阶段；`HUMAN` 是路由能力，不是业务模块。旧的“Markdown instruction → PARSE → 执行”不再作为生产链路。

`TARGET_PROJECTION` 只把已组装的 `PlanningProgram` 编译成 `IntentCompilationResult + SpatialReferenceSpec`；它不读取 Markdown、不查询地块、不生成坐标。`GROUND` 负责地点/实体/几何接地，`SELECT` 的职责由 `Demand/Suitability/Allocation` 领域链承接；当前 post-L3 阶段名称可以保留，但不得重新引入文本解析和隐式选址。

每个 stage 只做四步：

```text
读取显式 refs
  -> 校验 schema / parent digest
  -> 调用一个 domain service
  -> 写入不可变 artifact、gate 和事件，返回 WorkflowState patch
```

阶段完成协议建议统一为：

```text
StageCompletion {
  stage,
  status,
  output_refs,
  gate_decision_ref,
  diagnostics,
  next_action
}
```

失败必须是 typed outcome：`success`、`partial`、`unresolved`、`blocked`、`human_required`、`diagnostic`。不能用空集合、默认 approve 或静默 fallback 表示成功。

Gate 只做三件事：检查进入条件、生成 `ValidationIssue`/`ExplorationRequest`、决定通过/定向反馈/HUMAN/终止；Gate 不执行领域算法、不拼接报告、不刷新 Bundle。

定向反馈规则：

| 缺陷 | 返回 |
|---|---|
| 事实缺失/证据过期 | `EXPLORE -> 原阶段` |
| L1 事实矛盾 | `L1` |
| 策略与现状冲突 | `L2` 或 `EXPLORE` |
| 规划目标/分类缺失 | `L3` / `TARGET_PROJECTION` / HUMAN |
| 实体歧义或几何缺失 | `EXPLORE` / `GROUND` / HUMAN |
| 候选为空或冲突 | `GROUND` / `ALLOCATION` |
| worker 算法失败 | `EXECUTE`，保留选址决定 |
| 文本与成果不一致 | `RECONCILE -> L3/EXECUTE` |
| 输出规范失败 | `VALIDATE`，不得只改渲染结果 |

建议的人工确认点为 L1 事实、L2 目标策略、L3 规划程序和 Delivery；GROUND 歧义、低置信度选址、分类决定也可触发局部 HUMAN，不必暂停整个会话。

### 4.2 规划形成

```text
ObservedNeed
  -> PlanningObjective
  -> Evidence-backed Claim
  -> InterventionCandidate
  -> SpatialFeasibility
  -> PortfolioDecision
  -> PlanningProgram
```

LLM 输出 `PlanningClaimDraftSet`，经确定性 adapter、分类决定和领域校验后，才能组装 `PlanningProgram`。JSON Schema 只约束传输格式，不代表规划正确性。

报告分为两类：`AnalysisReport` 面向人阅读，保留 `content`、独立 `instruction` 和 provenance；typed artifact 面向机器消费。`legacy summary` 只能做 UI 预览，字段优先级固定为：明确证据/provenance > 报告正文 > 可验证 instruction > legacy summary。不得从 Markdown 或 summary 直接编译执行对象。

### 4.3 空间执行

`SELECT` 只产出 `SiteSelectionDecision`；`EXECUTE` 只消费 `SiteSelectionDecision + ExecutionPlan`，不得重新解释名称、分类、地名或位置。

执行 worker 互不直接调用：

```text
ExecutionPlan
  -> Project Worker  ┐
  -> Zone Worker     ├─> WorkerResult[] -> ExecutionResult
  -> Facility Worker │
  -> Road Worker     │
  -> Axis Worker     ┘
```

`ExecutionResult` 是唯一跨阶段根 artifact，至少引用 `ParcelChangeSet`、`PlannedState` 和 layout/config 子 artifact。下游不得读取旧的平行结果字段。

SELECT 进入 EXECUTE 前必须完成硬过滤：几何有效、管制/灾害/基本农田等约束满足、目标面积可承载；被排除的候选保留稳定原因码。需要多地块合并时，必须由分区分配器显式声明聚合策略，不能由普通项目选择器隐式放宽约束。

## 5. 关键模块卡片

### M0 Contracts & Artifact

冻结以下基础类型：`ArtifactDescriptor`、`ArtifactRef`、`StageCompletion`、`GateDecision`、`WorkflowState`、`RunEvent`、`WorkerResult`、`ExecutionResult`。

完成标准：schema 可生成；parent/digest 可验证；重放幂等；同 ref 不同 payload 返回 CAS 冲突；无 `Any` 和 legacy 双写。

### M1 Data Snapshot

职责：读取报告、Bundle 和 GIS，建立 collection registry，统一 `feature_id`、CRS/SRID、schema、digest、source、feature count，并输出 `DataQualityReport`。Data/KG Builder 只负责构建 `BaseFacts`；外部 POI、行政编码、地图锚点的刷新必须先生成新的 Bundle revision。

关键约束：快照冻结后 worker 不得隐式刷新 provider；Agent/Workflow 不接收 `gis_data`、`gis_bundle` 或裸 GeoJSON。

### M2 Spatial Kernel

职责：统一 `SpatialFeature`、`GeometryRef`、`CRSRef`、`AreaMeasurement`，提供 query、grounding、allocation、network、change、validation。

关键约束：所有空间计算从 `SpatialWorkspace` 进入；面积单位显式；可恢复的拓扑错误统一 `make_valid`，不可恢复几何阻断快照；不得用 `(0, 0)` 占位几何推断位置或范围。

### M3 Evidence & KG

职责：本地 KG、报告、Bundle、历史证据和可选外部搜索的统一检索入口。KG 只做语义索引，不替代几何引擎；`BaseFacts`、`DerivedRelations`、`IntentGraph`、`PlannedState` 的写入者和版本必须分开。

`ExplorationRequest` 至少带 `requested_by`、`stage`、`dimension_key`、`query_purpose`、`required_facts`、`entity_scope`、`source_policy` 和 `parent_artifact_ref`；返回 `EvidenceBundle/ExplorationResult`，区分 `not_found`、`stale_snapshot`、`query_error`、`ambiguous`、`insufficient_geometry`。缓存键必须包含 context/KG version 和 query purpose，源版本变化时标记 stale。

地点证据链必须明确：

```text
L1LocationFact
  -> PlaceEvidenceIndex
  -> directed / inverse RelationEvidence
  -> PlaceResolutionResult
  -> GROUND
  -> SELECT 决定最终位置
```

`PlaceResolutionResult` 必须保留 `status`、候选 refs、evidence refs、relation refs、query trace、index/KG version。精确、歧义、未解析和冲突必须区分；`祠堂@自然村` 等反向关系不能取第一个候选。

外部搜索只允许通过 `ExternalSearchPort`，由 `infrastructure/search/exa_adapter.py` 实现。调用前先查本地证据；Exa 结果只是带来源的 `ExternalClaimDraft`，必须经过归一化和冲突检查，不能创建 entity、BSM、geometry、classification、`ParcelChange`、`SiteSelectionDecision` 或 `ExecutionPlan`。

### M4 Planning Domain

建议拆成以下独立子包，分别产出根 artifact：

| 子模块 | 输出 |
|---|---|
| `assessment` | `AssessmentSnapshot` |
| `objectives` | `ObjectivePortfolio` |
| `demand` | `DemandPortfolio` |
| `program` | `PlanningClaimSet`、`ProgramProposal`、`PlanningProgram`、`ClassificationDecision` |
| `suitability` | `SuitabilityResult` |
| `allocation` | `PortfolioDecision`、`SiteSelectionDecision` |
| `materialization` | `ExecutionPlan`、`ExecutionResult` |
| `validation` | `ValidationReport`、`ReconciliationReport`、`IterationRecord` |
| `delivery` | `DeliverySpatialSnapshot`、`DeliveryManifest` |

每个子模块只接收 typed input，不能从报告正文、自然语言名称或导出文件重新推断业务事实。

L1 内部可以并行执行多个维度 worker，但只有一个确定性的 aggregate 生产 `L1Snapshot`；L2/L3 同理，层级 gate 消费一个版本化 snapshot。`L1LocationFact` 由 L1 compiler 从明确来源段落产生，不能只留在 `facts: list[str]` 中。

### M5 Workflow

拆成 `root_graph`、`state`、`routing`、`dispatch`、`interrupts`、`stage_adapter`、`terminal` 和 `stages/*`。LLM 可以提出 `DispatchProposal`，但必须经 `DispatchPolicy` 校验阶段、工具、父 refs、预算、重试和幂等性后，才能成为 `DispatchCommand`。

HUMAN 只保留一个传输协议，业务频道用 `channel` 区分：`event_id`、`channel`、`reason`、`paused_stage`、`items`、`error_feedback`；恢复输入统一为 `{action, feedback, dimensions, images, deferred_target_ids}`，旧客户端别名只在 API 边界归一化。中断前不执行不可幂等副作用，SSE 发布必须可重放。

### M6 Execution Workers

每个 worker 独立实现 `WorkerInput -> WorkerResult`，结果包含目标 ref、输入 refs、变更 refs、diagnostics 和 provenance。worker 不自行找点、不自行补分类、不修改 source layer、不静默 fallback。

正式 worker 为 Project、Zone、Facility、Road、Axis；Zone 通过 `ZoneAllocatorPort`/约束求解器，Road 通过唯一 `RoadPlannerPort`，失败返回 `unresolved/degraded`，不能悄悄切换第二套算法。

### M7 Validate & Reconcile

校验必须能追溯到责任阶段和目标 ref。自动修复采用有界循环：

```text
EXECUTE -> VALIDATE -> diagnose
  -> ValidationAdjustmentExecutor
  -> 最早受影响阶段重算
  -> VALIDATE
  -> RECONCILE -> DELIVER
```

`ValidationAdjustment` 必须绑定 responsible stage、target refs、input/evidence refs、受限参数、parent digest 和 fingerprint。最多两轮；重复 fingerprint、振荡、越权参数或无法收敛时进入 rollback、partial 或 HUMAN。

多模态证据复用同一 artifact 链，不建立平行 state：

```text
ImageArtifact
  -> ImageEvidence / VisualFact
  -> L1/L2/L3/GROUND evidence
  -> post-EXECUTE VisualReview
  -> ValidationAdjustment
```

`ImageArtifact` 保存 hash、MIME、尺寸、来源、页码/CRS/bbox 和预处理 ref；`ImageEvidence` 保存区域、OCR/图例/视觉要素和 provenance；`VisualReview` 必须绑定 `target_id` 和已有 validation issue。视觉模型只能提供证据或评分，不能直接写坐标、BSM、分类或空间 PASS；视觉失败降级到 OCR/文本证据或 HUMAN。日志只记录 ref/hash/元数据，不记录完整 Base64。

### M8 Delivery

DELIVER 只消费 `DeliverySpatialSnapshot`，统一生成：current/planned 图层、变化图层、项目/设施/道路/轴线图层、土地平衡、HTML、PNG、GeoJSON 和导出 manifest。所有输出必须从同一快照重建，不能各自读取不同来源。

交付采用“一图、一表、一规则”：图携带图层版本/符号/空间参考；表携带统计口径/输入版本/校验结果；规则携带编码来源/适用范围/冲突处理。数据库字段 registry、渲染和报告不得各自维护映射。阻断问题只输出诊断包，不输出看似完成的正式成果。

规划分类缺失、几何不可恢复、没有实际变化或存在未决目标时，manifest 必须显式标记 `partial/deferred`，不能把现状复制图当作规划完成。

### M9 Application & API

Commands：`CreateSession`、`StartPlanning`、`SubmitHumanDecision`、`ResumeCheckpoint`、`DeleteSession`、`RetryDelivery`。

Queries：`GetSessionProjection`、`GetWorkflowState`、`GetHumanReviewProjection`、`GetDeliveryProjection`、`GetMapLayerCollection`、`SyncRunEvents`。

稳定 API 只保留 `/api/v1`；路由只调用 command/query。SSE 的历史事件从持久 `EventRepository` replay，`Last-Event-ID` 只映射 `RunEvent.seq`；发生缺口时返回 `resync_required`，前端读取 state，不触发 graph resume。

资源按职责拆分为 session、state、events、human-review、resume、delivery、map-layers 和 artifacts。路由不读取 `Runtime`、`ArtifactStore`、`ReportStore` 或 `EventConnectionHub` 内部状态。

### M10 Infrastructure Adapters

按 port 拆分 checkpoint、persistence、artifact、events、LLM、GIS、KG、RAG、search、media、rendering、export。adapter 负责 provider SDK、重试、超时、凭证和序列化；业务层只看到 canonical contract。每个 adapter 先用 fake 实现完成 substitutability/failure tests，再接真实 provider。

## 6. 并行落地方案

按依赖分波次。每个并行任务都必须先提交 contract，再提交 adapter/实现，最后由 owner 做切换；不要建立长期兼容 facade 或双写路径。

### Wave 0：冻结公共边界（串行）

- M0：Artifact/CAS、`WorkflowState`、stage completion、gate、event 和 worker contracts。
- 冻结 `PlanningContextProvider`、`ResumePlan`、canonical HUMAN interrupt 和 `ClassificationDecision`。
- 建立架构测试：依赖方向、禁止裸 GIS、禁止 provider 类型上浮、禁止 API 直读 runtime。
- 以 `10_IMPLEMENTATION_STATUS.md` 建立 CURRENT/PARTIAL/GAP 基线。

### Wave 1：基础能力（可并行）

| 任务 | 负责模块 | 交付 |
|---|---|---|
| A | M1 Data | Snapshot manifest、collection registry、质量报告、冻结/重放测试 |
| B | M2 Spatial | workspace、几何/面积/拓扑/查询 contract 和 adapter |
| C | M3 Evidence | EvidenceBundle、L1 location、PlaceEvidenceIndex、resolution contract |
| D | M9 Application | commands/queries/UoW、API 投影边界、EventRepository 接线 |
| E | M10 Infra | checkpoint、DB、LLM、GIS、KG、媒体、search ports 的 fake adapters |

A/B/C/D/E 之间只依赖 Wave 0 contract，可并行开发。

### Wave 2：规划与编排（部分并行）

| 任务 | 负责模块 | 前置 | 交付 |
|---|---|---|---|
| F | M4 assessment/objectives/demand | A、C | 需求与目标根 artifact |
| G | M4 program/suitability/allocation | B、C、F | PlanningProgram、可行性、PortfolioDecision |
| H | M5 Workflow | M0、F/G contract | 主图、gate、interrupt、dispatch、resume |
| I | M3 Exa adapter | C、E | 外部搜索成功/空结果/冲突/超预算路由 |

F 可与 H/I 并行；G 依赖 F；H 先接 fake domain service，待 G 完成后切真实实现。

地点语义另设 C1 子任务：`L1LocationFact -> PlaceEvidenceIndex -> PlaceResolutionResult -> GROUND`，覆盖 exact、alias、反向关系、同名异类型、冲突、外部 geocoder-only 和 unresolved；短名称 fuzzy 只能产生 `ambiguous`。

### Wave 3：执行、校验、交付（可并行拆 worker）

| 任务 | 负责模块 | 前置 | 交付 |
|---|---|---|---|
| J1 | M6 Project/Zone workers | B、G | 独立 WorkerResult、变更集 |
| J2 | M6 Facility/Road/Axis workers | B、G | 独立 WorkerResult、依赖图 |
| K | M7 Validate/Reconcile | M0、J1/J2 contract | typed report、adjustment executor、两轮预算 |
| L | M8 Delivery | B、J1/J2、K contract | 唯一快照、双 panel PNG/HTML/GeoJSON/manifest |
| M | M3 media evidence | M0、E | ImageArtifact → ImageEvidence → VisualReview |

J1/J2/M 可并行；K 先写 contract 和 fake tests，再接 worker；L 先做 snapshot-only adapter，再接真实执行结果。

本波次的第一条业务闭环优先解决 `ClassificationDecision -> TARGET_PROJECTION -> EXECUTE -> ParcelChangeSet`；没有显式分类决定时必须保持 HUMAN/partial，不能用 `dlbm`、名称、KG 或 crosswalk 补码。

### Wave 4：切换与清理（串行）

1. API 全部切到 Application；SSE 全部切到持久事件。
2. Workflow 全部切到 `WorkflowState + artifact refs`。
3. 删除旧 PARSE、旧 `execution_outcome`、旧 report/store 双写和宽泛 service/tool 生产入口。
4. 更新 OpenAPI、JSON Schema、实现状态和架构测试；删除已替代测试与空目录。

每个波次均按“contract → fake adapter → integration → 唯一调用点切换 → 删除旧入口”的顺序完成；并行分支不得同时修改同一个旧 god module 的不同职责，优先新建窄模块后再切换调用方。

## 7. 每个模块的完成定义

模块同时满足以下条件才可标记 `CURRENT`：

- 输入、输出、owner 和依赖方向唯一；
- contract tests 覆盖成功、空结果、unresolved、冲突、超时/不可用和越权；
- artifact 有 schema、digest、parents、provenance，历史不可覆盖，重放幂等；
- 有 fake adapter 的 integration test 和至少一个真实数据链路证据；
- 失败不会静默变成空集合、默认成功或猜测值；
- 相关 API、OpenAPI、JSON Schema、状态台账和文档同步；
- 影响地图的模块完成实际输出和视觉检查；
- 新能力没有把业务逻辑塞入 `WorkflowState` 或 provider adapter。

额外门槛：

- 地点能力必须覆盖 L1 → KG/PlaceEvidenceIndex → GROUND，含反向关系、歧义和未解析。
- 自动修复必须覆盖 fingerprint、幂等、两轮预算、振荡回滚和 HUMAN/partial 终态。
- 多模态必须覆盖媒体 checksum、区域/source refs、target binding 和失败降级。
- 外部搜索必须覆盖 allowlist、freshness、成本/延迟、idempotency、provenance 和失败路由。
- 交付必须证明所有输出来自同一个 `DeliverySpatialSnapshot`。

## 8. 推荐验收路径

### Contract / architecture

```powershell
pytest backend/tests/contracts backend/tests/core -q
```

重点验证：CAS 不覆盖、checkpoint 分支、依赖方向、WorkflowState 投影、事件 replay、stage completion、dispatch policy、空间输入边界。

### Integration

```powershell
pytest backend/tests/e2e -q
```

至少覆盖：固定 fixture 摄取、snapshot digest、KG/地点证据、真实 API create/resume、worker changeset、validate/reconcile 和 delivery projection。

### Real acceptance

真实验收必须经过：

```text
真实报告 + VillageBundle + Session KG
  -> typed planning artifacts
  -> GROUND / SELECT / EXECUTE
  -> ExecutionResult
  -> VALIDATE / RECONCILE
  -> DeliverySpatialSnapshot
  -> HTML + GeoJSON + 双 panel PNG
```

必须实际 reopen/resume LangGraph checkpoint，并检查输出内容、变化数量、延期项、manifest、HTML、GeoJSON 和 PNG。没有分类决定、空间证据或真实变化时，验收结果应为 `partial/blocked`，不能用 approve、fallback 或合成对象掩盖。

验收至少包含以下闭环：

1. `SessionDataSnapshot` 与 `SpatialWorkspace` 可由固定 fixture 重建相同 digest。
2. L1/L2/L3 typed artifact 具有报告来源、证据和版本；`legacy summary` 不参与权威决策。
3. 地点解析覆盖 exact/alias/反向关系/歧义/冲突/无几何，GROUND 不猜第一个候选。
4. `SiteSelectionDecision` 具有完整排名、淘汰原因、约束和 evidence refs；`UNKNOWN/INFEASIBLE` 不得进入 EXECUTE。
5. `ExecutionResult` 的 changeset、planned state、worker refs 和 checksum 一致。
6. VALIDATE 能按责任阶段反馈；自动修复最多两轮，并能停止重复/振荡。
7. Delivery 的地图、表格、规则、HTML、PNG、GeoJSON 和 manifest 均由同一个 snapshot 重建。
8. API create/state/events/human-review/resume/delivery 只经过 application projection；重启或跨进程事件 sync 与单进程一致。

## 9. 禁止的落地捷径

- 把整个 `AgentState`、裸 GeoJSON、660 个地块或文件路径塞进 graph state。
- 让 LLM 直接生成 `PlanningProgram`、分类、坐标、`ParcelChange` 或执行 task。
- 用 `dlbm`、名称、crosswalk、导出器或第一个候选自动补分类/位置。
- 让 EXECUTE、renderer 或 exporter 各自读取不同的空间事实。
- 用空集合、默认 approve、旧结果或复制现状图表示成功。
- 为了迁移保留长期双写、兼容 facade、第二套事件序号或第二个 artifact owner。

## 10. 文档取舍与权威关系

本次整理后的文档分工如下。原则是“一个目标架构、一个当前状态、多个专题细节”，不再让多个文档各自维护迁移顺序和目标结论。

| 文档 | 处理 | 保留内容 |
|---|---|---|
| `00_SYSTEM_DESIGN.md` | 保留为 North Star | 产品定位、总图、权威产物和运行时原则；不再另写后端模块目录 |
| `01_LAYERED_ARCHITECTURE.md` | 保留为分层细节 | 依赖方向、允许/禁止 import、单一 Context；目标冲突以本文为准 |
| `02_DATA_PERSISTENCE.md` | 保留为持久化细节 | Context、artifact 生命周期、ResumePlan、checkpoint 语义 |
| `03_KG_SEMANTIC_BRIDGE.md` | 保留为 KG 细节 | KG 四类数据和 KG+Spatial 组合；原补充文档内容已吸收并删除 |
| `04_PLANNING_PIPELINE.md` | 保留阶段细节 | L1/L2/L3、Gate 和确定性空间链；主阶段名称以本文为准 |
| `05_EXPLORE_BRIDGE.md`、`11_EXPLORE_KG_ENRICHMENT.md` | 保留为 Evidence 细节 | 请求粒度、来源范围、缓存失效、审计字段和禁止越权 |
| `06_TARGET_PROJECTION_EXECUTE.md` | 保留执行细节 | projection、GROUND、SELECT、Worker 输入输出和迁移对应 |
| `07_VALIDATION_FEEDBACK.md`、`08_DELIVERABLES_COMPLIANCE.md` | 保留验收细节 | 定向反馈、一图一表一规则、Delivery Gate；不再维护第二套修复契约 |
| `09_INTEGRATION_BREAKPOINTS.md` | 降级为历史断点 | 只记录问题证据；迁移顺序以本文第 6 节为唯一推荐顺序 |
| `10_IMPLEMENTATION_STATUS.md` | 独立保留 | 唯一 CURRENT/PARTIAL/GAP 台账，不混入目标设计 |
| `12_PLACE_NAME_RESOLUTION.md` | 保留为地点专题 | `L1LocationFact`、索引、解析评分、GROUND 接线和验收用例 |
| `13_AUTOREPAIR_MULTIMODAL.md` | 保留为扩展专题 | 自动修复、多模态 artifact、视觉边界和真实验收 |
| `15_IMPLEMENTATION_OVERVIEW_FOR_PPT.md`、`16_PROJECT_INTRO_PPT.md` | 保留为汇报材料 | 只服务 PPT，不作为实现依据 |
| `docs/audits/*` | 保留为证据 | 代码审查、真实运行和迁移问题；不作为目标架构源 |
| `docs/superpowers/plans/*` | 保留为任务清单 | 仅描述如何执行；不得反向改变本文边界 |

应淘汰或不再扩展的内容：旧 `PARSE` 生产入口、Markdown/JSON 直接生成 `PlanningProgram`、`AgentState` 中的完整业务对象、隐式 `latest`、第二套 artifact/event owner、通用总重试、静默 GIS fallback、由名称/`dlbm`/crosswalk 自动补分类，以及把现状复制图当成规划完成。

若专题文档与本文冲突，优先级为：本文目标边界 > `10_IMPLEMENTATION_STATUS.md` 当前事实 > 专题细节 > 审计/计划中的历史表述。完成一个模块后，应同步更新本文引用、状态台账和专题文档；不要在多个文档复制同一套目录或迁移清单。

## 11. 参考

- [当前实现状态台账](10_IMPLEMENTATION_STATUS.md)
- [后端架构收敛计划](../superpowers/plans/2026-08-11-backend-architecture-convergence.md)
- [地点证据集成计划](../superpowers/plans/2026-08-12-blueprint-place-evidence.md)
- [自动修复、多模态与 Exa 计划](../superpowers/plans/2026-08-12-autorepair-multimodal-exa-blueprint.md)
- [后端理想架构审计](../audits/backend-ideal-architecture-2026-08-11.md)
