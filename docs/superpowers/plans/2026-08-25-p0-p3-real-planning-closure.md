# P0→P3 实际规划闭环分阶段实施计划

> 目标：针对真实会话 `7ad20404-6e3d-4ce2-b343-bc2409a3c38f` 暴露的链路问题，把“可检索范围、可执行候选、关系可计算性、求解准备度、项目输出、证据回放”分成明确的契约，并最终让系统对每个目标给出可追溯的 `feasible / human_required / not_groundable / deferred` 结论。
>
> 约束：保留现有用户未提交改动；沿用现有 TARGET_PROJECTION → GROUND → SELECT → EXECUTE → VALIDATE 链路；不把粗粒度搜索范围、LLM 建议或 suitability 分数提升为可执行事实；每个阶段都必须有定向单测和至少一条阶段级回放测试。

## 阶段边界与验收口径

| 阶段 | 交付边界 | 通过条件 |
|---|---|---|
| P0 | 关闭错误候选、置信度混用、角色错误硬约束、求解前置缺口 | 粗范围不会生成可求解候选；候选身份/几何置信度与 suitability 分数分离；overlay 规则按角色执行；SELECT 在重计算前 fail-closed |
| P1 | 建立物理项目、来源绑定、关系就绪、人审决策闭环 | 同一项目不会被按维度重复求解；每个正式 grounding request 有来源快照和 lineage；关系缺口被阻塞而不是假通过；人审请求可验证且可防陈旧 |
| P2 | 建立 demand/network 数据产品、拓扑/叠加空间后端、统一求解 | coverage/network/parcel/topology 子问题均有 typed readiness；存在跨目标资源冲突时由统一 master 协调；不完整数据不能产出 complete/feasible |
| P3 | 建立黄金样本、输出核算、真实回放验收 | 可重复计算指标；L1/L2/L3/target/candidate/scenario/output 数量对账；真实记录回放覆盖成功、人工介入、不可求解和降级四类结果 |

## P1→P3 并行依赖图

P0 的正式契约冻结后，P1→P3 不需要按单一长链路逐项等待。可以拆成三条低耦合轨道，最后在统一 coordinator 和真实回放处汇合：

```text
                         ┌─ P1-A PhysicalProject ───────┐
P0 contract freeze ──────┼─ P2-A Demand/Network/Spatial ──┼─ P2-B Master Coordinator ──┐
                         └─ P3-A Benchmark/Accounting ───┘                           │
                                      ▲                                               │
                         P1-B SourceBinding ── P1-C RelationReadiness ───────────────┘
                                                                                      │
                                      P3-B RealReplay/Acceptance ◄───────────────────┘
```

可并行的工作包：

- P1-A：只写 program/project assembly 与 canonical identity。
- P2-A：只写 demand/network snapshot 与确定性空间 evaluator。
- P3-A：只写 benchmark manifest、指标和输出对账，不改变业务求解逻辑。
- P1-B：在 P1-A 的 project ref 接口冻结后，可与 P2-A、P3-A 并行实现 source binding/request lineage。

必须串行的汇合点：

- P1-C 要消费 P1-B 的 request/source fingerprint，并与 P2-A 的 evaluator/network refs 对齐。
- P2-B 要同时消费 physical project、relation readiness、demand/network snapshot，不能提前合并局部结果。
- P3-B 必须最后执行，才能验证完整 root graph 和四类最终 route。

实现调度采用“阶段级并行设计、共享工作树串行落地”：每个轨道先用固定 brief/接口做独立分析，代码写入仍按阶段合并，避免多个实现者同时改同一契约造成冲突；这样减少重复项目扫描，同时保留每个阶段一次独立审查。

## 实施顺序

### Task 1 — P0-A：搜索范围与可执行候选彻底分离

**目标**：修复 `resolver.py` 中 `village_coarse_fallback` 将搜索范围写入 `final_bsms` 的问题。

**实现**

