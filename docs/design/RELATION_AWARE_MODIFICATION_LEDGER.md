# 关系感知空间规划实现修改台账

> 核验日期：2026-08-18  
> 目的：把“契约存在”“生产者写出”“消费者使用”“验证器复核”和“真实验收通过”分开记录，避免把设计文档、目录、历史运行或静态渲染图当作当前规划能力。  
> 状态以当前工作树和可复核 artifact 为准；未通过 acceptance 的行不得标记为 CURRENT/COMPLETE。

> 当前状态覆盖页：[`10_IMPLEMENTATION_STATUS_CURRENT_20260818.md`](10_IMPLEMENTATION_STATUS_CURRENT_20260818.md)。
> 已归档的 `10_IMPLEMENTATION_STATUS.md` 中的历史 P0 空图层段落仍保留作为 test3/旧入口证据，不再单独代表
> replay28 的最新 clone-only 结果。

## 当前结论

> **当前证据补充（PARTIAL / CLONE_ONLY）：** `replay-sourceaware-replay28-report.json` 记录了
> source-aware clone/replay 的完整阶段链，但不构成默认 live `COMPLETE`。可复核事实为：GROUND 有
> 42 exact Point、1802 parcel candidates、329 corridor candidates；SELECT 为 16 placed、154 deferred；
> EXECUTE 使用 16 worker tasks 并产出 16 final features；DELIVER 写出 15 render layers、122 non-baseline
> overlays，orphan 与 invalid/empty/placeholder/duplicate geometry quality defects 均为 0。exact Line
> 仍为 0，且道路/轴线缺少可审计 source-feature binding，因此整体保持 `PARTIAL`。

> **来源几何边界（PARTIAL）：** `task-f5-source-line-audit-report.md`、`task-road-geometry-report.md`
> 和 `task-wave3-geometry-persistence-report.md` 证明当前道路源层有 131 个 `MultiLineString` features，
> 显式 source ID 可贯通 source bundle → KG → spatial adapter → GROUND，并保留权威 WKT。131 是 GIS
> source feature 数，不是规划文本中的人工数量 275；真实 line 需要 source feature IDs、同快照 lineage
> 和 digest，不能用数量相等或文本推断自动绑定。

> **2026-08-18 复核覆盖：** 本节的旧结论仍适用于 `fresh-ground-20260817-test3`、历史 test5 和默认
> `.run-tmp/runs` 活动会话，不适用于最新的 source-aware clone-only replay28。replay28 已从 clean main
> cursor 完成主链并写出 15 个 render layers、122 个 non-baseline planning overlay features、16 个
> selected/final features、0 orphan 和 0 几何质量错误，因此当前整体状态应写作
> `PARTIAL/CLONE_ONLY`，不能继续写成“所有主链规划图层均为 0”。但它不是默认 live demo 的
> `COMPLETE`：exact Line=0、roads/axes 尚无真实 source-feature ID/network binding、154 个目标 deferred，
> 且 live 二次 resume 的 LLM/worker 零增量尚未完成验收。`actual_change_count=0` 只表示相对 baseline 的
> 变化字段，不得覆盖上述 122 个 planning overlay 统计。

**HISTORICAL / PARTIAL：** 默认活动 demo 尚未形成有效的可发布规划图层。旧 fresh-GROUND artifact 的
`grounding_result` 曾只有 161 个 union 候选，且 161 个候选均为 `hard_constraint=failed`。
补上“按来源 BSM 展开地块候选”后，隔离 fresh branch
`fresh-ground-20260817-test5` 重新产出 6,699 个单 BSM 候选，其中 3,512 个通过硬约束、
3,187 个明确失败，仍有 9 个未解析目标进入 HUMAN。该结果证明粗 union 确实放大了禁建区
冲突，但不等于已有可执行点线；test5 是修复前的历史 GROUND artifact，不能用来证明新
source geometry producer 已被重建消费。最新 source-aware replay28 已证明设施 Point 和
polygon overlay 可以进入 SELECT→EXECUTE→DELIVER，但仍是 clone-only partial：exact Line=0、
154 deferred，默认 `/map-layers` live acceptance 尚未完成。旧 `.run-tmp/runs` 会话中产生的
`planning_scenario`/`planned_state` 不能覆盖默认入口的 fresh live 验收；但 replay28 的同 run
CAS refs 可以作为当前 partial 证据。

