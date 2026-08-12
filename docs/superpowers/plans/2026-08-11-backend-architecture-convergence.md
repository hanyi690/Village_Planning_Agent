# Backend Architecture Convergence Implementation Plan

> 状态：`ACTIVE PLAN`  
> 依据：[后端模块蓝图](../../design/14_BACKEND_MODULE_BLUEPRINT.md)  
> 原则：不保留旧生产路径兼容层；每个模块切换后立即删除原入口和死代码。

## 目标

把当前“报告 -> Markdown INSTRUCTION/PARSE -> GROUND -> SELECT -> EXECUTE”的链路，收敛为：

```text
SessionDataSnapshot
  -> AssessmentSnapshot
  -> ObjectivePortfolio
  -> DemandPortfolio
  -> SuitabilityResult
  -> PortfolioDecision
  -> ExecutionResult
  -> ScenarioSnapshot
  -> DeliverySpatialSnapshot
```

真实 LLM 负责分析、claims、解释和有限排序建议；数据、需求、适宜性、分配、分类、几何、校验和
交付由 typed domain services 负责。最终验收必须是实际 LangGraph checkpoint resume、真实数据、真实
LLM 和实际读取/目视检查 HTML、GeoJSON、一个双 panel PNG。

## 全局完成规则

- 一个业务事实只有一个 owner；
- checkpoint 只保存控制状态和 explicit artifact descriptors；
- artifact 使用不可覆盖的内容寻址存储；
- workflow 不查询 latest，不传裸 GIS，不直接发 SSE；
- API 只调用 application commands/queries；
- 删除 `tests/unit/` 后，不重新建立同名杂乱测试树；
- 模块不变量进入 `tests/contracts`，真实能力进入 `tests/integration`，最终链进入
  `tests/acceptance`；
- 每个阶段完成时同步 CURRENT 架构、状态台账、OpenAPI/JSON Schema 和审计证据。

## Phase 0：冻结错误成功声明与建立基线

### 0.1 记录当前真实状态

- [ ] 固定当前真实 session、thread、checkpoint、artifact refs 和 LLM 调用记录；
- [ ] 将 74 个 GROUND HUMAN items 和 205 interventions 记录为失败基线，不 approve；
- [ ] 标记 deterministic GIS replay 只证明 checkpoint/GIS 通路，不证明规划语义；
- [ ] 删除文档中重复或互相矛盾的“权威验收”段落；
- [ ] 生成当前 import/state owner 报告，不使用 2026-08-06 的 Graphify 结果冒充当前图。

退出门槛：`10_IMPLEMENTATION_STATUS.md` 不再把文件存在、合成规划或 deterministic replay 写成真实
规划完成。

## Phase 1：Artifact CAS 与分支恢复

当前最高风险是历史 checkpoint fork 根据 `vN` 覆盖已有 artifact payload。必须先修复，否则后续
任何真实 resume 证据都不可信。

### 1.1 Contracts

- [x] 新建 `ArtifactDescriptor`：digest、media_type、size、schema、semantic_digest、parents、producer、
  run_id、branch_id、provenance；
- [x] 分开 immutable blob identity 与 mutable run named ref；
- [x] 删除业务代码对 revision folder 和 latest revision 的依赖。

### 1.2 Repository

- [x] 实现 `ContentAddressedArtifactRepository`；
- [x] blob 使用 create-if-absent，存在时逐字节校验，绝不 `os.replace` 已有 blob；
- [x] named ref 更新使用 compare-and-set；
- [x] 历史 checkpoint resume 创建新 branch ID；
- [x] 删除 `FilesystemArtifactStore` 的 revision index 和覆盖写路径。

### 1.3 验证

- [x] 同 logical ref 重放相同 payload 不改变 manifest；
- [x] 同 logical ref 不同 payload/parent identity 返回冲突；
- [x] checkpoint resume 为新执行分支派生 branch identity；
- [x] 两个 checkpoint fork 不互相覆盖；
- [x] parent digest 变化使下游 ref 明确失效。

退出门槛：任何 replay/fork 都不能改变历史 blob checksum。

## Phase 2：SessionDataSnapshot 与 SpatialWorkspace

### 2.1 数据层

- [x] 建立 `SessionDataSnapshot` manifest 和 `SpatialWorkspace` 注入边界；
- [ ] 建立 collection registry：current land-use、boundary、road、facility、constraints、imagery；
- [ ] 每个 collection 固化 schema、CRS/SRID、feature ID、digest、source 和 feature count；
- [ ] 建立 `DataQualityReport`：missing layer、invalid geometry、duplicate BSM、unknown CRS、单位问题；
- [ ] `SessionDataSnapshot` 冻结后禁止 worker 隐式刷新 provider；
- [x] 删除 EXECUTE Agent/tool 的 `gis_bundle`/`gis_data` 状态入口，改为 data-owned `SpatialWorkspace`；
- [ ] 清除所有 spatial adapter 的自由形态 GeoJSON 参数。

### 2.2 空间内核

