# 关系感知空间规划：实现、设计与合理图层产出差距审计

**审计日期：** 2026-08-17
**审计对象：**

- `06_TARGET_PROJECTION_EXECUTE.md`
- `23_EXPLORE_RETRIEVAL_REDESIGN.md`
- `28_RELATION_AWARE_SPATIAL_PLAN_GENERATION.md`
- 当前工作树中的 Explore、TARGET_PROJECTION、GROUND、SELECT、EXECUTE、VALIDATE、DELIVER 实现与相关测试

**审计原则：** 设计文档只作为“目标、历史和假设”的来源；当前能力结论以可到达的生产代码、运行产物和可实际执行的测试为准。文档中的“已完成”不自动等价于形成了有效的规划闭环。

---

## 1. 结论先行

当前代码已经具备类型逐步收紧、遇到不支持能力时倾向于 fail-closed、局部 worker 能物化 GIS feature 的内部部件。但是，**当前用户可见演示链路的有效规划图层产出为零**。因此不能再把“内部存在物化能力”表述成“系统能够产出部分演示规划图层”。

但当前系统还不是 28 文档定义的“关系感知空间方案生成器”。更准确的定位是：

> **带有关系元数据占位的、以单目标候选评分和容量分配为核心的空间图层物化管线。**

决定性证据如下：

1. `PlanningIntentGraph`、`ConstraintFactor`、`RelationSatisfaction`、typed `CandidateGeometry` 和 `GroundedPlanningProblem` 已有契约并已在主链路上传递。
2. 这些关系目前只被一对一复制为扁平 factor；除 `precedes` 被先验标成 `satisfied` 外，其他关系通常只得到 `unknown` 或 `deferred`。
3. SELECT 的全局 MIP 只优化“目标—地块”选择、面积容量和地块排他；没有 `near`、`serve`、`access_via`、`connect`、`co_locate` 等成对或网络关系变量。
4. SELECT 完成后直接复制 GROUND 阶段的 `relation_satisfaction`，没有基于选中几何重新测量。
5. `PlanningScenario` 尚不存在，`scenario_id="evidence_baseline"` 只是选择结果上的默认字符串，不是可比较、可重算、可审计的方案对象。
6. ExecutionPlan 能写出 `depends_on`，但实际执行图仍按 worker 类型静态并发，`run_workers` 不按 task dependency 拓扑调度。
7. VALIDATE/DELIVER 没有消费 `PlanningIntentGraph`、`ConstraintFactor` 或 `RelationSatisfaction`；最终检查无法证明关系成立。
8. 当前默认 `.run-tmp` 活动 CAS 没有 `render_layers` / `delivery_spatial_snapshot` 引用，最近会话只留下 L1/L2 review，前端演示没有可读取的规划交付图层。
9. 2026-08-12 隔离历史运行不是当前演示产出，而且也没有形成土地规划结果：`complete_planned_landuse` 虽有 660 个 baseline 要素，实际 change 数为 0；只有 17 个项目标记点和 16 个设施点，没有规划道路、规划分区或规划变更地块。

因此，当前合理图层产出成熟度约处于下表的 **L1～L2 局部能力**，而 28 文档目标是 L4：

| 等级 | 能力定义 | 当前判断 |
|---|---|---|
| L0 | 用户可见链路能稳定交付至少一个真实规划 feature | 当前演示未具备；内部历史部件可局部物化 |
| L1 | 输出绑定稳定 target，区分点/线/面，基本 fail-closed | 部分具备 |
| L2 | 全部输出几何合法、来源完整、单目标约束可信 | 部分具备；验证范围和 lineage 仍有缺口 |
| L3 | 单一方案中关键目标关系、容量、网络服务和时序均可验证 | 未具备 |
| L4 | 可生成、比较、局部修复多个 `PlanningScenario` | 未具备 |

### 1.1 空演示图层的证据边界

本次补充核对后，需要把三类产物严格分开：

