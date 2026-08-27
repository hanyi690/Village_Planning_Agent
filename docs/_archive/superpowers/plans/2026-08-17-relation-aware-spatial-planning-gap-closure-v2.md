# Relation-Aware Spatial Planning Gap Closure v2 Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 从当前演示规划图层实际为零的基线出发，先建立一个来自主 workflow、非 baseline 复制、可由 `/map-layers` 读取的非空垂直切片，并让零产出 fail-closed；随后在保留 typed target、artifact/checkpoint、parcel allocation、road worker 和 delivery 基础的前提下，把“关系元数据占位”升级为可参数化、可求解、可物化、可独立复测的单方案闭环，并补齐 Explore 的 gate-driven evidence 闭环。

**Architecture:** `EvidenceSnapshot → PlanningIntentGraph v2 → GroundedPlanningProblem v2 → ScenarioSolver → PlanningScenario → ExecutionDAG → IndependentRelationValidator → Scenario-aware Delivery`。LLM 只在闭集 schema 内编译目标、关系草图和歧义候选；地块筛选、网络分析、几何生成、容量、拓扑、阈值测量和最终验收全部由确定性模块执行。

**Tech Stack:** Python 3.12、Pydantic v2、Shapely、GeoPandas/现有 `app.spatial` 端口、PuLP/CBC、NetworkX 或现有 network port、LangGraph、artifact CAS、pytest。

**执行状态说明（2026-08-18）：** 下方早期 Step checkbox 保留为原始设计清单，不能单独作为完成证据；当前真实状态以“当前执行状态”表、修改台账、progress ledger 和每个 task report 为准。Wave 0–2 的代码/专项证据已基本收敛，Wave 3 已接上 source geometry 与 L1 binding 的实际 TARGET_PROJECTION stage wiring，但真实金田村仍未通过 `GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER` 验收。任何没有 fresh artifact、selected candidate 和非 baseline `/map-layers` feature 的 checkbox 都不得解释为真实主链完成。

### GROUND / SELECT / EXECUTE 边界重申（2026-08-17）

这三个阶段不能因为都处理空间对象就承担相同职责，必须围绕候选域和最终几何分层：

| 阶段 | 允许做的事 | 不允许做的事 | 主要产物 |
|---|---|---|---|
| GROUND | 从证据、KG、gazetteer、bundle 和网络快照召回候选；生成 point/line/parcel/corridor/zone 候选；标记 granularity、uncertainty、来源和 hard-constraint 预检结果 | 不把村域/多地块 union 直接宣称为最终 footprint；不替 SELECT 决定唯一地块；不伪造点、线或坐标 | `GroundedPlanningProblem`、typed candidate domains、candidate geometry evidence |
| SELECT | 在每个 target 的候选域上联合求解容量、排他性、硬/软 relation、网络可达性和资源；选择 candidate ID 或明确 deferred | 不重新猜地点；不把 candidate-only/scope geometry 当执行 feature；不在缺少候选时把 assignment 标为 placed | `PlanningScenario`、selected candidate IDs、relation satisfactions、findings |
| EXECUTE | 只消费 `PlanningScenario.selected_candidate_ids` 和 target binding；按 worker/DAG 将已选候选生成最终 point/line/polygon，并保留 lineage | 不重新选址、不从 target 文本重新解析 geometry、不为 deferred target 调 worker；不能用 baseline 复制冒充规划 feature | `ExecutionResult`、`PlannedState`、execution trace |

GROUND 的“候选”不是只能返回单一地块，也不是可以把整村合并成一个可执行 polygon。明确证据时应暴露单地块、地块内代表点/入口点、真实线/端点和可审计 corridor alternatives；村域或多地块集合只能保留为 `candidate_only`/`scope_geometry`，不能直接进入最终 GIS 选择。SELECT 的输入应是这些 alternatives，而不是一个已经被 GROUND 合并成大 polygon 的单项。EXECUTE 只负责把 SELECT 已经选中的 candidate materialize，不能承担补救上游空间语义的职责。

**依据：** `docs/design/modules/spatial-execution/29_RELATION_AWARE_IMPLEMENTATION_GAP_AUDIT.md`。本计划取代同目录下早先的 `2026-08-17-relation-aware-target-projection-execute.md` 作为当前缺口执行清单；旧计划保留为历史，不覆盖。

### 当前执行状态（2026-08-18，以下一律以真实主链 artifact 为准）

> 本表区分“代码/专项测试完成”和“真实主链验收完成”。Wave 0–2 的实现与 focused
> tests 已基本收敛，但这不等于真实金田村已经产出规划图层；Wave 3 未通过前不得把任何
> `PlannedState` 或静态渲染结果标为交付。

| 波次 | 状态 | 证据 |
|---|---|---|
| Wave 0 | 代码/专项验收完成，整链 Explore 回放仍受内存约束 | 空图层 audit/gate 与 v2 contracts 已落地；evidence digest 已做 canonicalize/dedupe/sort，窄回归通过；组合回放仍不得无界重跑 |
| Wave 1 | 代码/专项验收完成，真实主链待复核 | GROUND 已区分 exact/candidate-only，SELECT 只提升 hard-pass；focused tests 通过；旧 artifact 不能证明新 producer 已生效 |
| Wave 2 | 代码/专项验收完成，真实主链待复核 | ScenarioSolver、final relation/reconciliation/topology tests 通过；hard violation 拒绝，unresolved 保持 partial/deferred |
| Wave 3 | 上游 geometry producer、source-binding 投影及实际 stage wiring 已补，真实闭环未完成 | KG builder 现在持久化 source-backed road LineString/MultiLineString 和 facility Point；existing asset 的唯一 exact binding 可投影为 KG 再核验的 named reference；TARGET_PROJECTION stage 已实际加载并传递 L1 snapshots 与 workspace source features。离线真实 GeoJSON 编译可得到 4 组 exact facility points，但 clean main cursor 的 fresh GROUND 仍为 6,699 个 polygon/parcel_set 候选，point/line/exact_feature=0；最新 clone-only post-L3 replay 仍是旧上下文的 2,183 个 polygon/parcel_set 候选，不能作为 source-aware acceptance。partial continuation 可到 SELECT，但 portfolio infeasible，未进入 EXECUTE→DELIVER |
| Task 12 | 进行中；已完成无冲突 main cursor 的 TARGET_PROJECTION→GROUND，并在 clone-only 分支验证 GROUND HUMAN defer→SELECT 路由；尚未通过 SELECT HUMAN gate | 不复制 baseline、不从旧 SELECT checkpoint 修绿；下一步必须补/核验 L1/L3 source feature identity 与设施/道路的 authoritative WKT，再在同一 fresh branch 通过 GROUND→SELECT→EXECUTE→VALIDATE→RECONCILE→DELIVER；当前 SELECT 证据是 47 assigned/123 unplaced、12 polygon scenario features、158 deferred tasks，因此仍只能输出 partial/deferred/no_planning_output |

**下一检查点（Wave 3 继续条件）：** 在不复制 18GB 业务数据库、且不启动无界后台进程的前提下，从 GROUND 之前的 checkpoint 重新生成
`GroundedPlanningProblem`，确认 `materialization_role`、candidate domain 和
`hard_constraint_status` 均来自最新 producer；固定 replay branch 语义后，重新执行 SELECT → EXECUTE → VALIDATE →
RECONCILE → DELIVER。若仍失败，记录新的 failure counts 和首个丢失 artifact，禁止只从旧
SELECT/EXECUTE checkpoint resume 来“修绿”交付审计。

**内存/进程约束：** 真实回放必须使用受控的 checkpoint 副本、唯一 branch/session、有限日志和明确超时；每次 pytest、KG 构建或后端启动后都要检查并关闭 `python`/`uvicorn`。Explore 的组合回放曾达到约 590 MB RSS，未完成低内存拆分前不得重跑整条 Explore。

**最新修复补充：** 已补上 `PlanningIntervention → SpatialReferenceSpec → GROUND`
的 `materialization_role` 传播；未知 zone 不再默认降级为 `land_use_assignment`，无角色的
polygon candidate 仅保留为 grounding evidence。该修复尚未在 fresh branch 上重新跑完
GROUND→DELIVER，因此仍不能视为真实图层验收通过。

### Wave 3 closure plan（按独立 owned files 拆分）

以下任务是当前主链继续实现的最小分工；每个任务都必须在自己的 clone/run-root 和唯一 branch 上验证，完成条件不能用旧 artifact 或静态 planned 图层替代。