**HISTORICAL：** 该重放从 GROUND 之后的旧 checkpoint 恢复，161 个候选缺少最新的
`materialization_role`，其中 46 个为 coarse/village fallback；因此它只能证明旧 GROUND
artifact 与当前 VALIDATE 边界不兼容，不能证明最新 GROUND producer 已通过真实验收。下一步
必须固定 replay branch 语义，从 GROUND 之前重新生成候选和约束状态，再重走
SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER；在该 fresh run 产生非 baseline feature、
非空 overlay 且 `/map-layers` 可读前，
所有相关行保持 `PARTIAL`/“未通过真实验收”。

2026-08-12 的隔离历史运行只能作为 HISTORICAL/PARTIAL 证据：SELECT 有 178 assignments、1 个 selected site，
但 PlannedState 中有 0 parcels、0 zones、0 roads、16 facilities、1 axis、17 project points；660 个
`complete_planned_landuse` 要素是 current/baseline 延续，实际 `ParcelChange` 为 0。独立脚本生成的
`integrated_planning_map.png` 直接读取静态 current/planned 文件和报告，不是主 workflow 的 delivery 证据。

旧的 161-candidate/test3 空输出是 **HISTORICAL fail-closed artifact**：候选全为
`polygon/parcel_set` 且 hard constraints 全失败，不能解释成 rendering loss，也不能删除历史证据。
任何仍写“PlanningScenario does not exist”或“275 versus 131 proves binding is impossible”的旧句子均为
**DEPRECATED**；当前事实是 typed scenario 已存在，且 source-line characterization 已证明在显式 ID、
同快照 lineage 下 exact line 能力存在，缺口在目标语义与 source collection binding。

下一实现门禁：按 `docs/superpowers/plans/2026-08-18-gis-fact-source-collection-binding.md` 从 T1
起串行执行；T4A 先提供动态 L1-constrained source semantics，再建立 source collection binding 与
required/alternative cardinality，执行 operation-aware EXECUTE，并完成 `/map-layers`、fresh
default-live replay 和 idempotent resume。未完成这些 gate 前，所有 acceptance 行保持 `PARTIAL`/`GAP`。

## 五列状态台账

