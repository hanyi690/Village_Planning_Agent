# 关系感知空间规划闭环验收记录

核验日期：2026-08-18

## 当前结论

状态：`PARTIAL / REAL_RUN_ACCEPTED`（真实主链已经产生非空、可追溯的规划图层；尚未达到 statutory-complete）。

关系感知 contracts、候选域、网络服务、ScenarioSolver、ExecutionDAG、最终几何验证、Explore
统一证据适配器和 SELECT/VALIDATE/DELIVER 的 fail-closed 接线已经完成代码级收敛。source-aware
replay28 已从 clean main root 真实走通 `TARGET_PROJECTION → GROUND → SELECT → EXECUTE →
VALIDATE → RECONCILE → DELIVER`，并生成同一 run 的 `render_layers`、`delivery_spatial_snapshot`
和 `delivery_manifest`。历史 `complete_planned_landuse`、静态 PNG 和没有实际变化的 checkpoint
仍不计入本验收。

最新真实重放 `relation_gap_real_20260817c`（从 GROUND 之后的历史 checkpoint 恢复）已经证明：
SELECT 能产生 68 个候选选择，EXECUTE 形成 28 个 candidate-backed parcel 和 29 个 overlay，
但 VALIDATE 发现 36 个真实硬约束冲突、151 个同权威层重叠和 11 个缺失最终 feature，因而按
策略暂停在 `RETRY_SELECT`。这次重放消费的是旧 GROUND artifact（161 个候选均缺失
`materialization_role`，其中 46 个为 coarse/village fallback），所以它是“旧 artifact 与新
验证边界的兼容性证据”，不是新 GROUND 规则已经通过真实验收的证据。

随后建立的可重复 fresh-GROUND branch `fresh-ground-20260817-test5` 已将粗粒度问题拆开：
GROUND 产出 6,699 个单 BSM 候选、9 个 unresolved，其中 3,512 个通过硬约束、3,187 个
失败。facility 仍为 parcel candidate，road/linear/axis 仍为 parcel/corridor candidate，
point/line exact feature 仍为 0；这不是 centroid 或入口猜测可以安全修复的缺口。继续到
SELECT 时，恢复脚本的自动 `resume-*` 分支与 fresh branch 冲突，随后产生 artifact branch
不一致，因此尚未获得同一 branch 的 scenario/execution/delivery 结论。当前空图层仍不能
归因于渲染丢失，也不能把本次 replay 基础设施失败误报成“没有可行地块”。

下一步不是继续从该旧 SELECT/EXECUTE checkpoint 修补计数，而是固定 replay branch 语义，
从 GROUND 之前的 checkpoint fresh 生成 `GroundedPlanningProblem`，核对
`materialization_role`、candidate domain 和 `hard_constraint_status`，然后重走
SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER。
在同一 fresh run 产生 `render_layers`、`delivery_spatial_snapshot` 和 `delivery_manifest`，
并由 `/map-layers` 读取到非 baseline feature 之前，本验收保持 `PARTIAL`。

对同一目录运行 `python scripts/audit_planning_layer_quality.py --run-dir
.run-tmp/runs/relation_gap_real_20260817c` 仍返回 `status=no_planning_output`、
`first_zero_stage=DeliverySnapshot`、`materialized_feature_count=0` 和
`planning_overlay_feature_count=0`。这是当前交付审计的有效结论；中间 `PlannedState` 只能证明
执行阶段有候选物化，不能替代 DELIVER named ref。

历史活动目录 `F:/project/Village_Planning_Agent/.run-tmp/runs/a178f66e-0dde-4903-8d13-3836e5cd9788`
的只读 audit 结果为：`status=no_planning_output`、`target_count=0`、`selected_count=0`、
`materialized_feature_count=0`、`non_baseline_feature_count=0`、`planning_overlay_feature_count=0`，
首个可观测零产出边界为 `DeliverySnapshot`；该目录没有 `spatial_yield` 或 `RenderLayers` payload。

## 已复核命令

以下命令均显式关闭仓库默认 e2e marker，避免“全量测试”实际没有执行核心用例：

