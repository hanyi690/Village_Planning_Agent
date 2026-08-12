um'qm

# 后端模块蓝图与唯一状态模型

> 状态：`TARGET DESIGN`
> 日期：2026-08-12
> 适用范围：后端模块、LangGraph、数据/KG/空间、Artifact、API/SSE、测试与交付。
> 当前实现差距见 [10_IMPLEMENTATION_STATUS.md](10_IMPLEMENTATION_STATUS.md)，代码证据见
> [backend-ideal-architecture-2026-08-11.md](../audits/backend-ideal-architecture-2026-08-11.md)。

## 1. 设计结论

最终后端不再以 `agent/`、`services/` 和 `modules/` 三个宽泛目录互相调用，而按唯一责任拆为：

```text
API transport
  -> application use cases
     -> workflow orchestration
        -> planning domain
           -> data / spatial / evidence ports
              <- infrastructure adapters
```

系统只有六类权威状态：

1. `SessionDataSnapshot`：原始资料与 GIS 输入，由数据层拥有；
2. `WorkflowState`：图控制与 artifact refs，由 LangGraph checkpoint 拥有；
3. `StageArtifact`：阶段业务结果，由不可变 Artifact Store 拥有；
4. `RunEvent`：面向运行过程的追加事件，由 Event Repository 拥有；
5. `PublicProjection`：前端查询模型，由 application query service 构建；
6. `DeliverySpatialSnapshot`：交付空间事实，由 DELIVER 构建并被全部输出消费者只读。

任何业务事实只能有一个 owner。SSE、Markdown、StepReport、PNG、HTML 和导出包都是投影或
交付物，不能反向成为规划真相。

## 1.1 2026-08-12 迁移进度

本分支已经开始按上述边界迁移，而不是在旧 `bootstrap` 入口上继续增加兼容逻辑：

- 根图位于 `backend/app/workflow/root_graph.py`，TARGET_PROJECTION/GROUND/SELECT/EXECUTE/VALIDATE/RECONCILE
  已分别位于 `backend/app/workflow/stages/target_projection.py`、`ground.py`、`select.py`、`execute.py`、
  `validate.py` 和 `reconcile.py`；HUMAN projection 已迁入 `application/interrupts.py`。旧
  `agent/bootstrap/graph.py`、`agent/bootstrap/post_l3_main_nodes.py` 和
  `agent/bootstrap/stage_audit.py` 生产路径已删除，审计实现归位到 `workflow/stage_audit.py`。
- CAS artifact runtime 位于 `backend/app/infrastructure/artifacts/runtime.py`；阶段节点通过
  `workflow/stage_adapter.py` 持久化 typed artifact，主状态只保留控制字段和 refs。
- LLM provider 只能先产生 `PlanningClaimDraftSet`，再由领域 adapter 组装 proposal；嵌套 JSON
  字符串只在 provider adapter 边界归一化，不能直接进入空间执行层。
- `DeliverySpatialSnapshot` 已在真实运行中成为 current/planned/constraint/render/export 的
  唯一空间输入。真实 MiniMax 会话已完成真实 LangGraph checkpoint resume 并写出
  `RECONCILE`、`DELIVER`、660 个 current/planned features、PNG 和 HTML；法定完整性仍以
  `partial` 和 DeferralLedger 明确表达，不把延期目标伪装成已执行。
- DELIVER 阶段入口位于 `workflow/stages/deliver.py`；主图只接收被审计的
  阶段入口，快照、渲染、导出和 manifest 不再和其他 post-L3 节点共用一份交付实现。
- DELIVER 和所有 post-L3 stage service 使用 `workflow/stages/support.py` 的阶段中立 helper，不反向导入
  application/API；HUMAN projection 已由 `application/interrupts.py` 统一拥有。
- 渲染范围由现状地类/边界定义；未解析的 `POINT (0 0)` 等占位几何不得改变地图范围或把真实
  双面板渲染成空白。`/api/v1/.../map-layers` 对 `RenderLayers` 的列表 artifact 直接返回，
  不再把合法列表误判为缺失。
- Data→DELIVER 边界统一收敛几何质量：可恢复的源拓扑错误由 `make_valid` 修复；规划 overlay
  的 `(0, 0)` 无坐标占位被丢弃并保持空层，不由 renderer 猜测位置；不可恢复几何直接阻断快照。
  Agent 仍只接收 workspace/bundle，不接收裸 GeoJSON。
- StepReport 与 Markdown stage report 已从 `app/services/` 无兼容迁移到
  `app/modules/evidence/`；阶段审计只依赖 evidence writer，services 不再拥有第二套审计实现。
- EXECUTE 的跨阶段同步已迁移为单一 `ExecutionResult` 根 artifact；其
  `parcel_changeset_ref`、`planned_state_ref` 和 `layout_configs_ref` 保存精确 CAS 子引用，
  VALIDATE/RECONCILE/DELIVER 不再读取 `execution_outcome` 或并列的执行结果根。
- SSE 的历史事件和 `(session_id, seq)` 已由
  `backend/app/infrastructure/events/repository.py` 的 `EventRepository` 持久化；
  `backend/app/infrastructure/events/connection_hub.py` 的 `EventConnectionHub` 只负责在线
  订阅队列，`application/queries/run_events.py` 统一 REST sync 与 SSE replay。outbox/跨进程发布
  的完整拆分仍是未完成项。
- 稳定 API 的 state/HUMAN 查询已通过 `app/application/queries/workflow_state.py`，由
  `control_state_from_checkpoint()` 将内部 checkpoint 投影为 `WorkflowState`；API 不再直接
  读取 `AgentState` 的 legacy routing/payload 字段。真实 resume 仍由 runtime 使用完整 cursor。
- 根图已从 `AgentState` 切换为 `WorkflowState`。迁移边界由
  `workflow/runtime_adapter.py` 负责：节点所需的旧 stage view 写入不可变
  `workflow_progress` artifact，checkpoint 只保留控制字段和 refs；该 artifact 不是新的
  业务真相，后续必须继续按 L1/L2/L3、conversation、gate 拆成 typed artifacts。
- TARGET_PROJECTION/GROUND/SELECT/VALIDATE/RECONCILE/DELIVER 六个新阶段已统一通过
  `StageCompletion` helper 写入 output refs 和不可变 `GateDecision` ref；post-L3 root routing
  与 HUMAN gate mutation 只信任这些 refs，缺失/损坏时 fail-closed。L1/L2/L3 的 inline gate
  仍是明确登记的迁移边界，不能扩展到新阶段。
- PNG 是一个包含“现状”和“规划”两个面板的真实交付物；规划面沿用快照中的地类字段着色，
  使用低透明度填充、细深色边界，图例显示真实地类名称。HTML、PNG、土地平衡和导出包都从同一
  `DeliverySpatialSnapshot` 重建。
