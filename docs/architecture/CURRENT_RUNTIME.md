# Current Runtime

> Status: CURRENT
> Authority: Evidence-backed map of behavior present in this worktree; target requirements and gaps belong in `../design/`.

## 1. Startup and composition

FastAPI 应用由 [`backend/app/main.py`](../../backend/app/main.py) 创建并注册统一 router；lifespan 位于 [`backend/app/bootstrap/lifespan.py`](../../backend/app/bootstrap/lifespan.py)，依赖组合入口位于 [`backend/app/bootstrap/composition.py`](../../backend/app/bootstrap/composition.py)。运行时编排服务是 [`PlanningRuntimeService`](../../backend/app/infrastructure/runtime/planning_runtime_service.py)，负责图初始化、session 执行、checkpoint 状态、resume 和事件发布。

可重复检查：

```powershell
rg -n "FastAPI|lifespan|include_router" backend/app/main.py backend/app/bootstrap backend/app/api -g '*.py'
```

## 2. Four workflow segments

当前 root graph 在 [`backend/app/workflow/root_graph.py`](../../backend/app/workflow/root_graph.py) 中构造；[`backend/app/workflow/segments.py`](../../backend/app/workflow/segments.py) 将其编译为四段：

- `intent_loop`：对话和工具执行；
- `cognitive`：L1/L2/L3 workers、聚合和认知路由；
- `spatial_chain`：TARGET_PROJECTION 到 DELIVER；
- `hitl`：人工 review 的 prepare/publish/wait/apply。

当前空间阶段顺序为：

```text
TARGET_PROJECTION → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER
```

gate/repair 路由已经能从 SELECT 返回 GROUND，也能从 VALIDATE 返回 EXECUTE、SELECT、GROUND、TARGET_PROJECTION 或 L3；证据见 `root_graph.py` 的 stage route 表和 [`backend/app/workflow/stages/support.py`](../../backend/app/workflow/stages/support.py)。这证明已有反馈路径，不证明每种修复都已达到目标验收。

## 3. L1/L2/L3 and target projection

L3 的 typed `PlanningProgram` 定义在 [`backend/app/contracts/domain/l3_contracts.py`](../../backend/app/contracts/domain/l3_contracts.py)。TARGET_PROJECTION 的当前 stage 位于 [`backend/app/workflow/stages/target_projection.py`](../../backend/app/workflow/stages/target_projection.py)，输出包括 `IntentCompilationResult` 等 typed artifacts。

这些能力仍是 `PARTIAL`，但目标准入已收紧。当前 [`claim_adapter.py`](../../backend/app/domain/program/claim_adapter.py) 只有声明 `planning_role=spatial_intervention`、`project_package_ref`、类别专属 typed parameters、locator/grounding requirement 和 evidence/source lineage 的 claim 才能生成 `PlanningIntervention`；证据陈述、指标、约束、目标、项目包和非空间行动保留在 `PlanningProgram`，不会机械转换为空间 target。已审计运行 `4ddc7cdb-d6c4-4976-963c-c8b484efebc8` 的 93 个 intervention 是旧准入逻辑的历史反例，只能说明为什么需要当前 gate，不能代表最新代码行为；新鲜真实运行仍需验证 provider 是否持续输出完整 project package、typed parameters、位置和 lineage。

会话原始文本现在只来自当前会话持久化的 `village_data/task_description/constraints` 和显式上传文件。`load_session_documents()` 不再自动扫描仓库 `docs/` 并把 `project_doc/current_status` 注入会话；仓库参考文档只有在显式导入并写入 document ref 后才能成为输入。L1 的 [`input_register.py`](../../backend/app/domain/assessment/input_register.py) 只在 L1 边界建立 source index，并且只接受 `village_data` 与显式 `upload` 作为事实源；旧 `current_status` 键只留下忽略诊断，不再作为第二个输入。这样 `jintian_village.md` 的原始输入和 L1 生成的分析报告是两类不同 artifact，后者仍由 LLM 生成并写入 ReportStore。

当前工作树进一步收敛了原始输入边界：[`input_register.py`](../../backend/app/domain/assessment/input_register.py) 只在 L1 worker 内建立 L1-owned source index；每个 L1 维度通过 [`l1_extraction_loop.py`](../../backend/app/domain/assessment/l1_extraction_loop.py) 执行有界的 observe → register → validate → repair/coverage 调用，维度输出负责确认语义归属，canonical `source_ref/source_span` 由 source index 物化。`l1_aggregate` 只合并维度 artifact，并通过 `l1_source_index` artifact 恢复已经由 L1 typed draft 物化的登记行和任意输入的 source segments；它不再生成 provisional 行，也不再重新读取或解析会话原文。后续 Project Bank/RAG/GROUND/前端只消费 `L1Snapshot`；循环的定向补证复用统一 `retrieve_evidence` 路由，RAG/embedding 不可用时保留 local/KG/bundle 结果并显式记录缺口。代码和 focused 回归已通过，但仍需 fresh real run 检查多轮 pass、artifact 持久化和历史 resume 后 digest 是否一致；因此当前仍为 `PARTIAL`，登记行数也不能被当作可执行目标数。

## 4. Horizontal evidence calls

当前检索 router [`backend/app/evidence/retrieval/router.py`](../../backend/app/evidence/retrieval/router.py) 已区分 `LOCAL_TEXT`、`REPORT`、`RAG`、`KG`、`BUNDLE`、`ARTIFACT`、`HISTORY`、`INTEGRITY` 和 `EXTERNAL`。Evidence service 在 [`backend/app/evidence/retrieval/evidence_service.py`](../../backend/app/evidence/retrieval/evidence_service.py) 按计划调用这些 retriever。

session-owned local text 不依赖向量服务，professional RAG 是可选外部 dense 通道；[`backend/app/evidence/retrieval/retrievers/local_text_retriever.py`](../../backend/app/evidence/retrieval/retrievers/local_text_retriever.py) 与 [`rag_retriever.py`](../../backend/app/evidence/retrieval/retrievers/rag_retriever.py) 是独立实现。当前 `retrieve_evidence` 已通过 [`coverage.py`](../../backend/app/evidence/retrieval/coverage.py) 产出逐 requirement `EvidenceCoverage`，并在 dense 通道失败时保留非 dense 结果。L1/L2/L3/TARGET_PROJECTION/GROUND 的 typed artifact 已各自投影 `evidence_requirements`，并可通过 `ExplorationRequest.requirements` 传入控制器；gate-scoped `retrieve_evidence_for_gate` 已按未解决 requirement 生成最多 2 层/8 次的 bounded missing-subquery loop，并把 follow-up/停止原因写入 packet 与 coverage trace。部分旧调用仍采用 request-level 过渡编译，跨阶段 requirement-set、source/budget policy 和固定 benchmark 尚未统一，因此整体为 `PARTIAL`。

`GET /api/v1/source-layers` 是只读的现状上下文投影，不是规划结果接口。当前仅配置金田村（`金田`、`金田村`、`jintian`）的 DataCatalog 图层；其他村名返回空图层、空栅格和明确诊断，禁止复用金田村数据。前端只在该村名门控通过时加载这一参考上下文；规划图层仍只能来自当前会话的 `/map-layers` DELIVER 快照。

## 5. Grounding

GROUND stage 位于 [`backend/app/workflow/stages/ground.py`](../../backend/app/workflow/stages/ground.py)。它结合 L1 scope、KG、bundle、PlaceEvidenceIndex、source binding 和空间查询生成 `GroundingResult`；核心问题契约 [`GroundedPlanningProblem`](../../backend/app/contracts/spatial/grounded_problem.py) 已包含 target domains、constraint factors、relations、candidate domains/geometries、network/shared refs、unresolved/deferred、baseline/source refs 和 fingerprint。

当前地点语义落地不是由向量库直接返回坐标，而是由本地 mention/L1 语义、KG/entity identity、bundle feature refs 和确定性空间/拓扑检查组合完成。实现分散在 [`backend/app/evidence/retrieval/evidence_graph.py`](../../backend/app/evidence/retrieval/evidence_graph.py)、[`backend/app/evidence/index/place_evidence_index.py`](../../backend/app/evidence/index/place_evidence_index.py) 和 GROUND stage。`ScenarioFeature` 现在要求显式 `relation_ids`，核心模型不再隐式补 lineage；没有关系因子的 reference adapter 只在其明确边界生成 `reference:<id>`。当前已增加白名单 [`SpatialQuery`](../../backend/app/contracts/spatial/query_ast.py)、[`postgis_executor.py`](../../backend/app/infrastructure/spatial/postgis_executor.py) 参数化 plan/compiler 与 `GroundedPlanningProblem.candidate_completeness` 投影；旧 GROUND/KG adapter 尚未全部迁移到新 AST，geometry uncertainty 和真实 PostGIS integration 仍不完整，因此仍为 `PARTIAL`。

## 6. Current SELECT boundary

当前 [`backend/app/workflow/stages/select.py`](../../backend/app/workflow/stages/select.py) 以 [`optimize_scenarios`](../../backend/app/domain/allocation/scenario_optimizer.py) 为 scenario 决策核心，持久化 `ScenarioSet`；正式 EXECUTE 由 `ApprovedExecutionInput` 直接绑定 `ScenarioSet` 成员和冻结后的 `ExecutionPlan`，生产代码不再导入旧 `scenario_worker_projection.py`、`SiteSelectionDecision` 或 `select_service.py`。`PlanningScenario`、`SolverCertificate`、`ScenarioSet` 位于 [`backend/app/contracts/planning/scenario.py`](../../backend/app/contracts/planning/scenario.py)。当前仍需用新真实会话证明所有 worker 都只消费获批 candidate/route/layout，而不是在 EXECUTE 内重新选择。

