# 校验盘点（死校验台账，以实际代码为准）

> 状态：`CURRENT`（事实台账）· 基准：`backend/app` 实际代码（核验日期 2026-08-15）
> 本文逐条列出实际存在的校验点：类型、失败严重度、路由、重试预算、指纹行为、可执行修复、是否已接 LLM，
> 并给出**死校验风险分级**与处置建议（处置细节见 26_LLM_VALIDATION_ORCHESTRATION.md）。
> 严重度：`error` 会进入语义重试或 gate 阻断；`warning`/`info` 只留痕不阻断。

## 0. 读法说明

- **类型**：`schema`（Pydantic 校验）/ `闭集`（enum/Literal）/ `确定性规则`（数值/范围/单位规则）/ `几何数学`（shapely 计算）/ `gate`（阶段门路由）/ `LLM修复`（已有 LLM 参与）。
- **死校验风险**：
  - `高`：失败必然触发无效重试或 HUMAN 阻断（无人值守会卡死），且无有效修复路径或修复不收敛。
  - `中`：失败会重试/阻断，但有确定性或 LLM 修复路径，收敛概率较高。
  - `低`：失败是真正的结构性错误或已能无损规范化。
- **预算**：`BUSINESS_RETRY_LIMIT=3`（阶段重试上限，`settings.py`）、`DIMENSION_RETRY_LIMIT=2`（维度 LLM 失败上限）、`L3_STRUCTURAL_COMPILE_RETRIES=2`、`L3_SEMANTIC_COMPILE_RETRIES=2`（`worker.py` 环境变量，默认 2）。

## A. L3 claim 编译校验（单位类"死校验"集中区）

| id | 位置（文件/函数） | 类型 | 严重度 | 触发 | finding/路由 | 重试目标/预算 | 指纹相同 | 可执行指令 | 已接LLM | 风险 | 处置建议 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `unsupported_measure_unit` | `domain/program/claim_draft.py::_measure_value` | 确定性规则（单位闭集） | error | 参数 measure 的单位不在 `_LENGTH_TO_M/_AREA_TO_HA` 等换算表 | `ERROR[unsupported_measure_unit]` → `claim_set_semantic_errors` → 语义修复环 | 语义重试 2 轮 → `program_rework` → L3 重试 3 次 → HUMAN/diagnostic | 相同 → HUMAN | 无（仅 diagnostic） | flash 单位修复先行（`flash_unit_repair.py`），失败即回退 | 高 | 单位修复前置：确定性别名/typo 建议 + flash 兜底；仍未知单位 → 目标级 defer，不 error |
| `unsupported_area_unit` | `claim_draft.py::_normalize_polygon_parameters` | 确定性规则（面积单位） | error | `area_range.unit` 不在 `_AREA_TO_HA` | 同上 → 语义修复环 → program_rework | 同上 | 同上 | 无 | 同 flash 先行 | 高 | 面积单位未知 → 丢弃该约束记 warning 或 defer 目标 |
| `incomplete_area_range` | `claim_draft.py` | 确定性规则 | error | area_range 缺 min 或 max | 同上 | 同上 | 同上 | 无 | 无 | 高 | 缺 min/max → 视为范围未定（保留 evidence）降 warning |
| `invalid_area_range` | `claim_draft.py` | 确定性规则 | error | min<=0 或 max<min | 同上 | 同上 | 同上 | 无 | 无 | 中 | 数值口径错误 → LLM 修复或 defer |
| `count_unit_as_area_dropped` | `claim_draft.py` | 确定性规则（规范化） | warning | 计数单位（处/个/座/点/人/户…）当作面积 | 丢弃面积约束，仅留痕 | 无重试 | — | 无 | 无 | 低（已修） | 保持现状 |
| `invalid_road/facility/axis/polygon/project_parameters` | `claim_draft.py::_normalize_*` | 闭集/schema | error | 参数对象字段违反闭集或 Pydantic | ERROR → 语义修复环 → program_rework | 同上 | 同上 | 无 | 语义修复环用 LLM 局部重生成失败 claim | 高 | 修复提示只改出错字段；枚举冲突交给 `semantic_repair` 闭集 patch |
| `unitless_quantity` | `claim_draft.py` | 确定性规则 | warning | quantity 有值但无 quantity_unit | 保留为无量纲 | 无 | — | 无 | 无 | 低 | 保持现状 |
| `phase_normalized` / `category_output_mismatch` / `materialization_role_mismatch` | `claim_draft.py` | 闭集规范化 | warning | 枚举不合法 | 无损归一化 | 无 | — | 无 | 无 | 低 | 保持现状 |
| 结构编译失败 | `worker.py::_normalize_with_structural_repair` | schema | error | 结构化输出违反 schema/闭集 | 反馈错误重生成（`L3_STRUCTURAL_COMPILE_RETRIES=2`）→ 耗尽抛异常 → `dimension_retry_counts` | 维度 2 次 | — | 无 | 有（反馈式重生成） | 中 | 保持；预算扣减已在 |
| 语义编译失败 | `worker.py`（semantic 修复环）| LLM修复 | error | `claim_set_semantic_errors` 非空 | 局部重生成失败 claim（`L3_SEMANTIC_COMPILE_RETRIES=2`）→ 耗尽 append `semantic_compile_exhausted`（ERROR） | 同上 → program_rework | — | 无 | 有 | 高 | 修复只针对 validator_errors 指出的字段；仍失败 → defer，不再整维度重跑 |
| L3 gate 矛盾 | `domain/program/gate.py::evaluate_l3_gate` | gate | error（program_issues） | 任一 `severity=error` 且 code != `classification_decision_required` | `program_rework`（`RETRY_L3`）| 整维度重试（autonomous 决策把 approve 转 retry）| 相同 → HUMAN | 无 | 无（仅有语义修复前置） | 高 | error 中属"单位/参数口径"类的应先规范化；仅真实矛盾才 rework |
| `classification_decision_required` | `gate.py` | gate | error（显式排除） | 空间 polygon/parcel 目标缺分类决定 | `HUMAN`（不进入矛盾 rework） | 无 | — | 无 | 无 | 中 | 保留 HUMAN（法定边界），不自动猜测 |