1. **当前前端演示：有效规划 feature 为零。** 当前默认 `.run-tmp/runs` 下没有活动会话的 `render_layers`、`delivery_spatial_snapshot`、`planned_state` named ref；2026-08-17 最近会话目录只出现 L1/L2 review 文件。这与用户看到的空规划图层一致。
2. **2026-08-12 隔离历史 CAS：有标记 overlay，但没有规划变更。** 抽查 `db6118ac-2efe-4cc5-9168-489444fb0f54`：SELECT 有 178 assignments、1 selected site；PlannedState 有 0 parcels、0 zones、0 roads、16 facilities、1 axis、17 project points；RenderLayers 的 660 个 `complete_planned_landuse` feature 中实际 changed feature 为 0，只有 `planned_project_point=17` 和 `facility_point=16` 两类规划 overlay。该历史结果不能证明当前 demo 可用，也不能证明土地/道路规划成立。
3. **`integrated_planning_map.png`：独立展示脚本产物。** `scripts/render_integrated_map.py` 直接读取静态 `data/gis/jintian/current`、`data/gis/jintian/planned`、dimension reports 和 gazetteer。它不是从当前 `DeliverySpatialSnapshot` / `RenderLayers` 主链生成，不能作为端到端演示成功证据。

因此第一道 P0 不是“优化图层质量”，而是**建立非空、非 baseline 复制、来自主 workflow 的垂直切片，并让空产出 fail-closed**。只有这道门通过后，才有资格衡量关系合理性。

**最短关键路径不是继续增加 worker，也不是继续扩写 prompt。** 最短关键路径是先恢复非空主链并禁止空交付假阳性，再把现有的“关系契约占位”贯通为：参数化关系 → 候选/绑定 → 联合选择 → 确定性测量 → 方案账本 → 执行 lineage → 最终逐关系验证。

---

## 2. 审计范围、证据强弱与限制

### 2.1 本次实际核对的主路径

```text
L1/L2/L3 workers
  ├─ run_rag()
  └─ retrieve_evidence()
         ↓
PlanningProgram
         ↓
TARGET_PROJECTION
  ├─ SpatialReferenceSpec[]
  └─ PlanningIntentGraph
         ↓
GROUND
  ├─ CandidateSite[] / CandidateGeometry
  ├─ ConstraintFactor[]
  └─ GroundedPlanningProblem
         ↓
SELECT
  ├─ SuitabilitySurface
  ├─ ZoneAllocation
  ├─ GlobalSiteAllocation
  └─ SiteSelectionDecision
         ↓
EXECUTE
  ├─ ExecutionPlan
  ├─ worker outputs / ChangeSet
  └─ PlannedState
         ↓
VALIDATE → DELIVER
```

核对重点不是类是否存在，而是：谁生产、谁消费、选择前后是否重算、状态是否真正影响决策、最终是否能够被验证。

### 2.2 证据等级

| 等级 | 本审计中的含义 |
|---|---|
| A | 当前生产代码存在明确调用链或数据消费者 |
| B | 契约/单元测试存在，但没有形成有效主链路闭环 |
| C | 设计文档声明或目标架构，当前没有生产实现 |
| D | 旧文档、旧路径或过时 graphify 快照中的历史信息 |

本文对“已实现”的判断只接受 A；B 会明确标成“骨架/占位/局部实现”。

### 2.3 验证结果

仓库 `pytest.ini` 默认只收集 `backend/tests/e2e` 且只运行 `e2e and not slow`。直接指定 core 文件仍会被 `-m` 过滤，容易得到“0 tests / 全 deselected”但退出码为 0 的假阳性。

使用 `pytest -o addopts=''` 运行与本审计直接相关的 8 个 core 文件后，结果为：

```text
19 passed, 3 failed
```

三个失败均来自 `test_target_projection_semantic_contract.py`：旧夹具创建 `category="road"` 的 `PlanningIntervention` 时没有给出新的闭集 `asset_kind`，被当前 Pydantic 校验拒绝。其含义是：

- 闭集资产语义校验已经落地；
- 对应测试和迁移路径没有同步；
- 当前不能把现有 core 测试集描述成全绿。

现有 relation 测试只证明：关系能被编译、未知关系不会自由分类、`precedes` 能写进任务依赖、不可测关系返回 `deferred`。它不证明任何实际空间关系被测量或优化。

### 2.4 本次没有依赖外部检索的原因

本次关键判断都是仓库内部的生产数据流事实，例如“SELECT 是否读取 factor”“VALIDATE 是否消费 satisfaction”“执行器是否按 task DAG 调度”。这些问题不需要 Exa 或 Context7 才能判定。外部资料无法替代本地消费者追踪，因此本次没有用外部检索为缺失实现背书。

现有 `graphify-out` 快照生成时间早于当前 2026-08-17 工作树，并包含已经迁移的旧 `backend/app/agent/...` 路径。本次只把它用于发现历史入口，没有把它作为当前实现证据，也没有以旧图覆盖源码核对结果。

---

## 3. 三份设计文档的可信度与冲突

### 3.1 总体判断