| 子任务 | 独立 owner 范围 | 输入/输出 | 完成条件 |
|---|---|---|---|
| 3E. Source bundle snapshot | `application/sessions/session_bundle.py`、bundle store/characterization | 从 `DataCatalog` 生成带 source URI/content digest/feature ID 的金田村 bundle；写入可恢复 snapshot | snapshot 中 `annotations_current`≥34、`roads_current`=131，context ref 含 snapshot digest；恢复后 source manifest 不丢失 |
| 3F. Fresh KG rebuild | `infrastructure/kg/manager.py`、`session_kg.py`、source-aware KG tests | 使用 3E snapshot 重建 L1/L3 KG，校验 Point/Line WKT 和 source IDs | `geo:hasGeometry/asWKT` 与 source feature ID 可按 exact label/explicit ID 查询；KG cache key 随 source geometry 改变 |
| 3G. Target projection source binding | `domain/program/target_projection`、`workflow/stages/target_projection.py` | 将明确的 facility/road existing-action 与 source feature IDs/typed count 绑定；新建资产继续 candidate-only | fresh artifact 中出现 directional exact specs；无数量/ID/语义证据时仍为 deferred/candidate-only |
| 3H. GROUND→SELECT feasibility | `domain/ground`、`domain/allocation`、relation evaluators | 在 3F/3G lineage 上生成 exact point/line + parcel candidates，运行硬约束与 suitability | `point/line/exact_feature>0`；hard-passed candidates 可进入 SELECT；穿越保护区的 parcel union 仍 failed，不得放宽约束 |
| 3I. EXECUTE/DELIVER acceptance | `materialization`、`validation`、`delivery`、audit script | 同一 branch 继续 SELECT→EXECUTE→VALIDATE→RECONCILE→DELIVER | 至少一个 worker task 和非 baseline `/map-layers` feature；每个 feature 有完整 lineage；空/partial 运行返回 `no_planning_output` 或 `partial` |
| 3J. Replay hygiene and memory | `backend/scripts/low_memory_spatial_acceptance.py`、replay characterization | 为 3E–3I 提供 ≤2 GiB clone、超时和子树清理 | 预检拒绝 live/超限 DB；每次回放后 `python/uvicorn` 为空；报告记录首个归零阶段和 artifact digest |

依赖顺序：`3E → 3F → 3G → 3H → 3I`；`3J` 可与 3E–3I 并行，但任何主链验收都必须经过 3J 的预检和清理。每个子任务只提交 owned files 与 characterization tests，主代理在 3I 后统一更新 ledger、plan 和最终审计结论。

---

## 1. 执行约束

- 当前工作树包含大量未提交用户改动。每个代理只修改任务表列出的 owned files；发现重叠时停止合并，由主代理协调。
- 每个任务使用独立 worktree/branch，默认分支前缀 `codex/`。任务提交不得包含其他任务或用户已有改动。
- 新增 Python 使用 4 空格、双引号；Markdown 和前端使用项目既有格式；所有文本文件保持 LF。
- 行为修改遵循 red → green → focused regression → self-review。不要先写实现再补测试。
- core 测试必须覆盖仓库默认 marker 过滤：统一运行 `pytest -o addopts='' -p no:cacheprovider -q <paths>`。
- 不用 fixture/mock 冒充最终真实验收；但单元测试必须使用小型确定性几何 fixture，避免把真实 provider 放进快速回归。
- LLM 不得输出坐标、WKT、BSM、距离、面积、网络路径或 satisfaction 真值。
- `unknown`、`not_evaluable`、`deferred` 和 `violated` 必须区分；hard relation 处于前三者时，scenario 不能标记 `complete`。
- `precedes` 在执行前只能是 pending/unknown；只有 ExecutionTrace 能将其验证为 satisfied/violated。
- 不支持的 utility 能力继续 durable deferred，不得回退到 road worker。
- 兼容旧 artifact 时只做显式 schema migration；不要在 Pydantic 字段上用 `Any` 或静默默认吞掉无效关系。
- 所有 feature 必须由 worker 写出 `scenario_id`、`target_id`、`candidate_id`、`generation_operation`、`source_refs` 和 `relation_ids`；删除“只有一个目标就自动归属”的 fallback。
- 任何计划内接口变更先完成 Task 2 的 schema，后续代理不得自行发明第二套同义契约。

---

## 2. 任务依赖与并行波次

```text
Wave 0（可并行开发，Task 1 验收优先）
  Task 1  空图层诊断、非空垂直切片与零产出闸门
  Task 2  v2 契约冻结
  Task 3  Explore 闭环

Wave 1（Task 2 后可并行）
  Task 4  IntentGraph 参数化编译
  Task 5  Typed candidate domain
  Task 6  关系 evaluator
  Task 7  设施服务/网络模型
  Task 8  Execution task DAG 与 feature lineage

Wave 2
  Task 9  ScenarioSolver 与单方案账本
          依赖 Task 4、5、6、7
  Task 10 最终关系验证与 reconciliation
          依赖 Task 6、8

Wave 3
  Task 11 主 workflow、artifact、resume 集成
          依赖 Task 3、8、9、10
  Task 12 Delivery、真实验收、文档清理
          依赖 Task 1、11
```

### 文件所有权表

| Task | Owned production area | 主要输出 | 可并行冲突 |
|---|---|---|---|
| 1 | characterization、delivery gate/projection、真实运行审计脚本 | 非空垂直切片、首个丢失边界、零产出闸门 | 与 Task 11/12 顺序执行，不并行改同文件 |
| 2 | `contracts/planning`、`contracts/spatial/candidate_geometry.py` | v2 schema | 是所有后续接口前置 |
| 3 | `evidence/retrieval`、conversation Explore edge | gate evidence 闭环 | 不碰规划 contracts |
| 4 | target projection compiler | 参数化 intent graph | 不碰 GROUND/SELECT |
| 5 | GROUND candidate domain | 点线面统一候选域 | 不碰 evaluator |
| 6 | relation evaluation package | 选择前后通用测量器 | 不碰 solver/workflow |
| 7 | demand/network service | 服务覆盖与网络子问题 | 不碰 generic evaluator |
| 8 | materialization scheduler/workers/planned state | task DAG 与 lineage | 不碰 solver |
| 9 | allocation/scenario solver | PlanningScenario | 不碰 workflow stage |
| 10 | validation | final measurement/reconciliation | 不碰 solver |
| 11 | workflow stages/artifact runtime | 主链集成 | 集中解决跨模块 wiring |
| 12 | delivery/scripts/docs | 交付与验收 | 最后执行 |

---

## 3. 冻结接口

Task 2 完成后，后续任务统一使用以下语义；字段名若因当前 Pydantic 兼容需要调整，Task 2 必须在 migration note 中给出唯一映射。

```python
RelationStatus = Literal[
    "pending",
    "satisfied",
    "partially_satisfied",
    "violated",
    "not_evaluable",
    "deferred",
]

class RelationMeasurement(BaseModel):
    value: float | int | bool | str | None = None
    unit: str = ""
    threshold: float | int | bool | str | None = None
    operator: Literal["lt", "lte", "eq", "gte", "gt", "contains", "connected"]
    method: str
    crs: str = ""
    network_ref: str = ""

class RelationSatisfaction(BaseModel):
    relation_id: str
    scenario_id: str
    status: RelationStatus
    subject_feature_refs: list[str]
    object_feature_refs: list[str]
    measurement: RelationMeasurement | None = None
    evidence_refs: list[str]
    evaluation_trace: list[str]
    evaluator_version: str

class ScenarioFeature(BaseModel):
    feature_id: str
    scenario_id: str
    target_id: str
    candidate_id: str
    geometry_kind: Literal["point", "line", "polygon", "multipatch"]
    geometry_wkt: str
    crs: str
    generation_operation: str
    source_refs: list[str]
    relation_ids: list[str]

class PlanningScenario(BaseModel):
    scenario_id: str
    parent_scenario_id: str = ""
    baseline_ref: str
    problem_fingerprint: str
    selected_candidate_ids: dict[str, str]
    feature_intents: list[ScenarioFeature]
    relation_satisfactions: list[RelationSatisfaction]
    metrics: dict[str, float]
    findings: list[dict[str, object]]
    status: Literal["draft", "partial", "complete", "failed"]
    fingerprint: str
```

关系参数必须是 template 对应的 typed model，而不是任意 dict：