| 模块/能力 | 契约 / schema | producer（生产者） | consumer（消费者） | validator（验证器） | acceptance（真实验收） |
|---|---|---|---|---|---|
| PlanningIntentGraph | v2 `backend/app/contracts/planning/intent_graph.py`；`PlanTargetNode`、typed `PlanRelationIntent`、`PlanningIntentGraph` | `backend/app/domain/program/target_projection/intent_graph_compiler.py`、`backend/app/workflow/stages/target_projection.py` | GROUND 编译为 `GroundedPlanningProblem`/factors；SELECT 的 ScenarioSolver 消费关系因素并持久化 `PlanningScenario`，不是只传递原始图 | VALIDATE 不直接验证原始图，而是从 scenario/factors 和最终 features 计算 `FinalRelationValidation`；DELIVER 读取该结果并 fail-closed/partial | 局部 contract/solver/validator tests 通过；当前真实主链仍无可发布非 baseline 图层，因此 acceptance 为 `PARTIAL` |
| Relation factors / satisfaction | v2 `constraint_factor.py`、`relation_parameters.py`、`scenario.py` 含阈值/单位/measurement、scenario、feature refs、trace | projection compiler、GROUND factor compiler、ScenarioSolver、final validator | SELECT 写入 `PlanningScenario`；VALIDATE 从最终 geometry/network/trace 重测量，DELIVER 读取 final validation | `relation_validation.py`、`scenario_reconciliation.py`、`check_relation_validation()` fail-closed | 模块测试通过；真实主链非空图层与 fresh/resume acceptance 尚未通过 |
| Candidate geometry | v2 `candidate_geometry.py` 含 stable candidate id、geometry role、`materialization_role`、generation op、lineage/source refs | GROUND candidate-domain builder 保留 point/line/polygon 的候选态/执行态区分，并传播 materialization role 与 hard-constraint 状态；KG L1 已能写入 source-backed point/line WKT | ScenarioSolver 只把 `execution_geometry` 构造成 ScenarioFeature；ExecutionDAG 传递 candidate binding | typed candidate tests、scenario feature lineage、final feature index | 模块测试通过；source producer raw smoke 通过，仍需 fresh run 确认 point/line 实际下沉到 map-layers |
| GroundedPlanningProblem | v2 `grounded_problem.py` 含 candidate domains/geometries、factors、baseline/source/network refs | `ground_aggregate.py` 与 GROUND stage 写入 `GroundingResult.problem` | SELECT 调 `solve_scenario()` 并持久化 `planning_scenario`（兼容旧 assignment 路径） | ScenarioSolver hard/soft feasibility 与 deterministic fingerprint | 旧 artifact 兼容性已复核；fresh GROUND/resume/前端 acceptance 未完成 |
| Explore evidence | `EvidenceBundle`、query-plan/sufficiency/cache/version contracts | router、artifact/history/integrity/RAG retriever；`run_rag` 仅作为 unified adapter | gate pending request 触发 scoped retrieval；worker 不再并列调用旧 RAG 和 `retrieve_evidence()` | sufficiency、artifact integrity、版本/fingerprint cache focused tests | 模块测试通过；真实 provider 运行和空间结果仍待验收 |
| Selection / allocation | `global_site_allocation_contracts.py`、`selection_contracts.py` + `PlanningScenario` | global allocator 保留 capacity/exclusivity；ScenarioSolver 统一候选组合和 relation objective | SELECT 持久化 scenario，并将 scenario candidate binding 写回 assignments；hard-blocked target deferred | Portfolio gate + scenario hard/soft/network tests | 模块/接线测试通过；真实非空规划图层尚未验收 |
| Facility service | `FacilityDemandPoint/DemandSnapshot`、network/service parameters、network graph | network graph + service area + ScenarioSolver network subproblem | serve/access/connect 使用 network impedance、facility type、demand、capacity；不以现状设施邻近代替覆盖率 | network service/connectivity tests、final validator typed demand fail-closed | 模块测试通过；真实主链 demand/network artifact 尚未验收 |
| Road / linear planning | `road` / `linear` typed target、`PlannedRoad` 线成果和道路等级/宽度参数；端点/网络证据仍不完整 | `backend/app/domain/materialization/road_worker.py` 及 staged road pipeline；新建/明确 `widen` 通过独立道路地块物化器按线宽求交当前地块，缺输入则 fail closed/deferred | EXECUTE 固定 worker 图调用 road worker；道路 worker 同时写线性成果与交通用地 `ParcelChange`，既有 `upgrade/repair/harden` 不虚构新增占地 | 道路线 source binding、线宽/等级/当前 DLBM/地块求交和 source overlap checks；scenario endpoint relation reconciliation 仍缺 | 2026-08-20 真实金田 bundle `new`/`widen` acceptance 通过：真实 `current_road` LineString/MultiLineString → `planned_road` → 1006 交通用地子面 + remainder → `PlannedState`/`function_zone`/`planned_road` render；默认 live root/resume 仍为 `PARTIAL` |
| ExecutionPlan / DAG | v2 execution contracts 含 scenario/candidate/relation/target binding、trace refs | task scheduler + plan builder | main EXECUTE path 按 Kahn DAG batches 调度，cycle/missing/deferred fail-closed | scheduler/lineage tests | 模块测试通过；真实主链 artifact/resume 未验收 |
| Worker output / PlannedState | planned state/worker result 含 scenario、candidate、feature、materialization role、relation/source lineage | project/facility/road/axis/zone workers + planned-state builder | 无显式 binding 不再单目标猜测；DELIVER 读取 authoritative snapshot | scenario lineage、final feature index/topology | 旧 GROUND 重放生成 28 candidate-backed parcels、29 overlays；仍因 VALIDATE 阻断，未形成 delivery refs |
| VALIDATE / RECONCILE | FinalScenarioValidation + reconciliation contracts | validate stage 调 final geometry/network/temporal evaluator 并写 `final_relation_validation` | execution review/DELIVER gate 对 hard relation fail-closed | final relation/topology/reconciliation tests | 最新真实重放 final relation 本身可写出，但旧 GROUND artifact 触发 36 hard constraint、151 overlap、11 missing-final-feature，真实 acceptance 未通过 |
| DELIVER / map-layers | `DeliverySpatialSnapshot`、`RenderLayers`、DeliveryManifest；空/无变化应降级 | `backend/app/domain/delivery`、`app/spatial/delivery`、render/export adapters | `/api/v1/sessions/{id}/map-layers` 只读 DELIVER 持久化 RenderLayers；final relation validation 缺失/失败降级 partial | no-planning-output、named refs、非 baseline feature、geometry/lineage、manifest 状态 | 默认活动 demo/test3 未通过；source-aware replay28 clone-only 已有 15 layers、122 planning overlays、0 orphan，但状态仍为 PARTIAL，不能当 live COMPLETE |