| 文档 | 可继续采用的核心判断 | 已过时/矛盾处 | 使用方式 |
|---|---|---|---|
| 06 | TARGET_PROJECTION 应不可变；点线面候选应分型；选择应联合化；最终几何须保留目标 lineage | 后半段仍保留旧实现诊断，如多条件默认 OR、GROUND 修改投影、依赖按列表顺序推断 | 当作迁移历史和问题目录，不当作当前状态表 |
| 23 | 当前 Explore 内联重复、无 router/query plan/sufficiency；gate 请求没有闭环；retriever 信息贫乏 | 对 `retrieve_evidence_for_gate` 有“无调用者”和“接线待核实”两种表述；目标架构仍未实现 | 当前状态大体可信，但每个“已实现”需查调用者 |
| 28 | 三图分工、observation/binding/geometry 分离、方案账本、闭集关系、确定性 GIS 验证是正确北极星 | 容易把 P0 契约骨架误写成能力落地；部分类型定义不足以支撑文档承诺 | 作为目标架构使用，不作为完成度报告 |

### 3.2 06 文档中应撤销或改写的旧结论

1. **“多个 spatial requirement 用 OR 合并”已过时。** 当前 `spec_mapper.py` 对独立条件默认使用 AND；单个 location 中多个候选名称使用 OR 更接近别名/候选语义。
2. **“GROUND 修改 target_projection”已过时。** 当前 workflow 明确保留投影不可变，GROUND 输出独立 `GroundingResult`。
3. **“ExecutionPlan 按目标列表顺序猜依赖”已过时。** 当前 `plan_builder.py` 只从显式 `precedes` 关系编译依赖。
4. **CandidateSite 面中心、局部选择、无方案对象、最终 lineage 弱**仍然成立，只是程度有所变化：已有 typed geometry 和全局 parcel MIP，但没有关系联合求解。
5. 文档需要把“契约存在”“主链路传递”“决策实际消费”“最终验证”分成四个状态，避免再次把 B 级证据写成 A 级完成。

### 3.3 23 文档中应澄清的状态

`retrieve_evidence_for_gate()` 确实存在，但仓库中没有主图调用者。`_route_explore()` 在 L1/L2 只决定重跑 dimension，在 L3 转人工，并不消费 pending request 来触发该函数。因此应该明确写成：

> **适配函数已实现；gate-driven retrieval 未接线，生产能力等同于未完成。**

另外，23 的“统一 evidence service”目标和当前 `run_rag()` + `retrieve_evidence()` 并行存在不一致。当前不是“统一后兼容旧 RAG”，而是两个上下文渠道并存，可能重复、冲突且无法统一审计。

### 3.4 28 文档中应降低的完成度表述

28 的概念边界是三份文档中最可靠的，但当前代码只落地了简化模型：

- `PlanRelationIntent` 是一个 subject、一个 object、一个 template 的二元边；没有阈值、单位、网络、方向、几何范围、权重或条件表达式。
- `ConstraintFactor` 只是关系边的扁平复制，不是可被求解器和 evaluator 执行的 factor。
- `RelationSatisfaction` 只有状态和说明，没有 measured value、threshold、unit、scenario、feature refs、evaluation trace。
- `GroundedPlanningProblem` 没有 baseline snapshot、实体绑定、候选几何集合、共享资源、网络引用和版本指纹的完整账本。
- `PlanningScenario`、`ScenarioFeature` 尚不存在。

因此，“P0 契约已落地”只能表述为**第一版 schema 骨架和局部传递已落地**，不能写成“关系感知生成主链已形成”。

### 3.5 相关状态文档也存在滞后

`27_IMPLEMENTATION_VS_DESIGN.md` 中仍有两类相反方向的陈旧信息：

- 它把 23 描述为归档/未实现，但当前文件仍是活跃设计文档，部分 evidence service 已进入 worker。
- 它又把 PlanningIntentGraph、ConstraintFactor、RelationSatisfaction 全部写成缺失，而当前工作树已经有第一版契约与传递。

建议今后状态文档采用“契约 / producer / consumer / validator / acceptance”五列，而不是单个 implemented 布尔值。

---

## 4. 分阶段实现差距

## 4.1 EXPLORE：检索存在，但不是闭环证据系统

### 当前实现