- 2026-08-12 最新真实分支已通过 `test_real_graph_resume_delivery`（真实 provider、LangGraph
  interrupt/checkpoint reopen/resume、`1 passed in 800.03s`）。最终 run 位于
  `.run-tmp/real-llm-41545f0093904940b7d0a47315103664/db6118ac-2efe-4cc5-9168-489444fb0f54/`：
  660 个现状/期末地块、17 个 `planned_project_point`、16 个 `planned_facility`，PNG/HTML/GeoJSON
  均从同一 `DeliverySpatialSnapshot` 读取。交付仍为 `partial`，未解析的规划分类继续进入
  DeferralLedger，不把“有项目动作”伪装为完整地块规划。

仍未完成的迁移必须继续沿此蓝图推进：删除 `workflow_progress` 中的旧 stage 字段，
由 application query/use-case 层承接 API 对 runtime、artifact 和 event repository 的调用。
未完成前不得宣称后端已经达到最终简洁态。

## 2. 不可妥协的不变量

- Agent/Workflow 只传 `bundle_ref`、`context_ref`、`artifact_refs` 和控制字段；不注入裸
  GeoJSON、660 个地块或可变 `gis_data`。
- 数据层负责摄取、CRS、schema、BSM、现状地类、来源和完整性；空间层只消费数据层给出的
  typed workspace。
- LLM 只能提出带证据的 `PlanningClaim/ProgramProposal`，不能直接生成权威
  `PlanningProgram`。JSON Schema 只约束传输格式，不构成规划正确性。
- KG 只返回事实、关系、证据、置信度和 provenance；不得生成规划分类、选址决定或
  `ParcelChange`。
- 规划分类只来自显式 `ClassificationDecision`，不能由 `dlbm`、名称、crosswalk 或导出器补码；
  因而真实 run 中未具备分类决定的 polygon/parcel 目标必须保持 deferred。
- SELECT 必须返回明确的 solver/decision status；`UNKNOWN`、`INFEASIBLE`、未落位和约束缺证据
  不能被当作成功。
- EXECUTE 只能执行 `SiteSelectionDecision + ExecutionPlan`，不得重新解释规划名称、分类或位置。
- `DeliverySpatialSnapshot` 是 current/planned/change/project/facility/road/axis、土地平衡、
  渲染和导出的唯一空间输入。
- checkpoint 历史和 artifact blob 不可覆盖；历史 checkpoint 分叉必须创建新分支引用。
- Artifact named-ref 写入必须可恢复：若阶段在 checkpoint 提交前已写入与当前 payload、schema 和
  parent digests 完全相同的 ref，重试应采用既有不可变 descriptor；不同 payload 仍必须触发 CAS 冲突。
- 正式 API 只有一个版本化入口；正式 SSE 只读取持久事件，进程内队列只负责在线广播。
- 不保留旧生产路径的兼容分支。每个切换在同一变更中删除旧入口、旧状态和旧测试。

## 3. 目标目录

```text
backend/app/
├── api/
│   └── v1/
│       ├── routes/
│       ├── contracts/
│       └── dependencies.py
├── application/
│   ├── commands/
│   ├── queries/
│   ├── projections/
│   └── unit_of_work.py
├── workflow/
│   ├── root_graph.py
│   ├── state.py
│   ├── stage_adapter.py
│   ├── routing.py
│   ├── dispatch.py
│   ├── interrupts.py
│   ├── terminal.py
│   └── stages/
├── domain/
│   ├── assessment/
│   ├── objectives/
│   ├── demand/
│   ├── program/
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
│   │   └── place_resolution.py
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
│   │   └── repair.py
│   ├── public/v1/
│   └── ports/
│       ├── place_evidence.py
│       ├── external_search.py
│       └── media_evidence.py
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

目标态删除宽泛的 `app/services/`、`app/tools/` 和 `app/modules/` 容器。删除发生在对应能力
完成迁移后，不保留同一能力的新旧生产实现。

## 4. 各模块功能与实现

### 4.1 API：纯 transport

职责：HTTP/SSE、认证、请求解析、公开 DTO、状态码和缓存头。

正式资源：

```text
POST   /api/v1/sessions
GET    /api/v1/sessions/{id}
GET    /api/v1/sessions/{id}/state
GET    /api/v1/sessions/{id}/events
GET    /api/v1/sessions/{id}/events/sync
GET    /api/v1/sessions/{id}/human-review
POST   /api/v1/sessions/{id}/human-review
POST   /api/v1/sessions/{id}/resume
GET    /api/v1/sessions/{id}/delivery
GET    /api/v1/sessions/{id}/map-layers
GET    /api/v1/sessions/{id}/artifacts/{key}
```

实现规则：

- router 只调用 application command/query，不实例化 Artifact Store、Graph 或数据库；
- 使用 FastAPI 0.141.1 原生 `EventSourceResponse` 和 `ServerSentEvent`；
- `Last-Event-ID` 只映射持久 `RunEvent.seq`；事件缺口返回 `resync_required`，前端随后读取
  `/state`，不能触发图 resume；
- OpenAPI 和 public JSON Schema 由代码生成，不维护第二份手写 schema；
- 删除未挂载的旧 session、render、export、dev GIS 生产路由。

### 4.2 Application：唯一用例边界

这是当前实现缺失的层。它协调事务和 ports，但不包含规划算法。

Commands：

- `CreateSession`：摄取文件，冻结 `SessionDataSnapshot`，创建 run/thread；
- `StartPlanning`：启动根图；
- `SubmitHumanDecision`：compare-and-set 当前 interrupt，再用 `Command(resume=...)`；
- `ResumeCheckpoint`：从显式 checkpoint 创建新执行分支；
- `DeleteSession`：按 repository 生命周期删除会话资源；
- `RetryDelivery`：只在上游 refs 未变化时重做纯交付 adapter。

Queries：

- `GetSessionProjection`；
- `GetHumanReviewProjection`；
- `GetDeliveryProjection`；
- `GetMapLayerCollection`；
- `SyncRunEvents`。

所有写用例通过 `UnitOfWork` 提交 checkpoint 元数据、artifact named ref、event/outbox 和会话状态。

### 4.3 Workflow：只编排，不做业务

根图只表达阶段和返回路由。L1/L2/L3 保留为面向报告和审查的认知视图，不再作为
“文本逐层传递后直接执行”的业务主干：

```text
INGEST
  -> ASSESS
  -> OBJECTIVES -> HUMAN OBJECTIVE GATE
  -> DEMAND
  -> SUITABILITY
  -> PORTFOLIO ALLOCATION -> HUMAN PORTFOLIO GATE
  -> MATERIALIZE
  -> VALIDATE
  -> SCENARIO EVALUATE
  -> DELIVER