```python
class DistanceParameters(BaseModel):
    max_distance_m: float
    metric: Literal["euclidean", "network"]
    network_ref: str = ""

class ServiceParameters(BaseModel):
    demand_ref: str
    facility_type: str
    max_travel_time_min: float
    min_coverage_ratio: float
    capacity: float
    capacity_unit: str
    network_ref: str

class ConnectParameters(BaseModel):
    network_kind: str
    endpoint_tolerance_m: float
    network_ref: str

class PrecedesParameters(BaseModel):
    required_event: Literal["start", "complete"] = "complete"
```

候选、factor 和 evaluator 使用稳定 ID；ID 来自 canonical payload hash，不来自数组位置或随机 UUID。

---

### Task 1: 锁定空图层首个丢失边界，建立非空垂直切片和零产出闸门

**Dependencies:** 无。可与 Task 2、3 并行。
**Owned files:** characterization、交付零产出闸门、map projection 和真实运行审计。Task 11/12 在本任务合并后再修改重叠文件。

**Files:**

- Create: `backend/tests/characterization/test_relation_aware_current_baseline.py`
- Create: `backend/tests/characterization/fixtures/jintian_minimal_planning_problem.json`
- Create: `backend/tests/integration/test_demo_non_empty_planning_vertical_slice.py`
- Create: `scripts/audit_planning_layer_quality.py`
- Modify: `scripts/run_pipeline_real_jintian.py`
- Modify: `backend/app/domain/delivery/gate.py`
- Modify: `backend/app/workflow/stages/deliver.py`
- Modify: `backend/app/application/projections/delivery.py`
- Create: `docs/superpowers/sdd/2026-08-17-relation-aware-gap-closure/baseline.md`
- Test: `backend/tests/characterization/test_relation_aware_current_baseline.py`
- Test: `backend/tests/integration/test_demo_non_empty_planning_vertical_slice.py`

**Interfaces:**

```python
def audit_planning_layer_quality(
    run_dir: Path,
    *,
    require_complete_hard_relations: bool = True,
) -> PlanningLayerQualityReport: ...

def trace_spatial_yield(state: PlanningState) -> list[StageSpatialYield]: ...
```

`StageSpatialYield` 按 PlanningProgram → TargetProjection → Grounding → Selection → Execution → PlannedState → DeliverySnapshot → RenderLayers 记录输入数、输出数、deferred 数、非 baseline feature 数和 artifact digest。`PlanningLayerQualityReport` 至少记录 target、candidate、selected、materialized、deferred、orphan feature、hard relation status、geometry validity、network evaluability、artifact digest 和 scenario fingerprint 数量。

- [ ] Step 1: 写 characterization test，固定当前 2026-08-17 事实：活动 demo 没有规划 delivery refs；隔离历史运行的 complete planned layer 有 660 个 baseline feature 但 actual changed=0，仅有 17 project points、16 facility points，且没有 planned road/zone/change layer。
- [ ] Step 2: 使用最小 fixture 表达一个有 exact point/parcel evidence 的卫生室和一个有真实端点/routing evidence 的道路；它们必须从 PlanningProgram 主链进入 RenderLayers，不能读取 `data/gis/jintian/planned` 或 dimension report 直接绘图。
- [ ] Step 3: 写失败的 integration test，逐阶段断言 spatial yield：target > 0、candidate > 0、selected > 0、active task > 0、materialized feature > 0、planned overlay feature > 0、`/map-layers` feature count > 0；失败消息必须指出第一个从正数变成零的阶段。
- [ ] Step 4: 实现只读 audit/trace 脚本。脚本区分 current/baseline feature、actual land change、project marker、facility、road、zone、axis；静态 `data/gis/jintian/planned` 和 standalone render 不计为 workflow 产出。
- [ ] Step 5: 修改 DELIVER gate：所有 planning overlays 的 feature 总数为 0，或 complete planned 与 current 等价且没有其他 materialized feature 时，状态必须为 `no_planning_output`/`partial`，不得发布 `complete` 或 `delivery_ready`。
- [ ] Step 6: 修改 map projection 和真实运行脚本，输出每层 feature count、non-baseline count、artifact ref；空规划层返回可诊断状态，不用空 FeatureCollection 伪装正常成功。

- [ ] Step 7: 在 `baseline.md` 记录 `pytest.ini` marker 陷阱、本次 19 passed / 3 failed、活动 demo 无 delivery ref、历史 0 changed feature 和 standalone PNG 非主链产物的证据。

- [ ] Step 8: 运行：

```powershell
pytest -o addopts='' -p no:cacheprovider -q backend/tests/characterization/test_relation_aware_current_baseline.py
pytest -o addopts='' -p no:cacheprovider -q backend/tests/integration/test_demo_non_empty_planning_vertical_slice.py
python scripts/audit_planning_layer_quality.py --help
```

- [ ] Step 9: 自审受控 fixture 的非空 feature 确实经过 artifact/snapshot/render 主链；不得通过放宽 gate、复制 baseline、载入静态 planned 文件或在 renderer 中生成 feature 使测试通过。提交：

```powershell
git add backend/tests/characterization backend/tests/integration/test_demo_non_empty_planning_vertical_slice.py scripts/audit_planning_layer_quality.py scripts/run_pipeline_real_jintian.py backend/app/domain/delivery/gate.py backend/app/workflow/stages/deliver.py backend/app/application/projections/delivery.py docs/superpowers/sdd/2026-08-17-relation-aware-gap-closure/baseline.md
git commit -m "fix: fail closed on empty planning delivery"
```

**Done when:** 受控 typed program 的主 workflow 能在 `/map-layers` 返回至少一个真实规划 feature；零规划 feature 的运行不会显示成功；真实 demo 仍为空时，audit 能精确指出第一个归零阶段，而不是只报告“图层为空”。

---

### Task 2: 冻结 PlanningIntentGraph v2、候选、factor、scenario 和 satisfaction 契约

**Dependencies:** 无。所有规划实现任务的接口前置。
**Owned files:** planning/spatial contracts 和对应 contract tests。

**Files:**

- Modify: `backend/app/contracts/planning/intent_graph.py`
- Modify: `backend/app/contracts/planning/constraint_factor.py`
- Modify: `backend/app/contracts/spatial/candidate_geometry.py`
- Modify: `backend/app/contracts/spatial/grounded_problem.py`
- Create: `backend/app/contracts/planning/scenario.py`
- Create: `backend/app/contracts/planning/relation_parameters.py`
- Modify: `backend/app/contracts/workflow/parse_result_contracts.py`
- Create: `backend/app/contracts/migrations/planning_v1_to_v2.py`
- Test: `backend/tests/contracts/test_relation_aware_planning_v2_contracts.py`
- Test: `backend/tests/contracts/test_planning_v1_to_v2_migration.py`

**Required contract changes:**

- `PlanRelationIntent` 增加 typed `parameters`、`source_claim_refs`、`source_binding_refs`、`weight`、`geometry_scope` 和 schema version。
- `CandidateGeometry` 增加 `candidate_id`、`target_id`、`source_bsms`、`generation_operation`、`hard_constraint_status`、`suitability_components`。
- `ConstraintFactor` 增加 `evaluator_key`、typed parameters、subject/object candidate domain refs、hard/weight、network refs。
- `GroundedPlanningProblem` 增加 baseline、bindings、candidate domains、networks/shared resources、unresolved/deferred、source artifact refs、fingerprint。
- `RelationSatisfaction` 按冻结接口扩展；兼容读取旧 unknown/deferred artifact，但写出一律为 v2。
- `PlanningScenario` 与 `ScenarioFeature` 成为正式契约。
- parse result 的 intent graph 从 `Any` 改为明确类型。

- [ ] Step 1: 先写失败测试：`near` 缺 `max_distance_m`、`serve` 缺 demand/network/capacity、`connect` 缺 endpoint tolerance 均被拒绝。
- [ ] Step 2: 写 candidate ID 稳定性测试：字段顺序变化不改变 ID，geometry/source/target 改变会改变 ID。
- [ ] Step 3: 写 hard relation 完整性测试：`pending/not_evaluable/deferred/violated` 中任一状态存在时 scenario 不能声明 complete。
- [ ] Step 4: 写 lineage 测试：ScenarioFeature 缺 scenario/target/candidate/source/generation operation 任一项都验证失败。
- [ ] Step 5: 实现 typed parameters 和 model validators；不接受任意 template/parameter 组合。
- [ ] Step 6: 实现 v1 → v2 显式 migration。旧 relation 没有参数时迁移为 `deferred` 并带 `migration_missing_parameters` finding，而不是猜默认阈值。
- [ ] Step 7: 为所有模型实现 canonical fingerprint；列表中具有集合语义的字段在 hash 前稳定排序。
- [ ] Step 8: 运行：