## B. post-L3 各 gate

| 阶段 | gate 函数 | 路由 | 严重度语义 | 重试目标/预算 | 指纹相同 | 可执行指令 | 已接LLM | 风险 | 处置建议 |
|---|---|---|---|---|---|---|---|---|---|
| target_projection | `domain/program/target_projection/gate.py::evaluate_target_projection_gate` | PASS / HUMAN / L3 | 有 error diagnostic → L3；空/NEEDS_REVIEW → HUMAN | 策略表无 L3/REPAIR/REVISE 命中 → 落默认 HUMAN | — | 无 | 无 | 高（路由不一致：gate 发 L3，策略表落 HUMAN） | gate 语义与策略表对齐：error diagnostic 应回 L3 或 defer |
| ground | `domain/ground/gate.py::evaluate_ground_gate` | PASS / EXPLORE / HUMAN | unresolved → HUMAN；无候选 → EXPLORE | EXPLORE → retry ground（证据重取）| 相同 → HUMAN | 无（unresolved 需人工或 evidence） | flash 提及增强（`_flash_enhance_unresolved`，仅 unresolved 减少才采纳） | 高（无人值守 unresolved → HUMAN 卡住） | unresolved 目标 → 目标级 defer；flash 增强失败不阻断 |
| select | `domain/allocation/select_gate.py::evaluate_select_gate` | PASS / HUMAN | unplaced>0 或 top score<threshold(0.4) 或 portfolio solver 非 OPTIMAL/FEASIBLE → HUMAN | 无重试（直接 HUMAN） | — | 消费 repair_directives（exclude_bsms/reallocate）| 无 | 高（unplaced/低置信 → HUMAN 卡住） | 低置信/未放置 → LLM triage 判定重选或 defer |
| execute | 无 gate（显式豁免 `route_after_execute`） | 仅 fatal_error → END_DIAGNOSTIC | L4 写失败/worker 超时 | 无（fatal 即诊断） | — | 消费 repair_directives（exclude_bsms/rebuild_strategy）| 无 | 低 | 保持 |
| validate | `domain/validation/validate_gate.py::evaluate_validate_gate` | PASS / RETRY_EXECUTE / RETRY_SELECT / RETRY_GROUND / RETRY_L3 / RETRY_TARGET_PROJECTION / HUMAN | 按 error 数最多阶段路由；平局/warnings-only → HUMAN | `_retry_or_human`（3 次）；`identical`/`inputs_changed=False` → HUMAN | 相同 → HUMAN | `RepairDirectiveCompilation`（见 C）| 无（LLM 不在 validate 内） | 高（"三轮不变"几何校验） | 见 C 处置 + 26 号编排 |
| reconcile | `domain/validation/reconcile_gate.py::evaluate_reconcile_gate` | PASS / RETRY_L3 / RETRY_EXECUTE / HUMAN | error 最多阶段路由 | retry 3 次；无进展 → HUMAN | 相同 → HUMAN | 无 | 无 | 中 | 覆盖缺口 → 目标级 defer 或定向 L3 修复 |
| deliver | `domain/delivery/gate.py::evaluate_deliver_gate` | PASS（complete/partial）/ END_DIAGNOSTIC | 有未搁置 blocker → diagnostic | 无 | — | DeferralLedger 已存在 | 无 | 低 | 保持（partial 即可交付） |