```

`PARSE` 被删除，不改名为另一种解析器。现有 GROUND、SELECT、EXECUTE 的有效算法分别归入
SUITABILITY、PORTFOLIO ALLOCATION 和 MATERIALIZE。EXPLORE 是可由 ASSESS、OBJECTIVES、
SUITABILITY 和 VALIDATE 调用的证据服务，不是固定主阶段。

EXPLORE 虽然不是固定主阶段，但属于必须存在的横向能力，不得在迁移时被泛化为不可追踪的
`evidence lookup`。任何阶段发现证据缺口时，必须形成带 `stage`、`query_purpose`、
`required_facts`、`entity_scope` 和父 artifact ref 的 `ExplorationRequest`，由 EXPLORE 返回
不可变 `EvidenceBundle`/`ExplorationResult`；Gate 再明确选择 `PASS`、证据重查、阶段重跑或
HUMAN。证据链必须支持以下闭环：

```text
Stage worker / Gate
  -> EvidenceGap / ExplorationRequest
  -> EXPLORE: KG + Bundle + reports + typed artifacts + prior evidence
  -> EvidenceBundle + provenance + unresolved / contradictions
  -> affected stage replay
  -> typed GateDecision
```

智能调度必须采用“LLM 提议、确定性策略批准”的边界，而不是取消阶段 contract 或让 LLM
直接修改 `WorkflowState`：

```text
WorkflowState + GateDecision + EvidenceGap
  -> LLM DispatchProposal
  -> DispatchPolicy 校验允许阶段、工具、依赖、artifact refs、预算和幂等性
  -> DispatchCommand / LangGraph Send
  -> EXPLORE、专业 Worker 或 Domain Solver
```

LLM 可以选择证据查询计划、允许的工具、可并行的专业 worker 和下一步候选阶段；不得创造
entity/BSM/geometry、绕过 Gate/solver/HUMAN 或直接触发 EXECUTE。`DispatchProposal`、
`DispatchPolicy` 和 `DispatchCommand` 必须可审计并携带 parent refs、reason、evidence refs、
retry budget 和 provenance。

#### 4.3.1 EXPLORE 的外部搜索边界（含 Exa）

外部搜索是 EXPLORE 的一个可替换证据提供方，不是新的规划阶段，也不是 LLM 的直接工具调用。
EXPLORE 必须先查询 session KG、VillageBundle、报告、typed artifacts 和 prior evidence；只有
`ExplorationRequest.source_policy` 明确允许外部来源，或本地证据已经返回 typed unresolved gap，才
能调用 `ExternalSearchPort`。目标接口如下：

```text
ExplorationRequest
  -> ExploreService
     -> local evidence providers
     -> ExternalSearchPort (optional)
        -> ExaSearchAdapter
     -> ExternalEvidence / EvidenceBundle
     -> Claim normalization + conflict check
     -> affected stage replay or HUMAN
```

`ExternalSearchRequest` 必须包含 query purpose、规范化实体和别名、entity scope、source policy、
allowed domains/categories、freshness、search mode、result limit、content mode、budget、父 artifact
refs 和 idempotency key。`ExternalSearchResult` 必须保留 provider/request ID、resolved search mode、
result URL/ID、标题、发布日期/作者、highlights 或 full-text artifact ref、retrieval status、latency、
cost、cache/livecrawl policy 和 provenance。`ExaSearchAdapter` 只能位于 infrastructure；domain 和
workflow 只依赖 `ExternalSearchPort`，不能读取 Exa API key 或 provider-specific response。

Exa 的 `highlights` 用于有限预算的 agentic retrieval；只有证据缺口要求完整上下文时才请求 full
text。Exa structured output 只能作为带来源的 `ExternalClaimDraft`，必须经过 source-backed claim
normalization、冲突检查和证据审查后才能进入 `EvidenceBundle`；搜索结果本身不能成为事实的无条件
提升。搜索结果不得直接创建 entity ref、BSM、geometry、classification、`ParcelChange`、
`SiteSelectionDecision` 或 `ExecutionPlan` task。没有可靠空间来源时，必须返回 unresolved/ambiguous
并进入 Gate/HUMAN，不能用网页文本猜坐标或自然村位置。

`DispatchPolicy` 只允许 LLM 提议 `EXPLORE.external_search`，并校验来源白名单、查询范围、数据新鲜度、
成本/延迟预算、父 refs、重试次数和幂等键；策略拒绝、Exa 不可用、无结果、内容抓取失败或来源冲突，
均转为 typed diagnostic、复用本地证据或 HUMAN，不得静默改用无约束的通用搜索。外部证据与本地
KG/L1 事实的关系必须在 `EvidenceBundle` 中显式记录，供 Gate 和后续复跑审计。

当前实现中的 `TARGET_PROJECTION` 不是 PARSE 的兼容改名：它只对已经由领域层组装的
`PlanningProgram` 做确定性空间引用投影，禁止 LLM、原始文本重解释、分类推导和 GeoJSON 读取；
它应在后续 MATERIALIZE/SUITABILITY 边界进一步合并，但不能重新引入自然语言 parser。

每个节点只允许执行：

```text
load explicit refs
-> validate schemas and parent digests
-> call one domain stage service
-> persist immutable outputs
-> append outbox events
-> return WorkflowState patch
```

节点不能直接写 ReportStore、发 SSE、查询“latest artifact”、加载文件路径或运行渲染器。

### 4.4 Assess / Objectives

`ASSESS` 消费冻结的数据和证据投影，产出 `AssessmentSnapshot`：事实、问题、存量能力、约束、
服务缺口和证据缺口。`OBJECTIVES` 只消费 Assessment refs，产出 `ObjectivePortfolio`：量化目标、
优先级、时间、预算边界、政策边界和冲突。

并行专业 worker 可以生成 L1/L2/L3 风格的分析报告和 claims，但 aggregate 是唯一
`AssessmentSnapshot/ObjectivePortfolio` 生产者。报告正文与根产物分离，报告不能被下游正则或
另一次 LLM 调用再次编译为权威业务事实。

### 4.5 Claims 与 Program Synthesis：规划形成，不是格式转换

当前核心错误不是 Markdown，而是把“专业报告中的建议”直接当成“可执行规划对象”。JSON
只能让同一错误更稳定。目标流程必须保留下面的因果链：

```text
ObservedNeed
  -> PlanningObjective
  -> Evidence-backed Claim
  -> Domain Intervention Candidate
  -> Spatial Feasibility
  -> Cross-domain Portfolio Decision
  -> Approved PlanningTarget
