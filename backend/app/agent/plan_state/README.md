# agent/plan_state 子包（上游状态 + 层完成检测）

> 上游主图的**状态模型**（`AgentState` TypedDict + reducer + 辅助）与**层完成检测节点**（`layer_completion_check`）。
> 两文件：`state.py` + `completion_node.py`。

---

## 职责边界

**做**：`state.py` 定义 `AgentState`（`total=False`）——进度（`phase` / `current_wave` / `completed_dimensions` / `step_mode` / `previous_layer`）、配置（`config`）、修订（`need_revision` / `revision_target_dimensions` / `revision_impact_tree` / `revision_feedback`）、性能（`pending_reports` / `layer_char_counts`）、P0 数据闭环（`_landuse_metrics` / `intent_targets`）；提供 reducer（`_messages_reducer` = `add_messages`，`completed_dimensions` 并行合并）、`create_initial_state`、`state_to_ui_status`、`get_*` 查询函数。`completion_node.py` 实现 `layer_completion_check`：reducer 合并并行结果后检测层完成、发 `layer_completed` / `layer_paused` SSE、`step_mode` 走 `interrupt()` 审批暂停、层边界触发 bundle 快照（`snapshot_session_bundle`）+ 绑定提取（`_maybe_extract_bindings`）+ KG enrichment。

**不做**：不包含任何维度分析逻辑；post-L3 阶段与人工审核状态直接归入 `AgentState`，不再维护独立 wrapper state。

## 输入/输出契约

| 契约 | 文件 | 关键类型 |
|---|---|---|
| 上游状态 | `app/agent/plan_state/state.py` | `AgentState`（TypedDict）、`ReportVersion`、`DimensionSummary` |
| 阶段枚举 | `app/agent/bootstrap/phase_machine.py` | `PlanningPhase`、`LAYER_DIMENSIONS`、`WAVE_DIMENSIONS`、`TOTAL_WAVES` |
| 消息契约 | `langchain_core.messages` | `BaseMessage`（`add_messages` reducer） |

**注意**：`_messages_reducer` 用 `add_messages`（`DeltaChannel` 不兼容 `SqliteSaver`——见代码注释 langgraph PR #7547）。

## 依赖方向

**可导入**：`app/agent/bootstrap/phase_machine`、`app/modules/schema/layers`、`langgraph` / `langchain_core`、`app/services/session_bundle` / `report_store` / `kg`（enrichment，`completion_node` 内局部导入）。

**禁止导入**：`app/agent/l1_observe` / `l2_strategize` / `l3_plan` 及各 post-L3 stage（状态层不依赖算法）。

## 禁止行为

- 不得把报告全文 / 摘要塞进 `AgentState`（已移除，存 `ReportStore`；`pending_reports` 仅作批量写库缓冲）。
- 不得在 `completion_node` 的 `interrupt()` 之前发不可重放的 SSE（`interrupt()` 恢复会重执行整节点，SSE 必须在暂停点之后）。
- 不得用 `DeltaChannel` 当消息 reducer（与 `SqliteSaver` 不兼容）。
- 不得在 `state.py` 引入不可序列化对象（状态需可进 checkpoint）。

---

## 相关文档

- `../README.md` — 主图状态模型（§四）
- `../bootstrap/README.md` — 图装配（`layer_completion_check` / `layer_aggregate` 接线）
- `../bootstrap/phase_machine.py` — `PlanningPhase` 枚举
- `app/services/report_store.py` — 报告/摘要存储