## 允许称为“已实现”的最低证据

对任何一个规划模块，至少要同时具备以下五项，否则只能写 `PARTIAL` 或 `GAP`：

1. schema 能表达该模块的实际语义，不依赖 `Any`、默认字符串或隐式 fallback；
2. 生产者在主 workflow 中写出带 digest/version 的 artifact；
3. 下游消费者实际读取该 artifact，并改变决策或物化结果；
4. validator 从最终产物重新计算关键不变量，而不是复制上游状态；
5. fresh、resume、局部失败/延期和前端 `/map-layers` 读取均有可复核 acceptance。

以下不能单独计入 acceptance：

- 只存在契约类或单元测试；
- `complete_planned_landuse` 与 current 相同的 baseline 复制；
- 只有 project/facility marker points；
- `scripts/render_integrated_map.py` 生成的静态 PNG；
- 旧运行目录中的 named refs；
- 只证明能到达 DELIVER、没有非 baseline `ParcelChange` 的 checkpoint 测试。

## 修改台账

| 日期 | 文件 | 修改内容 | 证据/目的 |
|---|---|---|---|
| 2026-08-17 | `docs/_archive/design/10_IMPLEMENTATION_STATUS.md` | 将当前活动 demo 空图层提升为顶部 P0；把 2026-08-12 数字降级为 HISTORICAL/PARTIAL，并注明实际土地变化为 0 | 防止 660 baseline、17 project points、16 facilities 被误报为当前规划成果 |
| 2026-08-17 | `docs/design/27_IMPLEMENTATION_VS_DESIGN.md` | 增加关系感知的五列差异索引；修正 23 文档活跃状态、第一版 relation contracts 已存在但未贯通的描述 | 让设计差异与代码状态一致 |
| 2026-08-17 | `docs/design/RELATION_AWARE_MODIFICATION_LEDGER.md` | 固化 schema/producer/consumer/validator/acceptance 台账和空图层验收门槛 | 作为 Wave 0–3 子任务的共享事实基线 |
| 2026-08-17 | `backend/app/domain/allocation/scenario_solver.py`、`backend/app/domain/ground/aggregate.py` | 候选硬约束状态、粗粒度候选和独占角色空间冲突进入 fail-closed 选择；旧 untyped candidate 仅保留显式兼容路径 | focused ScenarioSolver 6 passed；真实重放仍需从 GROUND 重新生成 artifact |
| 2026-08-17 | `backend/app/domain/validation/validate_checks.py`、`planned_state_builder.py`、`render_layers.py` | candidate identity 与 BSM 分离，overlay 按语义分层，candidate-backed geometry 不再伪造 ParcelChangeSet；delivery 只暴露对应角色图层 | materialization/delivery/final validation focused 16 passed；真实主链尚未到 DELIVER |
| 2026-08-17 | `backend/app/contracts/spatial/candidate_geometry.py`、`backend/app/domain/ground/aggregate.py`、`scenario_solver.py` | 候选增加 `materialization_role`，独占角色执行确定性空间冲突裁剪，避免同一权威语义层重叠；角色分层不放宽最终 hard relation 验证 | focused tests 通过；下一证据必须来自 fresh GROUND 后的真实主链 |
| 2026-08-17 | `backend/app/domain/ground/aggregate.py`、`backend/app/domain/allocation/refined_candidate_catalog.py`、`backend/app/workflow/stages/select.py`、`execute.py` | 将多 BSM union 拆为单 BSM parcel alternatives，并把 SELECT 的 suitability surface 细化候选接入 ScenarioSolver/EXECUTE catalog；不合成 centroid、入口点或道路中心线 | `fresh-ground-20260817-test5` 产出 6,699 candidates（3,512 hard pass、3,187 fail、9 unresolved）；SELECT/EXECUTE 仍待修复 replay branch 后复跑 |
| 2026-08-17 | `backend/app/workflow/state.py` | 历史显式 fork 存在时，忽略自动 `resume-*` pending writer，保留不同显式 fork 之间的冲突保护 | branch reducer smoke passed；真实 SELECT replay 仍需从未污染 checkpoint 重跑 |
| 2026-08-18 | `backend/app/infrastructure/kg/builder/geo_helpers.py`、`layer1_core.py` | 仅将 source GeoJSON 的 road LineString/MultiLineString 与 facility Point 写入 `geo:hasGeometry/asWKT`；无 centroid/入口/union 推断 | deterministic helper smoke 与真实 raw road/facility source smoke 通过；KG 重建和同 branch delivery 尚未验收 |
| 2026-08-18 | `backend/app/data/ingestion/compiler/spec_mapper.py`、`domain/program/target_projection/aggregate.py`、`workflow/stages/target_projection.py` | existing facility/road 的唯一 resolved exact binding 只投影为可由 KG 再核验的 named reference；TARGET_PROJECTION stage 实际加载 `l1_observations`/`l1_bindings` 并传递到 mapper；缺 geometry、非 existing action、多 binding 均保持 coarse/candidate-only | artifact-backed stage smoke：gate passed、170 specs（topological 107、composed 62、directional 1）；`祠堂群` 无唯一 KG label，故仍未产生执行 point；新增 binding/target/geometry focused tests 通过 |
| 2026-08-18 | `workflow/stages/target_projection.py` | source-aware TARGET_PROJECTION 同时收集 `annotations_current`、`facilities_current` 及所有可见 point/road layers，按稳定 `source_feature_id` 去重；无 provenance 的 feature 仍不能跨越 exact boundary | 9 个 target/source-binding tests passed；需要在 source-aware context/KG fresh replay 中再次证明 directional→GROUND point/line 下沉 |
| 2026-08-18 | `backend/app/contracts/spatial/spatial_reference_contracts.py`、`spatial_ref.py`、`resolver.py`、`ground/aggregate.py` | 增加独立 `GeometryRef` 列表和 source lineage；显式 multi-feature opt-in 才能返回多个 exact point/line，并逐个生成 CandidateSite；普通多匹配、缺失/非法成员仍 candidate-only/fail-closed | characterization multi-source tests 通过；真实 L3 尚未提供 source feature IDs，故真实 GROUND 仍无 point/line |
| 2026-08-18 | `backend/app/workflow/state.py`、`backend/scripts/resume_graph_checkpoint.py` | 已有 `resume-*` checkpoint 的历史重放使用 `resume-fork-*`，只允许受控 source→fork 迁移，拒绝任意 resume 分支并行写入 | terminal replay/resume service 10 passed；需在 clean test5 cursor 上做一次低内存 fresh GROUND smoke |
| 2026-08-18 | replay checkpoint / acceptance audit | `target_projection` 入口回放未能进入业务阶段：历史 checkpoint 的 reducer 在 `aget_state()` 期间即发现 stale parallel branch writes（`resume-*` 分支不一致）；复制 DB 不能清除其历史 writes。不得放宽 branch reducer 或把该失败当作 geometry/SELECT 结果 | 两次 clone-only bounded attempts 均 fail-closed 并已关闭进程；当前代码专项 26 passed，真实同 branch GROUND→SELECT→DELIVER 仍未验收 |
| 2026-08-18 | clean main-cursor target projection / GROUND replay | 从 pending writes 只有 `main` 的 root cursor `1f19a35a-c84e-68fc-8003-d022a8b240bf` 建立 `resume-safe-targetwire-main-20260818` clone fork；TARGET_PROJECTION 真实 stage 产出 170 specs（directional=1），GROUND 产出 6,699 candidates（hard pass=3,512、fail=3,187） | 几何仍为 polygon/parcel_set 6,699，point/line/exact_feature=0，GROUND gate=HUMAN；证明接线已生效但 source identity/authoritative geometry 仍未供给，未进入 SELECT/EXECUTE/DELIVER |
| 2026-08-18 | nested HUMAN resume + bounded SELECT continuation | `ResumeService` 读取 spatial-chain `interrupt_ref` 的 exact event token；clone-only 分支 `resume-select4-main-20260818` 仅 defer 当前 GroundingResult 中的 8 个 unresolved target 后进入 SELECT | SELECT gate 仍为 HUMAN/`portfolio_infeasible`：170 assignments 中 47 assigned、123 unplaced，distinct candidate IDs=2；PlanningScenario 仅 12 个 polygon features，site_selection 76 个 facility 全 unplaced、anchor=0，ExecutionPlan 12 worker/158 deferred。说明恢复路由已修复，但候选仍不足以形成合理规划图层；无 EXECUTE/DELIVER acceptance |
| 2026-08-18 | `workflow/stages/execute.py`、`infrastructure/artifacts/runtime.py`、`materialization/nodes/facility_worker.py`、`materialization/nodes/worker_common.py`、`domain/validation/relation_validation.py` | EXECUTE 读取 `SuitabilitySurface` 时补齐类型；artifact JSON 严格校验失败后显式非严格 coercion；facility worker 仅从选中 CandidateGeometry 的 authoritative Point WKT 注入 anchor；worker/final validation 对空 relation lineage 使用稳定 selection ID | source-aware replay 已实测 GROUND 42 exact Point 并进入 SELECT/EXECUTE；8 个窄测试通过。最后一次 replay 到 VALIDATE HUMAN 暴露旧 worker lineage 断点，已修复；需再跑一次干净 clone 才能验收非空 planned facility 与 `/map-layers` |
| 2026-08-18 | `infrastructure/context/planning_context_factory.py` | checkpoint 带 `expected_snapshot_digest` 时优先恢复持久化 session bundle，再执行原有 digest 校验；避免从 live catalog 重组同一输入造成 synthetic legacy ordering 变化而误报上下文漂移 | context/KG freshness + persisted bundle + artifact runtime 8 passed；对已消费的旧 HUMAN event 的重试被 resume guard 正确拒绝，未把它计作 DELIVER acceptance。当前 source-aware 证据仍为 4 个 facility Points、L4 写入 7、roads 0、VALIDATE 26 个非 target findings |
| 2026-08-18 | `backend/app/domain/validation/checks.py`、`backend/tests/characterization/test_wave3_validation_boundaries.py` | RECONCILE 面积检查仅在 PlannedState 存在正面积 parcel 时执行；overlay/facility-only 场景的 `area_ha=0` 占位记录不再伪造 L3 面积漂移，正面积 parcel 仍按原 5% 容差校验 | source-aware replay28：RECONCILE 从 `area=0`/期望 9426–9494 的误阻塞恢复为 PASS；4 个 characterization tests passed |
| 2026-08-18 | source-aware replay28 artifacts | 从 clean main root + v3 source bundle 完成真实 `TARGET_PROJECTION → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER`；42 exact Point candidates，16 placed/154 deferred，16 final features（4 Point + 12 polygon），relation validation 0 findings，delivery partial；planned overlay layers feature counts facility=4/project=1/project-point=3/protection=4/restoration=4/zone=1，geometry quality invalid/empty/placeholder/duplicates 均为 0 | `replay-sourceaware-replay28-report.json` 与 branch artifacts：`delivery_manifest sha256:08bfced...`、`delivery_spatial_snapshot sha256:10e513...`、`render_layers sha256:7ed08e...`；禁止把 current/complete_planned_landuse 660 baseline features 计入规划产出，154 deferred targets 保留在 immutable ledger |
| 2026-08-20 | `backend/app/domain/materialization/road_parcel_materializer.py`、`nodes/road_worker.py`、`merge.py` | 将“道路建设”明确拆成线性成果与地块用地变更：target-bound `planned_road` 线按已声明道路等级和米制宽度缓冲，与 bundle authoritative current landuse 求交，生成交通运输用地子面和 preserve remainder；同一源地块的非重叠子几何允许共存，真实重叠阻断合并；`upgrade/repair/harden` 只保留道路线 | `test_real_jintian_road_landuse_execution.py` 覆盖真实金田 131 条道路中的 source-bound `new` 和 `widen`；连同 materializer/overlap/road-preparation 回归 17 passed，complete execution/render 2 passed；默认 live root 仍未宣称完成 |
| 2026-08-20 | `tests/acceptance/test_simulated_root_graph_road_delivery.py` | 用真实金田 bundle/KG 和生产根图验证模拟 L1/L2/L3 结构化响应经 TARGET_PROJECTION、GROUND、SELECT 后进入道路 worker；道路 worker 同时生成 target-bound `PlannedRoad` 线和按 `1006` 分类的交通运输地块子几何，VALIDATE/DELIVER 读取同一 authoritative artifacts，终态再次 resume 不增加模型调用 | `1 passed`（RAG/Exa/真实 MiniMax 默认关闭）；这是 quota-free 的编排与空间成果验收，不替代真实 provider 的语义质量验收；当前 L1 gate 的显式 retry/HUMAN 仍是后续 token 收敛项 |
| 2026-08-18 | `backend/tests/characterization/test_real_source_line_grounding.py`、`task-f5-source-line-audit-report.md` | 用真实 `data/gis/jintian/current/road.geojson` 的 131 条 MultiLineString 验证显式 source ID 从 target projection 进入 source bundle → KG `source_feature_id + geo:hasGeometry/asWKT` → spatial adapter → resolver → GROUND 的 exact Line 闭环；不经过 parcel union | source-line/KG/bundle/target-projection focused runs passed；当前 live 缺口不是 producer，而是 24 个 road/axis intervention 没有显式 source IDs，且文本“275 条道路”与源层 131 条不一致，不能自动绑定 |
| 2026-08-18 | `backend/app/domain/validation/validate_checks.py` | direct `PlannedState` topology adapter 对旧的空 relation lineage 使用稳定 `topology:{scenario_id}` scope；不放宽持久化 `ScenarioFeature.relation_ids`，仍可发现断开的 facility/road/axis | `test_cross_layer_topology_validation.py` 通过；旧 core fixtures 仍有多个缺少必填 `relation_ids` 的 ACL 锁定维护项，不能通过放宽生产契约掩盖 |
| 2026-08-18 | `backend/app/data/ingestion/compiler/spec_mapper.py`、`backend/app/domain/program/target_projection/compile.py` | 修复 existing road source ID 在 projection 中的别名和传递：`source_feature_ids`、`existing_road_feature_ids`、`road_feature_ids` 均只作为显式审计输入；`RoadTarget.existing_road_feature_ids` 不再被 compile 丢弃；兼容 typed road/axis action 已是 upgrade 但旧 intervention action 仍为 new 的迁移输入 | road/axis/source-binding focused 通过；仍不自动从“275 条道路”文本猜测 131 条源线，缺 ID 继续 candidate/deferred |
| 2026-08-18 | source binding audit | 确认当前道路 source identity/index 已包含 URI、content/geometry digest、feature index，但没有 road name/class/road_level sidecar；JTC-014 的“275 条道路”不能安全映射到 131 条当前 MultiLineString | 21 个 source/bundle/road/axis/multi-source focused tests passed；最小安全上游输入是人工/证据审计后的显式 `spatial_requirements.source_feature_ids`，否则保持 candidate/deferred |
| 2026-08-18 | DOCS-PREFLIGHT replay28/source-line reconciliation | 将 replay28 标记为 `PARTIAL`/`CLONE_ONLY`，登记 42 exact Point、1802 parcel candidates、329 corridor candidates、16 placed、154 deferred、16 worker tasks、15 render layers、122 non-baseline overlays 与零几何质量缺陷；保留 161/test3 的历史 fail-closed 语义，并纠正 131 GIS features 与人工 275 数量的混淆 | `replay-sourceaware-replay28-report.json`、`task-f5-source-line-audit-report.md`、`task-road-geometry-report.md`、`task-wave3-geometry-persistence-report.md`；不声称默认 live 完成或未存在的测试 |
| 2026-08-20 | `backend/app/domain/assessment/observation_draft.py`、`analysis_node.py`、`data/ingestion/compiler/profiles/l1_observation.py` | L1 结构化输出要求非空 `report_body`；删除 Markdown/正文 fallback；编译器只把 source-backed 空间观察写入 `fact_records`，报告正文/约束/分类保留为 report/display context；错误进入显式 provider/typed-output diagnostic | `test_l1_typed_output_contract.py`、`test_l1_spatial_boundary.py`、`test_l1_source_fact_contract.py`；L1 仍不把分析正文冒充空间 fact |
| 2026-08-20 | `backend/app/domain/assessment/l1_fact_projection.py`、`aggregate.py`、`evidence/retrieval/retrievers/l1_retriever.py` | KG/GIS evidence 提升到 L1 时使用 `spatial_only=True`，L1 retriever 过滤非空间 record；`L1Fact.fact_kind=spatial_observation` 明确其用途是空间定位，不替代 L1 report | `test_l1_typed_fact_contract.py`、`test_l1_spatial_boundary.py`、`test_multisource_semantic_evidence.py`、`test_evidence_graph_join.py` 共 49 个 focused tests 通过 |
| 2026-08-20 | `backend/app/domain/materialization/nodes/road_worker.py` | 删除未产生 target-bound 线时的单目标成功兜底；道路 worker 必须同时交付 source-bound `PlannedRoad` 线和由道路线/宽度求交得到的 `1006` 交通运输用地子面及 preserve remainder | `test_real_jintian_road_landuse_execution.py`、`test_simulated_root_graph_road_delivery.py` 通过；模拟根图再次 resume 不增加模型调用 |
| 2026-08-20 | `backend/app/infrastructure/kg/builder/base.py` | CAS Turtle 恢复后重建 `RdfSpatialKGIndex`，保持 fresh KG 与 session resume 的实体/关系索引一致；不新增第二拓扑库 | `test_spatial_kg_store_contract.py`、`test_kg_source_fact_type_boundaries.py` 共 22 passed；覆盖恢复后按名称读取设施 |
| 2026-08-20 | `backend/app/evidence/index/place_evidence_index.py` | L1 scope 构建优先消费 typed `l1_fact_records`，旧 `location_facts` 仅在 typed records 缺失时使用；不把报告文本或旧 projection 越过空间 fact 边界 | `test_l1_semantic_scope_contract.py`、`test_evidence_graph_join.py` 共 22 passed；双输入时保留 typed fact refs 与来源 |
| 2026-08-20 | `tests/acceptance/test_simulated_root_graph_road_delivery.py` | DELIVER 后通过稳定 `/map-layers` 投影重新读取同一组 delivery refs；公开图层同时包含 `planned_road` 线和 `complete_planned_landuse` 中 `planning_code=1006` 的交通运输用地，分析性 `function_zone` 不替代权威地类层 | 模拟根图验收 `1 passed`（RAG/Exa/真实 MiniMax 关闭）；默认 live API/provider/resume 门槛仍为 `PARTIAL` |