```

L3 并行专业 Agent 只产出 `PlanningClaim`：事实依据、受影响人口/地块、问题强度、目标、建议措施、
证据 refs、不确定性和冲突。它可以使用结构化输出减少格式错误，但该结果不可执行。

`SYNTHESIZE` 由确定性领域能力和受控决策共同完成：

- `ServiceGapEngine`：人口、服务半径和现状设施 -> 设施需求；
- `LandUseNeedEngine`：指标、分类决定、面积和约束 -> 用地/分区需求；
- `ConnectivityEngine`：路网断点、可达性和项目连接 -> 道路/节点需求；
- `RiskEcologyEngine`：灾害、生态规则和冲突地块 -> 保护/修复需求；
- `ProjectCatalog`：把已证实需求映射到允许实施的项目类型、规模区间和必要输入；
- `FeasibilityPrecheck`：在成为目标前证明至少存在可行空间或明确需 HUMAN 的缺口；
- `PortfolioSolver`：在面积、资金、阶段、依赖和跨专业冲突下选择组合；
- `ProgramBoard`：对 solver 不能决定的价值取舍执行一次集中 HUMAN 审查。

最终实现不是一个大 `ProgramComposer`，而是四个相互独立、可审计的模型：

| 模型                 | 回答                   | 输入                                                | 输出                                |
| -------------------- | ---------------------- | --------------------------------------------------- | ----------------------------------- |
| `DemandModel`      | 需要什么、多少、何时   | assessment、objectives、标准和人口/产业预测         | `DemandPortfolio`                 |
| `SuitabilityModel` | 哪些位置可行、为什么   | data snapshot、criteria、hard exclusions            | `SuitabilitySurface/CandidateSet` |
| `AllocationModel`  | 哪个需求分配到哪个位置 | demand、candidate、capacity、budget、dependencies   | `PortfolioDecision`               |
| `ScenarioModel`    | 完整期末状态效果如何   | current state、全部 decisions、materialized changes | `ScenarioSnapshot + Metrics`      |

四个模型不得合并：需求不能从“找到了几个地块”反推；适宜性不能替代需求；分配不能生成不存在的
需求；情景评价不能偷偷修改分配结果。这对应规划支持系统中 demand、suitability、allocation、
scenario evaluation 的标准分工。

LLM 可以为候选生成解释、补全非决定性属性或对 portfolio 给出排序建议，但不得创建最终分类、
BSM、几何或绕过 infeasible 状态。最终 `PlanningProgram` 由 `ProgramAssembler` 从
`DemandPortfolio`、`PortfolioDecision`、领域引擎结果和 HUMAN decision 确定性组装。

权威规划对象闭集为：

```text
Project | Facility | Road | Axis | Zone | Restoration | Protection | Action
```

每个对象必须包含稳定 ID、object kind、expected geometry、量化需求、位置要求、硬约束、阶段、
证据 refs、need/objective refs 和产生它的 domain decision ref。`ProgramAssembler` 只完成：

- ID 分配与跨专业去重；
- object kind / geometry kind 合法性；
- 依赖无环；
- solver 已批准的总量和分类型预算复核；
- `ClassificationDecision` 的显式存在性；
- need/objective/evidence/feasibility 的全链覆盖；
- 形成唯一 `PlanningProgram`。

claim 缺证据、领域引擎不可用、空间预检不可行、solver 未给出允许状态或 HUMAN 未决，都进入
G3/SYNTHESIZE gate；不得靠 LLM 再写一份 JSON 或回退 Markdown 形成规划结果。

分类决定的运行时闭环如下：

```text
PlanningProgram
  └─ polygon/parcel without ClassificationDecision
       → L3 HUMAN request (classification_decision_required)
       → explicit closed-set ClassificationDecision payload
       → immutable PlanningProgram revision
       → TARGET_PROJECTION → GROUND → SELECT → EXECUTE
```

HUMAN 的 `approve` 不能绕过这个请求；决定必须覆盖全部未决空间目标，且由
`ClassificationDecision` 自身校验 code system、候选闭集、证据和 selected code。
提交决定时只从真实 HUMAN checkpoint 继续，已完成的 L1/L2/L3 不重复调用 LLM。

### 4.6 Data：GIS 和资料唯一 owner

`SessionDataSnapshot` 是会话数据的冻结清单，包含逻辑 collection、schema、CRS、feature count、
digest、source 和时间。`VillageBundleRef` 只指向该 snapshot，不携带数据正文。

数据层负责：

- 上传与外部数据摄取；
- 字段规范化、稳定 feature/BSM ID；
- CRS/SRID、几何有效性、单位和精度；
- current land-use、boundary、road、constraint 等 collection 注册；
- immutable snapshot 与数据质量报告；
- 为 spatial 层打开 typed `SpatialWorkspace`。

LLM 只能接收面积汇总、证据摘要和少量相关 feature projection，不能接收完整地块集合。
Workflow 只传 `VillageBundleRef`；所谓“注入”只能发生在 composition/application 调用 data port
打开 workspace 的边界，不能进入 Agent state。

### 4.7 Spatial：一个几何内核

所有空间能力统一使用 `SpatialFeature`、`GeometryRef`、`CRSRef`、`AreaMeasurement` 和
`SpatialWorkspace`。面积只能由 `AreaService` 计算并记录 CRS、算法、单位和精度。

- `query/`：索引、predicate、distance、overlay；
- `grounding/`：空间描述到实体/candidate refs；必须通过 `PlaceEvidencePort` 消费地点证据解析结果，
  不得只依赖原始文本、单一地名模糊匹配或 village-center/bbox fallback；
- `allocation/`：候选过滤、评分、冲突分配、CP-SAT/MIP；
- `network/`：道路图、连通、路径和线路几何；
- `change/`：`GeometryOperation -> ParcelChange`；
- `validation/`：validity、topology、面积、边界和约束；
- `delivery/`：从 validated execution 构建 snapshot，不渲染、不导出。

PostGIS 实现必须显式设置 SRID，写入前 `ST_IsValid`，面积计算明确 geometry/geography 语义，
查询使用 GiST 索引。文件型 adapter 必须提供相同 contract，不得使用另一套面积算法。

### 4.8 Evidence / KG

KG 分为 `BaseFacts`、`DerivedRelations`、`EvidenceIndex` 三个可重建投影。输入只来自
`SessionDataSnapshot` 和已验证 artifact；输出统一为 `EvidenceItem`：subject、predicate、object/ref、
confidence、source digest、query trace。

删除所有返回规划编码、规划 land-use、候选最终排名和地块变更的 KG helper。规划的
`IntentGraph`/`PlannedState` 若需要进入 KG，只作为只读派生视图，不成为执行输入。

#### 4.8.1 L1 语义富化与地点反向解析

L1 的 KG 语义辅助定位是目标架构的正式能力，不是旧 `agent/parse` 的可选兼容逻辑。L1
必须把报告中的地点事实编译为 typed `L1LocationFact`，至少包含：

```python
class L1LocationFact(BaseModel):
    mention: str
    normalized_name: str
    role: Literal["village", "facility", "road", "water", "landmark", "area", "unknown"]
    aliases: list[str]
    spatial_hint: str
    related_mentions: list[str]
    source_report_ref: str
    source_span: str
    evidence_refs: list[str]
    confidence: float
