# agent/parse 子包（PARSE 意图编译）

> PARSE 阶段：`PlanningProgram` → `IntentCompilationResult` + `SpatialReferenceSpec[]` → Parse gate。
> 把 L3 规划程序确定性编译为强类型 `SpatialPlanningIntent` 与闭集空间引用 DSL，是"文本 → 机器可执行意图"的翻译层。

---

## 职责边界

**做**：编排 PARSE 编译（`compile_program` / `compile_program_async` / `parse_aggregate`）。核心链路：
1. `compile_node.compile_program_deterministic` 把 `PlanningProgram.interventions` 按类别映射为 `ProjectTarget` / `FacilityTarget` / `RoadTarget` / `ZoneTarget`，构造 `SpatialPlanningIntent` + `ProjectRequirement[]`，并经 `spec_mapper.map_interventions_to_specs` 产出 `SpatialReferenceSpec[]`（无 LLM）；
2. `route_node.route_compilation` 按诊断做确定性路由（`merge` / `llm_patch` / `human_review`）；
3. `llm_patch.generate_llm_patches` 仅在 `llm_patch` 路由下调用 LLM——LLM **只**产 `CompilationPatch`（Instructor 约束），不直接写意图；
4. `merge_node.apply_patches` 对编译结果深拷贝做确定性 patch 应用（ADD/UPDATE/REMOVE/MERGE，支持白名单路径）并重新校验；
5. `gate_node.evaluate_parse_gate` 出 Parse gate（PASS / REPAIR / REVISE / HUMAN）。

**不做**：不产出任何空间几何/选址（那是 GROUND/SELECT）；不读原始规划文本（输入是 typed `PlanningProgram`）；LLM 不直接返回意图——只能经 patch 影响编译结果，且 patch 必须经确定性合并器校验。

### 目录文件

| 文件 | 职责 |
|---|---|
| `aggregate.py` | 顶层编排 + 公共 API（`compile_program` / `compile_program_async` / `parse_aggregate`）+ 审查包落库 |
| `compile_node.py` | `compile_program_deterministic`：确定性编译（无 LLM） |
| `route_node.py` | `route_compilation`：按诊断路由（merge / llm_patch / human_review） |
| `llm_patch.py` | `generate_llm_patches`：Instructor 约束的 LLM patch 生成（失败降级 `[]`） |
| `merge_node.py` | `apply_patches`：确定性 patch 合并 + 重新校验 |
| `gate_node.py` | `evaluate_parse_gate`：4 路门（PASS/REPAIR/REVISE/HUMAN） |
| `review.py` | `build_parse_review_package`：构造审查包内容 |

### 流程图

```
   PlanningProgram (L3 typed artifact)
        │
        ▼
   compile_program_deterministic（compile_node.py）
        │   → IntentCompilationResult + SpatialReferenceSpec[] + diagnostics
        ▼
   route_compilation（route_node.py）──┬─ merge ───────────────────┐
                                       ├─ llm_patch ─► generate_llm_patches（只产 CompilationPatch）
                                       │                     ▼
                                       └─ human_review ──► apply_patches（merge_node.py，确定性合并+重校验）
                                                                    │
                                                                    ▼
   evaluate_parse_gate（gate_node.py）──┬─ PASS    → GROUND
                                        ├─ REPAIR  → 局部修补（≤5 patches）
                                        ├─ REVISE  → 结构性返工（>5 patches）
                                        └─ HUMAN   → 审查检查点（NEEDS_REVIEW）
```

## 输入/输出契约

| 契约 | 文件 | 关键类型 |
|---|---|---|
| 编译结果（根产物） | `app/modules/schema/contracts/parse_result_contracts.py` | `IntentCompilationResult`、`CompilationPatch`、`CompilationStatus`、`ParseMode`、`ParseDiagnostic`、`ParseTrace`、`ProjectRequirement` |
| 空间引用 DSL | `app/modules/schema/contracts/spatial_reference_contracts.py` | `SpatialReferenceSpec`、`RefObject`、`CandidateSet`、`ResolvedSpatialRef` |
| 意图模型 | `app/modules/schema/contracts/parse_contracts.py` | `SpatialPlanningIntent`、`ProjectTarget`、`FacilityTarget`、`RoadTarget`、`ZoneTarget`、`AxisTarget` |
| 输入程序 | `app/modules/schema/contracts/l3_contracts.py` | `PlanningProgram`、`PlanningIntervention` |
| 门决定 | `app/modules/schema/contracts/workflow_contracts.py` | `GateDecision`、`PendingRequest` |

`compile_program*` 返回 `(IntentCompilationResult, list[SpatialReferenceSpec], GateDecision)`；`parse_aggregate` 返回 `parse_result_ref`、`parse_gate_decision`、`parse_review_id`。

## 依赖方向

**可导入**：`app/modules/parsing/compiler/spec_mapper`（`map_interventions_to_specs`）、`app/modules/schema/contracts/*`、`app/services/artifact_store`、`app/services/review_package`、`app/core/instructor_client`（LLM patch，`llm_patch.py` 内局部导入）。

**禁止导入**：所有下游 stage 的实现（`ground`/`select`/`execute`/`validate`/`reconcile`/`deliver`）；桥接层旧 PARSE agent（bridge isolation，见 `compile_node.py` 注释）；上游 L1/L2/L3 的 worker 实现。

## 禁止行为

- LLM 不得直接输出或改写 `SpatialPlanningIntent`——只允许产 `CompilationPatch`，且必须经 `apply_patches` 确定性合并与重新校验（`SCHEMA_MISMATCH` 诊断保护）。
- 不得使用未在白名单的 patch 路径（仅 `project_requirements` / `spatial_reference_specs` / `typed_intent.*`）。
- 不得在 `merge_node.py` / `route_node.py` / `gate_node.py` 内调用 LLM 或做 I/O（保持纯函数）。
- 任何 error 级诊断不得走自动修补，必须路由到 `human_review`。
- 根产物 `IntentCompilationResult` 必须继承 `ContractMeta`；`typed_intent` 为懒引用（避免循环依赖，保持 `Any` 注解）。

---

## 相关文档

- `../README.md` — agent 编排层总览
- `../bootstrap/post_l3_chain.py` — PARSE 在 post-L3 链中的重试路由（REPAIR/REVISE）
- `../ground/README.md` — GROUND（下游消费者：`SpatialReferenceSpec` → `CandidateSite`）
- `app/modules/schema/contracts/parse_contracts.py` — 意图模型契约
- `docs/gis/integration/PARSE_SPATIAL_GROUNDING_DESIGN.md` — 空间引用设计