- L1/L2/L3 worker 内部先调用 `run_rag()`，再调用 `retrieve_evidence()`。
- `retrieve_evidence()` 固定并行查询 report、KG、bundle 三个 retriever，没有 router 和 query planner。
- report retriever 基本按 dimension 和含数字的空间句过滤，没有真正使用 query 进行相关性检索。
- KG retriever返回固定的村庄认知与道路/水系模板，基本不使用 query 和 entity scope。
- bundle retriever主要输出 group count/label，没有数据完整性、字段质量、CRS、覆盖范围和版本证据。
- 缓存键包含 session、stage、dimension、query、entity scope、purpose，但不包含 questions、required facts、known gaps、上游 artifact digest 和数据源版本。
- facts 用截断文本进行去重，存在不同事实误碰撞的风险。
- `unresolved` 主要继承 request questions，不是 sufficiency evaluator 的判断。
- `retrieve_evidence_for_gate()` 没有调用者。
- 旧 `ExploreService` / `ExploreFlashAgent` 没有形成当前主路径。

### 与 23 设计的差距

| 23 目标 | 当前状态 | 后果 |
|---|---|---|
| Router 按问题选择检索器 | 固定全查 | 成本和噪声不可控，不能区分语义、结构、完整性问题 |
| QueryPlanner 生成子查询 | 没有 | `query=dimension_name` 过粗，无法回答 gate 的具体缺口 |
| SufficiencyEvaluator | 没有 | “查到了事实”不等于“足够继续”，重复运行仍可能原地打转 |
| gate-driven retrieval | 适配器孤立 | pending request 不会转成新证据，只会重跑 worker/转人工 |
| typed artifact/history/integrity retriever | 没有 | 无法回答上游产物、历史决策和数据质量问题 |
| 统一 RAG/evidence 入口 | 两套入口并存 | prompt 上下文重复或冲突，来源审计分裂 |

### 对合理规划图层的影响

Explore 不是最终几何生成器，但它决定了规划问题是否拥有足够事实。当前最危险的不是召回率低，而是**没有机制区分“事实不存在”“查询失败”“已经充分”“只有粗粒度证据”**。这会让后续把村域、地块集合或固定 KG 摘要误当成精确位置依据。

优先级：**P1**。它应与关系求解并行改造，但不能用“先重构完整 Explore”阻塞 P0 的确定性几何与关系闭环。

## 4.2 TARGET_PROJECTION：节点和关系图已产生，但语义编译仍薄

### 已有进展

- `PlanningProgram` 可确定性编译为目标投影。
- 目标带有闭集 `asset_kind`、`expected_output_kind`、typed facility/linear/road 参数。
- `PlanningIntentGraph` 随投影产出并写入 KG overlay。
- `serve` 等闭集 relation 可以从 `spatial_requirements["relations"]` 编译。
- intervention dependency 可转成显式 `precedes`。
- 未支持的关系模板会 diagnostic，而不是自由创造类型。
- 投影在 GROUND 中保持不可变。

### 仍缺失的能力

1. **关系依赖上游已经结构化的 dict。** 编译器没有从 observation、claim、target parameters 和领域规则构造完整关系草图。
2. **关系参数不足。** 例如 `near` 没有最大距离，`serve` 没有需求集、覆盖半径、容量与网络模式，`connect` 没有端点与网络种类。
3. **类型兼容校验不足。** subject/object 是否允许该模板、对象是否为 target/entity/network/zone、是否需要真实 geometry，都没有完整验证。
4. **证据强度不足。** relation 可没有 evidence，dependency 生成的 `precedes` 也没有完整来源链。
5. **未知空间目标仍可能被粗略回退成 site_area。** 这优于路由到错误 worker，但仍可能在下游造成面候选偏置。
6. **parse result 对 intent graph 使用 `Any`。** 阶段边界没有把 schema 校验完全封死。

### 对合理规划图层的影响

即使后续求解器完整，当前关系也常常没有足够参数变成可执行约束。它能表达“卫生室 serve 某聚落”，但不能回答“沿什么网络、多少分钟、多少需求、容量多少、满足阈值是多少”。

优先级：**P0 契约基础**。

## 4.3 GROUND：typed geometry 已有，但仍由 polygon-centric CandidateSite 主导

### 已有进展

- `CandidateGeometry` 区分 point、line、polygon 以及 execution、anchor、corridor、parcel、scope role。
- 面范围不会被直接伪装成道路或管线执行线。
- line reference 可以成为 executable geometry；polygon 对 linear target 只成为 corridor candidate。
- GROUND 输出独立 `GroundingResult`，不修改 target projection。
- `ConstraintFactor[]`、`RelationSatisfaction[]` 和 `GroundedPlanningProblem` 随结果传递。