1. 在 `backend/app/contracts/spatial/spatial_reference_contracts.py` 增加显式的搜索范围字段/契约（至少包含范围 BSM、bbox、范围类型、来源、原因和 `candidate_materialization_allowed=False`），扩展 `ResolvedSpatialRef`，保持现有序列化兼容。
2. 在 `backend/app/spatial/grounding/resolver.py` 中把 gazetteer/cluster/flash/bbox 的粗定位结果写入 search scope；只有具备可执行 geometry、明确 feature identity 和来源快照的结果才能写入 `final_bsms`、`feature_bsms` 或 `reference_geometries`。
3. 在 `backend/app/domain/ground/aggregate.py`、`candidate_domain_builder.py` 和相关 contract validator 中禁止从 search scope 直接创建 `CandidateSite`、`CandidateGeometry` 或 resolved target domain；search scope 只能影响下一步检索范围和诊断。
4. 在 GROUND artifact/provenance 中保留“使用了哪个搜索范围、为什么未 materialize 候选、需要补什么来源”的可读诊断。

**测试**

- `backend/tests/core/test_grounding_search_scope_boundary.py`：粗粒度村域回退只产生 search scope，不产生 candidate domain。
- 精确 polygon、单个 parcel、多个可辨识 parcel 的回归测试：现有候选行为不变。
- `backend/tests/acceptance/test_real_spatial_stage_chain.py` 增加一条 coarse fallback 断言。

### Task 2 — P0-B：置信度、身份、几何和适宜性分账

**目标**：消除 `refined_candidate_catalog.py` 用 `max(source.confidence, candidate.score)` 覆盖事实置信度的行为。

**实现**

1. 在 `backend/app/contracts/spatial/candidate_geometry.py` 与 CandidateSite 相关契约中增加明确字段：`identity_confidence`、`geometry_confidence`、`suitability_score`；新 schema 只信任显式 grounding 字段并限制在 `[0, 1]`（suitability score 使用独立的模型/量纲），不把旧 `confidence` 作为长期兼容输入。
2. 修改 `backend/app/domain/ground/aggregate.py`、`backend/app/domain/allocation/refined_candidate_catalog.py`、scenario optimizer 和 artifact 序列化：grounding confidence 只来自来源/几何证据；suitability score 只来自 suitability evaluator；不得相互覆盖。
3. 更新 candidate completeness、gate、solver feasibility 的读取逻辑，禁止用 suitability score 代替 grounding readiness。
4. 对缺少显式 grounding 字段或仍使用旧 `confidence` 的 artifact 直接标记 schema-invalid/pending，禁止静默兜底为高置信度或可执行候选；旧格式需要按新 schema 重建。

**测试**

- 候选 score 为 `1.8` 时不得把 geometry confidence 提升到 `1.8`。
- identity/geometry 不足但 suitability 高时，candidate 仍为 `candidate_only` 或 `human_required`。
- 旧 artifact 不得被静默当作新 schema；缺字段/旧 confidence 必须 fail-closed 并给出 schema-invalid 诊断。

### Task 3 — P0-C：按 materialization role 执行 suitability 规则

**目标**：site footprint、functional overlay、protection overlay、restoration overlay 使用不同的空间硬约束策略。

**实现**

1. 在 `backend/app/domain/suitability/spatial_factors.py` 或相邻 contracts 中定义 role policy；把 farmland/ecological overlap、hazard、road/facility distance 等规则分别标记为 `site_hard_exclusion`、`overlay_constraint` 或 `advisory`。
2. 修改 `SpatialFactorIndex.evaluate` 与 `backend/app/domain/suitability/service.py`，显式接收 materialization role 并按 policy 计算 hard feasibility；overlay 不得因为“被保护/恢复图层相交”而被当作 site footprint 排除，但真实建设 footprint 仍保留相应硬约束。
3. 确保角色策略写入 suitability artifact、constraint factor 和 evaluation trace，便于回放解释。

**测试**