修复前 `GroundedPlanningProblem` 曾在 candidate completeness 为 `human_required` 时错误产生 complete/recommended 场景；当前工作树已把 completeness、specialized input gate 和 ScenarioSet formal membership 纳入求解硬门。该反例仍保留在历史审计段落中，不能再作为当前行为描述；新鲜真实运行仍需证明所有目标在 live provider 输入下保持同一 fail-closed 边界。

当前 optimizer 主要使用固定的三个 objective 且 dominance 按 maximize 方向比较，尚未形成按任务类型路由的 solver portfolio；facility-location、CP-SAT/MILP、道路图搜索、走廊和拓扑布局并未作为统一 SELECT 后端完整接入。SELECT HUMAN/auto-deferral 已有 `DeferralLedger` 和 scoped problem 路径，但仍需在 completeness 硬门可信后重新验收。生产 SELECT 已不再调用旧 `select_aggregate`，ScenarioSet→ApprovedExecutionInput→ExecutionPlan 的正式链已接通；任务专用 solver portfolio 和新真实空间执行仍保持 `PARTIAL`。
`scenario_solver.py` 仅保留 ScenarioOptimizer 使用的私有候选/关系搜索原语；旧的 `solve_scenario(max_scenarios=1)` 入口已删除，调用者统一通过 `ScenarioSet.recommended` 读取推荐方案。

## 7. EXECUTE, VALIDATE, RECONCILE and DELIVER

当前阶段入口分别位于：

- [`backend/app/workflow/stages/execute.py`](../../backend/app/workflow/stages/execute.py)；
- [`backend/app/workflow/stages/validate.py`](../../backend/app/workflow/stages/validate.py)；
- [`backend/app/workflow/stages/reconcile.py`](../../backend/app/workflow/stages/reconcile.py)；
- [`backend/app/workflow/stages/deliver.py`](../../backend/app/workflow/stages/deliver.py)。

已有 `ExecutionPlan`、`PlannedState`、`ValidationReport`、`ReconciliationReport` 和 `DeliveryManifest` typed contracts，也已定义 [`ApprovedExecutionInput`](../../backend/app/contracts/planning/approval.py) 与 [`ExecutionStaging`](../../backend/app/contracts/artifacts/execution_staging_contracts.py)。当前工作树已把所有正式 EXECUTE 入口收紧为强制 executable approval，并校验 ScenarioSet/member、scenario fingerprint 和完整 ExecutionPlan semantic digest；缺失、provisional、过期、替换或 context drift 会在加载执行 context、构图和启动 worker 之前失败。真实会话 `2e4095c8-1691-4b5b-8c7d-b9f820c75eaf` 证明了 approval 与 atomic commit 可以闭合，但其 `ParcelChangeSet.changes=0`，因此不能把“任务提交成功”写成“土地利用规划已生成”。

原子边界的组件实现也已收紧：staging ChangeSet 的 expected task IDs 必须非空、唯一并与全部成功结果完全相等；空集合、重复、遗漏、意外 task 或 deferred/failed result 都会 abort，正式 `ExecutionResult` 只有 `committed` 或 `aborted`，不会提升 partial PlannedState。`ValidationCertificate` 只接受已原子提交的结果，正式 reconcile 也只接受 passed 且 atomic 的证书。approval/digest、atomic/staging/validation 相关 focused/adjacent tests 以及 3 个 direct acceptance tests 已通过；新真实会话进一步观察到 committed → passed → reconcile → deliver。整体状态仍是 `PARTIAL`，原因已转为尚未完成 ScenarioSet 到 ExecutionPlan 的单一生产权威迁移、全部 worker materializer-only 收敛、独立验证 benchmark、进程恢复重放、混合子图验收和非现状复制的规划变更；已有组件测试和一次成功会话仍不能替代完整规划交付证明。

## 8. Artifact store, state and snapshot lineage

[`WorkflowState`](../../backend/app/workflow/state.py) 保存控制字段、`artifact_refs`、gate/interrupt/terminal refs 和运行诊断；artifact repository/runtime 位于 [`backend/app/infrastructure/artifacts/`](../../backend/app/infrastructure/artifacts/)。Pydantic `ArtifactRef` 位于 [`backend/app/contracts/artifacts/ref.py`](../../backend/app/contracts/artifacts/ref.py)。

运行时通过 LangGraph checkpoint 读取和恢复 state，`PlanningRuntimeService.resume_from_interrupt` 使用 `Command(resume=...)` 并校验 interrupt event。真实会话 `5461e8c4-ab1f-466c-bdfe-2ed3f795a6c9` 曾在 L1 `historical_culture` 因 `llm_typed_output_error` 停止，并留下 API 仍为 running 的 silent-END 反例。当前工作树已在 [`edges.py`](../../backend/app/workflow/conversation/edges.py)、root graph、runtime service 和 state reducer 中补齐 typed failure 的 HUMAN/terminal 路由及 stream-without-terminal 兜底；该结论目前只有 focused/runtime tests，仍需新真实会话验证。

## 9. Reproduced audit snapshot (2026-08-22)

| Evidence | Observed result | Meaning |
|---|---|---|
| Session `4ddc7cdb-d6c4-4976-963c-c8b484efebc8` | 110 claims → 93 interventions/targets；target compilation `needs_review` with 80 diagnostics | L3 claim 到 executable target 的准入层缺失 |
| Same session GROUND | 93 target domains；50 candidate domains/geometries；43 unresolved；0 constraints；0 relation satisfactions；46 `candidate_only`、4 `ambiguous`、0 `resolved` | 有候选数量不等于目标已接地，关系、约束和解析状态没有闭合 |
| Same session execution projection | 0 workers；93 deferred tasks；全部理由为 `scenario_hard_relation_blocked` | 规划图层没有进入真实物化，断点位于执行之前 |
| Same session commit | `approved_input_ref=null`；`atomic_commit_status=partial` | 审批和原子提交边界可被兼容路径绕开 |
| Session `5461e8c4-ab1f-466c-bdfe-2ed3f795a6c9` | L1 11/12 后 typed-output failure；API 仍显示 running | live failure 到 terminal state 的投影不完整 |
| Direct optimizer reproduction | `can_solve=false` / `human_required` 仍得到 complete + feasible + recommended | candidate completeness 目前不是权威求解门 |
| Focused regression suite | 23 tests passed；现状输入修复另有 4 tests passed | 组件测试覆盖已有契约，但没有覆盖上述真实运行反例 |

上述 session ID 是本地审计定位，不是可移植 fixture。后续修复必须将这些现象固化为最小回归测试，并重新创建真实会话；不得复用旧 artifacts 或把旧 session replay 当成新实现的验收。

### 9.1 Current-worktree closure status

上表记录的是修复前真实会话的审计事实，必须保留为回归输入；它不等同于当前工作树已经验证过的运行状态。截至 2026-08-22，当前工作树已完成但尚未经过新真实会话验收的修复如下：

- L1 typed-output failure 已统一为 `CONTEXT_OVERFLOW`、`OUTPUT_TRUNCATED`、`TOOL_CALL_MISSING`、`SCHEMA_INVALID`、`TIMEOUT`，并进入可恢复 HUMAN 或 typed terminal failure；只有 provider 明确返回 `finish_reason=length` 才允许一次有界扩容。MiniMax M2.7 的 structured path 使用 `reasoning_split=true`，缺失 tool call 时只接受完整且可验证的 L1 wrapper，再经过 Pydantic contract。49 个 focused tests 和一个脱敏真实 endpoint probe 已通过；旧 session `5461e8c4-ab1f-466c-bdfe-2ed3f795a6c9` 仍只表示修复前反例，不代表完整工作流已 live verified。
- L3 已加入 fail-closed executable-target admission、typed readiness、项目包压缩、claim/intervention 重算校验和 evidence requirement 同源校验；直接 intervention 与未完成 claim 不再具有正式执行权。旧 session 的 `110 → 93` 仍是修复前目标膨胀证据。
- GROUND/ScenarioOptimizer 已使 candidate-domain status、candidate completeness、objective direction、ordered recommendation priority、formal scenario membership 和 SolverCertificate 一致性成为正式硬门；`can_solve=false` 只允许 partial 诊断行，不能产生 feasible/Pareto/recommended/可执行证书。
- approval-bound、all-or-nothing EXECUTE 已完成代码级收紧和 focused/acceptance 回归：计划摘要冻结全部非 metadata 语义，缺失/过期/不匹配 approval 在 worker 前失败，任一任务不完整都会 abort；新会话已证明 `approved_input_ref`、16 个 formal targets 和 `atomic_commit_status=committed` 同时存在。仍需失败 worker、进程恢复 replay 和混合子图的真实验收，旧 session 中的 `approved_input_ref=null`、`atomic_commit_status=partial` 仅保留为回归负例。

因此，当前状态是“关键前置断点已有代码与组件回归证据，但完整生产链仍未验收”。只有新建真实会话、重新调用真实 provider、生成同一会话的批准/执行/验证/交付 artifact，并由 Playwright 看到规划图层，才能更新为 live verified。

## 9.2 新真实会话验收（2026-08-23）