- [ ] 统一 `SpatialFeature/GeometryRef/CRSRef/AreaMeasurement`；
- [ ] 统一 `AreaService`，清除数值大小推断单位；
- [ ] PostGIS/file adapter 通过同一 contract；
- [ ] 所有索引、overlay、distance、topology 只通过 `SpatialWorkspace`。

退出门槛：从真实 bundle 得到一个可重复 digest 的 SessionDataSnapshot；AgentState 不包含 GIS 正文。

## Phase 3：Application、Event Log 与 API 读取边界

### 3.1 Application

- [ ] 建立 `application/commands`、`queries`、`projections` 和 `UnitOfWork`；
- [ ] API route 不再直接读取 Runtime、Artifact Store、ReportStore、SSE manager；
- [ ] session create/delete、review、resume 和 delivery query 各有一个用例实现。

### 3.2 Events

- [x] 建立 append-only `RunEventRepository(session_id, seq)`；
- [ ] 写事务 outbox 和 publisher；
- [ ] `SSEConnectionHub` 只保留在线 queue；
- [x] 删除 SSE 内存 seq/history owner；关键事件 cache、outbox 和跨进程 publisher 仍待拆分。

### 3.3 FastAPI 0.141.1

- [ ] 统一使用原生 `EventSourceResponse/ServerSentEvent`；
- [ ] Last-Event-ID 从 EventRepository 补发；
- [ ] gap 返回 resync，REST/SSE 共用一个 projection builder；
- [ ] 删除旧 `/api/sessions/.../stream` 和重复 sync 入口。

退出门槛：服务重启后 SSE 可从持久 seq 恢复；断线重连不运行 LangGraph。

## Phase 4：Assessment、Objectives 与 Demand

### 4.1 Assessment

- [ ] 从 L1 有效逻辑抽取 `AssessmentService`；
- [ ] 12 个专业 worker 产出 typed findings/claims，不产出执行对象；
- [ ] aggregate 形成唯一 `AssessmentSnapshot`；
- [ ] 报告正文成为 projection，不再被下游解析。

### 4.2 Objectives

- [ ] 从 L2 有效逻辑抽取 `ObjectiveService`；
- [ ] 目标必须量化 priority、time horizon、budget/policy boundary 和 evidence；
- [ ] 建立一次 objective HUMAN gate，批准目标而不是逐个解析错误。

### 4.3 Demand engines

- [ ] `ServiceGapEngine`；
- [ ] `LandUseNeedEngine`；
- [ ] `ConnectivityNeedEngine`；
- [ ] `RiskEcologyNeedEngine`；
- [ ] `ProjectCatalog`；
- [ ] 形成唯一 `DemandPortfolio`，每项都有 need/objective/evidence chain。

退出门槛：需求回答“什么、多少、何时”，不包含 BSM/geometry；缺标准或证据时 fail closed。

## Phase 5：Suitability 与 Portfolio Allocation

### 5.1 Suitability

- [ ] 从现有 GROUND、selection、spatial index 提取 criteria pipeline；
- [ ] 每类需求显式定义 criteria source、transformation、weight 和 hard exclusion；
- [ ] 输出逐候选 criteria score 与排除原因；
- [ ] 不从可用地块数量反推需求量。

### 5.2 Allocation

- [ ] 建立 `AllocationProblem`；
- [ ] 对设施显式建模 demand、capacity、required/candidate facilities、travel cutoff；
- [ ] 对用地显式建模面积、相容性、连片、阶段和冲突；
- [ ] 对道路显式建模连接需求、网络约束和依赖；
- [ ] CP-SAT/MIP 返回完整 solver status 和 objective；
- [ ] 建立 portfolio HUMAN gate 处理价值取舍，不 approve infeasible。

退出门槛：只有 OPTIMAL 或明确批准的 FEASIBLE 可产生 `PortfolioDecision`；unmet demand 始终可见。

## Phase 6：PlanningProgram 与 Materialization

### 6.1 PlanningProgram

- [x] 删除 L3 `【INSTRUCTION】` 机器段、L3 Markdown table compiler 和旧 revision profile；post-L3 intent projection 仍待移除；
- [x] L3 编译先产出 `ProgramProposal`，不再直接产出权威 `PlanningIntervention`；
- [x] `ProgramAssembler` 成为 proposal → `PlanningProgram` 的唯一边界；
- [x] LLM structured output 只用于 `PlanningClaim`，不直接形成 PlanningProgram；
- [ ] `ProgramAssembler` 最终只从 DemandPortfolio、PortfolioDecision 和 HUMAN decision 组装；
- [ ] 删除按名称/维度猜 object kind、classification 或 geometry 的逻辑。

### 6.2 ExecutionPlan

- [ ] 每个 task 固化 classification、assignment、geometry expectation、dependencies 和 parent refs；
- [ ] project/facility/road/axis/zone/restoration/protection/action worker 各只做一种动作；
- [ ] 删除 worker 内重新选址、重新分类和直接 KG 查询；
- [ ] fan-in 检查 BSM/geometry 冲突；
- [ ] 形成唯一 `ExecutionResult` 根 artifact。