```powershell
python -m compileall -q backend/app
pytest -o addopts='' -p no:cacheprovider -q backend/tests/contracts/test_relation_aware_planning_v2_contracts.py backend/tests/contracts/test_planning_v1_to_v2_migration.py backend/tests/core/test_parameterized_intent_graph_compiler.py backend/tests/core/test_relation_type_compatibility.py backend/tests/core/test_typed_candidate_domains.py backend/tests/core/test_point_line_grounding_without_parcel_area.py backend/tests/core/test_relation_geometry_evaluators.py backend/tests/core/test_relation_factor_compilation.py backend/tests/core/test_precedes_execution_trace.py backend/tests/core/test_facility_network_service_coverage.py backend/tests/core/test_network_connectivity_relations.py backend/tests/core/test_service_coverage_not_existing_facility_proximity.py backend/tests/core/test_execution_task_dag_scheduler.py backend/tests/core/test_scenario_feature_lineage.py backend/tests/core/test_final_relation_validation.py backend/tests/core/test_solver_validator_reconciliation.py backend/tests/core/test_cross_layer_topology_validation.py backend/tests/core/test_unified_rag_adapter.py backend/tests/integration/test_demo_non_empty_planning_vertical_slice.py
```

结果：`57 passed`（本次命令包含 manifest 缺失时 `/map-layers` fail-closed 回归用例；此前记录的
`56 passed` 已过期）。

专项 ScenarioSolver 命令结果：`7 passed`；关系最终复测、场景 reconciliation、跨层拓扑命令结果：
`6 passed`；关系 evaluator 加最终验证合计 `11 passed`，包含 network demand fail-closed。

确定性渲染验收：

```powershell
pytest -o addopts='' -p no:cacheprovider -q backend/tests/acceptance/test_complete_execution_render.py
```

结果：`1 passed`。该测试证明合成 bundle 的 GROUND→EXECUTE→Render 可以产出可渲染结果，不能替代
真实金田村主 workflow 的非空图层验收。

另有旧的 `backend/tests/acceptance/test_grounding_anchors_fixture.py` 在当前脏工作树中失败（fixture
期望的“社前”聚落簇未生成）；该失败发生在关系感知交付之前的 anchor fixture 断言，不被计入本轮
关系模块回归，但真实验收前仍需单独修复或明确基线。

核心目录回归的最新结果为 `624 passed, 1 failed`。唯一失败是
`backend/tests/core/test_spec_mapper_location_refs.py::test_generic_road_words_are_not_place_names`：
该 v1 characterization fixture 直接构造缺少 `asset_kind` 与 `road_parameters` 的道路干预，和当前
闭集 v2 道路资产契约不相容。没有为缺失资产语义静默填充默认值；该项应迁移 fixture，而不是放宽
canonical contract。

## 2026-08-18 source-aware replay28 真实证据

运行输入：

- checkpoint：`.run-tmp/wave3-replay2/checkpoints.db`，root `1f19a35a-c84e-68fc-8003-d022a8b240bf`；
- source-aware business clone：`.run-tmp/wave5-replay-source/village_planning_sourceaware_v3.db`；
- run root：`.run-tmp/wave3-replay15`，branch `resume-sourceaware-replay28-20260818`。

阶段结果：

| 阶段 | 结果 |
|---|---|
| TARGET_PROJECTION | 170 specs；`topological=107`、`composed=62`、`directional=1` |
| GROUND | 42 exact source-backed Point candidates；1,802 parcel candidates；329 corridor candidates；exact Line 仍为 0 |
| SELECT | 16 placed、154 deferred；16 worker tasks；deferred 保留 immutable ledger |
| EXECUTE | 16 scenario features：12 polygon/overlay 或 site/zone，4 facility Point；roads/axes 仍为 0 |
| VALIDATE | `final_relation_validation`：16 features、0 findings；validation checks 全部通过 |
| RECONCILE | 初次暴露 zero-area placeholder 与全量 deferred area range 的错误比较；修复后 PASS |
| DELIVER | `delivery_status=partial`、`statutory_complete=false`；manifest/snapshot/render refs 均存在 |