会话 `2e4095c8-1691-4b5b-8c7d-b9f820c75eaf` 使用默认前端的一键完整输入重新运行：项目为“金田村村庄规划（2022—2035年）”，输入为 `frontend/public/demo/jintian_village.md`，`rag_enabled=false`。这次不是旧 artifact replay；后端重新执行了 DataCatalog、KG、TARGET_PROJECTION、GROUND、SELECT、EXECUTE、VALIDATE、RECONCILE 和 DELIVER。

观察到的闭环：

- DataCatalog 载入 25 个 sources、3 个 connections；KG 返回 36,236 triples；当前土地利用 660、规划土地利用 582、道路 current 131 / planned 170。RAG 保持关闭，RAG 计数为 0 是配置结果，不是检索失败。
- GROUND 首次发现 6 个 `spatial_reference_unresolved`，人工批准了精确的 6 个 target 延期；SELECT 随后发现 1 个互斥几何冲突并再次延期。累计 `deferral_summary.count=7`。延期 target 没有被伪造为可执行场景，后续 scoped problem 保留累计 deferred IDs。
- 17 个 grounded candidate domains 中最终形成 16 个 formal selected targets；ScenarioSet、ApprovedExecutionInput 和完整 ExecutionPlan digest 均存在。EXECUTE 的 `atomic_commit_status=committed`，但 `ParcelChangeSet.changes=0`；PlannedState 主要写入 9 个 facility points、1 个 candidate-backed parcel/point 选择、1 个 planned project 及其 overlay，不能把任务成功写成土地利用地类变更。
- VALIDATE 经过修复后的稳定 snapshot lineage 和 accessibility 规则后通过；ValidationCertificate 为 `passed`，`can_reconcile=true`。RECONCILE 和 DELIVER 均完成，session API 终态为 `completed / 100% / active_stage=deliver`。
- `/delivery` 明确返回 `delivery_status=partial`、`statutory_complete=false`，因此本次是“真实闭环的部分规划成果”，不是法定完整规划。DELIVER 返回 13 个 deliverables；地图快照包含 22 个真实图层、3,545 个现状要素、660 个 planned-landuse 要素和 122 个非基线 overlay/项目要素。
- 重要限制仍可见：`actual_change_count=0`、`changed_planned_feature_count=0`，planned landuse 当前是现状复制（`planned_is_current_copy=true`）；本次没有道路规划结论，road metric 仍为 131 且标记为“尚未产出道路结论”。因此图层已经能真实返回并可定位，但土地利用调整、道路网络和多目标空间关系尚未形成可信的规划变更。

Playwright 已在同一 session 检查到：空间成果页显示 `660 规划成果 · 已返回 DELIVER 规划图层`，规划筛选显示 `782 项已返回`，地图加载 9 个设施点和项目/分区 overlay；总览页同时显示 `部分成果（partial）` 警告。截图证据保存在 [`output/real-run-2e4095c8/screenshots/`](../../output/real-run-2e4095c8/screenshots/)。这证明“同一次真实运行的规划图层能到达前端”，但不改变 partial/statutory gate 的结论。

### 9.3 新真实会话失败记录（2026-08-23）

会话 `8aa67ba5-5eab-4939-8881-acf93b80c14e` 通过前端“一键加载完整示例”真实提交了 `jintian_village.md` 和 DataCatalog GIS，L1 12/12、L2 4/4，并进入 L3；但 `spatial_structure` 与 `disaster_prevention` 两个专题产生 `dimension_error`，人工“批准继续”后 provider 又返回 `No tool calls or function call found in response (mode: TOOLS)`，重试闸门随后以 `provider_retry_requires_explicit_retry` 终止。API 终态为 `failed / active_stage=deliver / delivery_status=diagnostic_only`，没有进入 TARGET_PROJECTION/SELECT/EXECUTE。

这次失败说明 provider/结构化输出边界仍会阻断真实完整运行；它不是几何修复的反例，也不能用来证明新 `site_footprint` materializer 已 live 通过。当前 live 证据应同时保留：旧会话证明闭环可达但土地利用仍是现状复制；新会话证明 provider 失败会形成明确 terminal failure，而不是静默 hanging。

### 9.4 当前工作树新增但待 live 验收的修复

- `subdivision.py` 不再把 OBB 遍历顺序的微小碎片当成目标地块；`subgeometry.py` 在面积超出容差时写入 `planning_area_insufficient` 并 fail-closed。
- `project_worker.py` 对单一 source BSM、有效候选几何和 resolved classification 的 `site_footprint` 生成 source-backed `ParcelChange(create + preserve remainder)`；protection/restoration/functional overlay 仍只写 overlay，不改变现状地类。
- `delivery_snapshot.py` 保留带几何的 `preserve/unchanged` remainder，并将其状态正确标为 `preserved`。相关 subgeometry、worker、delivery、approval、atomic 和 execute 切片的最新组合为 108 passed（2 个 PuLP deprecation warnings）；仍需 provider 正常的 fresh run 检查 `ParcelChangeSet` 和 `complete_planned_landuse`。

### 9.5 第二次完整真实会话（2026-08-23，修复后）

会话 `428f2e76-ef15-4dba-9afc-4ab9e07b90be` 使用同一前端“一键加载完整示例”重新提交 `jintian_village.md` 与 DataCatalog GIS，且 `rag_enabled=false`。这次 L1、L2、L3 均完成，没有重现上一会话的 provider `No tool calls` terminal failure；但它在 GROUND/SELECT 正确 fail-closed，最终没有形成批准执行输入。

- L1/L2/L3 事件序列完整到达：L1 `1→51`，L2 `52→186`，L3 `187→237`；最终 API 为 `completed / 100% / active_stage=deliver`，但运行期间 `/state` 曾在 L3 并发时短暂滞留为 L1/15%，说明状态投影比事件流滞后，前端实时进度仍需修复。
- `planning_program` 产生 145 claims、6 interventions；所有 intervention 都是 `spatial_intervention`，但没有对象级 BSM/feature/source refs。TARGET_PROJECTION 为 `needs_review`，6 个空间引用全部产生 `UNSUPPORTED_SPATIAL_REFERENCE`；根因是语义分类被显式关闭，村名/河道/道路等自然语言位置没有绑定到 GIS 对象。
- GROUND 只得到 5 个候选和 1 个未解析拓扑引用；候选主要是 corridor/parcel-set 粗粒度几何，3 个目标为 `candidate_only`，其余 resolved domain 的 members 仍为空；候选硬约束均未通过，其中河道走廊与 `farmland_protection` 重叠。
- SELECT 返回 8 个 `partial` 诊断场景，`feasible_scenario_ids=[]`、`pareto_scenario_ids=[]`、`recommended_scenario_id=""`。两次人工批准只允许流程继续记录缺口，不能创造候选、证书或批准输入；最终 `/delivery` 为 `diagnostic_only`，原因是 `approved_execution_input` 缺失，`deliverables=[]`，没有 EXECUTE/VALIDATE/RECONCILE 的本次规划物化。前端修复后保留后端 `completed` 状态和 diagnostic delivery，并显示“已完成但只有诊断结果”的阻断原因；截图见 [`diagnostic-only.png`](../../output/real-run-428f2e76/screenshots/diagnostic-only.png)。

这次运行把当前生产断点从“provider 工具调用失败”收敛为 **L3 → TARGET_PROJECTION → GROUND 的语义空间绑定与候选生产不足**：报告已经进入认知层，检索/本地 GIS 也可用，但自然语言目标尚未变成带对象、几何、关系、约束和可执行候选的 PlanningIntervention。RAG 关闭不是本次失败原因；向量召回也不能替代 GIS 对象绑定和任务专用候选生成。

### 9.6 第三次完整真实会话（2026-08-23，当前运行）

会话 `c69e8566-8ec6-4549-b10b-1289c6137720` 由前端“一键加载完整示例”真实提交，输入为 `jintian_village.md` 与 DataCatalog GIS，`rag_enabled=false`。L1、L2、L3 文本阶段均完成（L1 12/12、L2 4/4、L3 12/12），但 L3 聚合得到 25 个空间干预、143 个准入问题，主要是缺少来源事实/对象 lineage、类别化 typed parameters 或 project package。人工批准只允许流程继续做边界检查，不能补齐这些事实。

继续运行后，TARGET_PROJECTION 已生成带 artifact lineage 的结果；GROUND 仍以 `passed=false`、HUMAN review 停止，尚未进入 SELECT/EXECUTE，当前 `delivery_status=null`。因此这次运行再次证明：系统可以完成认知层和空间投影，但没有把不完整的自然语言目标伪装成可执行规划图层。RAG 关闭是配置状态，不是本次阻断原因。

当前工作树新增了候选可用性与邻接语义：`fully_available`、`partially_available`、`fully_unavailable`、`unknown` 与 `eligible/excluded_area_ha` 在子几何、SuitabilityCandidate、CandidateGeometry、ScenarioFeature、worker feature 和 PlannedState 间传递；大地块切割保留 `source_area_ha`、`planning_area_ha`、`coverage_ratio`、`subgeometry_operation` 与 remainder 诊断。EXECUTE 的 `WorkerTask`、`TaskExecutionResult`、`ParcelChange` 和 `PlannedParcel` 也冻结相同字段，避免执行阶段退化成“整块地块可用”。邻接 BSM 作为显式执行上下文和证据引用贯穿任务、变更集与 PlannedState；执行不会因为“相邻”自动合并或改写周围地块，只有后续 typed relation/worker task 明确要求时才允许联动处理。相关 focused/affected 组合当前为 108 passed，另有 2 个 PuLP deprecation warnings。