```powershell
pytest -o addopts='' -p no:cacheprovider -q backend/tests/contracts/test_relation_aware_planning_v2_contracts.py backend/tests/contracts/test_planning_v1_to_v2_migration.py
```

- [ ] Step 9: 自审序列化 round-trip、Pydantic error message、旧 artifact migration；提交：

```powershell
git add backend/app/contracts backend/tests/contracts/test_relation_aware_planning_v2_contracts.py backend/tests/contracts/test_planning_v1_to_v2_migration.py
git commit -m "feat: define relation-aware planning v2 contracts"
```

**Done when:** 后续任务不需要 `Any`、自由 dict 或隐藏默认值即可表达可测量关系、typed candidate 和单方案账本。

---

### Task 3: 完成 Explore router、query plan、sufficiency 与 gate-driven retrieval

**Dependencies:** 无。可独立于规划 contract 开发。
**Owned files:** evidence retrieval、Explore route、对应 tests。

**Files:**

- Create: `backend/app/evidence/retrieval/router.py`
- Create: `backend/app/evidence/retrieval/query_planner.py`
- Create: `backend/app/evidence/retrieval/sufficiency.py`
- Create: `backend/app/evidence/retrieval/retrievers/artifact_retriever.py`
- Create: `backend/app/evidence/retrieval/retrievers/history_retriever.py`
- Create: `backend/app/evidence/retrieval/retrievers/integrity_retriever.py`
- Modify: `backend/app/evidence/retrieval/evidence_service.py`
- Modify: `backend/app/evidence/retrieval/retrievers/report_retriever.py`
- Modify: `backend/app/evidence/retrieval/retrievers/kg_retriever.py`
- Modify: `backend/app/evidence/retrieval/retrievers/bundle_retriever.py`
- Modify: `backend/app/workflow/conversation/edges.py`
- Test: `backend/tests/core/test_explore_query_plan_and_sufficiency.py`
- Test: `backend/tests/core/test_explore_gate_retrieval_loop.py`
- Test: `backend/tests/core/test_explore_cache_versioning.py`

**Interfaces:**

```python
def route_request(request: ExplorationRequest) -> list[RetrieverKind]: ...
def build_query_plan(request: ExplorationRequest) -> EvidenceQueryPlan: ...
def evaluate_sufficiency(
    request: ExplorationRequest,
    response: ExplorationResponse,
) -> SufficiencyDecision: ...
async def satisfy_pending_requests(
    state: PlanningState,
) -> EvidenceLoopResult: ...
```

- [ ] Step 1: 测试 spatial lookup、artifact lookup、history lookup、data integrity 五类请求只路由必要 retriever；不再固定全查。
- [ ] Step 2: 测试 query plan 使用 questions、required facts、known gaps、entity scope 和 upstream artifact refs 生成稳定子查询。
- [ ] Step 3: 测试 sufficiency 区分 `sufficient`、`missing_fact`、`ambiguous`、`source_unavailable`、`insufficient_geometry`，并给出下一步 request。
- [ ] Step 4: 测试 `_route_explore()` 消费 pending requests：最多两轮 evidence loop；新 evidence digest 不变时停止并转人工/上游修正，不盲目重跑全部 dimensions。
- [ ] Step 5: 修复 cache key，加入完整 request fingerprint、retriever versions、source artifact digests；删除按前 80 字符去重，改用 normalized typed fact hash。
- [ ] Step 6: report/KG/bundle retriever 真正消费 query/entity scope；integrity retriever输出 CRS、字段、覆盖、空值和数据版本事实。
- [ ] Step 7: 明确 `run_rag()` 迁移策略：主 prompt 只使用 EvidenceResponse 渲染结果；旧 RAG 作为一个 retriever adapter，禁止 worker 双重拼接。
- [ ] Step 8: 运行：

```powershell
pytest -o addopts='' -p no:cacheprovider -q backend/tests/core/test_explore_query_plan_and_sufficiency.py backend/tests/core/test_explore_gate_retrieval_loop.py backend/tests/core/test_explore_cache_versioning.py backend/tests/core/test_explore_evidence_cache.py
```

- [ ] Step 9: 提交：

```powershell
git add backend/app/evidence/retrieval backend/app/workflow/conversation/edges.py backend/tests/core/test_explore_*.py
git commit -m "feat: close the explore evidence retrieval loop"
```

**Done when:** gate 的具体缺口能触发有范围的检索、sufficiency 能终止循环、缓存对问题和数据版本敏感，且 worker 不再并列注入两套 RAG 上下文。

---

### Task 4: 将 Target Projection 关系草图编译为参数化 PlanningIntentGraph v2

**Dependencies:** Task 2。
**Owned files:** target projection compiler/mapper 和 tests。

**Files:**

- Modify: `backend/app/domain/program/target_projection/intent_graph_compiler.py`
- Modify: `backend/app/domain/program/target_projection/compile.py`
- Modify: `backend/app/data/ingestion/compiler/spec_mapper.py`
- Create: `backend/app/domain/program/target_projection/relation_catalog.py`
- Create: `backend/app/domain/program/target_projection/relation_validator.py`
- Test: `backend/tests/core/test_parameterized_intent_graph_compiler.py`
- Test: `backend/tests/core/test_relation_type_compatibility.py`
- Modify: `backend/tests/core/test_target_projection_semantic_contract.py`

**Interfaces:**

```python
def compile_intent_graph_v2(
    program: PlanningProgram,
    *,
    observations: list[EvidenceObservation],
    bindings: list[GroundedEntityBinding],
) -> PlanningIntentGraph: ...

def validate_relation_intent(
    relation: PlanRelationIntent,
    node_index: Mapping[str, PlanTargetNode],
) -> list[PlanningDiagnostic]: ...
```

- [ ] Step 1: 先修复已有三项 core failure：旧 road fixture 给出正确 `asset_kind="road"`，确认不是放松生产 validator。
- [ ] Step 2: 测试 `facility serve settlement` 必须有 demand/network/capacity 参数；`road connect facility` 必须有 network kind/end tolerance；`utility precedes facility` 允许显式完成事件。
- [ ] Step 3: 测试 template 的 subject/object type compatibility；非法组合进入 diagnostic 并让 hard relation deferred，不静默丢弃。
- [ ] Step 4: 实现 relation catalog，列出每个模板允许的 target/entity/network 类型、必需参数、evaluator key 和 hard/soft 默认策略。
- [ ] Step 5: 从 typed `spatial_requirements`、intervention dependency 和已绑定 observation 编译 relation；不从名字关键词猜 relation。
- [ ] Step 6: 所有 dependency 关系保留 source intervention/evidence refs；没有证据的领域默认关系明确标记 `source_kind="domain_rule"`。
- [ ] Step 7: 修复 `_explicit_village_names` 只取第一个匹配的问题，并测试多个显式地名的 AND/OR 语义。
- [ ] Step 8: 运行：

```powershell
pytest -o addopts='' -p no:cacheprovider -q backend/tests/core/test_parameterized_intent_graph_compiler.py backend/tests/core/test_relation_type_compatibility.py backend/tests/core/test_planning_intent_graph_compiler.py backend/tests/core/test_target_projection_semantic_contract.py backend/tests/core/test_target_projection_location.py
```

- [ ] Step 9: 提交：

```powershell
git add backend/app/domain/program/target_projection backend/tests/core/test_parameterized_intent_graph_compiler.py backend/tests/core/test_relation_type_compatibility.py backend/tests/core/test_target_projection_semantic_contract.py
git commit -m "feat: compile parameterized planning relations"
```

**Done when:** 每条 hard relation 要么具有足够参数和类型进入 GROUND，要么带可解释 diagnostic/deferred 原因，不能只有一个无阈值的 relation 名称。

---

### Task 5: 把 CandidateSite 重构为点、线、面统一的 typed candidate domain

**Dependencies:** Task 2。
**Owned files:** GROUND aggregate/domain builder 和 tests；不实现关系测量。

**Files:**

- Create: `backend/app/domain/ground/candidate_domain_builder.py`
- Create: `backend/app/domain/ground/candidate_identity.py`
- Modify: `backend/app/domain/ground/aggregate.py`
- Modify: `backend/app/contracts/spatial/grounding_contracts.py`
- Modify: `backend/app/workflow/stages/ground.py`
- Test: `backend/tests/core/test_typed_candidate_domains.py`
- Test: `backend/tests/core/test_point_line_grounding_without_parcel_area.py`
- Modify: `backend/tests/core/test_typed_candidate_geometry.py`

**Interfaces:**