修复点：`check_quantitative_drift()` 只有在 PlannedState 存在正面积 parcel 时才执行面积范围比较；
overlay/facility-only 场景的 `area_ha=0` 占位值不再被当成真实测量，正面积 parcel 的原 5% 容差仍保留。
`backend/tests/characterization/test_wave3_validation_boundaries.py` 为此新增边界测试，结果 `4 passed`。

交付层质量（读取 `delivery_spatial_snapshot`/`render_layers` blob，而不是只看 baseline）：

- delivery manifest：`sha256:08bfced426b799333b3200b98b9f04045345d4c09a155ac2987132d78e0db00b`；
- spatial snapshot：`sha256:10e513b3b66ac5c06dc5c796f142e071d920d8659b395ff4cce6fefbb8529597`；
- render layers：`sha256:7ed08e53e0034d139ffe8c04facca9ae998011ba4c58a70065a2723bcc724267`；
- `quality_report.status=passed`，invalid/empty/placeholder geometry 均为 0，duplicate feature IDs 为 0；
- selected planned layers：facility=4、project=1、project-point=3、protection=4、restoration=4、zone=1；
- 660 个 `current/complete_planned_landuse` features 是 preserved baseline，不计入规划产出；规划产出来自上述 selected layers；
- 154 个 deferred target、155 个 pending human items 明确写入 manifest，故只能标 `partial`，不能标 `complete`。

`scripts/audit_planning_layer_quality.py` 直接对只含 descriptor refs 的 branch 目录会报告
`no_planning_output`，因为它不会自动解引用 run-root blob store；本次 acceptance 以同一 run 的
resolved delivery snapshot/render blob 和 manifest 为准，不能把该读侧工具的 descriptor-only 限制误判为渲染为空。

真实 resume 验收的 preflight 当前明确跳过：

```text
pytest ... backend/tests/acceptance/test_real_graph_resume_delivery.py
2 skipped
```

运行环境只有 `EXA_API_KEY`，没有配置 `LLM_PROVIDER` 对应的 provider key；因此没有伪造一次
“真实运行通过”。

## 尚未通过的矩阵行

| 矩阵行 | 当前证据 | 缺口 |
|---|---|---|
| 非空主链 | replay28 同一 branch 已有 scenario/execution/planned_state/final_validation/render/delivery refs | 仅 16/170 targets placed；整体仍为 partial |
| 合理规划图层 | replay28 selected layers：4 facility Points、12 polygon/overlay/site/zone features；quality report passed，relation findings=0 | 道路/轴线 exact Line 仍为 0；需补 source feature IDs/network bindings 后再验收线性层 |
| resume 零增量 | CAS/descriptor 代码和局部测试 | 需同一真实 run 第二次 resume，记录 LLM/worker 调用计数与 fingerprint 不变 |
| network service | disconnected、capacity、facility type、typed demand tests；delivery manifest 保留 network/source refs | 当前 real run 未生成 road/axis worker output；network-backed utility 维持 deferred |

## 真实运行准入与完成标准

真实 provider 或数据未配置时，验收必须明确 `SKIP`/`BLOCKED` 原因，不能生成伪造通过。完成前必须
运行 `scripts/audit_planning_layer_quality.py --run-dir <真实run目录>`，并同时满足：

1. 主 workflow 产生至少一个 non-baseline planning feature 和一个非空 planning overlay；
2. `/map-layers` 从同一 run 的 `RenderLayers` named ref 读取这些 feature；
3. zero orphan、zero geometry-kind mismatch、zero hard `violated/not_evaluable/deferred`；
4. Scenario/FinalValidation fingerprint 在 resume 中保持不变，已完成 artifact 不增加 LLM/worker 调用；
5. manifest 明确列出 scenario、problem、relation measurements、network、artifact digests 与任何 partial/deferred。

补充读侧 fail-closed 结论：即使 `delivery_spatial_snapshot` 和 `render_layers` 存在，缺少
`delivery_manifest` 也不会从 `/map-layers` 暴露图层；返回 `no_planning_output` 和空 layers。
存在 manifest 但缺 snapshot/render refs 时同样降级为空规划输出。manifest 存在而 final relation
validation 缺失或 hard relation 失败时，DELIVER 会保留诊断图层但将 manifest 标记为 `partial`、
`statutory_complete=false`，不会宣称完整交付。