本次真实恢复还暴露出一个性能边界：旧运行进程在人工批准后长时间占用 CPU，健康接口也暂时无法响应；原因高度指向旧代码对全量禁止约束几何重复解析/union。当前工作树已改为先按源地块空间相交过滤约束再剪裁（代码级回归通过），但该修复尚未在这次已运行的进程中 live 验证；必须重启/刷新后重新创建会话，不能把这次长时间运行误判为前端静态资源问题或成功交付。

### 9.7 第四次完整真实会话（2026-08-23，候选/邻接修复后的 live 检查）

会话 `399bb7c6-33b9-4259-adf1-b18af846a9fe` 由 API 按前端“一键加载完整示例”的同一输入创建：完整 `jintian_village.md`、DataCatalog GIS、`rag_enabled=false`。这次 L1/L2/L3 均完成，随后按真实人工门只延期明确无候选的目标：GROUND 延期 2 个 `spatial_reference_unresolved` 目标，SELECT 再延期 2 个当前无可执行候选的目标。

该运行验证了候选边界实际生效：`suitability_surface` 产出 26 个候选，诊断区分了 `planning_area_insufficient`、坡度/永久基本农田硬约束和 `spatial_reference_unresolved`；没有把这些状态统一压成“整块地可用”。但当前 L3 目标集合在上述 deferral 后没有剩余可求解的 grounded target，`ScenarioSet` 明确返回 `status=infeasible`、`problem_kind=unknown`、`feasible_scenario_ids=[]`，原因是 `NO_EXECUTABLE_CANDIDATE_GEOMETRY` 与 `no grounded planning targets are available`。随后以“保留诊断、不生成规划图层”收束，最终 API 为 `completed / 100% / diagnostic_only`，`/delivery` 无 deliverables，`/map-layers` 返回 `no_planning_output`；没有 `ApprovedExecutionInput` 或 EXECUTE。

因此，这次 live 检查证明了“整块不可用/部分可用/大地块切割/邻接证据”的代码路径不会制造伪规划成果；同时也把距离合理规划产出的真正剩余问题收敛为：L3 必须至少稳定产生一个带真实项目包、typed spatial parameters、对象级 source refs 和可执行候选的窄切片目标，且候选必须能通过硬约束后再进入 ScenarioOptimizer。当前不能把人工延期当成规划选择，也不能把 `suitability_surface` 的 26 个 recall 候选冒充正式规划图层。

### 9.8 第五次完整真实会话（2026-08-23，窄切片正式执行与交付）

会话 `51adbc48-cc95-4525-a8f8-692942bae45c` 使用完整 `jintian_village.md`、DataCatalog GIS、`rag_enabled=false`，并在任务输入中显式限定一个源地块 BSM `441426211000049280` 和 300 平方米的窄切片。L3 的完整报告/Claims 包被严格解析，GROUND 仅延期 1 个没有候选的拓扑目标；其余窄切片目标形成正式 `ScenarioSet`、`ApprovedExecutionInput`，EXECUTE 原子提交成功，VALIDATE 的最终关系证书 `passed=true`，随后完成 RECONCILE/DELIVER。最终 API 为 `completed / 100% / deliver`，但 `delivery_status=partial`、`statutory_complete=false`，原因是仍有 1 个明确延期目标；这不是完整村庄法定规划完成。

这次运行首次给出可核查的 source-backed 子地块结果：

- 源 BSM `441426211000049280` 的候选为 `candidate:5d166dbeeb0a9da50849c18d`，候选 `availability_status=fully_available`、`excluded_area_ha=0`；因此 `coverage_ratio=0.38407669` 表示只分配了源地块的一部分，不表示源地块有 61.6% 因约束不可用。
- EXECUTE 生成 footprint `0.028859267262 ha`（约 288.6 平方米）并保留同一源地块 remainder `0.046280068149 ha`（约 462.8 平方米），两者均保留 `source_bsms`、candidate/feature/target/scenario lineage 和 `coverage_ratio`；没有把大地块恢复成整块 BSM，也没有删除剩余面。
- 邻接 BSM `441426211000050003` 以 `bundle:landuse_current:441426211000049280:adjacent:441426211000050003` 进入候选、ChangeSet 和 PlannedState。它只是显式上下文，未被自动合并或改写；若未来需要联动，必须由 typed adjacency/topology relation 和额外 worker task 在 SELECT/approval 中冻结周围地块成员与几何。
- 交付快照的 `current_landuse=660`、`complete_planned_landuse=661`、`planned_changes=1`，非现状规划特征数为 111，几何有效性和最终关系验证均通过。此次 live artifact 在导出属性中仍暴露了源 `area_sqm`，工作树随后已把 candidate、availability、coverage、子几何、邻接和 `new_area_ha` 投影到 complete planned GeoJSON；23 个交付回归测试通过，需下一次 fresh run/Playwright 检查确认前端展示这些新增属性。

该运行把“几何已能物化”与“合理规划已完成”明确分开：当前窄切片的选址、切割、余量保留、邻接证据和证书闭环已成立；全村仍有 L3 目标膨胀、未解析目标和 coverage/network/topology 专用求解器缺口。另发现候选 `eligible_area_ha=0.076043773658 ha` 与物化几何的 `source_area_ha=0.075139335412 ha` 存在约 9 平方米差异，当前 ChangeSet 只对物化源几何做守恒；这需要在正式放大到多地块前统一面积 CRS/来源口径。随后已收紧两处边界：Suitability 将 `eligible/excluded` 重新归一为源地块面积分割，EXECUTE 在获批 candidate 已携带面积时保持其冻结预算、缺失时才用 WKT+metric CRS 推导；有邻接要求的 site footprint 还必须同时具备邻接 BSM、邻接证据和 typed relation ref，否则延期且不改写周围地块。该修复已由 26 个子几何/执行/交付测试覆盖。

### 9.9 第六次真实复跑与最新范围修复（2026-08-24）

- 会话 `da690155-0488-4558-b9ab-28ad7c358562` 使用带窄切片 marker 的输入；L1/L2/L3/GROUND 均可达，但修复前 SELECT 在全量 suitability 阶段产生 `select_validationerror`，最终为 `diagnostic_only`。这不是可执行规划图层证据。
- 会话 `c4292619-ae7f-47fb-8576-96e8a8c55bb0` 是重启后的真实复跑，但创建请求没有携带 typed narrow-slice marker，GROUND 记录 13 个候选后，SELECT 对 7 个普通目标严格返回 `scenario_or_approval_incomplete` HUMAN。该结果符合 fail-closed 规则，不能通过人工批准伪造 ScenarioSet 或执行输入。
- 最新 `select.py` 已把 marker 派生的 demo target scope 前移到 suitability 输入，只缩减 SELECT 计算，不修改完整 GROUND artifact；因此下一场必须带精确 marker 的 fresh run 才能验证最新 GeoJSON 的 footprint/remainder 属性和前端显示。

### 9.10 第七次真实复跑：最新代码已形成同次闭环（2026-08-24）

- 会话 `4957576d-ed98-4847-a026-361f6c739dbe` 使用完整 `jintian_village.md`、DataCatalog GIS、`rag_enabled=false` 和精确窄切片 marker。L3、GROUND、SELECT、EXECUTE、VALIDATE、RECONCILE、DELIVER 均在同一次持久会话中完成；终态为 `completed / 100% / deliver`，`delivery_status=complete`、`statutory_complete=true`，最终关系验证与 `ValidationCertificate` 均为通过。
- `ScenarioSet` 为 `feasible`，唯一场景同时是 Pareto/recommended；`ApprovedExecutionInput.approval_status=auto`，仅绑定该正式 scenario/member 和 candidate。EXECUTE 产生 1 个 worker task，未重新选址，ChangeSet 原子提交成功。
- 源 BSM `441426211000049280` 的交付变更明确分为两条：`footprint=create` 约 `288.59 m²`，以及同源 `remainder=preserve` 约 `471.85 m²`（源面积约 `760.44 m²`）。因此“整块不可用”与“仅分配部分面积”不再共用一个布尔结论：本次 `availability_status=fully_available` 表示源地块可用，`coverage_ratio=0.3795` 表示本次只分配了子几何，余量保留；若是 `partially_available`，必须另有 excluded 几何/面积；`fully_unavailable` 不得进入 SELECT/EXECUTE。
- 邻接 BSM `441426211000050003` 只作为 `adjacent_parcel_bsms` 和 adjacency evidence context 出现在 ChangeSet/PlannedState，未被自动修改。只有 typed adjacency/topology relation、明确的邻地 worker task 和获批成员集合同时存在时，执行才允许联动周围地块。
- `/delivery` 的 planning output 为 `planned_changes=1`、`current_landuse=660`、`complete_planned_landuse=661`、`non_baseline_feature_count=111`；交付快照实际输出 12 个图层/1968 个要素，`planned_changes` 图层为 1 个非空 GeoJSON feature。前端 `/drawings` 同一 session 显示 `completed`、规划筛选 7 图层、规划地块 661，分类面板诚实显示功能分区/既有规划路/本轮结论为 0，没有把窄切片冒充全村道路或分区规划。
- 这次复跑修复了前一次 `eligible_area_ha > source_area_ha` 的 SELECT 校验错误：refined candidate 优先使用精确 suitability BSM 面积并重新归一 `eligible/excluded` 分割；因此 GROUND 的粗粒度合并面积不会再覆盖候选的精确源面积。截图保存在 [`planning-layers-latest.png`](../../output/real-run-4957576d/screenshots/planning-layers-latest.png)。