```python
def build_candidate_domains(
    intent_graph: PlanningIntentGraph,
    resolved_refs: Sequence[ResolvedSpatialRef],
    context: SpatialContext,
) -> list[GroundedTargetDomain]: ...
```

每个 domain 可同时拥有 exact execution geometry、anchor、corridor、parcel、zone、scope 候选；`CandidateSite` 只作为 polygon parcel adapter 保留，不再是所有 target 的总抽象。

- [ ] Step 1: 测试 exact POINT 没有 parcel area 仍能成为 facility 候选；exact LINE 没有 parcel area 仍能成为 road/linear execution 候选。
- [ ] Step 2: 测试 village scope、settlement scope 和 parcel union 不能成为 final point/line；它们只能生成 search/scope/corridor 候选。
- [ ] Step 3: 测试 candidate ID、source BSM、source ref、evidence、granularity、generation operation 和 hard status 全部保留。
- [ ] Step 4: 实现 candidate domain builder；把 `available_area_ha > 0` 条件限制到真正需要面积容量的 polygon targets。
- [ ] Step 5: 对 facility 同时保留 exact point/entrance candidates 与 parcel footprint candidates，并显式表达二者关系，不用 representative point 覆盖 exact evidence。
- [ ] Step 6: 对 road/utility 保留 endpoint、existing segment、corridor、execution line 不同 role。
- [ ] Step 7: GROUND 输出 v2 problem 的 candidate domain、bindings、baseline/source refs 和 fingerprint；不在此任务评估 relation。
- [ ] Step 8: 运行：

```powershell
pytest -o addopts='' -p no:cacheprovider -q backend/tests/core/test_typed_candidate_domains.py backend/tests/core/test_point_line_grounding_without_parcel_area.py backend/tests/core/test_typed_candidate_geometry.py
```

- [ ] Step 9: 提交：

```powershell
git add backend/app/domain/ground backend/app/contracts/spatial/grounding_contracts.py backend/app/workflow/stages/ground.py backend/tests/core/test_typed_candidate_domains.py backend/tests/core/test_point_line_grounding_without_parcel_area.py backend/tests/core/test_typed_candidate_geometry.py
git commit -m "refactor: ground targets into typed candidate domains"
```

**Done when:** 点/线目标不再因没有正面积面候选而消失，scope/corridor 也不会被误当最终几何。

---

### Task 6: 实现可复用的确定性关系 evaluator 与 factor 编译器

**Dependencies:** Task 2。
**Owned files:** 新 relation evaluation package 和 GROUND factor compiler。

**Files:**

- Create: `backend/app/domain/relations/__init__.py`
- Create: `backend/app/domain/relations/registry.py`
- Create: `backend/app/domain/relations/geometry_evaluators.py`
- Create: `backend/app/domain/relations/temporal_evaluator.py`
- Create: `backend/app/domain/relations/service.py`
- Modify: `backend/app/domain/ground/constraint_factors.py`
- Test: `backend/tests/core/test_relation_geometry_evaluators.py`
- Test: `backend/tests/core/test_relation_factor_compilation.py`
- Test: `backend/tests/core/test_precedes_execution_trace.py`

**Interfaces:**

```python
class RelationEvaluator(Protocol):
    evaluator_key: str

    def evaluate(
        self,
        factor: ConstraintFactor,
        features: Mapping[str, Sequence[ScenarioFeature]],
        context: RelationEvaluationContext,
    ) -> RelationSatisfaction: ...

def evaluate_relations(
    factors: Sequence[ConstraintFactor],
    features: Sequence[ScenarioFeature],
    context: RelationEvaluationContext,
) -> list[RelationSatisfaction]: ...
```

- [ ] Step 1: 写小型投影 CRS fixture，覆盖 `near/far/contain/avoid/adjacent/co_locate/connect/access_via/precedes` 的 satisfied 与 violated。
- [ ] Step 2: 测试距离 evaluator 拒绝在 EPSG:4326 上直接把 degree 当 meter；必须投影或返回 not_evaluable。
- [ ] Step 3: 测试缺 geometry、network、execution trace 分别返回 not_evaluable/deferred/pending，不返回 satisfied。
- [ ] Step 4: 实现 factor compiler，将 typed relation 参数、candidate domain refs 和 evaluator key 写入 factor。
- [ ] Step 5: 实现 geometry evaluator，记录 measurement、unit、threshold、CRS、feature refs、method 和 evaluator version。
- [ ] Step 6: `precedes` 只读取 ExecutionTrace 的 start/complete timestamp；删除编译阶段自动 satisfied。
- [ ] Step 7: evaluator registry 对未知 key fail-closed，返回 deferred + `unsupported_evaluator`。
- [ ] Step 8: 运行：

```powershell
pytest -o addopts='' -p no:cacheprovider -q backend/tests/core/test_relation_geometry_evaluators.py backend/tests/core/test_relation_factor_compilation.py backend/tests/core/test_precedes_execution_trace.py
```

- [ ] Step 9: 提交：

```powershell
git add backend/app/domain/relations backend/app/domain/ground/constraint_factors.py backend/tests/core/test_relation_geometry_evaluators.py backend/tests/core/test_relation_factor_compilation.py backend/tests/core/test_precedes_execution_trace.py
git commit -m "feat: evaluate planning relations deterministically"
```

**Done when:** 关系状态来自可重放的 measurement，而不是说明字符串；选择前后和最终验证可以复用同一 evaluator protocol。

---

### Task 7: 重建设施服务覆盖与网络子问题

**Dependencies:** Task 2。可与 Task 6 并行，最后通过 network evaluator adapter 对接。
**Owned files:** demand/suitability/facility network modules 和 tests。

**Files:**

- Create: `backend/app/spatial/network/network_graph.py`
- Create: `backend/app/spatial/network/service_area.py`
- Create: `backend/app/domain/demand/facility_demand_model.py`
- Modify: `backend/app/domain/suitability/spatial_factors.py`
- Modify: `backend/app/spatial/allocation/facility_location.py`
- Create: `backend/app/domain/relations/network_evaluators.py`
- Test: `backend/tests/core/test_facility_network_service_coverage.py`
- Test: `backend/tests/core/test_network_connectivity_relations.py`
- Test: `backend/tests/core/test_service_coverage_not_existing_facility_proximity.py`

**Interfaces:**

```python
def build_network_graph(
    road_features: Sequence[SpatialFeature],
    *,
    impedance: Literal["distance_m", "travel_time_min"],
) -> NetworkGraphSnapshot: ...

def evaluate_facility_service(
    facility: ScenarioFeature,
    demand: DemandSnapshot,
    network: NetworkGraphSnapshot,
    parameters: ServiceParameters,
) -> ServiceCoverageMeasurement: ...
```

- [ ] Step 1: 测试道路几何直线距离很近但网络不连通时 coverage 为 0/not reachable。
- [ ] Step 2: 测试 facility capacity 小于可达 demand 时 coverage 受容量限制。
- [ ] Step 3: 测试不同 facility type 只消费匹配 demand；卫生室不能满足消防站需求。
- [ ] Step 4: 写回归测试证明“靠近现状设施”不再被命名为 service coverage；如保留该指标，改名为 `existing_service_redundancy` 并默认作为惩罚/诊断。
- [ ] Step 5: 实现 network graph snapshot、snap tolerance、connected component、impedance shortest path 和版本 fingerprint。
- [ ] Step 6: 实现需求权重、容量分配、coverage ratio/travel-time measurement。
- [ ] Step 7: facility MCLP 改为可选 network impedance，haversine 只作为明确的 fallback diagnostic，不用于 hard service relation。
- [ ] Step 8: 注册 `serve/access_via/connect` network evaluators。
- [ ] Step 9: 运行：

```powershell
pytest -o addopts='' -p no:cacheprovider -q backend/tests/core/test_facility_network_service_coverage.py backend/tests/core/test_network_connectivity_relations.py backend/tests/core/test_service_coverage_not_existing_facility_proximity.py
```

- [ ] Step 10: 提交：

```powershell
git add backend/app/spatial/network backend/app/domain/demand/facility_demand_model.py backend/app/domain/suitability/spatial_factors.py backend/app/spatial/allocation/facility_location.py backend/app/domain/relations/network_evaluators.py backend/tests/core/test_facility_network_service_coverage.py backend/tests/core/test_network_connectivity_relations.py backend/tests/core/test_service_coverage_not_existing_facility_proximity.py
git commit -m "feat: model facility service on the road network"
```

**Done when:** 服务覆盖由需求、设施类型、容量、道路网络和时间阈值共同决定，不再等同于到现状设施或道路的直线距离。

---

### Task 8: 实现真正的 task-level ExecutionDAG 和 feature lineage