### 关键缺口

1. `CandidateGeometry` 缺少稳定 candidate id、target id、generation operation、source BSM lineage、hard-filter result、suitability components 和 relation score。
2. `CandidateSite` 仍要求 `available_area_ha > 0` 且有 polygon WKT 才进入候选列表；这使精确点/线证据仍要依附地块面候选结构。
3. point 的 `anchor_geometry` 按当前属性不是 executable；真正执行往往还是从 selected parcel 取 representative point。
4. `GroundedTargetDomain` 主要持有 site refs，没有把 point/line/polygon candidates 作为统一的一等域。
5. factor 编译只复制 relation；没有参数解析、hard/soft 转换、共享资源、hyperedge 或 network subproblem。
6. evaluator 没有 GIS 测量。除 `precedes` 被直接标成 satisfied 外，其余通常 unknown/deferred。
7. `precedes` 在执行前被标成 satisfied 是语义错误：它最多是“可编译/待执行”，只有执行 trace 能证明实际顺序。
8. GROUND 的轻量 retry evidence 和 Explore evidence service 不是同一个闭环，统计到层数/地块数不等于补足具体 grounding 缺口。

### 对合理规划图层的影响

当前能防止一部分 geometry-kind 错配，却不能形成“每个目标一个包含多种几何角色、可被关系联合评价的候选域”。点设施最终落在地块代表点上，可能几何合法但位置不具备入口、道路可达性、服务覆盖或用地适宜性。

优先级：**P0**。

## 4.4 SELECT：有全局容量优化，但不是关系联合优化

### 已有进展

- zone、site/facility、road/linear 使用明确 target assignment。
- site_area/facility 可进入一次性全局 MIP，而不是完全按 target 顺序贪心。
- MIP 处理每目标至多一个地块、地块面积容量、排他与 priority。
- suitability 有 slope、hazard、road access、service coverage 等单候选分量。
- 硬关系未解决时可把 decision 标成 pending review。

### 决定性缺口

1. 全局 MIP 不读取 `GroundedPlanningProblem.factors`，没有任何关系变量或 pairwise candidate score。
2. objective 只累加目标自身优先级/候选质量；两个目标的组合是否满足 `near/connect/serve/co_locate` 不影响最优解。
3. zone allocation 与 site allocation 分开，不能保证设施选址、功能分区和土地变化互相一致。
4. road/linear 在 SELECT 中主要被标成 ready/deferred，没有与端点选择共同求解。
5. GROUND 的 satisfaction 被原样复制到 decision，选择后没有重新测量。
6. `scenario_id="evidence_baseline"` 没有对应方案实体、候选集、指标、指纹或父版本。
7. 当前 `service_coverage` 是到已有设施的最近欧氏/投影距离。这会奖励新设施靠近已有设施，而不是覆盖未满足需求；语义可能与真实服务规划相反。
8. legacy facility MCLP 使用聚落/锚点和 haversine 半径，不使用道路网络、容量和设施类型；在 workflow 已提供 global allocation 时通常又不会成为主选择器。

### 对合理规划图层的影响

这是当前从“可出图”到“规划合理”的最大断点。单目标评分可以选出每个目标看起来不错的地块，但组合后可能出现：

- 新设施彼此扎堆，未覆盖真实需求；
- 设施离道路几何很近但道路网络不可达；
- 道路目标和设施端点不是同一方案中的选择；
- 设施、分区和地块变化互相冲突；
- 公共服务容量不足但距离指标仍通过；
- 关键关系在 GROUND 时 unknown，SELECT 后仍然 unknown，却继续执行。

优先级：**最高 P0**。

## 4.5 EXECUTE：worker 能力比求解层强，但没有执行 Scenario/DAG

### 已有进展

- `plan_builder.py` 从显式 `precedes` 关系生成 task dependency，不再猜列表顺序。
- worker task 保留 stable target、assignment 和 target binding snapshot。
- facility worker 能生成设施点和可选 footprint。
- road worker 要求 typed target、端点和 routing evidence，缺失时 fail-closed；内部已有真实 route planner 接口和 staged generator。
- utility/未知 linear 不会伪装成 road，当前进入 durable deferred。
- worker common 只从 active tasks 重建 execution intent，deferred target 不进入错误 worker。

### 关键缺口