- site footprint 与 protection/restoration overlay 在同一 geometry 上产生不同 hard result。
- role 缺失或未知时 fail-closed，不默认放宽 site 约束。
- `test_candidate_validation_boundary.py`、`test_scenario_hard_relation_feasibility.py` 回归。

### Task 4 — P0-D：SELECT 前的 Solver Readiness Preflight

**目标**：在耗时 suitability/refinement/solver 之前发现不能求解的目标，避免“先算完再 HUMAN”。

**实现**

1. 新增 `backend/app/contracts/planning/solver_readiness.py`：定义 target、relation、demand、network、candidate、backend、snapshot、task graph 的 typed readiness；状态至少包括 `ready`、`pending`、`blocked`、`human_required`、`not_groundable`，并保存 blocker refs、source refs、fingerprint。
2. 新增 `backend/app/domain/allocation/solver_readiness.py`：从 GroundedPlanningProblem、candidate completeness、relation satisfaction、network/demand refs 和 solver backend registry 构造 readiness report；硬缺口必须阻塞，软缺口只能降级为 advisory。
3. 在 `backend/app/workflow/stages/select.py` 中将 preflight 放在 suitability surface、refinement、subproblem compile/optimize 之前；没有 ready targets 时直接生成可解释的 select gate/HUMAN artifact，不调用昂贵求解器。
4. 将 readiness 接入 `select_gate.py`、`subproblem_compiler.py` 与 scenario certificate；只允许 readiness 通过且证据闭合的目标进入 complete/feasible 结论。

**测试**

- 缺 demand/network/关系 evaluator/backend 时不进入 solver。
- 候选只有 search scope 或 candidate_only 时不进入 solver。
- 全部就绪的 parcel-only fixture 保持既有 solver 结果。
- 添加 stage-level test 断言 preflight 失败时 suitability/optimizer 未被调用。

## P1：项目与证据闭环

### Task 5 — P1-A：Canonical Physical Project 与跨维度聚合

**目标**：同一物理项目不得按多个 L1/L2 维度重复生成独立选址和建设决策。

**实现**

1. 在 `backend/app/contracts/program.py` 或相邻 contracts 增加 `PhysicalProject` / `PhysicalProjectAssembly`：稳定 project id、package ref、intervention refs、target refs、materialization roles、source claim/fact refs、assembly mode、variant key 和 fingerprint。
2. 在 `backend/app/domain/program/claim_adapter.py`、`aggregate.py` 中以 package + variant + materialization role 构造 canonical project；保留维度级 claim 作为 project component，避免 component 自己进入求解。
3. 在 target projection/grounding request 中传递 physical project ref 与 component refs；SELECT 以 project 为协调单元，同时保留 target-level evaluation。
4. 在 output accounting 中区分 component、physical project、scenario intervention，明确每层的去重键。

**测试**

- 同 package 的多个 claims 只产生一个 physical project 和一个选址决策。
- 不同 materialization role 或不同 variant 的项目保持隔离。
- canonical IDs、artifact round-trip、`test_l3_program_target_compaction.py` 回归。

### Task 6 — P1-B：GroundingRequest/source binding 与正式目标边界

**目标**：所有正式参与 GROUND 的目标都有完整来源链；不支持的空间描述进入 pending，而不是伪装成正式 spec。

**实现**

1. 定义/补齐 `GroundingRequest`：target/project/intervention refs、semantic spec、retrieval scopes、source collection/snapshot、source binding、requested geometry kind、materialization role、request fingerprint、defer reason。
2. 修改 TARGET_PROJECTION、root graph、GROUND stage 的编译和 artifact 持久化，使 request lineage 从 L3 claim 到 source bundle 一路可追溯。
3. 修改 `_filter_unsupported_spatial_specs`：unsupported spec 不进入正式 `grounding_specs`；生成带 reason/source/fingerprint 的 pending request，并让 candidate completeness 正确反映缺口。
4. 防止同一 request 在重试/回放中生成不同 source binding；无 source snapshot 时 fail-closed。