**Dependencies:** Task 2。可与 solver 工作并行。
**Owned files:** materialization scheduler、worker output lineage、planned state contracts/tests。

**Files:**

- Create: `backend/app/domain/materialization/task_scheduler.py`
- Modify: `backend/app/domain/materialization/plan_builder.py`
- Modify: `backend/app/domain/materialization/execute_agent.py`
- Modify: `backend/app/domain/materialization/worker_contract.py`
- Modify: `backend/app/domain/materialization/nodes/route_prepare.py`
- Modify: `backend/app/domain/materialization/planned_state_builder.py`
- Modify: `backend/app/contracts/spatial/planned_state_contracts.py`
- Modify: `backend/app/domain/materialization/facility_worker.py`
- Modify: `backend/app/domain/materialization/project_worker.py`
- Modify: `backend/app/domain/materialization/road_worker.py`
- Modify: `backend/app/domain/materialization/axis_worker.py`
- Modify: `backend/app/domain/materialization/nodes/facility_worker.py`
- Modify: `backend/app/domain/materialization/nodes/project_worker.py`
- Modify: `backend/app/domain/materialization/nodes/road_worker.py`
- Modify: `backend/app/domain/materialization/nodes/axis_worker.py`
- Test: `backend/tests/core/test_execution_task_dag_scheduler.py`
- Test: `backend/tests/core/test_scenario_feature_lineage.py`

**Interfaces:**

```python
def validate_execution_dag(plan: ExecutionPlan) -> DagValidationResult: ...
async def run_ready_tasks(
    plan: ExecutionPlan,
    completed_task_ids: set[str],
    worker_registry: WorkerRegistry,
) -> TaskBatchResult: ...
```

- [ ] Step 1: 测试跨 worker 和同 worker 的 `depends_on` 都控制执行；依赖未完成的 task 不进入 batch。
- [ ] Step 2: 测试 cycle、missing dependency、dependency on deferred task 都被 plan gate 拒绝并生成可解释 finding。
- [ ] Step 3: 用 task scheduler 替代固定 worker-type 拓扑作为执行顺序来源；worker type 只用于选择 handler 和并发池。
- [ ] Step 4: 每个 task 带 scenario、target、candidate、relation、expected geometry、capability 和 binding snapshot。
- [ ] Step 5: 每个 worker 直接输出完整 ScenarioFeature lineage；统一 project worker 的 `project_ref` 与 target id 语义。
- [ ] Step 6: 删除 PlannedStateBuilder 的“唯一目标自动补 target”分支；缺 lineage 的 feature 进入 execution error，不进入 PlannedState。
- [ ] Step 7: PlannedState 保存 scenario id、feature lineage 和 execution trace refs。
- [ ] Step 8: 保持 utility unsupported/deferred；scheduler 不把 deferred task 视为 completed dependency。
- [ ] Step 9: 运行：

```powershell
pytest -o addopts='' -p no:cacheprovider -q backend/tests/core/test_execution_task_dag_scheduler.py backend/tests/core/test_scenario_feature_lineage.py backend/tests/core/test_planning_intent_graph_compiler.py backend/tests/core/test_execute_routing_and_point_allocation.py
```

- [ ] Step 10: 提交：

```powershell
git add backend/app/domain/materialization backend/app/contracts/spatial/planned_state_contracts.py backend/tests/core/test_execution_task_dag_scheduler.py backend/tests/core/test_scenario_feature_lineage.py
git commit -m "feat: execute scenario tasks as a dependency dag"
```

**Done when:** `depends_on` 决定真实执行顺序，cycle fail-closed，任何最终 feature 都不依赖自动 lineage 猜测。

---

### Task 9: 实现关系感知 ScenarioSolver 和不可变单方案账本

**Dependencies:** Task 4、5、6、7。
**Owned files:** allocation/scenario solver 和 tests；不修改 workflow stages。

**Files:**

- Create: `backend/app/domain/allocation/scenario_solver.py`
- Create: `backend/app/domain/allocation/relation_terms.py`
- Create: `backend/app/domain/allocation/network_subproblem.py`
- Create: `backend/app/domain/allocation/scenario_builder.py`
- Modify: `backend/app/domain/allocation/global_site_select.py`
- Modify: `backend/app/spatial/allocation/global_site_allocator.py`
- Test: `backend/tests/core/test_relation_aware_scenario_solver.py`
- Test: `backend/tests/core/test_scenario_hard_relation_feasibility.py`
- Test: `backend/tests/core/test_scenario_network_cut.py`
- Test: `backend/tests/core/test_scenario_fingerprint_determinism.py`

**Interfaces:**

```python
def solve_scenario(
    problem: GroundedPlanningProblem,
    *,
    scenario_id: str,
    evaluator_context: RelationEvaluationContext,
) -> PlanningScenario: ...

def derive_network_cuts(
    provisional: PlanningScenario,
    problem: GroundedPlanningProblem,
) -> list[ScenarioCut]: ...
```

- [ ] Step 1: 测试 hard near/contain/avoid factor 改变 feasible set；soft factor 只改变 objective，不伪装成 hard constraint。
- [ ] Step 2: 测试两个单体高分候选因 pairwise relation 冲突时，solver 选择组合分数更高且 hard-feasible 的方案。
- [ ] Step 3: 测试 zone、facility/site、road endpoint 在同一 selected candidate ledger 中，不再由互不知情的独立结果拼接。
- [ ] Step 4: 保留现有 parcel capacity/exclusivity MIP 作为 master problem，增加 relation pair variables/linearized terms。
- [ ] Step 5: 对 network relation 采用 master + deterministic subproblem；不可达时返回 cut/replacement，不在通用 MIP 中伪造欧氏距离可达性。
- [ ] Step 6: 从 selected candidates 构造 pre-execution ScenarioFeature intents，并调用 Task 6/7 evaluator 生成预验证 satisfaction。
- [ ] Step 7: scenario 状态规则：所有 hard relations satisfied 才能 complete；有可恢复 deferred/not_evaluable 为 partial；hard violated 且无替代为 failed。
- [ ] Step 8: `fingerprint` 覆盖 problem、selected candidates、feature intents、measurement、evaluator/network versions；同输入稳定。
- [ ] Step 9: 第一阶段只要求生成一个可信 scenario；`max_scenarios > 1` 返回明确 unsupported capability，不用复制同一结果冒充多方案。
- [ ] Step 10: 运行：

```powershell
pytest -o addopts='' -p no:cacheprovider -q backend/tests/core/test_relation_aware_scenario_solver.py backend/tests/core/test_scenario_hard_relation_feasibility.py backend/tests/core/test_scenario_network_cut.py backend/tests/core/test_scenario_fingerprint_determinism.py
```

- [ ] Step 11: 提交：

```powershell
git add backend/app/domain/allocation backend/app/spatial/allocation/global_site_allocator.py backend/tests/core/test_relation_aware_scenario_solver.py backend/tests/core/test_scenario_hard_relation_feasibility.py backend/tests/core/test_scenario_network_cut.py backend/tests/core/test_scenario_fingerprint_determinism.py
git commit -m "feat: solve a relation-aware planning scenario"
```

**Done when:** SELECT 的最小产物是有完整关系状态和稳定指纹的 PlanningScenario，而不是独立 assignments 加一个装饰性 scenario id。

---

### Task 10: 从最终几何独立复测关系并进行 solver/evaluator reconciliation

**Dependencies:** Task 6、8。
**Owned files:** validation/review 和 tests。

**Files:**

- Create: `backend/app/domain/validation/relation_validation.py`
- Create: `backend/app/domain/validation/scenario_reconciliation.py`
- Modify: `backend/app/domain/validation/validate_checks.py`
- Modify: `backend/app/domain/materialization/nodes/execution_review.py`
- Test: `backend/tests/core/test_final_relation_validation.py`
- Test: `backend/tests/core/test_solver_validator_reconciliation.py`
- Test: `backend/tests/core/test_cross_layer_topology_validation.py`

**Interfaces:**

```python
def validate_final_scenario(
    scenario: PlanningScenario,
    planned_state: PlannedState,
    problem: GroundedPlanningProblem,
    context: RelationEvaluationContext,
) -> FinalScenarioValidation: ...
```

