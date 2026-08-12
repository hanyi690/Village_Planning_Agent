# agent/validate 子包（VALIDATE 规划校验）

> VALIDATE 阶段：`ParcelChangeSet` + `PlannedState` → 9 项确定性检查 → `ValidationReport` → Validate gate。
> 对 EXECUTE 产出做合规/几何/可达性校验，并按责任阶段把失败路由回对应上游 stage 重试。

---

## 职责边界

**做**：编排 9 项校验（`validate_aggregate`）：`hard_constraints`（硬约束）、`area_conservation`（面积守恒）、`topology`、`overlap`、`continuity`（连续性）、`accessibility`（可达性）、`contract_completeness`（契约完整性）、`classification_missing`（规划分类缺失）、`traceability`（溯源）；扁平化 `ValidationCheck[]` 为 `ValidationReport`（`overall_passed` / `issues_by_stage` / `adjustments` / `provenance`）；`evaluate_validate_gate` 按**主导责任阶段**路由（error 级问题最多者决定 RETRY_* 目标；平局或仅 warning → HUMAN）。

**不做**：不修复任何问题（只出诊断与 `ConstraintAdjustment` 建议）；不运行 EXECUTE / 不重排地块；不调用 LLM / KG / MIP。

### 目录文件

| 文件 | 职责 |
|---|---|
| `aggregate.py` | `validate_aggregate`：编排 9 项检查 → `ValidationReport` |
| `checks.py` | 9 项 `check_*` 函数（确定性纯函数） |
| `gate.py` | `evaluate_validate_gate` / `validate_gate_route`：5 路 + HUMAN 路由（纯函数） |
| `review.py` | `build_validate_review_package`：构造审查包 |

### 流程图

```
   PlannedState + ParcelChangeSet + layout_configs + intent + constraint_index
        │
        ▼
   validate_aggregate ──► 9 × check_*（checks.py）
        │                     ├─ hard_constraints / area_conservation / topology / overlap
        │                     ├─ continuity / accessibility / contract_completeness
        │                     └─ classification_missing / traceability
        ▼
   ValidationReport（overall_passed / issues_by_stage / adjustments）
        │
        ▼
   evaluate_validate_gate ──┬─ PASS          → RECONCILE
                            ├─ RETRY_EXECUTE → 主导 stage=EXECUTE
                            ├─ RETRY_SELECT  → 主导 stage=SELECT
                            ├─ RETRY_GROUND  → 主导 stage=GROUND
                            ├─ RETRY_L3      → 主导 stage=L3（post-L3 链转 human_review）
                            ├─ RETRY_PARSE   → 主导 stage=PARSE
                            └─ HUMAN         → 多 stage 平局 / 仅 warning
```

## 输入/输出契约

| 契约 | 文件 | 关键类型 |
|---|---|---|
| 校验报告（根产物） | `app/modules/schema/contracts/validation_report_contracts.py` | `ValidationReport`、`ValidationCheck`、`ValidationIssue`、`ConstraintAdjustment` |
| 被校验产物 | `planned_state_contracts.py` / `parcel_change_contracts.py` | `PlannedState`、`ParcelChangeSet` |
| 门决定 | `app/modules/schema/contracts/workflow_contracts.py` | `GateDecision`、`PendingRequest`、`StageId` |
| 元数据 | `contract_meta.py` / `provenance.py` | `StageIssue`、`Provenance` |

`validate_aggregate(planned_state, changeset, intent, constraint_index, run_id)` 返回 `ValidationReport`。它只消费 typed execution outputs，不消费 render layers。`ValidationCheck.responsible_stage` 取值为 `L3/PARSE/GROUND/SELECT/EXECUTE` 字面量，作为门路由与 `issues_by_stage` 的键。

与 EXECUTE review 的关系：`execute/execute_agent.py` 的 `execution_review` 只做执行级检查（输入/输出完整性、变更血缘、几何有效性、worker 冲突）并产出 `validation_result`；完整的面积守恒、硬约束、拓扑、可达性、阶段归因等 9 项检查在本目录的 `validate_aggregate` 中运行，二者职责互补、不重复。失败项产出的 `ConstraintAdjustment` 供 post-L3 链在 `RETRY_EXECUTE` 时作为约束调整回灌 `prepare_inputs`（见 `execute/_prepare_inputs_node`）。

## 依赖方向

**可导入**：`app/modules/schema/contracts/*`、`app/modules/spatial_ops/*`（几何/面积计算，`checks.py` 内局部导入）、`provenance.py`。

**禁止导入**：任何 LLM 层、`app/agent/execute` 的实现（只经 `PlannedState`/`ParcelChangeSet` 契约交互）、上游分析层实现。

## 禁止行为

- 不得在 VALIDATE 内修复/改写 `PlannedState` 或 `ParcelChangeSet`（只读校验 + 诊断建议）。
- 不得在 `checks.py` / `gate.py` 内调用 LLM 或做 I/O（确定性纯函数）。
- 不得把失败静默降级为 PASS；`overall_passed` 必须为全部 check 通过。
- 门路由不得猜测责任 stage——必须按 `issues_by_stage` 的 error 计数（`_dominant_stage`）判定。

---

## 相关文档

- `../README.md` — agent 编排层总览
- `../../workflow/root_graph.py` / `../../workflow/stages/validate.py` — VALIDATE 的 RETRY_* 回退路由
- `../execute/README.md` — EXECUTE（上游：`ParcelChangeSet` + `PlannedState`）
- `../reconcile/README.md` — RECONCILE（下游消费者：`ValidationReport`）
- `app/modules/schema/contracts/validation_report_contracts.py` — 校验契约
