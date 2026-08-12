# agent/reconcile 子包（RECONCILE 全链对账）

> RECONCILE 阶段：对**全链覆盖**做对账（intervention → spec → candidate → selection → change → planned），产出 `ReconciliationReport`（`CoverageMatrix` + inconsistencies）→ Reconcile gate。
> 验证"每个 L3 干预方案是否一路贯通到最终规划地块"，是 DELIVER 溯源清单的数据源。

---

## 职责边界

**做**：编排 6 项对账检查（`reconcile_aggregate`）：`check_intervention_coverage`、`check_spec_candidate_coverage`、`check_candidate_selection_coverage`、`check_selection_change_coverage`、`check_change_planned_coverage`、`check_quantitative_drift`，另加 `check_l3_l4_target_coverage`（L3 目标 vs PlannedState 一致性）；`build_coverage_matrix` 逐 intervention 追踪五环覆盖（`covered`/`partial`/`missing`）；`evaluate_reconcile_gate` 按主导责任阶段路由（L3 / EXECUTE / HUMAN）。

**不做**：不修复任何断链（只出 `ReconciliationInconsistency` 与覆盖矩阵）；不重新执行任何 stage；不调用 LLM / KG / MIP。对账为只读聚合：输入全部由 post-L3 链一次性注入，本目录不触发任何 stage 算法。

> 注：intervention→spec、spec→candidate 因契约无语义连接键，采用**位置配对**（PARSE/GROUND 按干预顺序产出）；candidate→selection 按 BSM 语义连接（顺序无关）。

### 目录文件

| 文件 | 职责 |
|---|---|
| `aggregate.py` | `reconcile_aggregate` / `build_coverage_matrix` / `check_l3_l4_target_coverage` |
| `checks.py` | 6 项 `check_*` 覆盖检查（确定性纯函数） |
| `gate.py` | `evaluate_reconcile_gate` / `reconcile_gate_route`：4 路门（纯函数） |
| `review.py` | `build_reconcile_review_package`：构造审查包 |

### 流程图

```
   planning_program + specs + grounding_result + site_selection
        + parcel_changeset + planned_state + intent
        │
        ▼
   reconcile_aggregate ──► 6 × check_*（checks.py）+ l3_l4_target_coverage
        │
        ├─► build_coverage_matrix：intervention → spec(i) → candidate(i) → selection(BSM) → change(BSM) → planned(BSM)
        │        每行状态 covered / partial / missing
        ▼
   ReconciliationReport（coverage_matrix + inconsistencies）
        │
        ▼
   evaluate_reconcile_gate ──┬─ PASS          → DELIVER
                             ├─ RETRY_L3      → 主导 stage=L3（post-L3 链转 human_review）
                             ├─ RETRY_EXECUTE → 主导 stage=EXECUTE → 回 execute
                             └─ HUMAN         → 平局 / 非可重试主导 stage
```

## 输入/输出契约

| 契约 | 文件 | 关键类型 |
|---|---|---|
| 对账报告（根产物） | `app/modules/schema/contracts/reconciliation_contracts.py` | `ReconciliationReport`、`CoverageMatrix`、`CoverageMatrixRow`、`ReconciliationInconsistency` |
| 全链输入 | `l3_contracts.py` / `spatial_reference_contracts.py` / `grounding_contracts.py` / `selection_contracts.py` / `parcel_change_contracts.py` / `planned_state_contracts.py` / `parse_contracts.py` | `PlanningProgram`、`SpatialReferenceSpec`、`GroundingResult`、`SiteSelectionDecision`、`ParcelChangeSet`、`PlannedState`、`SpatialPlanningIntent` |
| 门决定 | `app/modules/schema/contracts/workflow_contracts.py` | `GateDecision`、`PendingRequest`、`StageId` |

`reconcile_aggregate(...)` 返回 `ReconciliationReport`。DELIVER 的 `TraceabilityEntry` 直接由 `CoverageMatrixRow` 映射生成（Wave K → Wave L 桥）。

覆盖矩阵语义：`CoverageMatrixRow.status` 取五环（spec / candidate / selection / change / planned）全满足 → `covered`、部分满足 → `partial`、全缺 → `missing`；`spec_index` / `candidate_site_id` 为位置配对索引，`selected_bsm` / `change_bsm` / `planned_parcel_bsm` 按 BSM 语义连接（顺序无关）。`check_quantitative_drift` 对比规划目标面积与 `PlannedState` 实际面积，超差记 `ReconciliationInconsistency`。

## 依赖方向

**可导入**：`app/modules/schema/contracts/*`、`provenance.py`。

**禁止导入**：任何 LLM 层；各 stage 的实现（`parse`/`ground`/`select`/`execute`/`validate`/`deliver` 的内部函数——只经 typed 契约交互）。

## 禁止行为

- 不得在 RECONCILE 内调用任何 stage 的 aggregate / worker（它是纯聚合器，输入全部由 post-L3 链注入）。
- 不得把 `missing`/`partial` 覆盖静默视为通过（门必须看到 inconsistencies）。
- 不得猜测连接键（positional 配对是当前契约约束，不得伪造 intervention_id 语义键）。
- `gate.py` / `checks.py` 不得做 I/O 或调用 LLM。

---

## 相关文档

- `../README.md` — agent 编排层总览
- `../../workflow/root_graph.py` / `../../workflow/stages/reconcile.py` — RECONCILE 的 RETRY_* 回退路由
- `../validate/README.md` — VALIDATE（上游）
- `../deliver/README.md` — DELIVER（下游消费者：`CoverageMatrix` → `TraceabilityEntry`）