**测试**

- unsupported named-village spec 只生成 pending，不产生 candidate。
- source binding、snapshot digest、request fingerprint 在 TARGET→GROUND→SELECT round-trip 中保持。
- 同一 request 重放结果稳定；缺 snapshot 时不能进入 complete。

### Task 7 — P1-C：关系编译、Evaluator readiness 与 HUMAN 决策指纹

**目标**：关系语义和可计算性分离；缺 evaluator/network/reference 时明确阻塞；人审结果可验证且不会被旧结果污染。

**实现**

1. 扩展 `backend/app/contracts/planning/constraint_factor.py` 与 relation contracts，区分 relation semantic validity、input readiness、evaluation status、solver support；为每个 hard relation 保存 evaluator key/version、required refs 和 source snapshot refs。
2. 修改 `backend/app/domain/relations/service.py`、`subproblem_compiler.py` 和 `select_gate.py`：unsupported/pending/not_evaluable 的 hard relation 必须进入 readiness blocker；只有 evaluator 返回 satisfied/violated/partially_satisfied 且证据可回溯时才可进入 certificate。
3. 增加 `DecisionFingerprint` / `HumanDecisionRecord`（或复用现有人审契约并补字段）：问题指纹覆盖 target/project/request/source snapshot/constraint/evaluator version；提交时校验 fingerprint，陈旧 decision 只能重新请求。
4. 在 `backend/app/workflow/root_graph.py` 的 human resume/interrupt 路径接入校验和审计事件，保持现有 HUMAN route 兼容。

**测试**

- 缺 evaluator 或 relation input 时 gate 为 pending/blocked，不能假通过。
- 相同问题指纹可复用人审；source snapshot 或约束改变后旧人审失效。
- 多关系 mixed target fixture 的 subproblem blockers 与 gate 结果一致。

## P2：数据产品、空间后端与统一求解

### Task 8 — P2-A：Demand/Network Snapshot 与确定性空间后端

**目标**：把需求、网络和空间关系从临时 mapping/诊断升级为带 fingerprint 的可回放数据产品。

**实现**

1. 以现有 `FacilityDemandPoint` / `DemandSnapshot` 为基础，补齐 production builder、source binding、CRS、时间切片、coverage semantics、total demand 校验和 artifact 持久化。
2. 新增 typed `NetworkSnapshot`/`NetworkRef`（network id、edge/node refs、version/digest、metric CRS、source refs、availability），让 `RelationEvaluationContext` 不再依赖无类型字典。
3. 为 `near/within/adjacent/intersects/overlaps/contains/connect/access/serve` 建立确定性 evaluator registry；拓扑关系至少返回明确的 relation status、measurement、trace 和 evaluator version。
4. 为 overlay/restoration/protection geometry 增加独立的 geometry backend 输入和 role-aware evaluation；无法计算时返回 not_evaluable/deferred，不返回 satisfied。

**测试**

- demand/network snapshot fingerprint 和 source refs round-trip。
- RCC/几何边界案例（相交、包含、相邻、分离）结果稳定。
- 网络缺 edge/node/version 时 readiness 阻塞。
- overlay 与 footprint 的确定性角色策略回归。

### Task 9 — P2-B：Portfolio 与统一 Master Coordinator

**目标**：让多个 target/subproblem 在共享 parcel、network capacity、demand coverage、mutually-exclusive/intervention conflict 下由一个协调器产生全局一致解。

**实现**