- [ ] Step 1: 测试最终 worker geometry 偏离候选后，near/connect/contain relation 能从 satisfied 变为 violated。
- [ ] Step 2: 测试 facility、road、axis、parcel、zone 全部进入跨层 topology 集合；不只验证 parcels/zones。
- [ ] Step 3: 测试 accessibility 使用需求点到设施的 network measurement，不使用 planned parcel 平均质心。
- [ ] Step 4: 实现 final feature index，以 scenario/target/candidate 建索引；缺失或孤儿 feature 产生 hard finding。
- [ ] Step 5: 复用 evaluator protocol，但从 final geometry 重新计算，禁止直接信任 SELECT satisfaction。
- [ ] Step 6: reconciliation 比较 pre-execution 与 final measurement；阈值跨越、feature 替换、evaluator version 不一致均生成 finding。
- [ ] Step 7: delivery gate 规则：hard relation violated/not_evaluable/deferred 不得标 full success；允许输出 partial package，但 manifest 必须显式列出缺口。
- [ ] Step 8: 运行：

```powershell
pytest -o addopts='' -p no:cacheprovider -q backend/tests/core/test_final_relation_validation.py backend/tests/core/test_solver_validator_reconciliation.py backend/tests/core/test_cross_layer_topology_validation.py
```

- [ ] Step 9: 提交：

```powershell
git add backend/app/domain/validation backend/app/domain/materialization/nodes/execution_review.py backend/tests/core/test_final_relation_validation.py backend/tests/core/test_solver_validator_reconciliation.py backend/tests/core/test_cross_layer_topology_validation.py
git commit -m "feat: validate planning relations from final geometry"
```

**Done when:** 最终验收能回答每条关系测了什么、阈值是什么、哪些 feature 参与、为何通过/失败，并能发现执行几何偏离求解假设。

---

### Task 11: 将 Explore、Scenario、ExecutionDAG、Validation 接入主 workflow 与 artifact/resume

**Dependencies:** Task 3、8、9、10。
**Owned files:** workflow stages、artifact keys/runtime、integration tests。这是唯一集中修改 wiring 的任务。

**Files:**

- Modify: `backend/app/workflow/stages/target_projection.py`
- Modify: `backend/app/workflow/stages/ground.py`
- Modify: `backend/app/workflow/stages/select.py`
- Modify: `backend/app/workflow/stages/execute.py`
- Modify: `backend/app/workflow/stages/validate.py`
- Modify: `backend/app/workflow/stages/deliver.py`
- Modify: `backend/app/infrastructure/artifacts/runtime.py`
- Modify: `backend/app/infrastructure/runtime/planning_runtime_service.py`
- Modify: `backend/app/application/recovery/resume_service.py`
- Test: `backend/tests/integration/test_relation_aware_workflow_artifacts.py`
- Test: `backend/tests/integration/test_relation_aware_resume.py`
- Test: `backend/tests/integration/test_hard_relation_blocks_full_delivery.py`

**Artifact keys:**

```text
planning_intent_graph_v2
grounded_planning_problem_v2
planning_scenario_v1
execution_plan_v2
execution_trace_v1
final_relation_validation_v1
```

- [ ] Step 1: 写 integration test，证明每阶段只读上游不可变 artifact、写本阶段新 artifact；GROUND 不修改 projection，EXECUTE 不修改 scenario。
- [ ] Step 2: SELECT 调用 `solve_scenario()`；删除把 GROUND satisfaction 原样复制为选择结果的逻辑。
- [ ] Step 3: plan builder 只从 PlanningScenario 生成 active tasks；partial scenario 中被 hard relation 阻断的 target 进入 deferred/review，不物化。
- [ ] Step 4: EXECUTE 保存 task trace；VALIDATE 保存 final relation validation；DELIVER gate 使用 final validation。
- [ ] Step 5: 所有 artifact descriptor 包含 schema/version、producer stage、input digests、run/session、fingerprint、created time。
- [ ] Step 6: resume 以 input digest + producer version 判定复用；binding、network 或 relation evaluator version 改变时只失效受影响下游。
- [ ] Step 7: Explore evidence digest 不变时不得反复重跑；scenario/validation artifact 已完成且输入未变时 LLM call count 和 worker call count 都保持零增量。
- [ ] Step 8: 对旧 artifact 使用 Task 2 migration；无法迁移的 hard relation进入 durable deferred，不静默采用 baseline。
- [ ] Step 9: 运行：

```powershell
pytest -o addopts='' -p no:cacheprovider -q backend/tests/integration/test_relation_aware_workflow_artifacts.py backend/tests/integration/test_relation_aware_resume.py backend/tests/integration/test_hard_relation_blocks_full_delivery.py
```

- [ ] Step 10: 提交：

```powershell
git add backend/app/workflow/stages backend/app/infrastructure/artifacts/runtime.py backend/app/infrastructure/runtime/planning_runtime_service.py backend/app/application/recovery/resume_service.py backend/tests/integration/test_relation_aware_workflow_artifacts.py backend/tests/integration/test_relation_aware_resume.py backend/tests/integration/test_hard_relation_blocks_full_delivery.py
git commit -m "feat: integrate scenario planning artifacts into the workflow"
```

**Done when:** 主 workflow 的控制产物从 assignment 切换为 PlanningScenario，resume 可证明没有重复调用，并且 hard relation 缺失会控制执行与交付状态。

---

### Task 12: 交付方案说明、真实金田村验收与设计文档清理

**Dependencies:** Task 1、11。
**Owned files:** delivery presentation、scripts、acceptance、文档。不得修改求解逻辑来让 acceptance 变绿。

**Files:**

- Modify: `backend/app/contracts/artifacts/delivery_manifest_contracts.py`
- Modify: `backend/app/domain/delivery/delivery_snapshot_builder.py`
- Modify: `backend/app/domain/delivery/delivery_renderer.py`
- Modify: `backend/app/domain/delivery/delivery_validator.py`
- Modify: `backend/app/domain/delivery/gate.py`
- Modify: `scripts/run_pipeline_real_jintian.py`
- Modify: `scripts/render_integrated_map.py`
- Modify: `scripts/audit_planning_layer_quality.py`
- Create: `backend/tests/acceptance/test_real_relation_aware_jintian.py`
- Create: `docs/superpowers/sdd/2026-08-17-relation-aware-gap-closure/final-acceptance.md`
- Modify: `docs/design/modules/spatial-execution/06_TARGET_PROJECTION_EXECUTE.md`
- Modify: `docs/design/modules/explore/23_EXPLORE_RETRIEVAL_REDESIGN.md`
- Modify: `docs/design/modules/spatial-execution/28_RELATION_AWARE_SPATIAL_PLAN_GENERATION.md`
- Modify: `docs/design/27_IMPLEMENTATION_VS_DESIGN.md`

**Delivery requirements:**

- manifest 列出 scenario id/fingerprint、problem fingerprint、target/materialized/deferred counts、hard/soft relation status counts、final measurement refs、orphan count、network snapshot、artifact digests。
- 地图图层属性至少包含 scenario、target、candidate、relation、source、generation operation。
- 报告区分 `complete`、`partial`、`failed`，并列出每个 hard relation 的 measurement/threshold/status。

- [ ] Step 1: 写 acceptance preflight；真实数据或 provider 未配置时明确 skip/fail reason，不生成伪造 pass。
- [ ] Step 2: 运行 fresh 金田村流程，保存 bundle/KG/network/evidence/problem/scenario/execution/validation digest 和实际计数。
- [ ] Step 3: 第二次 resume，断言已完成 artifact 被复用，LLM/worker 调用不增加，scenario/final validation fingerprint 不变。
- [ ] Step 4: 改变一个 relation threshold 或 entity binding，运行局部 replay，断言只失效相关 problem/scenario/execute/validate 下游。
- [ ] Step 5: 渲染 target projection、candidate domains、selected scenario、final layers、relation findings 五类图层；人工检查设施落点、道路端点、网络断连、禁止区穿越和图层偏移。
- [ ] Step 6: 运行质量 audit。最低 acceptance：至少一个来自主 workflow 的 non-baseline planning feature、至少一个非空 planning overlay、零 orphan、零 geometry-kind mismatch、零 hard violated/not_evaluable/deferred 才能标 complete；`complete_planned_landuse` 复制 current、静态 planned 输入和 standalone PNG 均不计数。不支持 utility 允许 partial，但必须显式计数。
- [ ] Step 7: 更新 06：标记 OR、GROUND mutation、列表依赖三条旧诊断已过时，并区分 schema/producer/consumer/validator/acceptance。
- [ ] Step 8: 更新 23：把 gate adapter 状态写成“函数存在、生产调用已在本任务接线”，记录 router/sufficiency/cache 的实际测试证据。
- [ ] Step 9: 更新 28/27：逐项链接实现、测试、真实 artifact 和仍 deferred 能力；不得用类存在替代 consumer/validator 证据。
- [ ] Step 10: 运行完整分层回归：