## C. VALIDATE 10 项确定性检查 + RepairDirective 映射（`validate_checks.py` + `repair_directives.py::_POLICIES`）

> 实际检查 **10 个**（文档字符串写"Nine"是过时描述）。`repair_directives._POLICIES` 是 finding code → 指令类型的映射表。

| check_id | 位置 | 类型 | 失败 stage | 是否有指令 | 指令类型/策略 | 死校验风险 | 说明/处置 |
|---|---|---|---|---|---|---|---|
| `hard_constraints` / `constraint_index_unavailable` | `check_hard_constraints` | 几何数学 | SELECT | 有 | `EXCLUDE_BSMS` | 中 | constraint_index 缺失 → `constraint_index_unavailable` error 阻断；应允许无约束时跳过并记录 |
| `area_conservation` | `check_area_conservation` | 几何数学（5% 容差） | EXECUTE | 有 | `REBUILD_GEOMETRY(rebuild_from_authoritative_assignments)` | 高 | "三轮不变"重灾区；需进展护栏 + LLM 判定是否真误差 |
| `topology`（+validity/gaps） | `check_topology` | 几何数学 | EXECUTE | 有 | `REBUILD_GEOMETRY(repair_invalid_geometry)` | 中 | 有修复路径，但需确保 worker 真正消费 |
| `overlap` | `check_overlap` | 几何数学 | EXECUTE | 有 | `REALLOCATE` | 高 | "三轮不变"重灾区 |
| `continuity` | `check_continuity` | 几何数学 | EXECUTE | 有 | `REALLOCATE` | 中 | 同上 |
| `accessibility` | `check_accessibility` | 确定性规则 | SELECT | 无 | —（不在 `_POLICIES`）| 高 | 无指令 → 编译 blocked → HUMAN；需补指令或 defer |
| `contract_completeness` | `check_contract_completeness` | 确定性规则 | EXECUTE/L3 | 无 | — | 高 | 同上 |
| `classification_missing` | `check_classification_missing` | 确定性规则 | EXECUTE | 有 | `REQUIRE_SOURCE_EVIDENCE(authoritative_classification)` | 中 | 有指令；分类决定走 HUMAN 边界 |
| `traceability` | `check_traceability` | 确定性规则 | EXECUTE | 无 | — | 中 | 无指令 → blocked；应支持目标级 defer |
| `worker_failures` | `check_worker_failures` | 确定性规则 | EXECUTE | 无 | — | 中 | worker 失败应直接重派受影响 target，不整链重试 |

## D. 空间/跨维度校验

| id | 位置 | 类型 | 状态 | 风险 | 说明 |
|---|---|---|---|---|---|
| `MetricConflict`（5% 阈值） | `spatial/validation/detector.py` | 确定性规则 | **未接线**（全仓仅 detector/resolver 引用自身） | 低（不参与主链） | 跨维度指标冲突检测为侧线模块，主图未消费 |
| `ConstraintViolation` / `SpatialConflict` + resolver | `spatial/validation/resolver.py` | 确定性规则 | 未接线 | 低 | 维度优先级裁决未接入 |
| 候选可实施性硬过滤 | `domain/allocation/selection.py::_PROHIBITED_CONSTRAINTS` | 确定性规则 | 已接（validate `check_hard_constraints` 使用） | 中 | 建议保留为硬过滤 |

## E. 循环防护与预算（实际代码）

