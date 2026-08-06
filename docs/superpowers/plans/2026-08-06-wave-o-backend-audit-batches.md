# Wave O — 后端全面审计 + 分批修复

> 分支：`refactor/phase1-planning-context`
> 状态：in_progress
> 日期：2026-08-06

## 背景

用户要求重新审视完整后端实现，对比设计文档与 Context7 最佳实践。已完成 4 个 explore 子代理并行映射 + 关键文件直读 + Context7 LangGraph 文档对比，产出审计发现并分三批解决。

## 审计方法

- 4 个 explore 子代理：post-L3 主链、VALIDATE/RECONCILE/DELIVER、EXECUTE 子图、PARSE/GROUND/SELECT
- 直读关键文件：`bootstrap/graph.py`、`post_l3_main_nodes.py`、`execute_agent.py`、`select/aggregate.py`、`deliver/checks.py`、`export_package.py`、`canonical.py`
- Context7：LangGraph 子图组成、BaseModel state schema、interrupt、retry 最佳实践
- 依赖违规 grep：`modules -> agent|services|api`

## 审计发现（Risk Register）

### P0 — 阻断端到端 MVP

| # | 发现 | 证据 | 状态 |
|---|------|------|------|
| P0-1 | DELIVER 法定图层导出缺口：`admin_area/current_landuse/planned_landuse/ecological_redline/farmland_protection/construction_zone` 多数缺失 → `deliver_gate=HUMAN` | `export_package.py:70-86` + `canonical.py:362` + `deliver/checks.py:15-22`；运行期 `hi-layers-*` 4 个 blocking item | 待修 |
| P0-2 | 主图 reconcile 与诊断脚本分歧：`mvp_verify_graph_chain.py` "reconcile retry exceeded 3 rounds -> human" vs `_diag_postl3.py` `reconcile_gate=None` | 两脚本运行期输出分歧 | 待查 |

### P1 — 架构债务

| # | 发现 | 证据 | 状态 |
|---|------|------|------|
| P1-1 | 两套并行 post-L3 实现：`post_l3_main_nodes.py`(593) 生产 vs `post_l3_nodes.py`+`post_l3_chain.py`(862) 独立；独立版更丰富（`build_execution_plan`/`retrieve_evidence`/step_report） | 子代理映射 | 待修 |
| P1-2 | EXECUTE 无 gate：`execute->validate` 硬边（`graph.py:169`），`AgentState` 无 `execute_gate`，`PostL3ChainState:58` 字段从不填充 | `graph.py:169` + `post_l3_state.py:58` | 待决策 |
| P1-3 | `_to_typed` dict→model 创建新对象（mutation 不持久化）：`plan_intent is intent.typed_intent`=False 当 typed_intent 为 dict | `post_l3_main_nodes.py:120-131`；已运行时验证 | 已缓解（fix6），主图未验证 |

### P2 — 设计偏差

| # | 发现 | 证据 | 状态 |
|---|------|------|------|
| P2-1 | `AgentState` TypedDict 缺节点写入字段：`grounding_result_ref/site_selection_ref/parcel_changeset_ref/planned_state_ref` | `plan_state/state.py:224-260` | 待修 |
| P2-2 | Reconcile 覆盖矩阵位置匹配：`spec_index=i`、`candidates[i]` 无 ID join | `reconcile/aggregate.py:55-106` | 已部分（Wave N4 语义化 candidate→selection），保留 |
| P2-3 | `score_breakdown` stub：`road_access`/`service_coverage`=0.0 | `select/aggregate.py:44-50` | Wave N3 记录 deferred，保留 |
| P2-4 | `PlannedState.zones` 永远空：zone changes→PlannedParcel 非 PlannedZone | `planned_state_builder.py:99-100` | 已知 quirk，保留 |
| P2-5 | `planning_text` 模块 `modules->services` 依赖违规 | `modules/planning_text/generator.py:25` 等 | DEPRECATED 待删 |

### Context7 对比

| 最佳实践 | 当前实现 | 结论 |
|----------|---------|------|
| BaseModel 作 StateGraph schema | `ExecuteAgentState` BaseModel / `AgentState` TypedDict | ✅ 两者受支持 |
| Compiled subgraph 直接 add_node | 手动 `build_execute_agent_graph()`+`ainvoke()` | ⚠️ 可行但绕过原生子图 checkpoint |
| `Annotated` reducer 并发写 | `_upsert_worker_results` | ✅ 符合 |
| `interrupt()` HITL | `human_review_node` | ✅ 符合 |
| retry 条件边+计数 | `_route_after_execution_review`+`validation_round` | ✅ 符合 |

## 分批解决计划

### Batch 1 (P0)
- B1-1: 修复 DELIVER 法定图层导出
- B1-2: 排查主图 vs 诊断脚本 reconcile 分歧

### Batch 2 (P1)
- B2-1: 合并两套 post-L3 实现（移植独立链功能到主图）
- B2-2: EXECUTE gate 决策（新增或文档化）

### Batch 3 (P2)
- B3-1: `AgentState` TypedDict 补全 ref 字段
- B3-2: 清理 `planning_text` DEPRECATED 模块 + 其他

### 回归
- 全量 `pytest tests/unit/` + `mvp_verify_graph_chain.py`