这次证明的是“最新代码下单源地块窄切片的真实闭环和前端交付属性已经成立”，不是“全村合理规划已经完成”。共享多地块资源池/容量耦合的代码契约随后已接入，但全村仍缺少该路径的真实多地块候选生成与混合执行验收，以及 coverage、network、topology 专用 solver backend 和 L3 对完整目标的稳定 typed admission；这些缺口必须继续保持 `PARTIAL/GAP`，不能由一次单地块成功运行掩盖。

这两次复跑同时说明当前墙钟时间主要消耗在 L3 多维 provider 生成（完整输入约 10–20 分钟，随后 GROUND/SELECT 通常约 1–3 分钟，人工门视情况增加）；它是运行效率问题，不是把候选或邻地错误合并的理由。

### 9.11 多地块资源池与共享容量（2026-08-24，代码级已接入，live 尚未闭合）

针对“大地块切割后多个目标可能争用同一源地块”的断点，当前工作树已把源 BSM 从单个候选属性提升为独立的 `ParcelResourcePool`：每个资源记录 source/eligible 面积、可用性状态、几何/证据引用、候选成员和邻接上下文，按 BSM 唯一化。`GroundedPlanningProblem` 自动保守派生资源池，SELECT 的 refined candidate 会用精确 suitability 面积重算资源池，并将 pool/resource/geometry/source/evidence/adjacency refs 纳入 `SolverProblemView` 和 replay 输入。候选状态混杂（例如同一 BSM 同时出现 fully/partially available）会被标为 `unknown`，不会被压成一个全地块可用结论。

`default_solver_registry()` 已注册 `parcel_assignment_bounded`。它只接受 `parcel_assignment` 且输入完整的问题，组合选择时强制：候选必须绑定单一 source BSM、有正的获批 planning area、子几何有效且同源候选不重叠；同一 BSM 的所有获批面积不得超过资源 eligible 面积。超容量返回 infeasible 与稳定诊断，不会降级成普通 single-choice；容量足够且候选不重叠时，ScenarioSet 可同时选择多个目标的成员。该路径由 `test_solver_portfolio_slice1.py` 的容量超限/双成员/unknown 与混合可用性反例及 combined `107 passed` 覆盖。

这仍不是“全村多地块规划已完成”的证据：当前只有 backend 契约和确定性 fixture 证明，尚未在真实 `jintian_village.md + DataCatalog GIS` 会话中同时生成多个共享 BSM 候选、形成一个 approved ScenarioSet 并由混合 worker 原子物化。周围地块也仍只在有 typed adjacency/topology relation、邻地成员/几何、evidence refs 和额外获批 worker task 时才能联动；仅因相邻不会自动写入邻地。

### 9.12 共享 BSM 真实复跑的最新断点与修复（2026-08-24）

真实会话 `c3ada43b-0486-400a-a1f7-2e153f02faa5` 在 L3 retry 后到达 GROUND/SELECT，确认两个窄切片 claim 已经由 producer 保留 `affected_parcel_refs=[441426211000049280]`，`IntentGraph.solver_kind=parcel_assignment`，而不是旧的 `auto`。但旧的资源汇总把同一 BSM 的粗粒度 `bundle_extent` 回退候选与精确 `fully_available` 子几何混在一起，形成 `availability_status=unknown`，最终按 `SOLVER_INPUT_INCOMPLETE` 正确停在 SELECT HUMAN；这证明失败点是候选作用域/资源聚合，而非 GIS 地块不存在。

当前修复已收敛为三条边界：

- `ParcelResourcePool` 只从当前 SELECT candidate domain 的成员派生；已存在精确、source-backed、通过硬约束的候选时，粗粒度 recall-only `bundle_extent` 不再污染资源可用性；若没有任何可执行成员，仍保留 `unknown` 并 fail-closed；
- `partially_available` 的单源或共享 BSM 在 EXECUTE 分别保留 eligible remainder 与 excluded region，不把“部分可用”错误写成整块不可用，也不把排除面吞入普通 remainder；
- 相邻 BSM 仍仅作为 `adjacent_parcel_bsms`/evidence context。只有 typed adjacency/topology relation、明确的邻地 worker task、邻地几何和同一 approved task set 才能联动写入周围地块。

修复后的 focused regression 为 `derive_parcel_resource_pool` 粗候选污染反例、共享 eligible-parent 切割、共享 partial remainder/excluded、邻地不变更和证书闭环；截至本次记录相关切片均通过。会话 `92c33189-329c-4d44-89d0-80abd6b5dbe5` 已验证最新 producer/编译器输入，但因服务重启前创建的旧 checkpoint 仍持有旧资源池，不能把它宣称为修复后的正向 SELECT/EXECUTE 证据；需要下一次 fresh run 才能闭合真实多地块链路。

当前 fresh run `1b466731-f45d-4e77-850d-145b736d4838` 已完成 L1/L2 并进入 L3，尚未到 GROUND/SELECT，因此不计为多地块正向证据。该运行同时暴露出状态投影滞后：日志事件已进入 L3，而 `/state` 的 `active_stage/progress` 仍可能暂时显示 L1/15%；排查时必须以事件流和持久 artifact 为准。L3 中缺失 typed parameters 的 claim 会被 strict contract quarantine，不能进入空间候选。

随后该会话确实进入了 `parcel_assignment_bounded`，生成 2 个同源 BSM 子候选并通过容量/选择校验，但 EXECUTE 以 `EXECUTE_APPROVED_CANDIDATE_GEOMETRY_MISMATCH` 正确停止：EXECUTE 重建 catalog 时把 suitability 的原始 parent geometry 覆盖了 SELECT 已持久化的切割 geometry。修复已收敛为：若 `scoped_grounding_problem` 已含 candidate ID，候选目录重建不得覆盖该成员，只能补充缺失候选；相关回归已通过，v5 fresh run 正在验证该闭环。

### 9.13 共享源地块执行调度修复（2026-08-24）

v6 fresh run 已把 SELECT 的两个同源子候选送入 EXECUTE，但 VALIDATE 发现 4 个变更中的 footprint/remainder 重叠和面积守恒漂移。根因不是候选切割算法，而是 `route_prepare._task_level_execution_node` 在调用 project worker 前把每个 task 强制过滤成 singleton，worker 看不到同一 source BSM 的兄弟 footprint，因而分别生成两个 remainder。当前修复将同一批次、同一 source BSM、且 `materialization_role=site_footprint` 的任务组成一个明确 isolation group；其他任务仍保持单任务隔离。没有放宽 VALIDATE，也没有把邻地变成隐式执行成员。

修复后的 focused 回归覆盖：持久化 partitioned candidate 在 EXECUTE 不被 raw suitability parent 覆盖；同源多 footprint 只生成一个 remainder；部分可用地块分别保留 eligible remainder 与 excluded region；邻接地块仅作为上下文时不被修改；调度器把共享 source BSM 的任务一起交给 worker；未知源地块不会在 EXECUTE 被当成 fully available；fully_unavailable 的诊断几何会归一为零 planning area；混合 site/facility worker 仍保持任务隔离并在 merge 阶段汇合；RECONCILE 绑定测试通过。代码切片为 `18 passed`，选定扩展组合为 `97 passed`（此前更宽组合 `99 passed`）；fresh v7 会话 `42d2b51b-9c5b-44d6-951b-2acbd528432b` 已完成同一链路的 live 验证。

v7 实际结果：GROUND 形成 17 个 typed candidate domains、370 个候选；人工只延期 2 个无候选空间引用，SELECT 形成 1 个正式 ScenarioSet，EXECUTE 路由 2 个同源 `site_area` task 并由一个 worker group 写入 3 个变更（2 个 footprint + 1 个统一 remainder）。EXECUTE review 0 violations，VALIDATE/RECONCILE 通过，DeliveryGate PASS；交付为 `partial` 而非法定完整规划，`planned_changes` 图层有 2 个实际新增 footprint，另有同源 preserve remainder，邻地没有被修改。

这条边界的含义是：`fully_unavailable` 不进入正式候选；`partially_available` 必须携带 eligible/excluded 两套几何与面积；`fully_available` 也可能只分配 footprint，余量必须 preserve；同一大地块的多个获批 footprint 必须在同一资源池内不重叠、面积不超容量，并由一个 worker group 生成统一 remainder。邻地只有在 typed adjacency/topology relation、邻地几何/evidence、明确额外 task 和同一 approved task set 齐备时才允许联动。

另外，RECONCILE stage 已改为关键字传递 `ParcelChangeSet`、`PlannedState` 和意图，避免旧式位置参数把执行结果错位到 quantitative-drift 检查。该修复不放宽证书门，只恢复同一 run-root 的正确对象绑定。

### 9.14 最新真实复跑：面积守恒与严格候选门（2026-08-24）

会话 `3b4bfaf3-b7d1-49f1-8369-e67bd2d6f0d3` 是一次真实的窄切片复跑：SELECT/EXECUTE 产生了两个同源 footprint 和一个 `preserve` remainder，`ValidationCertificate` 已通过，但 RECONCILE 把 remainder 也计入目标数量，错误报告了 `0.0760437737 ha` 对 `0.022 ha` 的 quantitative drift。这个结果不是规划失败，而是验证指标把“保留的源地块余量”误当成新增规划量。

当前 `check_quantitative_drift` 已明确排除 `operation=preserve` 的 PlannedParcel；remainder 仍保留在 `ParcelChangeSet`、`PlannedState` 和交付图层中，用于面积守恒和 lineage，不再污染目标面积检查。新增回归覆盖“两个 create + 一个 preserve remainder”的正确计量，相关执行/子几何/证书组合为 `104 passed`。