1. `execute_agent.py` 仍使用固定 worker-type 图：project → zone → facility/axis → road → action → merge。
2. worker fan-out 不读取每个 task 的 `depends_on`，因此同一 worker 内或任意 `precedes` 的顺序没有真正被调度。
3. plan builder 没有对 `precedes` 做 cycle detection。
4. task 没有 scenario id、relation ids、candidate id 和预期 satisfaction。
5. facility point通常来自地块 representative anchor，不是经过网络/入口/布局联合求解的 ScenarioFeature。
6. project worker 的图层属性使用 `project_id/project_ref`，与统一 `target_id` lineage 不完全一致。
7. utility 全部 deferred，意味着供水、污水、雨水、电力、通信等“关系型线网目标”没有实际 materializer。
8. `PlannedStateBuilder` 在只有一个 facility/road/axis target 时会给缺 target id 的 feature 自动补归属。该 fallback 会掩盖 worker lineage 缺失，而不是证明 lineage 正确。
9. PlannedState 不记录 scenario、relation、candidate、generation operation、CRS/hash 等完整来源。

### 对合理规划图层的影响

道路 worker 本身已有较严谨的失败边界，但上游没有给它一个经联合求解的 scenario，执行器也不按 scenario DAG 调度。结果是“强 worker 被弱协调层隔离”：局部能生成合理路线，不代表整套规划关系一致。

优先级：**P0（DAG/lineage）+ P1（utility capability）**。

## 4.6 VALIDATE / DELIVER：检查图层技术有效性，不检查规划关系成立

### 当前实现

- execution review 检查输入、worker 输出存在性、parcel change lineage、几何报告、worker conflict/error。
- validation 检查目标 traceability、部分 topology、same-layer overlap 和简化 accessibility。
- delivery 从 PlannedState 渲染图层并生成 manifest。

### 关键缺口

1. validation/delivery 没有生产消费者读取 `intent_graph`、`ConstraintFactor` 或 `relation_satisfaction`。
2. `_planned_geoms()` 的 topology 集合重点覆盖 parcel/zone，没有把 road/facility/axis 作为统一跨层拓扑图验证。
3. overlap 主要做同层面几何检查，无法检查设施落在禁止用地、道路断连、线网穿越限制等跨层关系。
4. accessibility 以设施坐标到 planned parcel 平均质心的 haversine 距离近似，既不是需求点到设施，也不是道路网络时间。
5. 没有 per-relation evaluator、measurement、threshold、feature refs 和 solver/evaluator reconciliation。
6. delivery 没有展示多个 scenario、关键关系通过率、deferred/unknown 原因和方案差异。
7. 当前“图层成功写出”可在大量规划目标未 materialize 时发生。

### 对合理规划图层的影响

最终系统只能较有把握地回答“文件能否打开、部分面是否有效、输出是否有 target 线索”，不能回答“为什么这个设施在这里、服务谁、是否可达、容量是否够、与道路/分区/其他设施是否一致”。

优先级：**最高 P0**。没有这一层，即使优化器声称满足关系也不可验收。

---

## 5. 与“实际能够产出合理规划图层”的差距

## 5.1 合理图层的最低验收定义

“合理”不能只靠视觉观感，也不能只靠几何 validity。对本项目，最低应同时满足：

1. **语义正确：** target、asset kind、operation、output kind 一致；不把范围面当最终线，不把村域中心当精确设施点。
2. **证据可追溯：** 每个目标、候选、选择和 feature 都能回溯到 observation、binding、source data 和 generation operation。
3. **单体可行：** 面积、坡度、灾害、用地兼容、几何形态等硬条件成立。
4. **组合一致：** 目标之间的 near、serve、connect、access、avoid、contain、co-locate、precedes 可被确定性测量。
5. **网络可信：** 交通和市政关系基于真实 network graph、端点、阻抗、容量和连通性，而不是直线距离。
6. **资源一致：** 地块容量、设施容量、道路/管线共享通道、阶段预算和排他条件不冲突。
7. **方案完整：** 一次输出属于明确 scenario；没有把 baseline、候选、选择和最终 geometry 混在一起。
8. **执行一致：** worker 只物化 scenario 中已选 feature，按 DAG 依赖执行，并保留 relation lineage。
9. **独立复核：** validator 从最终 geometry 重新测量关系，不盲信 solver 状态。
10. **人类可解释：** delivery 能展示关键选择理由、失败/未知关系、deferred 能力和替代方案。

当前对第 1、3、8 项有局部基础；第 2 项不完整；第 4～7、9、10 项没有形成闭环。

## 5.2 在空图层问题修复后，现有算法最可能产出的“看似合理但实质不可靠”图层