```powershell
pytest -o addopts='' -p no:cacheprovider -q backend/tests/contracts
pytest -o addopts='' -p no:cacheprovider -q backend/tests/core
pytest -o addopts='' -p no:cacheprovider -q backend/tests/integration
pytest -o addopts='' -p no:cacheprovider -q backend/tests/acceptance/test_real_relation_aware_jintian.py
```

- [ ] Step 11: 在 `final-acceptance.md` 记录所有命令、通过/失败/跳过数量、真实产物绝对路径、视觉检查结论和剩余 P1/P2。
- [ ] Step 12: 提交：

```powershell
git add backend/app/contracts/artifacts/delivery_manifest_contracts.py backend/app/domain/delivery scripts backend/tests/acceptance/test_real_relation_aware_jintian.py docs
git commit -m "feat: deliver and audit relation-aware planning scenarios"
```

**Done when:** 用户收到的不是一组没有语义保证的 GeoJSON，而是一份能从目标、证据、候选、方案、执行到最终关系测量完整追溯的交付包；不完整能力被明确标成 partial/deferred。

---

## 4. 主代理集成清单

每个子代理完成后，主代理按下列顺序审查，不直接信任“tests passed”摘要：

- [ ] 查看该任务 `git diff --stat` 和完整 diff，确认没有跨 owned files。
- [ ] 检查新模型没有 `Any`、自由 relation dict、隐藏 threshold 默认值。
- [ ] 检查测试命令包含 `-o addopts=''`，不是被默认 e2e marker 全部 deselect。
- [ ] 检查 GIS hard result 来自确定性 evaluator，不来自 LLM 字段或说明字符串。
- [ ] 检查 error/deferred 分支持久化原因和 lineage。
- [ ] 按依赖顺序 cherry-pick：1 → 2 → 4/5/6/7/8 → 9/10 → 3 → 11 → 12；同波次内部发生接口冲突时以 Task 2 schema 为准，Task 11/12 在 Task 1 的零产出闸门之上增量修改。
- [ ] 每个波次结束运行该波次全部 focused tests。
- [ ] Wave 2 后运行现有 8 个审计相关 core 文件，确认原有 3 个 semantic contract failure 已修复且没有新增回归。
- [ ] Wave 3 后运行 contract/core/integration/acceptance 四层测试并保存输出。

---

## 5. 非本轮目标

以下内容不应混入上述 P0 单方案闭环，避免任务失控：

- 多方案 Pareto frontier、diversity objective 和交互式方案编辑；单方案账本稳定后另开计划。
- 所有 utility worker 一次性实现；本轮只保留 capability registry/deferred，按供水、污水、雨水、电力分别规划。
- 用神经模型替代 deterministic GIS/network measurement。
- 大规模前端重构；delivery 只增加 scenario/relation 图层和清晰状态。
- 把视觉审查作为 hard relation 的替代品。
- 重建完整 graphify 知识图；实现完成后可单独刷新，不作为本计划验收依赖。

---

## 6. 最终验收矩阵

| 要求 | 必需证据 | 禁止替代证据 |
|---|---|---|
| 参数化关系 | v2 schema + invalid relation contract tests | 设计文档示例 |
| 点线面候选 | exact point/line 无 parcel area 的 core tests | 类字段存在 |
| 关系参与选择 | 组合候选改变最优解的 solver test | SELECT 结果带 relation 字段 |
| 网络服务 | disconnected/capacity/type tests + network snapshot | 欧氏/直线距离 |
| 单方案账本 | PlanningScenario artifact + stable fingerprint | `scenario_id` 字符串 |
| 执行依赖 | 同/跨 worker task DAG ordering test | ExecutionPlan 写了 depends_on |
| lineage | worker 直接写完整字段 + orphan=0 | PlannedState 自动补 target |
| 最终关系成立 | final geometry 独立 measurement | 复制 solver satisfaction |
| Explore 闭环 | pending request 触发检索且 sufficiency 终止 | helper 函数存在 |
| resume | 第二次调用计数为零且 digest 不变 | 日志写了 resume |
| 非空主链 | `/map-layers` 至少一个 non-baseline planning feature + 各阶段 yield | baseline 复制、静态 planned 文件、standalone PNG |
| 合理图层 | 真实运行 + audit + 图层人工审查 | 文件存在/几何 validity 单项 |

计划完成的定义不是“12 个任务都提交”，而是最终验收矩阵每一行都有可复现证据；任何未满足行必须把交付状态降为 partial，并在 manifest 和 final acceptance 中公开记录。

## Replay28 后续独立任务拆分（供子代理执行）

> **2026-08-18 执行状态覆盖：** F1/F2 已完成；F3 的 source-backed producer、resolver 和
> worker 边界已完成，并以真实金田道路文件验证到 GROUND，但 live target→source binding 尚未完成；
> F4 的 bounded solver/resume 合同已完成，真实二次调用计数仍待验收；F5 仍进行中。replay28
> 是 `PARTIAL/CLONE_ONLY` 证据，不是默认 live `COMPLETE`。详见
> `docs/design/10_IMPLEMENTATION_STATUS_CURRENT_20260818.md` 和修改台账。

以下任务以 replay28 的 `PARTIAL / CLONE_ONLY` 为基线，彼此通过 artifact contract 交接；每个任务只修改自己的 owned files，完成后提交报告、测试命令和进程清理证据。`REAL_RUN_ACCEPTED` 只在默认入口完成 fresh live、`/map-layers`、二次 resume 零增量和进程清理后才能使用。

### F1：map-layers 读侧与 artifact blob 解引用

- Owned：`scripts/audit_planning_layer_quality.py`、`backend/app/application/queries/workflow_state.py`、对应 map-layers/contract tests。
- 目标：让 descriptor-only branch refs 能通过同一 run-root 的 blob store 解引用；区分 current/baseline 与 selected planning layers；禁止无 manifest、无 snapshot 或无 render ref 时返回“有规划图层”。
- DoD：对 replay28 branch 解析出 15 render layers、selected planned feature 非空；对 baseline-only fixture 保持 `no_planning_output`；`/map-layers` integration test 通过。

### F2：设施/点几何 provenance 完整传递

- Owned：`backend/app/domain/materialization/nodes/facility_worker.py`、`worker_common.py`、facility lineage tests。
- 目标：保留 selected CandidateGeometry 的 `source_refs/source_bsms/geometry_ref` 到 PlannedFacility、FinalRelationValidation 和 RenderLayers；禁止只留下 `artifact:portfolio_decision`。
- DoD：4 个 replay28 facility Point 的最终 source refs 包含 authoritative source feature；orphan=0；不引入 centroid/representative point。

### F3：道路/轴线 source-ID 与 network binding

- Owned：`backend/app/data/ingestion/compiler/spec_mapper.py`、road/axis workers、KG/spatial adapters、network tests。
- 目标：为 existing road/axis 只接受显式 `source_feature_ids` 和 authoritative LineString/MultiLineString；绑定 endpoint/network snapshot；无 ID 继续 deferred/corridor candidate-only。
- DoD：至少一个 exact Line candidate 经 GROUND→SELECT→EXECUTE→DELIVER；Line 不由 parcel union、两点连线或 centroid 推导；disconnected/network relation 测试保留 fail-closed。

### F4：SELECT/EXECUTE deferred 与 resume 零增量验收

- Owned：`backend/app/domain/allocation/scenario_solver.py`、`backend/app/workflow/stages/select.py`、`execute.py`、resume/integration tests。
- 目标：验证 hard `violated` 终止组合，pending/unknown/deferred 进入 durable ledger；EXECUTE 只物化 passed selected candidates；第二次 resume 不增加 LLM/worker 调用且 scenario/final-validation fingerprint 不变。
- DoD：replay28 16 placed/154 deferred 计数稳定；复 resume 事件被正确拒绝或复用；无重复 worker output、无 baseline 注入。

### F5：fresh live demo 与最终文档回写

- Owned：`scripts/run_pipeline_real_jintian.py`、acceptance tests、`docs/design/27_IMPLEMENTATION_VS_DESIGN.md`、本文件与 final-acceptance。
- 目标：将 source-aware bundle/KG/branch 配置接入实际演示入口，记录绝对 artifact digest、`/map-layers` 响应和人工图层检查；不把 clone-only replay 冒充 live demo。
- DoD：fresh live run 至少有一个 non-baseline planning feature 和 overlay；partial/complete 状态与 deferred ledger 一致；运行前后无残留 Python/uvicorn；所有未实现 road/utility 能力继续显式标为 deferred。