会话 `b1dda639-2c6e-49ef-a47a-6970b2a53f11` 则证明了另一条必须保留的 fail-closed 边界：完整现状报告和 DataCatalog 成功进入 L1/L2/L3，GROUND 生成 4 个 typed domains、97 个候选，但报告中的“挂牌保护”只形成 `protection_overlay`、`availability_status=unknown` 的 recall 候选，缺少可执行 footprint/eligible area。SELECT 因 `candidate_only`、`recommended_scenario_missing` 和 `scenario_not_feasible_member` 停止，未生成 approval 或 EXECUTE。该会话没有把保护线错误地当成可建设地块，也没有把整块 BSM 当作可用；它暴露的是“普通报告目标尚未被 producer 转换为 typed、source-backed 执行目标”，不是 RAG 关闭或 DataCatalog 缺失。

随后创建的 fresh session `a77f2eb8-46d9-4452-80b4-a31dc967022d` 使用同一完整报告，并在任务描述中明确加入两个同源 BSM marker（100 m²、120 m²）；其最终正向结果见 9.15。只有 candidate domain 同时出现稳定 candidate ID、source BSM、planning/eligible/excluded area 和切割 WKT 时，才能作为多目标共享容量的 live 正证据；若 L3/provider 超时或仍返回无 typed candidate，则只记为诊断性失败。

### 9.15 第八次真实复跑：共享源地块双切片闭合（2026-08-24）

会话 `a77f2eb8-46d9-4452-80b4-a31dc967022d` 最终在同一持久会话中完成 L1/L2/L3 → TARGET_PROJECTION → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER。输入为完整 `jintian_village.md`、DataCatalog GIS、`rag_enabled=false`，并明确给出同一源 BSM `441426211000049280` 的 100 m² 与 120 m² 两个窄切片目标。

- GROUND 生成 9 个 typed candidate domains、78 个候选；6 个无候选的普通目标被显式延期。两个 marker 目标均有稳定 candidate ID、源 BSM、切割 WKT、`eligible_area_ha=0.076043773658`、`planning_area_ha` 与 `availability_status=fully_available`，进入 `parcel_assignment_bounded`；ScenarioSet 为唯一 feasible/recommended 场景，`ApprovedExecutionInput` 和 `ValidationCertificate` 均闭合。
- EXECUTE 只提交两个目标 footprint：约 `0.0099627108 ha`（99.63 m²）与 `0.0119648860 ha`（119.65 m²），另保留一个统一 `shared:441426211000049280:remainder` 约 `0.0541161769 ha`。同源候选不重叠、总面积不超 eligible pool，保留余量不作为新增规划量。
- 邻接 BSM `441426211000050003` 仅出现在 `adjacent_parcel_bsms` 与 adjacency evidence context；ChangeSet/PlannedState 没有邻地 mutation。没有 typed adjacency/topology relation + 邻地 worker task + 同一批准成员集合时，执行不会联动周围地块。
- 该 run 首次现场触发了“延期目标面积不能污染当前批次”的真实反例：RECONCILE 原先把延期的 35 ha 区域与本批次 0.022 ha 相加，产生 `35.022 ha` 预期。`check_quantitative_drift` 现按非 preserve 物化 parcel 的 `project_ref/target_id/intervention_id` 只匹配当前批准目标；新服务重启后重新执行，RECONCILE/DeliveryGate 通过，终态为 `completed / delivery_status=partial / statutory_complete=false`。这代表部分交付而非法定完整村庄规划。
- `/delivery` 返回 `planned_changes=2`、`current_landuse=660`、`complete_planned_landuse=662`，前端同一 session 的 Playwright DOM 显示 L1/L2/L3 completed、规划筛选 7 图层、规划成果 662、道路成果 131 且明确“尚未产出道路结论”；没有把延期目标或现状复制误报为本批次新增规划。截图见 [`planning-layers-planning-view.png`](../../output/real-run-a77f2eb8-46d9-4452-80b4-a31dc967022d/screenshots/planning-layers-planning-view.png)。

本次 live 证据把“共享资源池→双候选切割→统一 remainder→原子执行→证书→部分交付”闭合；但它仍只覆盖两个同源 site-area 目标。报告中其他设施、道路、分区和生态目标被延期或保持诊断，不能据此宣布 coverage/network/topology 或全村法定规划完成。另修正后的定量检查已由 focused/affected 组合 `21` 个本地回归及此前 `104 passed` 组合覆盖。

### 9.16 第九次真实复跑：一键完整示例的单目标正式交付（2026-08-24）

会话 `3e1b75ca-b53b-4e75-bdbd-ddc5aa5ba345` 通过前端“L3 详细规划 → 一键加载完整示例”创建，使用完整 `jintian_village.md`、DataCatalog GIS、`rag_enabled=false`，并在人工审查面点击“批准继续”。同一会话实际完成 `L1 12/12 → L2 4/4 → L3 12/12 → TARGET_PROJECTION → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER`；终态 API 为 `completed / 100% / deliver`、`delivery_status=complete`、`statutory_complete=true`。

- L3 产出的 15 个空间/项目输入中，11 个在 TARGET_PROJECTION/GROUND 因缺少可执行空间引用被延期或诊断；GROUND 最终有 8 个 typed domains / 247 个候选，SELECT 只批准 1 个正式候选，并没有把报告里的普通设施/道路目标自动扩张成执行任务。
- EXECUTE 只路由 1 个 `site_area` task，`ExecutionReview=PASS`，`ParcelChangeSet` 原子写入 2 个变更：一个约 `0.0288592673 ha` 的获批 footprint，以及同源约 `0.0471845065 ha` 的 `preserve` remainder。源 BSM `441426211000049280` 的 `availability_status=fully_available`、`eligible_area_ha=0.0760437737 ha`、`excluded_area_ha=0`；`coverage_ratio=0.3795` 只表示本次切出子几何，不表示整块不可用。邻接 BSM `441426211000050003` 及 adjacency evidence 进入属性，但没有邻地 mutation。
- `/delivery` 返回 `planned_changes=1`、`current_landuse=660`、`complete_planned_landuse=661`、`non_baseline_feature_count=111`，`ValidationCertificate=passed`，最终关系验证通过。前端同一 session 的规划筛选显示 7 个规划图层、661 个规划成果、131 条道路现状且明确“尚未产出道路结论”；截图见 [`planning-layers.png`](../../output/real-run-3e1b75ca-b53b-4e75-bdbd-ddc5aa5ba345/screenshots/planning-layers.png)。
- 该复跑确认“一键完整示例”现在能生成真实完整会话和交付，而不是只填摘要；同时也确认“法定完整”只代表本次批准任务集合的证书闭合，并不等于全村所有 L3 目标都有专用求解器。`coverage/network/topology` 仍没有正式 backend，普通目标仍会被明确 deferred/diagnostic。

本次运行结合新增的执行边界回归（`61 passed`）确认：生产 EXECUTE 图只保留 8 个可达节点，worker 由 `task_scheduler` 调度，旧的 per-worker graph wrapper 已从生产导出面移除；zone/facility 对 `fully_unavailable`、`partially_available`、`unknown` 的候选可用性重新复核，避免只凭 `role + WKT` 误把整块不可用地块写入规划层。大地块切片、统一 remainder 与邻地 context-only 规则继续由 v11 双切片 live 证据覆盖。

随后补上的候选契约边界要求 `planning_area_ha <= eligible_area_ha <= source_area_ha`（字段存在时），并拒绝超过源面积的 planning area；相关 availability/shared-parcel/delivery 回归为 `110 passed`。这保证“部分可用”不会因面积字段异常被当作整块可用或超容量资源，且不改变邻地仅上下文、显式联动才可写入的执行边界。

### 9.17 网络关系后端与生产上下文接线（2026-08-24，代码级，live 尚未验收）

前述“coverage/network 没有 backend”的判断需要细化：当前工作树已注册 `network_relation_bounded`，用于已具备 typed `connect/access/serve` factor、`NetworkGraphSnapshot`（以及 coverage 所需 `DemandSnapshot`）的问题；它复用专用网络关系评估，不把关系退化成 single-choice。`build_solver_problem_view` 会把参数中的 `network_ref`/`demand_ref` 纳入 required/snapshot refs，输入不全时保持 `unknown/diagnostic-only`。网络因子在 ScenarioSet 追加 cut/finding 后会重新计算 scenario fingerprint，避免后置网络诊断造成证书成员失配。

生产 `PlanningContext` 现在从 DataCatalog 权威 `roads_current` 构建唯一的 `network:road:current` 快照，带稳定 fingerprint，并在 SELECT/VALIDATE 的 `RelationEvaluationContext` 中可见；它只从显式命名的 `demand_points`/`population_demand` 图层、且仅在点具备 `demand_id`、`demand_value`、`demand_unit` 时构建 DemandSnapshot；普通注记、人口表和设施数量不会被猜成需求点。道路 typed claim 的 `road_parameters.connects` 已由 TARGET_PROJECTION 编译为 `typed_road_endpoint` relation，GROUND 仅在当前道路快照存在时绑定 `ConnectParameters`；从 typed claim→factor→`network_path`→`network_relation_bounded` 的闭环回归已通过。context/portfolio/network/demand 回归切片为 `75 passed`，道路闭环新增 3 个测试通过。这关闭了“后端虽存在但生产 context 永远空”的代码断点，但还没有证明真实 L3 会话稳定产生足够的 typed endpoints、可执行道路候选或真实需求图层。因而真实会话仍可能没有 network/coverage target，前端仍应显示“尚未产出道路结论”，topology 仍未完成，整体状态继续为 `PARTIAL`。