1. 扩展 `subproblem_compiler.py` 的 typed subproblem input/output，明确 coverage、network、parcel、topology 各自的 required refs、candidate variables、hard constraints 和 certificate requirements。
2. 新增 `backend/app/domain/allocation/master_coordinator.py`：先复用现有 portfolio/subproblem optimizers 生成局部候选，再以稳定 candidate/project IDs 构造全局决策；对小规模问题使用确定性的 bounded enumeration/branch-and-bound（或仓库已存在且可锁定版本的 solver backend），对超出边界的问题返回 solver_deferred 并保留 blocker。
3. 将共享资源、冲突集、project assembly 和 hard relation cuts 编译为 master constraints；禁止把局部 feasible 结果直接拼成全局 feasible。
4. 让 `scenario_optimizer.py`、`subproblem_optimizer.py`、`select_gate.py` 消费统一 master certificate：complete/feasible 只在所有硬目标、关系、资源和输出核算通过时产生。

**测试**

- 两个目标竞争同一 parcel 时全局只选一个且证书能解释冲突。
- 共享网络容量不足时返回 bounded infeasible 或 human_required，不产出超容量方案。
- 子问题局部可行但全局不可行时不生成 recommended scenario。
- 单目标旧 fixture 与现有 solver portfolio 测试保持兼容。

## P3：基准、输出核算与真实回放

### Task 10 — P3-A：黄金样本、指标与分层输出对账

**目标**：让每次改动都能量化识别率、候选质量、关系闭合度、求解完成度和输出守恒。

**实现**

1. 在 `backend/tests/fixtures/` 或现有 fixture 目录建立最小黄金样本 manifest，覆盖 exact parcel、multi-parcel ambiguity、coarse search scope、overlay、network/coverage、human decision、not_groundable、deferred solver。
2. 新增 benchmark runner/metrics module，输出 source binding coverage、candidate materialization precision、candidate completeness、relation readiness/completion、solver readiness、scenario feasibility、human escalation、output accounting 等指标及版本 fingerprint。
3. 增加 L1 fact → L2 dimension → L3 claim → target/project → candidate → scenario → intervention/output 的数量与金额/面积对账 artifact；每层记录 admitted、deferred、rejected、deduped refs。
4. 将指标接入 CI 定向测试；阈值变化必须显式更新 manifest/version，不允许静默放宽。

**测试**

- 黄金样本运行两次结果字节级稳定（时间戳等非确定字段排除）。
- intentionally incomplete fixture 被指标识别为 incomplete/human_required。
- output accounting 能定位丢失、重复和未落地的 claim/project refs。

### Task 11 — P3-B：真实记录回放与阶段验收

**目标**：用真实 artifacts 验证整条链路，而不是只验证 mock happy path。

**实现**

1. 复用现有 recorded replay 支持，增加对 `7ad20404-6e3d-4ce2-b343-bc2409a3c38f` 的脱敏/只读回放入口；不修改用户现有的未跟踪回放文件。
2. 增加 root graph acceptance matrix：成功可解、候选不足需人工、来源不可用不可求解、solver backend 延迟四类路径，分别检查 route、artifact、gate、certificate、output accounting。
3. 对 provider 依赖做显式 capability check；没有外部 provider 时运行本地 recorded replay，并在报告中区分 replay passed 与 live provider passed。
4. 汇总 P0→P3 变更、剩余 blocker、性能预算和下一步 live-run 命令，更新相关设计/迁移文档。

**测试与验收命令**

- `python -m pytest backend/tests/core backend/tests/e2e -q`
- 相关 acceptance/characterization/replay tests 的定向集合。
- benchmark runner 两次稳定运行。
- 若环境提供真实 provider，再执行一次完整 root graph；否则明确报告未执行 live provider，不把 replay 结果冒充 live 结果。

## 每个任务的执行协议

1. 实现前先读取当前文件和既有测试，保持用户 dirty files 不变。
2. 每个子任务独立提交、运行定向测试、由独立 reviewer 检查 diff 和测试；发现问题由该任务实现者修复后再进入下一任务。
3. 阶段完成时运行阶段级测试并记录：修改文件、测试命令、结果、已知降级和未覆盖项。
4. 任何无法获得来源、关系 evaluator、network/demand snapshot 或 solver backend 的情况，都必须落成 typed pending/deferred/human_required artifact，不能通过默认值或 coarse fallback 伪造闭环。