```

`L1Snapshot.location_facts` 只保存报告明确表达的地点语义和来源，不直接写入最终 BSM 或
选址决定。EXPLORE/Context service 必须基于 `context_version + kg_version + l1_snapshot_ref`
构建可重放的 `PlaceEvidenceIndex`，至少包含：

```text
canonical name / alias -> KG entity refs
L1 normalized name -> L1LocationFact refs
entity type / role -> candidates
directed relation and inverse relation -> related entity refs
village anchor -> geometry / BSM refs
Bundle geometry -> entity refs
provenance / version -> evidence refs
```

地点解析必须支持正向和反向关系，而不是只支持“自然村名查地块”：

```text
祠堂@社前村
  -> facility mention: 祠堂
  -> relation evidence: 祠堂 located_in 社前村
  -> inverse / related entity lookup: 社前村
  -> village geometry / centroid / BSM refs
  -> PlaceResolutionResult
  -> GROUND candidate refs
```

同样必须支持 `设施/地标/道路/水体 -> 位于/服务/邻近/连接 -> 自然村`，以及从自然村反查
其设施、地标和道路。`@`、`位于`、`所在位置`、`服务本村` 等表达只能生成带来源的
`RelationEvidence`，不能直接生成坐标；关系方向、逆关系、entity type、空间范围和来源必须
进入可解释评分。

地点解析输出为 `PlaceResolutionResult`，至少包含 `resolved | ambiguous | unresolved` 状态、
候选 entity refs、geometry/BSM refs、`evidence_refs`、`relation_refs`、`query_trace`、
context/KG/index version 和未决原因。`GROUND` 只消费该结果生成 `GroundingResult`；
`SELECT` 才负责候选之间的最终分配，地点解析不得直接写 `SiteSelectionDecision`。

确定性解析优先级为：session KG canonical/alias、L1 typed fact、关系/类型/拓扑一致性、
Bundle 几何、外部 geocoder，最后才是模糊匹配。LLM 只能在 `ambiguous` 的 Top-K 候选上做
结构化判别，并且不得创造 entity ref、BSM 或坐标；失败时必须保持 `ambiguous` 或
`unresolved`。

### 4.9 Suitability / Portfolio Allocation

SUITABILITY 将 `DemandItem.spatial_requirements` 编译为 criteria model，依次执行数据准备、硬排除、
指标统一量纲、权重/规则组合和候选区域定位，返回 candidate refs、逐项得分、排除原因、query trace
和 evidence。它不改变需求量，也不选择最终地点。

PORTFOLIO ALLOCATION 将需求、候选、容量和硬约束构造成显式 `AllocationProblem`：变量、约束、
目标、整数缩放、输入 digest。设施类任务必须显式区分 demand points、required facilities、candidate
facilities、capacity、travel mode 和 cutoff。返回 `PortfolioDecision`：assignments、solver status、
objective、constraint diagnostics、unplaced 和 unmet demand。

只有 `OPTIMAL` 或业务明确允许的 `FEASIBLE` 可以进入 MATERIALIZE。`INFEASIBLE`、
`MODEL_INVALID`、`UNKNOWN`、目标无候选和未满足需求必须进入修订/HUMAN。

### 4.10 Materialize

`ExecutionPlan` 是唯一 worker 调度输入。每个 task 已经包含 object kind、classification decision、
assignment、geometry expectation、dependencies 和 input refs。

Worker 只做一种空间动作：

- project：项目地块/项目面和小型定位点；
- facility：设施点及必要服务范围；
- road：道路线和网络变化；
- axis：轴线；
- zone/restoration/protection：面和地块变更；
- action：非空间实施任务。

Worker 不能重新分类、重新选址、按名称猜类型或直接发事件。fan-in 只合并 typed result，并检测
BSM/geometry 冲突。EXECUTE 根产物为：

```text
ExecutionResult
├── execution_plan_ref
├── task_results
├── parcel_change_set_ref
├── planned_state_ref
├── deferral_ledger_ref
└── diagnostics_ref
```

### 4.11 Validate / Reconcile

VALIDATE 只读取 `ExecutionResult` 及其精确 children refs，按 classification、geometry、topology、
constraints、area balance、network 和输出完整性生成 `ValidationReport`。每个 issue 必须携带
responsible stage 和 affected target IDs。

RECONCILE 建立 `PlanningProgram target -> selection -> execution task -> spatial output/change` 覆盖矩阵。
它不能补造结果；遗漏只能变为明确 deferral 或失败。

#### 4.11.1 VALIDATE 驱动的有界自动修复

`ValidationReport.adjustments` 是确定性修复动作的唯一入口。自动修复由内部
`ValidationAdjustmentExecutor` 执行，不由 LLM 自由改写 `PlannedState`，也不由某个 worker 静默
重跑。闭环必须是：

```text
EXECUTE
  -> VALIDATE
  -> diagnose issues_by_stage
  -> validate ValidationAdjustment target/stage/evidence/params
  -> apply_validation_adjustments
  -> earliest affected stage replay
  -> VALIDATE
  -> RECONCILE -> DELIVER
```

每个 `ValidationAdjustment` 必须携带 adjustment id、responsible stage、affected target refs、
input/evidence refs、bounded parameters、parent digests、issue fingerprint、idempotency key 和
provenance。每轮生成不可变 `IterationRecord`，记录轮次、问题 fingerprint、父 checksum、调整列表、
受影响目标、前后检查结果、空间 diff 和新 output checksum。调整只能修改已声明的面积/硬约束参数、
合法候选范围、分类缺口、设施缓冲/面积或道路/轴线合法性；禁止猜坐标、扩大无证据候选池、改写源图层、
跨系统映射和直接触发 EXECUTE。

自动修复最多两轮；相同 fingerprint 与输入 checksum 必须停止，振荡必须回滚到稳定 revision，
预算耗尽、证据不足或修复仍失败必须落为 `HUMAN`、`partial` 或 `diagnostic_only`。VALIDATE 只有在
调整执行器返回新的 typed artifact refs 且父链完整时，才允许继续后续阶段。

#### 4.11.2 多模态证据链

多模态输入与文本、KG、空间证据走同一 EvidenceBundle/provenance 链，媒体正文不进入 root
checkpoint：

```text
upload / scan / plan / remote sensing / site photo
  -> ImageArtifact
  -> OCR / layout / legend / vision
  -> ImageEvidence / VisualFact
  -> L1/L2/L3 or GROUND evidence
  -> EXECUTE
  -> VisualReview
  -> VALIDATE.adjustments
  -> RECONCILE / DELIVER