同日 fresh Playwright 会话 `028c3299-3fd0-4b79-9a28-88e811d68c6b` 暴露了一个与空间链无关、但会阻断真实流程的 HUMAN 动作映射问题：`project_bank` 的结构化 provider 输出返回 `SCHEMA_INVALID (InstructorRetryException)` 后端已正确发布 `transient_llm_failure`，前端却把所有 HUMAN 请求都发成 `approve`，最终进入 `failed / diagnostic_only`，而不是重试该维度。前端 `usePlanningActions.approve` 现按 `request_type` 对 `transient_llm_failure/provider_failure/llm_retry` 发送 `retry`，普通层闸门仍发送 `approve`；type-check 已通过。该修复尚需一次 fresh provider-failure→retry→继续空间链的 live 回归，不能把这次失败会话算作规划产出证据。

### 9.18 第九次真实复跑：完整示例交付与前端规划图层（2026-08-24）

会话 `e657e7d5-5fa2-4119-b236-0266dcfad006` 由前端一键完整输入真实启动，使用 `jintian_village.md`、DataCatalog GIS、`rag_enabled=false`。L1/L2/L3 均完成（12/12、4/4、12/12），在 L3 审查门点击“批准继续”后，同一次会话完成 TARGET_PROJECTION、GROUND、SELECT、EXECUTE、VALIDATE、RECONCILE 和 DELIVER。终态为 `completed / 100% / active_stage=deliver / delivery_status=complete / statutory_complete=true`。

- GROUND 形成 20 个输入、401 个候选域成员；9 个空间输入因缺少可执行事实保持 deferred/diagnostic，SELECT 只生成 1 个 formal scenario，未将普通道路、覆盖或分区目标降级成单设施选择。
- EXECUTE 只提交 1 个 `site_area` footprint，源 BSM `441426211000049280` 的源面积约 `0.0760437737 ha`；物化 footprint 约 `0.0288592673 ha`，同源 `preserve` remainder 约 `0.0471845065 ha`。`fully_available` 表示源地块在约束下可用，`coverage_ratio=0.3795` 只表示本次分配了子几何；它不是“整块不可用”或“剩余面积被排除”。
- `adjacent_parcel_bsms=[441426211000050003]` 及 adjacency evidence 进入 candidate/ChangeSet/PlannedState，但邻地没有写入变更。只有 typed adjacency/topology relation、邻地几何/evidence、明确 worker task 和同一 approved task set 同时存在时，执行才可联动周围地块。
- `/delivery` 的 planning output 为 `planned_changes=1`、`current_landuse=660`、`complete_planned_landuse=661`、`non_baseline_feature_count=111`；交付快照为 12 个图层、1968 个要素，ValidationCertificate 和最终关系验证均通过。前端空间成果页在同一 session 显示 19 个真实图层、661 个规划成果；切换“规划”后显示 7 个图层，且明确显示道路成果 131 条但“尚未产出道路结论”。截图见 [`planning-layers.png`](../../output/real-run-e657e7d5-5fa2-4119-b236-0266dcfad006/screenshots/planning-layers.png)。
- 当前道路计数仍有口径差异：DELIVER `map-layers` 的 `current_road` 图层为 301 个要素，而工作台道路指标显示 131（来自当前规划工作区道路子集）。两者都不能被解释为规划道路结论；正式 road backend 验收前必须统一 canonical road snapshot/count，避免前端把不同层级的现状数据混在一个指标里。
- 前端完成提示同时展示空间链各阶段累计 `25` 条 deferred/diagnostic 记录（TARGET_PROJECTION 16 + GROUND 9；阶段间可能重复），因此明确写成“本批次完成”，不把它解释为全村 25 个独立目标均未决或全村规划已完成。
- 该运行仍不是全村道路/覆盖/拓扑规划：RAG 为关闭配置，L1 页面明确显示 `fact 0 / RAG 0`，规划图层来自本地 DataCatalog、typed candidate 与同次执行证书，而不是 dense recall。

本次真实复跑还验证了前端 HUMAN provider 动作修复未破坏正常闸门：正常层审查仍发送 `approve`，provider transient failure 才发送 `retry`。同时修复了 `/state` 只读取旧 workflow checkpoint 的投影滞后：SessionProjectionService 现在从最新带 `layer`/`stage` 的 durable run event 推导 phase/active_stage，终态仍以 delivery manifest 优先；新增回归确保 L3 事件不会继续显示为 L1/15%。

### 9.19 道路图层语义收敛与部分候选执行边界（2026-08-24）

对 9.18 暴露的道路计数差异完成代码级修复：`VillageBundle.to_geojson_dict` 与 `SessionDataSnapshot` 现在把 `roads_current` 写入 `road_geojson`，把 `roads_planned` 单独写入 `planned_road_geojson`。DELIVER 快照分类器已将后者归入 planned overlay，因此规划/参考道路不会再被标记成 `current_road`；回归验证现状 1 条与规划 2 条分别落入各自集合，delivery snapshot 也不会把规划道路放进 current layers。下一次 fresh session 需要重新生成快照并用 Playwright 对账，旧 e657 artifact 不会被就地改写。

候选执行边界也进一步收紧：当 `availability_status=partially_available` 且候选携带 `eligible_geometry_wkt` 时，EXECUTE 必须验证获批 footprint 完全位于冻结的 eligible parent extent；越界候选 fail-closed，不会通过“与源地块相交”被截回可用区。已覆盖“部分可用越界 footprint”负例；既有语义保持不变：`fully_unavailable`/`unknown` 不得写入 source-backed site footprint，部分可用要分别保留 eligible remainder 与 excluded region，大地块的多个获批子候选按同一 BSM 资源池做容量/不重叠校验并只生成一个统一 remainder，邻地仍仅为上下文，除非 typed relation + 邻地几何/evidence + 明确 worker task 同时获批。

本轮相关回归为 `60 passed`；road worker 旧的 stage-26/诊断层宽松预期仍有 3 个 affected failures，它们与新的“EXECUTE 只接受 approved route geometry”契约冲突，不能作为道路规划正向证据。真实道路 candidate/route backend 及 fresh live 对账仍未完成，整体仍为 `PARTIAL`。

### 9.20 L1/L3 双投影结构化收敛（2026-08-24）

本轮把“有界 LLM loop”降回实现手段，收敛的是 L1/L3 的语义契约：

- L1 只读取当前 session 的持久化输入和显式上传；会话上下文不再扫描仓库 `docs/`，旧 `load_planning_text`/`list_available_documents` 死扫描入口已删除。`build_l1_source_index` 对任意叙述、OCR、清单或混合输入只生成带 digest、source ref、行/字符范围的 generic `source_segments`，不再按表头、Markdown 或 HTML 预解析台账；`current_assets`/`demands` 只能由 L1 typed draft 引用并核验 source segment 后物化。
- L1 每个维度保留 `report_body` 和结构化输出，但它们来自有界的独立投影调用：先执行 `L1ObservationPassOutput` 的 observe，再按需执行 `L1RegisterPassOutput` 的登记/修订和 source 校验，最后用只读已验证材料的 `L1ReportOutput` 生成正文。`report_body` 仍写入 ReportStore、step report、SSE 和前端报告视图；结构化通道输出 `L1ObservationDraft`、`L1InputRegister`、`L1Fact`/`L1LocationFact`、约束/冲突/不确定性和 pass cursor。`current_asset`、`demand`、`metric`、`constraint`、`relation` 等 observation kind 已分开，未确认 observation 不进入权威 fact records。即使没有表格行，source segments 也会持久化，避免把“没有固定表头”误报成“没有输入”。
- L3 接收 typed L1 facts、L2 strategy、任务约束、检索证据和维度语义契约，先用 `L3ClaimOutput` 生成 claims，再经过结构/语义修订和 deterministic admission，最后用 `L3ReportOutput` 只根据已验证 claims 生成 `report_body`。通过 `PlanningClaimSet` 输出 project package、`planning_role`、typed object parameters、objective/constraint refs、semantic `relations`、`shared_resource_refs`/`network_refs`/`required_input_refs` 和 `grounding_requirements`；坐标、WKT、GeoJSON、BSM、候选成员和最终选择仍被契约拒绝。只有带 project package、typed parameters、locator/evidence lineage 且 `planning_role=spatial_intervention` 的 claim 才进入 deterministic admission。
- claim adapter 将上述语义元数据原样传递到 TARGET_PROJECTION/GROUND；L3/Project Bank 不再从原始 Markdown 重新解析位置或台账。没有 typed relation、demand point、network snapshot、parcel membership 或 topology 输入时，目标保持 diagnostic/deferred，不降级成普通 single-choice。

本轮回归：L1/L3 typed-output、dimension contract、source-index、双投影 recovery 和 claim contract 组合 `33 passed`，source-index/input-register 组合 `8 passed`；设施和道路 simulated root-graph 窄切片分别通过，证明 claims/report 两次投影、TARGET/GROUND/EXECUTE、地图/证据查询和无新调用 resume 闭环。最新 touched modules 的 `python -B` 无字节码导入检查与 `git diff --check` 通过。Windows 临时 `__pycache__` 被测试进程锁定时，compileall 需在锁释放后重跑。