当前演示首先是零产出问题。下表描述的是恢复数据贯通后，若仍沿用现有选择与物化算法会出现的下一层质量风险，不代表这些图层已经在当前 demo 中出现。

| 图层现象 | 为什么看似合理 | 隐含问题 |
|---|---|---|
| 设施点落在某个候选地块内 | 点合法、地块适宜度不低 | 点常取 representative anchor；不证明有入口、网络可达或覆盖需求 |
| 道路几何连接两个坐标 | road worker 有 route planner | 两端点未必来自同一联合方案，依赖执行也未按 task DAG 保证 |
| 设施靠近现状道路 | road_access 分数较高 | 欧氏近不等于网络可进入，可能隔河、隔墙或在错误道路等级旁 |
| 新设施靠近现状设施 | service_coverage 分数高 | 对补齐服务缺口可能是反目标，导致重复覆盖 |
| 全部图层几何有效 | Shapely validity 通过 | 几何有效不代表土地、服务、容量和跨层关系合理 |
| manifest 标记交付成功 | 渲染文件齐全 | 大量任务可能 deferred，关键目标没有 feature，关系也未验证 |

## 5.3 P0 阻断项排序

### P0-0：非空主链垂直切片与零产出闸门

先证明一个显式 typed spatial target 能从 PlanningProgram 经过 projection、grounding、selection、execution、snapshot、render layers 和 `/map-layers` 成为至少一个非空规划 feature。任何阶段把计数降为零都必须记录首个丢失边界。`planned=current`、只有 baseline 完整期末地类、或所有规划 overlay 都为空时，DELIVER 必须返回 `no_planning_output` / `partial`，不能发出 `delivery_ready` 或 `complete`。

### P0-A：参数化关系与独立 evaluator

没有 threshold/network/mode/units 的关系无法优化，也无法验证。应先定义可执行 relation schema 和 evaluator protocol，再扩展模板数量。

### P0-B：统一 typed candidate domain

解除 CandidateSite 对面积面候选的统治，让 exact point、line endpoint、corridor、parcel、zone 和 scope 都作为独立候选角色进入目标域。

### P0-C：关系进入联合选择

单目标 suitability 和 parcel capacity 继续保留，但必须增加 pairwise/hyperedge/network factor，并让 hard relation 影响 feasible set、soft relation 进入 objective。

### P0-D：真实 PlanningScenario

选择结果、ScenarioFeature、relation satisfaction、metric、finding、baseline/version/fingerprint 必须成为同一个不可变方案账本。多方案可以后置，但单方案账本不能后置。

### P0-E：选择后与执行后双重验证

选择后用候选几何预验证；执行后从 final geometry 独立复测。`unknown/deferred` 的 hard relation 不能伪装成 complete。

### P0-F：执行 task DAG 和 lineage

按 task dependency 调度，检测 cycle；每个 feature 明确 scenario/target/candidate/relation/source/generator，删除唯一目标自动归属 fallback。

### P0-G：设施服务语义纠正

用 demand、facility type、capacity、road network impedance 计算覆盖；停止用“到现状设施最近距离”替代服务覆盖。

## 5.4 可以并行但不应阻塞 P0 的工作

- Explore router/query planner/sufficiency/gate wiring。
- artifact/history/integrity retriever 和缓存版本化。
- utility materializer 分资产逐个增加。
- multi-scenario diversity 和局部 cut/recompute。
- delivery 交互式方案比较。
- 更完整的视觉质量检查。

---

## 6. 推荐目标架构：保留现有资产，收紧阶段边界

```text
EvidenceSnapshot
  ├─ observations
  ├─ entity bindings + geometry granularity
  └─ source/artifact versions
            ↓
PlanningIntentGraph
  ├─ typed targets
  └─ parameterized relation intents
            ↓
GroundedPlanningProblem
  ├─ typed candidate domains
  ├─ deterministic unary factors
  ├─ pairwise/hyperedge factors
  ├─ network subproblem refs
  └─ unresolved/deferred ledger
            ↓
ScenarioSolver
  ├─ parcel/zone master problem
  ├─ facility service/network subproblem
  ├─ road/utility connectivity subproblem
  └─ cuts/replacements
            ↓
PlanningScenario (immutable ledger)
  ├─ selected candidates
  ├─ ScenarioFeature intents
  ├─ pre-execution relation measurements
  ├─ metrics/findings
  └─ fingerprint/version
            ↓
ExecutionDAG
  ├─ scenario-bound tasks
  ├─ capability registry/deferred ledger
  └─ final GIS features with lineage
            ↓
Independent Relation Validator
  ├─ final measurements
  ├─ solver/evaluator reconciliation
  └─ complete/partial/failed decision
            ↓
Scenario-aware Delivery
```