```

`ImageArtifact` 至少包含 artifact ref、sha256、storage ref、MIME、尺寸、来源、文件名、页码、CRS、
bbox、采集时间和 preprocessing ref。`ImageEvidence` 包含图片 ref、页/区域 bbox、OCR、版面元素、图例、
标签、置信度、空间/时间状态、review status 和 provenance。`VisualFact` 只表达带 evidence refs 的
typed subject/predicate/object observation；`VisualReview` 记录 target ref、规划状态、图面问题、证据
refs 和关联的 `ValidationAdjustment`。

L1 负责从视觉证据提取观察事实，L2/L3 负责将其作为带来源的约束/目标证据，GROUND 只有在 CRS、bbox
和来源可靠时才可使用其空间提示，SELECT/EXECUTE 仍不得接受视觉模型直接给出的坐标、BSM 或规划决定。
精确、歧义和未解析必须保持不同状态；OCR/视觉失败时按文本、KG、Bundle 的确定性证据降级，仍不足则
进入 HUMAN。媒体 adapter 负责裁剪、缩放、detail/token budget 和 `image_url`/Data URL 请求边界；事件
只记录 media refs、hash、区域、模型、预算、耗时和结果 checksum，不记录完整 base64。

### 4.12 Deliver / Render / Export

DELIVER 先从 data snapshot 和 validated `ParcelChangeSet` 构建唯一 `DeliverySpatialSnapshot`：

```text
DeliverySpatialSnapshot
├── current_landuse
├── complete_planned_landuse
├── planned_changes
├── projects / project_points
├── facilities
├── roads / axes
├── zones / restoration / protection
├── constraints
├── layer descriptors
├── parent digests
└── quality report
```

`complete_planned_landuse` 从 current land-use 复制后按 `ParcelChangeSet` 应用变更，必须保留地块边界
和未变化地块。renderer、exporter、land balance 和 map API 都只接收 snapshot descriptor。

正式预览要求：

- 一个 PNG，两个有标题的 panel：左为现状、右为规划；
- 两侧地类均按分类颜色渲染，保留地块边界；
- 右图高亮变更地块并叠加项目、设施、道路、轴线；
- 项目/设施定位点足够小，不遮挡地块；
- HTML 提供 current/planned 和各 planning overlay 的独立开关；
- 视觉质量检查读取实际 PNG/HTML，而不是只判断文件存在。

若未形成任何 `ParcelChange`，期末地类只能标记为 preserve/partial，不能标记为 statutory
complete；这不是规划变化。前端必须同时展示 `DeliveryManifest` 的 partial reason、未决目标和
DeferralLedger，避免把一张“现状复制图”误认为规划成果。

## 5. 唯一状态模型

### 5.1 WorkflowState

```python
class WorkflowState(TypedDict, total=False):
    run_id: str
    session_id: str
    branch_id: str
    phase: WorkflowPhase
    active_stage: StageName
    status: RunStatus
    context_ref: ArtifactDescriptor
    artifact_refs: dict[ArtifactKey, ArtifactDescriptor]
    gate_ref: ArtifactDescriptor | None
    retry: RetryBudget
    interrupt_ref: ArtifactDescriptor | None
    terminal_ref: ArtifactDescriptor | None
```

目标为 12 个左右字段。messages 属于独立 conversation graph；报告、GIS、gate history、diagnostics、
review items 和 delivery summary 都不进入 root checkpoint。

### 5.2 Stage 协议

```python
class StageCommand(BaseModel):
    run_id: str
    branch_id: str
    context_ref: ArtifactDescriptor
    input_refs: dict[ArtifactKey, ArtifactDescriptor]
    attempt: int

class StageCompletion(BaseModel):
    stage: StageName
    output_refs: dict[ArtifactKey, ArtifactDescriptor]
    gate_ref: ArtifactDescriptor
    event_refs: list[EventRef]
```

所有 stage adapter 共用一个实现模板；禁止七个节点各自重复 artifact/retry/audit 逻辑。

地点证据契约不进入 root checkpoint 的业务正文，只以 artifact refs 传递：

```python
class RelationEvidence(BaseModel):
    subject_ref: str
    predicate: str
    object_ref: str
    inverse_predicate: str | None = None
    source_refs: list[str]
    confidence: float
    query_trace: list[dict]

class PlaceResolutionResult(BaseModel):
    mention: str
    normalized_name: str
    status: Literal["resolved", "ambiguous", "unresolved"]
    candidates: list[dict]
    evidence_refs: list[str]
    relation_refs: list[str]
    query_trace: list[dict]
    context_version: str
    kg_version: str
    index_version: str
    unresolved_reason: str | None = None

class DispatchProposal(BaseModel):
    allowed_action: str
    target_stage: str
    input_refs: dict[str, str]
    evidence_refs: list[str]
    reason: str

class DispatchCommand(BaseModel):
    action: str
    target_stage: str
    input_refs: dict[str, ArtifactDescriptor]
    parent_digests: list[str]
    attempt: int
```

自动修复与多模态/外部搜索也必须在迁移期间先冻结为 typed contracts，再切换生产调用点：

```python
class ValidationAdjustment(BaseModel):
    adjustment_id: str
    responsible_stage: str
    affected_target_refs: list[str]
    input_refs: dict[str, ArtifactDescriptor]
    evidence_refs: list[str]
    bounded_params: dict[str, object]
    issue_fingerprint: str
    idempotency_key: str
    parent_digests: list[str]

class IterationRecord(BaseModel):
    iteration: int
    issue_fingerprint: str
    parent_checksum: str
    adjustment_refs: list[str]
    affected_target_refs: list[str]
    before_check_refs: list[str]
    after_check_refs: list[str]
    spatial_diff_ref: str | None = None
    output_checksum: str

class ExternalSearchRequest(BaseModel):
    query_purpose: str
    normalized_entities: list[dict]
    entity_scope: list[str]
    source_policy: dict
    allowed_domains: list[str]
    allowed_categories: list[str]
    freshness: dict
    search_mode: str
    result_limit: int
    content_mode: str
    budget: dict
    parent_refs: list[str]
    idempotency_key: str

class ExternalSearchResult(BaseModel):
    provider: str
    request_id: str
    resolved_search_mode: str
    result_records: list[dict]
    evidence_refs: list[str]
    retrieval_status: str
    latency_ms: int | None = None
    cost: dict | None = None
    provenance: dict

class ImageArtifact(BaseModel):
    artifact_ref: str
    sha256: str
    storage_ref: str
    mime_type: str
    width: int
    height: int
    source_ref: str
    page: int | None = None
    crs: str | None = None
    bbox: list[float] | None = None
    preprocessing_ref: str | None = None

class ImageEvidence(BaseModel):
    image_ref: str
    region_bbox: list[float] | None = None
    ocr_text_ref: str | None = None
    layout: list[dict]
    legend: list[dict]
    labels: list[dict]
    confidence: float
    spatial_status: str
    temporal_status: str
    review_status: str
    provenance: dict

class VisualFact(BaseModel):
    dimension: str
    fact_type: str
    subject: str
    predicate: str
    object: str
    evidence_refs: list[str]
    confidence: float
    human_required: bool