这次收敛解决的是“L1/L3 输出不够结构化、来源不明、正文被结构化结果替代、仓库文档被隐式混入”的问题，不等于全村规划已完成。真实全量运行仍需验证 provider 是否稳定生成完整 typed observations/claims；GROUND 的 candidate/geometry/relations、coverage demand、network endpoint/route、topology solver 和多目标 mixed-worker live 闭环仍按下节标为 `PARTIAL/GAP`。

### 9.21 旧合并投影与项目兼容命名清理（2026-08-24）

本轮将“旧兼容实现去除”落实到生产调用图，而不是只改文档：

- 删除 `L1DimensionOutput`、`L3DimensionOutput` 和 L3 `_cached_claim_generation` 合并缓存；L1 只走 `observe → register → validate/repair → report` 有界循环，L3 只走 `generate_claims → deterministic repair/admission → generate_report` 两个独立投影。`report_body` 没有被删除，仍由 `L1ReportOutput`/`L3ReportOutput` 生成并写入 ReportStore；结构化结果不再和正文共用一个 response model、缓存键或 fallback wrapper。
- 删除 structured runner 对旧 `l1_markdown_observations`/`l3_report_claims` 包装格式的解析，以及报告 fallback 中的 `observations=[]`/诊断混合字段。报告文本 fallback 只允许显式 `report_text` 模式，并只产生 `report_body`；observe/claims 通道仍 strict，缺少 typed output 不会偷偷生成空间事实。
- 删除 `project` category、`project_parameters`、`project_type`、`project_footprint` 和 `TargetAssignment.target_type=project` 的运行时迁移别名。`site_area`、`site_area_parameters`、`site_footprint` 是唯一写入契约；旧 v1 文件只可通过隔离的 `contracts/migrations` 离线工具转换，不再进入 L1/L3/GROUND/EXECUTE 生产链。缺失 typed category/output 的 claim 现在被 quarantine，而不是被猜成 site_area/action。
- 受影响的 L1/L3/structured/provider/target-admission/simulated-ground/flash-unit/worker 回归切片共 `91 + 1 + 62` 通过（其中模拟 GROUND 测试约 42 秒）；全量 `app` 目录 `AST` 解析 `693` 个 Python 文件通过，`git diff --check` 通过，`rg` 已无生产 `L1DimensionOutput`、`L3DimensionOutput`、旧 wrapper mode 或项目兼容别名引用。Windows 上已有进程锁定临时 `__pycache__` 时，`compileall` 的字节码替换会报权限告警；这不影响本轮无字节码 AST 校验。

该清理会让旧 provider payload 更早进入 `SCHEMA_INVALID`/diagnostic，而不是继续把未声明的“项目”语义转换成可执行目标。这是预期的 fail-closed 行为；下一次真实会话必须以新 typed L1/L3 输出重新生成，不能复用旧 artifact 证明新链路。

### 9.22 最新完整示例的前端/交付证据与边界（2026-08-24）

真实会话 `efb707cd-a052-411b-8860-9fdd27051621` 已在同一持久会话完成 L1/L2/L3、人审、TARGET_PROJECTION、GROUND、SELECT、EXECUTE、VALIDATE、RECONCILE 和 DELIVER；这次使用完整 `jintian_village.md` 与 DataCatalog GIS，RAG 关闭。终态为 `completed / active_stage=deliver / progress=100 / delivery_status=complete / last_event_seq=264`，历史列表在刷新后能直接恢复该终态，不会重跑。

- L1 artifact 有 `101` typed facts、`208` observations；L3 有 `164` claims，但只有 `2` interventions、`1` typed target、`2` grounded geometries、`1` formal scenario、`1` approved target 和 `1` execution task 进入正式空间链；其余目标仍保持 deferred/diagnostic。
- GROUND 保存 `network:road:current`、共享 BSM `441426211000049280`、`ParcelResourcePool` 和邻地 `441426211000050003` 上下文。当前正式 solver 是 `parcel_assignment_bounded`；network ref 只是输入 lineage，未因缺少 route candidate 把道路冒充规划成果。
- DELIVER 返回 13 个 deliverables 和 13 个地图层：`current_landuse=660`、`complete_planned_landuse=661`、1 个 `planned_changes` footprint。该大地块由一个源 BSM 切出约 `288.59 m²` footprint 与约 `471.85 m²` preserve remainder；`fully_available + coverage_ratio=0.3795` 表示源地块可用但本次只分配子几何，不是整块不可用。邻地只出现在 adjacency context/evidence，没有邻地 mutation。
- Playwright 已验证分层分析 `L1 12/12、L2 4/4、L3 12/12`、规划图层开关、现状/规划统计和“尚未产出道路结论”的诚实提示。截图保存在 [`map-panel.png`](../reports-weekly/2026-08-24-real-run/map-panel.png)、[`layers-complete.png`](../reports-weekly/2026-08-24-real-run/layers-complete.png)、[`l3-complete.png`](../reports-weekly/2026-08-24-real-run/l3-complete.png)。
- 该会话是在本轮 TARGET_PROJECTION admission 收紧前生成的历史正向样本；新代码对 `needs_review`/缺 typed spatial admission 会在 GATE→HUMAN 停止，不再静默进入 GROUND。因此它证明旧链路的可见交付和前端 hydration，不证明清理后的 provider 在全村目标上已全部准入。

当前合理规划图层的判定仍是：只有 source-backed、candidate geometry、availability/eligible/excluded 面积、typed relation/network/topology 输入和 approved scenario lineage 同时闭合的对象才进入正式规划图层；现状图层、recall-only 候选、deferred/diagnostic 目标和未获批道路不能被前端显示成规划结论。全村 coverage、真实道路 route、topology/layout 和混合 worker 执行仍是 `PARTIAL/GAP`。

## 10. Remaining partial boundaries

- professional dense RAG 依赖配置的 embedding provider；不可用时不能提供 dense recall；
- L1/L3 双投影结构化契约已在代码级收敛：正文 `report_body` 与 typed facts/claims 分开持久化，任意原始输入先建 source index，旧仓库文档扫描入口已移除；observe/claims 与 report synthesis 使用独立 response model、缓存键和 checkpoint，恢复时不会重复已完成的 provider 调用。但全量 provider 仍需 fresh-session 抽样证明每个 L1/L3 维度持续输出足够的 typed observations/claims，而不是只通过 schema 或 loop。
- evidence orchestration 已形成 EvidenceRequirement/EvidenceClaim/EvidenceCoverage 基础，五个阶段已有 artifact-bound producer，gate-scoped bounded gap loop 已接入，但跨阶段合并、source/budget policy 和 benchmark 尚未完全统一；
- 现状报告的 L1 输入绑定已在当前工作树修复并由新 live session 进入完整空间链；仍需 artifact 级抽样确认 12 个 L1 worker 均未混入规划方案文档；
- L3 admission 已在当前工作树 fail-closed；最新窄切片 session 已证明一个带 marker 的项目包可稳定产出 `planning_role`、typed parameters、位置和 evidence lineage，但全村普通目标的稳定准入仍未证明；旧 artifact 不能替代新准入逻辑的正向证据；
- 地点落地能力存在，SpatialQuery AST、参数化 plan/compiler 和 candidate completeness gate 契约已存在，但旧 adapter、uncertainty、统一 evaluator 和真实 PostGIS integration 尚未完全统一；
- ScenarioOptimizer 的 completeness、objective direction、ordered recommendation 与 certificate/ID 一致性已修复；共享 BSM 的 `ParcelResourcePool → parcel_assignment_bounded` 和有网络/需求快照前置条件的 `network_relation_bounded` 已接入默认 portfolio 并通过代码级回归，typed road endpoint 已有保守的 claim→GROUND bridge，但多目标 benchmark、coverage demand producer、真实 L3 道路候选/需求图层、topology backend 和多地块真实空间执行会话仍未收敛；旧 SiteSelectionDecision/ExecutionPlan 决策投影已从生产 import graph 移除，剩余引用只允许作为测试/历史文字清理对象；
- ApprovedExecutionInput、ExecutionPlan semantic digest、ExecutionStaging、all-or-nothing commit 和 ValidationCertificate 的代码级边界已通过针对性回归；旧真实 session 的无批准/partial commit 仍是待新会话消除的负例，ScenarioSet→plan 的旧投影和部分 worker 仍需收敛；
- live typed-output boundary 已通过组件/runtime tests；第二次完整真实会话已不再被 `No tool calls` 阻断，最新窄切片也已稳定产出带 planning role、typed parameters、对象位置和 evidence lineage 的可执行干预；但全村普通目标仍未证明稳定满足同一准入，且状态投影在并发 L3 期间存在滞后；
- 最新窄切片 session 已证明 `ParcelChangeSet` 非空、source-backed footprint + preserve remainder、planned landuse 非现状复制、前端规划图层和同次证书闭环；共享多地块资源池已有代码级容量/重叠约束但未做真实混合执行验收，当前 live 仍无 typed 道路规划结论，coverage/topology 和全村资源耦合尚未完成，因此不能用该局部 session、clone/replay 或局部测试替代全村“非复制土地利用 + 道路/关系”真实验收。

目标、迁移状态和验收指标分别只在 [`00_SYSTEM_DESIGN.md`](../design/00_SYSTEM_DESIGN.md)、[`05_MIGRATION.md`](../design/05_MIGRATION.md) 和 [`04_EVALUATION_AND_ACCEPTANCE.md`](../design/04_EVALUATION_AND_ACCEPTANCE.md) 维护。