| 机制 | 位置 | 行为 |
|---|---|---|
| `gate_progress_metadata` | `domain/common/gate_progress.py` | 计算 `input_checksum`/`output_checksum`/`issue_fingerprint`/`inputs_changed`/`identical`；gate 对 `RETRY_*` 且 identical 或 inputs 未变 → 改判 HUMAN（`validate_gate.py`、`_retry_or_human`） |
| `_retry_or_human` | `workflow/root_graph.py` | 阶段重试预算 `BUSINESS_RETRY_LIMIT=3`，耗尽 → `END_DIAGNOSTIC`；validate 有可执行修复时允许重放 |
| `_dimension_retry_limit` | `root_graph.py` / `settings.py::DIMENSION_RETRY_LIMIT=2` | 维度 LLM 失败预算，耗尽 → HUMAN/provider resume |
| provider circuit | `dimension_runtime.py::provider_failure_open/trip_provider_failure` | 传输层熔断，避免全维度连锁重试 |
| `GRAPH_RECURSION_LIMIT=100` | `settings.py` | LangGraph 递归护栏 |

## F. 死校验高风险清单（按优先级）

1. **单位/参数口径 error → 整维度 program_rework**（A 组 `unsupported_measure_unit`、`unsupported_area_unit`、`incomplete_area_range`、`invalid_*_parameters`、`semantic_compile_exhausted`、L3 gate 矛盾）。`flash_unit_repair` 只是前置补丁，未知单位仍会 error 并进入重试环。
2. **VALIDATE 几何检查"三轮不变"**（C 组 `area_conservation`、`overlap`，部分 `topology`/`continuity`）：无进展重试 → 指纹相同 → HUMAN（无人值守卡死）。
3. **无 RepairDirective 的检查**（`accessibility`、`contract_completeness`、`traceability`、`worker_failures`）：finding 无法编译指令 → blocked → HUMAN。
4. **GROUND/select HUMAN 卡点**：unresolved / unplaced / 低置信直接 HUMAN，无自动 defer。
5. **gate 语义与策略表不一致**：`target_projection` gate 发 `L3`，`gate_policy` 表无该项 → 落默认 HUMAN。

## 关联

- 处置设计：`docs/design/26_LLM_VALIDATION_ORCHESTRATION.md`
- 模块/产物：`docs/design/24_MODULE_OUTPUT_INVENTORY.md`


## 8. 已落地修复（2026-08-15，代码已实现并测试）

以下条目已从“高/中风险死校验”降级为“有确定性处置”，无需再 HUMAN 卡死：

- `unsupported_measure_unit` / `unsupported_area_unit` / `incomplete_area_range` / `invalid_area_range` / `invalid_*_parameters` / `missing_claim_identity`：由 ERROR 降为 WARNING + 丢弃该约束（raw 单位保留在诊断消息中审计）；`claim_set_semantic_errors` 只保留结构契约错误（缺必需参数对象）。
- `constraint_index_unavailable`：无约束图层时直接跳过（not_applicable），不再产生不可修 blocker。
- 无处置检查（`accessibility` / `parcels_present` / `parcel_fields` / `changeset_flags` / `traceability` / `worker_failures`）：`validate_node` 在 repair compilation blocked 且带 target_ids 时，自动把受影响目标写入 `DeferralLedger`（reason=validate_auto_defer:no_repair_policy）并修订 ExecutionPlan（worker_tasks -> deferred_tasks），gate 转 PASS -> partial delivery，不再 `typed_repair_blocked` HUMAN。
- `target_projection` gate 的 `L3` 路由已加入 `GATE_ROUTE_POLICY`（有界重试，不再落默认 HUMAN）。
- 相同 `issue_fingerprint` 的可执行修复只允许 1 次重放（第 2 次 -> HUMAN/defer）；新增 per-session `VALIDATION_BUDGET_PER_SESSION`（默认 20）兜底，超限 -> END_DIAGNOSTIC。
- EXECUTE worker 子图超时不再硬抛异常，改为写 typed `execution_diagnostics` + fatal_error -> END_DIAGNOSTIC（避免 resume 循环吞掉真实原因）。
- `_approve_ground` / `_approve_default`：审批 GROUND 等阶段评审后按 `STAGE_FORWARD_TARGET` 继续（ground->select），不再静默 END 或回环 HUMAN（修复 run#6 post_l3 死态）。

关联：`docs/design/26_LLM_VALIDATION_ORCHESTRATION.md`（部分实施）、`docs/design/27_IMPLEMENTATION_VS_DESIGN.md`。