class VisualReview(BaseModel):
    target_ref: str
    planning_status: str
    evidence_refs: list[str]
    issue: str
    adjustment_refs: list[str]
```

端口约束为：`ValidationAdjustmentExecutor` 消费 `ValidationReport` 并返回新的 artifact refs；
`MediaEvidencePort` 负责媒体存储，`VisualEvidencePort` 负责 typed 提取；`ExternalSearchPort` 负责
外部检索。Exa、MiniMax vision、OCR 引擎和本地文件存储均只能实现这些 ports，不能被 stage 直接导入。

`PlaceEvidenceIndex` 必须支持 canonical name、alias、role、entity type、directed/inverse
relation、geometry/BSM 和 provenance 的组合查询。`祠堂@社前村` 解析得到的必须是可追溯的
`PlaceResolutionResult`，而不是仅把“祠堂”作为一个孤立设施名称返回。

## 6. Artifact、checkpoint 与 resume

当前 `{artifact_id}/{revision}` 可在历史 checkpoint 分叉时撞到同一 `vN` 并覆盖 payload。
目标使用内容寻址：

```text
blobs/sha256/{digest}
descriptors/{digest}.json
runs/{run_id}/branches/{branch_id}/refs/{artifact_key}.json
```

`ArtifactDescriptor` 至少包含：digest、media type、byte size、schema ID/version、semantic digest、
parents、producer stage、run/branch、created_at 和 provenance。blob 写入为 create-if-absent；若已存在则
校验字节完全相同，永不覆盖。

checkpoint 只保存 descriptor。Workflow 内禁止 `latest` 查询；named ref 只由当前 run/branch 更新。
历史 checkpoint resume 创建新 `branch_id`，复用有效 parent digest，下游生成新 descriptor。

LangGraph interrupt 的恢复规则：

- 使用相同 `thread_id`；
- 只有当前真实 pending interrupt 使用 `Command(resume=decision_ref)`；
- interrupt 节点会从头重放，之前的副作用必须幂等；
- 普通历史 checkpoint 分叉使用显式 checkpoint config，不伪装 HUMAN resume；
- 进程恢复复用已提交 CAS artifact，pending writes 只按 LangGraph 官方语义处理。

## 7. Event Log、SSE 与前端投影

`RunEvent` 使用 `(session_id, seq)` 唯一约束，写入 append-only 表。业务事务同时写 outbox；publisher
提交后投递在线 hub。`SSEConnectionHub` 不存会话状态、不生成 seq、不缓存关键业务事实。

REST `/state` 与 SSE `resync_required` 都调用同一个 `SessionProjectionService`。projection 只读取：

- 当前 checkpoint metadata；
- checkpoint 中的 explicit refs；
- 持久 Event Repository cursor；
- Delivery manifest/snapshot descriptors。

它不能扫描文件夹找“最新 artifact”。

## 8. 测试与真实验收

目标测试布局：

```text
backend/tests/
├── architecture/      # import/owner/禁止路径
├── contracts/         # schema、CAS、ID、状态不变量
├── integration/
│   ├── data/
│   ├── spatial/
│   ├── evidence/
│   │   └── test_l1_place_reverse_resolution.py
│   └── application/
├── scenarios/
│   └── jintian_real/  # 固定真实数据与 checkpoint trace
└── acceptance/
    └── test_real_graph_resume_delivery.py