需要保留并复用的现有资产：

- typed PlanningIntervention 和闭集 asset semantics；
- TargetProjection 的不可变边界；
- PlaceEvidenceIndex / grounded anchor 的现有数据源，但要补版本和粒度；
- suitability unary factors 和 global parcel capacity MIP；
- RoadPlannerPort 与 road worker 的严格失败边界；
- artifact/CAS、checkpoint/resume 和 PlannedState/delivery 基础；
- capability deferred 思路。

不建议保留为兼容行为的部分：

- `precedes` 在执行前自动 satisfied；
- relation satisfaction 在 SELECT 中原样透传；
- service coverage 等同于到现状设施的最近距离；
- point/line target 必须依附正面积 CandidateSite；
- worker 按类型静态顺序替代 task DAG；
- PlannedStateBuilder 的单目标自动 lineage fallback；
- hard relation unknown/deferred 仍可被标成完整方案。

---

## 7. 文档维护建议

1. 将 06 标为“历史迁移设计 + 当前差距索引”，删除或加醒目标记说明 OR、GROUND mutation、列表依赖三条已过时。
2. 将 23 的 gate 状态统一为“adapter exists / no production caller”。
3. 在 28 增加实现状态图例：`schema`、`produced`、`consumed`、`validated`、`accepted`。
4. 更新 27，不再用单一完成百分比；为每个契约列 producer、consumer、validator、acceptance evidence。
5. 任何“真实运行成功”必须同时报告：目标数、selected 数、materialized 数、deferred 数、hard relation 各状态数、ParcelChange 数、最终 feature 数、独立 validation 结果。
6. 计划实施以独立文档 `docs/superpowers/plans/2026-08-17-relation-aware-spatial-planning-gap-closure-v2.md` 为准。旧的 `2026-08-17-relation-aware-target-projection-execute.md` 混合了已部分完成和仍未完成的任务，不能直接作为当前执行清单。

---

## 8. 最终判断

三份设计文档最有价值的共同方向是：**LLM 只编译闭集意图，GIS/网络模块决定几何真值，方案用关系和证据账本贯穿，最终从产出几何独立验证。**

当前实现已经跨过“自由文本直接驱动 worker”的危险阶段，但只完成了这条路线的前半段。最需要警惕的误判是：看到 PlanningIntentGraph、ConstraintFactor、RelationSatisfaction 类存在，就认为关系感知规划已经落地。实际数据流显示，它们目前主要是可传输的元数据，尚未成为求解、执行和验收的控制面。

当前系统只能把内部 worker、历史 overlay 和独立展示脚本用于调试，不能声称当前 demo 已有规划图层产出。先完成 P0-0，证明主 workflow 能稳定交付非空且非 baseline 复制的 feature；再完成 P0-A～P0-G。此前任何空图层、静态 planned 输入、报告标记点或现状复制图都不应表述为已经满足设施服务、道路连接、空间关系和多目标一致性的规划方案。

### 2026-08-18 后续复核（以新实现和 replay28 artifact 为准）

上面的结论保留为历史审计基线，但不能继续概括为“所有主链都只有空产出”。在 clean main cursor + source-aware bundle 的 clone-only replay28 中，主链已经实际完成 `TARGET_PROJECTION → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER`：GROUND 产生 42 个 exact Point、1802 个 parcel candidate、329 个 corridor candidate；SELECT 置放 16 个目标、延期 154 个；EXECUTE/FINAL VALIDATE 产出 16 个 feature 且 0 findings；DELIVER 写出 15 个 render layers，facility/project/project-point/protection/restoration/zone 规划 overlay 均非空，几何质量检查 invalid/empty/placeholder/duplicate 均为 0。

该结果的状态是 `partial`，不是默认 live demo 的 `complete`：道路/轴线仍没有真实 source-feature ID 与网络绑定，exact Line=0；154 个 deferred target 仍在 durable ledger；replay 使用 clone-only run root。F1 读侧已能从 descriptor 解引用同一 CAS blob，F2 已将设施 candidate/source provenance 贯通到 RenderLayers，F3 已把道路/轴线收紧为显式 ID + 权威 LineString/MultiLineString。默认演示入口仍需从 fresh source-aware cursor 重跑并证明 `/map-layers`、resume 零增量和无残留进程后，才可把 P0-0 标为 live acceptance。