退出门槛：每个项目能追溯到 demand/objective/evidence/assignment；没有“执行了但不知道是什么项目”。

## Phase 7：Validation、Scenario 与 Delivery

### 7.1 Validation / Scenario

- [ ] Validation 只读取 ExecutionResult exact children refs；
- [ ] 校验 geometry、topology、classification、constraints、area、network 和输出完整性；
- [ ] ScenarioModel 从 current + changes 构建完整期末状态和指标；
- [ ] coverage matrix 证明每个 approved demand 已完成、延期或失败；
- [ ] evaluator 不补造变更。

### 7.2 Delivery

- [ ] DeliverySpatialSnapshot 只由 validated ScenarioSnapshot 构建；
- [ ] renderer/exporter/land balance/map API 只接收 snapshot descriptor；
- [ ] 一个 PNG 两个 panel，左右分别为现状和规划；
- [ ] 两侧地类按分类着色并保留地块边界；
- [ ] 右图叠加小型项目/设施点、项目面、道路和轴线；
- [ ] HTML 提供图层独立开关；
- [ ] 实际读取 GeoJSON/HTML 并目视检查 PNG。

退出门槛：规划变化、项目名称/类型/位置、定位点和 land balance 均可从同一 snapshot 证明。

## Phase 8：最小 WorkflowState 与图切换

- [x] 新建 14 字段 `WorkflowState` 并让根图以它编译；
- [x] 将旧 stage view 在 checkpoint 写入前固化为单一 `workflow_progress` artifact，根 checkpoint 不再保存旧字段；
- [ ] 删除 `workflow_progress` 中的 legacy stage 字段，改由 typed stage artifacts 和独立 conversation progress 承担；
- [ ] conversation messages 移出规划图；
- [ ] gate history、audit、diagnostics、review items 全部 artifact/event 化；
- [ ] 建立统一 `StageCommand/StageCompletion` adapter；
- [ ] 拆分 root graph、routing、interrupt、terminal；
- [x] 删除 `post_l3_main_nodes.py` 和旧主图入口；
- [ ] 删除旧 AgentState/ExecuteAgentState；
- [ ] HUMAN 只允许当前真实 interrupt + event ID + `Command(resume=...)`；
- [ ] checkpoint fork 与 interrupt resume 明确分离。

退出门槛：checkpoint 只有控制字段/refs；进程重启后同 thread resume 到正确下一阶段。

## Phase 9：测试收敛与最终真实验收

### 9.1 测试布局

- [ ] `tests/architecture`：依赖方向、禁止旧 import、状态 owner；
- [ ] `tests/contracts`：CAS、schema、分类、solver status、事件幂等；
- [ ] `tests/integration`：真实 data/spatial/evidence/application；
- [ ] `tests/acceptance/test_real_graph_resume_delivery.py`：唯一完整真实主图验收；
- [ ] 删除重复 synthetic state/program tests 和旧 fixture-only E2E；
- [ ] pytest 使用 `tmp_path`，移除共享固定 `--basetemp`；正式产物写独立 run-artifacts。

### 9.2 Acceptance

- [ ] `/api/v1` 创建真实会话；
- [ ] 真实 jintian data snapshot、KG 和真实 LLM；
- [ ] 运行到真实 LangGraph HUMAN interrupt；
- [ ] 关闭并重开 SQLite/Postgres checkpointer；
- [ ] 同 thread/event resume，已完成 LLM 阶段不重复调用；
- [ ] 达到 DELIVER；
- [ ] 检查所有 artifact parent digests；
- [ ] 读取 complete planned GeoJSON，证明不只是 660 地块原样复制；
- [ ] 打开实际 HTML 和双 panel PNG；
- [ ] 记录项目、设施、道路、轴线、分区、保护修复的实际数量和延期原因；
- [ ] 只有结果稳定、可解释、可视和可运行才标记完成。

## Phase 10：文档与死代码清理

- [ ] `design/` 只保留 TARGET；
- [ ] `architecture/` 只记录 CURRENT；
- [ ] `audits/` 只保存一次运行证据；
- [ ] `10_IMPLEMENTATION_STATUS.md` 是唯一差距台账；
- [ ] 删除重复段落、旧 endpoint、旧状态、旧类和旧路径说明；
- [ ] 重新运行 Graphify/static import analysis；
- [ ] `git diff --check`、OpenAPI diff、JSON Schema diff 和文档链接检查通过。

## 当前实施切片

Artifact CAS 和持久 EventLog 已完成基础迁移；当前切片是把根图切换到 `WorkflowState`，并将
旧 stage view 迁入 `workflow_progress` artifact。下一步不是增加兼容 facade，而是拆分该 artifact
并删除 `AgentState`/`ExecuteAgentState` 的剩余依赖；每个拆分都必须通过真实 checkpoint resume、
StepReport 和实际交付渲染验收。