```

不恢复庞杂的 `tests/unit/`。但真实 graph resume 不能替代 CAS 不可覆盖、面积单位、几何有效性、
solver status、分类闭集和事件幂等等模块不变量；这些放在 contracts/integration。

正式 acceptance 必须：

1. 通过 `/api/v1` 创建真实会话；
2. 使用真实 `jintian` data snapshot、真实 KG 和配置的真实 LLM；
3. 主图运行到真实 LangGraph interrupt；
4. 关闭并重开持久 checkpointer；
5. 用同一 `session_id/thread_id` 和当前 event ID resume；
6. 证明已完成 LLM 阶段没有重复调用；必要阶段允许真实 LLM 调用；
7. 到达 DELIVER，读取 snapshot descriptor 和全部 parent digests；
8. 读取 `complete_planned_landuse.geojson`，核对现状/规划变化、项目和定位点；
9. 打开并检查一个双 panel PNG 和 HTML；
10. 只有规划对象真实落地、校验/对账通过且图面可读，才允许标记可用。

真实 acceptance 若遇到 `classification_decision_required`，不得用通用 approve 或
`defer_unresolved_spatial_references` 绕过；必须由运行操作员通过
`REAL_CLASSIFICATION_DECISIONS_JSON`/`REAL_CLASSIFICATION_DECISIONS_PATH` 提供完整的、带证据
refs 的闭集决定。未提供时，验收应保留真实 HUMAN checkpoint 并失败，而不是生成“规划完成”的结果。

地点证据闭环还必须通过以下 contracts/integration/acceptance 用例：

11. L1 `L1LocationFact` 从结构化报告位置表产生，并保留 `source_report_ref`、`source_span`、
    `related_mentions` 和 `evidence_refs`；
12. `祠堂@社前村`、`祠堂 位于 社前村` 能通过正向或逆向 KG 关系解析到社前村 entity、
    geometry/centroid 和 BSM refs；
13. 自然村反查其设施、地标、道路时，候选带有 relation refs、source refs 和 query trace；
14. KG 与 L1 事实冲突、同名自然村多候选、只有模糊名称和无几何时，分别返回
    `ambiguous`/`unresolved` 并进入 GROUND Gate，不得选第一个候选；
15. GROUND 消费 `PlaceResolutionResult` 后保留 `target_ref`/`intervention_id`，SELECT 才进行
    最终位置分配，EXECUTE 不再重新解析地名。
16. LLM `DispatchProposal` 经过 `DispatchPolicy` 校验后才生成 `DispatchCommand`；拒绝、超预算、
    缺父 artifact 或越权阶段必须进入 typed diagnostic/HUMAN，不能静默执行。
17. `ValidationAdjustmentExecutor` 能从 `ValidationReport.adjustments` 驱动最早受影响阶段重算，
    记录 `IterationRecord`、空间 diff 和新 checksum；重复 fingerprint、振荡和超过两轮必须停止。
18. `ImageArtifact`、`ImageEvidence`、`VisualFact`、`VisualReview` 的父 digest、区域、来源和
    target ref 可重放；视觉证据能进入 L1/L2/L3 或 GROUND，视觉问题能绑定现有 adjustment，失败
    时进入文本/OCR fallback 或 HUMAN，不得直接写坐标/BSM。
19. `ExternalSearchPort` 的 fake adapter 与 Exa adapter 均能返回相同的
    `ExternalSearchResult`；请求 ID、URL/ID、highlights/text ref、来源、freshness、成本、延迟和
    provenance 可重放，重复 idempotency key 不产生重复证据。
20. Exa 无 key、超时、空结果、抓取失败、来源冲突、来源不在 allowlist 或超预算时，EXPLORE
    保留 local evidence/unresolved 并进入 Gate/HUMAN；外部结果不能绕过 GROUND/SELECT/EXECUTE。

pytest 不使用共享固定 `--basetemp`。本地使用 `tmp_path`；CI 如需 basetemp，路径必须包含唯一 job/run ID。
正式验收产物写入独立、显式的 `run-artifacts/{run_id}`，不从 pytest 临时目录冒充交付物。

## 9. 无兼容迁移顺序

每一阶段采用“新实现完成 -> 切换唯一调用点 -> 删除旧实现 -> 真实验收”的原子切换，不建立
长期双写或兼容 facade。

1. **基础正确性**：先实现 CAS Artifact Repository 和持久 Event Repository；修复历史覆盖风险。
2. **应用边界**：引入 commands/queries/UoW，API 不再直读 runtime/store/SSE。
3. **图状态**：建立最小 WorkflowState、统一 stage adapter 和受控 DispatchProposal →
   DispatchPolicy → DispatchCommand 边界；拆 root graph/post-L3 god files。
4. **规划形成**：删除 L3 Markdown `INSTRUCTION` 和直接 JSON program 路径，建立 claims、领域需求引擎、可行性预检、portfolio solver 与 ProgramAssembler。
5. **数据与证据接口冻结**：先冻结 `EvidenceBundle`、`L1LocationFact`、`PlaceEvidenceIndex`、
   `RelationEvidence`、`PlaceResolutionResult`、`ExternalSearchRequest/Result` 和
   `ExternalSearchPort`；统一 SessionDataSnapshot/SpatialWorkspace，先接本地 KG/Bundle/report
   providers，再接 `ExaSearchAdapter`。只有 adapter contract、provenance、预算、幂等和失败路由
   验收通过后，才切换 EXPLORE 的唯一调用点；接通 L1 → KG 语义富化 → 反向关系解析 → GROUND，
   并清除 raw GIS/KG 决策 helper。
6. **选址与执行**：统一 SelectionProblem、ExecutionPlan、worker result 和 ExecutionResult root artifact。
7. **自动修复与多模态接口冻结**：先冻结 `ValidationAdjustment`、`IterationRecord`、
   `ValidationAdjustmentExecutor`、`ImageArtifact`、`ImageEvidence`、`VisualFact`、`VisualReview`、
   `MediaEvidencePort` 和 `VisualEvidencePort`；完成 fake adapter、CAS/provenance、目标绑定、
   两轮预算、fingerprint/rollback 和视觉失败降级测试后，再切换 VALIDATE/媒体调用点。
8. **交付**：snapshot-only render/export/balance/map API；完成双 panel 真实视觉验收，并将
   `VisualReview` 作为交付前校验输入而不是新的规划事实来源。
9. **API/SSE**：只保留 `/api/v1` 和持久事件重连；删除旧端点和进程内状态缓存。
10. **最终清理**：删除空目录、死 contract、旧文档和被替代测试，重新生成当前架构图。

任何阶段若真实输出不可用，保持未完成，不用 fallback、合成对象或“文件已生成”掩盖。

## 10. 模块完成定义

一个模块只有同时满足以下条件才算完成：

- 输入/输出 contract 唯一且无 `Any`/legacy 分支；
- owner 和依赖方向通过 architecture test；
- 失败为 typed result，不能静默空集合或默认成功；
- artifact 具有 schema、digest、parents 和 provenance；
- replay 幂等，不覆盖历史；
- 有真实数据 integration 证据；
- 若模块涉及地点语义，必须有 L1 → PlaceEvidenceIndex → GROUND 的真实链路证据，并覆盖
  `设施/地标/道路/水体 → 自然村` 的反向关系解析；
- 解析结果必须保留 status、candidate refs、evidence refs、relation refs、query trace 和
  context/KG/index version；
- 若模块涉及自动修复，必须由 `ValidationAdjustmentExecutor` 消费 typed adjustments，具备
  `IterationRecord`、两轮预算、fingerprint 去重、振荡回滚和 HUMAN/partial/diagnostic 终态证据；
- 若模块涉及多模态，必须具备 `ImageArtifact` → `ImageEvidence/VisualFact` → `VisualReview` 的
  不可变链路、target 绑定、区域/来源/provenance 和失败降级证据，且视觉模型不能直接写空间决定；
- 若模块涉及外部搜索，必须通过 `ExternalSearchPort` 和可替换 adapter，具备 source policy、
  allowlist、freshness、成本/延迟预算、request/idempotency trace 和 Exa 失败/冲突路由，且外部
  结果不得越过 GROUND/SELECT/EXECUTE 的权威边界；
- 若模块影响地图，实际读取并视觉检查输出；
- CURRENT 文档、OpenAPI/JSON Schema 和代码同时更新。

## 11. 研究依据

- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [LangGraph checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)
- [FastAPI Server-Sent Events](https://fastapi.tiangolo.com/tutorial/server-sent-events/)
- [FastAPI 0.141.1 release notes](https://fastapi.tiangolo.com/release-notes/)
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [Microsoft Event Sourcing pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing)
- [OCI content descriptor](https://github.com/opencontainers/image-spec/blob/main/descriptor.md)
- [PostGIS spatial data management](https://postgis.net/docs/en/using_postgis_dbmanagement.html)
- [PostGIS ST_IsValid](https://postgis.net/docs/ST_IsValid.html)
- [PostGIS ST_Area](https://postgis.net/docs/ST_Area.html)
- [OGC API Features](https://ogcapi.ogc.org/features/)
- [OR-Tools CP-SAT solver](https://developers.google.com/optimization/cp/cp_solver)
- [Exa Search API](https://exa.ai/docs/reference/search)
- [Exa Search API guide](https://exa.ai/docs/reference/search-api-guide)
- [Exa Contents Retrieval](https://exa.ai/docs/reference/contents-retrieval)
- [ArcGIS Suitability Modeler workflow](https://doc.esri.com/en/arcgis-pro/latest/help/analysis/spatial-analyst/suitability-modeler/implement-the-suitability-modeling-workflow-using-the-suitability-modeler.html)
- [ArcGIS location-allocation](https://developers.arcgis.com/documentation/mapping-and-location-services/routing-and-directions/location-allocation/)
- [ArcGIS Urban parcel suitability](https://doc.esri.com/en/arcgis-urban/latest/help/help-suitability.html)
- [EU Joint Research Centre LUISA](https://joint-research-centre.ec.europa.eu/luisa/technical-description_en)
- [pytest temporary directories](https://docs.pytest.org/en/stable/how-to/tmp_path.html)
- [pytest good integration practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html)
