# L1/L2/L3 整体迁移决策

> 日期：2026-08-12
> 目的：记录 L1/L2/L3 维度 worker 机制从 `app/agent/` 迁出的综合决策依据（设计文档回顾 + 外部实践 + 官方实现 + 循环依赖验证）。

## 1. 为什么 L1/L2/L3 必须整体迁移而非逐阶段

探索确认 L1/L2/L3 是互相咬合的整体，不能像 post-L3 六阶段那样逐个搬：

- 三个 worker（`l1_observe/analysis_node`、`l2_strategize/worker`、`l3_plan/worker`）都 **MOD 级** 依赖 `app/agent/common/dimension_runtime`（共享执行器，673 行）。
- 三个 aggregate 都 **MOD 级** 依赖 `app/agent/bootstrap/context_guard`。
- 整个 dispatch/aggregate/advance 机制绑定在 `bootstrap/layer_router` + `layer_aggregate_node` + `conversation_router/edges` + `plan_state/completion_node` 上。
- `bootstrap/phase_machine` 被 `services/runtime.py:43`、`checkpoint.py:15`、`sse_publisher.py:464` 等 **MOD 级** 导入，改它牵连 Phase 4 的 services。
- 与 post-L3 不同，L1/L2/L3 **不是双事实**——`domain/assessment`、`domain/objectives` 不存在，迁它们只是目录正确性。但用户裁决：**必须迁移**，且"不必兼容"。

## 2. 设计文档目的（04_PLANNING_PIPELINE.md）

L1/L2/L3 的 **并行维度 worker 模式是设计核心**，不是需要消除的 legacy：

- L1 = 12 × 并行 analysis worker → per-worker `L1DimensionFragment` 编译 → 唯一确定性 `l1_aggregate` → `L1Snapshot`。
- 权威产物是 typed artifacts（`L1Snapshot`/`L2Strategy`/`PlanningProgram`）；Markdown 报告保留为人读视图（"报告不是要被结构化产物替代的临时文本"）。
- L1/L2/L3 prompt 只通过 EXPLORE 获取空间认知，worker 不直接调 KG。

**迁移必须保留** Send/并行/fan-in/reducer 机制。

## 3. LangGraph 官方实现（context7）

- `Send(node, state)` = 官方 map-reduce fan-out；`add_node(..., defer=True)` = fan-in barrier。
- 当前实现已符合官方模式：`layer_completion_check` 注册为 `defer=True`（root_graph.py:625），WorkflowState 27 个 Annotated reducer 键是官方要求的并行写合并方式。
- checkpoint resume 用 `thread_id`/`checkpoint_id`——当前已实现。

## 4. 外部实践（exa）

- 并行写同一 key 必须 Annotated reducer，否则 `INVALID_CONCURRENT_GRAPH_UPDATE`——当前已遵守。
- **风险警示**：`defer=True` + `Command` + 条件边组合有已知 bug（issue #5182/#6005）。当前 `layer_completion_check`(defer) 与 `layer_aggregate`(条件边) 的组合在 Round 1.5 已验证无此问题，迁移后保持拓扑不变。
- 最佳实践：worker 写 append-only key + 下游 aggregator 合成——当前 `completed_dimensions` 等正是此模式。

## 5. 循环依赖验证（决定性）

**全局不变量（验证确认）**：`app/domain/*` **零** MOD 级导入 `app/workflow/*`。当前依赖方向是 `workflow → domain` 单向。任何新增的 domain→workflow MOD 边都会成环。

因此必须遵守：
- **R1**：任何 domain 模块不得 MOD 导入 workflow（`persist_gate_decision`/`stage_audit` 只能 FUNC 导入，沿用 `l1:279`/`l2:180`/`l3:362` 的既有模式）。
- **R2**：`phase_machine` 是叶子（仅 config+schema）→ 可进 workflow。
- **R3**：`context_guard` 被三个 domain aggregate MOD 导入 → **不能进 workflow**，放 `app/domain/common/`。
- **R5**：`plan_state/state.py` 不能占用 `app/workflow/state.py`（文件名冲突）→ 放嵌套子包 `app/workflow/plan_state/`。
- **R4/R6**：`dimension_runtime` 的 services 依赖全 FUNC → 任意叶子位均可，推荐 `app/infrastructure/llm/`。

## 6. 最终目标布局

| 源 | 目标 | 依据 |
|---|---|---|
| `agent/l1_observe/*` | `app/domain/assessment/` | R1 满足，无 workflow MOD 边 |
| `agent/l2_strategize/*` | `app/domain/objectives/` | 同上 |
| `agent/l3_plan/*` | `app/domain/program/` | 已 MOD 依赖 domain.program，并入消除跨包边 |
| `agent/bootstrap/{phase_machine,layer_router,layer_aggregate_node,context_bootstrap}.py` | `app/workflow/layers/` | R2；layer_router→domain MOD 边合法（R1 成立） |
| `agent/bootstrap/context_guard.py` | `app/domain/common/` | R3 |
| `agent/common/{gate_progress,execution_evidence}.py` | `app/domain/common/` | 纯叶子 |
| `agent/common/dimension_runtime.py` | `app/infrastructure/llm/` | R4；LLM/RAG/ReportStore adapter |
| `agent/plan_state/{state,state_factory,completion_node}.py` | `app/workflow/plan_state/` | R5 |
| `agent/explore/*` + `retrievers/` | `app/evidence/retrieval/`（service.py→evidence_service.py） | Q4 干净叶子 |
| `agent/conversation_router/{node,edges}.py` | `app/workflow/conversation/` | Q5 |
| `agent/tools/execute_node.py` | `app/workflow/tools/` | Q5 零 agent 依赖 |

## 7. LEGACY_GATE_STAGES 删除（"不必兼容"）

- 三个 aggregate 已构建 pydantic `GateDecision`（`evaluate_l1/l2/l3_gate`）。
- 改为在 aggregate 内 **FUNC** 导入 `persist_gate_decision(state, stage, gate, ...)`（签名匹配，state 已含 run_id/session_id/branch_id/artifact_refs/context_ref）。
- 同一 commit 内必须同步：`workflow/state.py:26` 删除 `LEGACY_GATE_STAGES`、`load_root_gate:49-58` 删 legacy 分支、`root_graph.py:361-362` `_gate_mutation_patch` 删 legacy 分支、`state.py:329-331` `_latest_gate` 删 `l1/l2/l3_gate_decision`、`root_graph.py:724,742-746,755-757,819-825,1127-1136,1284-1285,1444` 及 `edges.py` 的 inline 写点全部改为 CAS gate_ref。
- `state_factory.py:89-91` 初始化 inline keys 的代码删除。

## 8. 执行顺序（多 subagent 分批，每批跑全量回归）

1. **Batch A（基座）**：`phase_machine` + `layer_router` + `layer_aggregate_node` + `context_bootstrap` → `workflow/layers/`；`context_guard` + `gate_progress` + `execution_evidence` → `domain/common/`；`dimension_runtime` → `infrastructure/llm/`；`plan_state/` → `workflow/plan_state/`。所有 import 重指 + 全量回归。
2. **Batch B（L1/L2/L3）**：三个 stage 包 → domain 目标；`explore/` → `evidence/retrieval/`；`conversation_router/` + `tools/execute_node.py` → workflow。所有 import 重指 + 全量回归。
3. **Batch C（gate 统一）**：L1/L2/L3 aggregate 改 `persist_gate_decision`，删除 LEGACY_GATE_STAGES 全链路。
4. **Batch D**：删除 `app/agent/` 剩余（bootstrap/common/l1/l2/l3/explore/conversation_router/tools/plan_state），更新所有残留 import + 测试，架构测试 `test_no_app_agent_import.py`。
5. **Batch E**：真实 LLM acceptance 验证。

## 9. 风险清单

- 最高风险：domain 模块 MOD 导入 workflow（R1 违反）。执行 subagent 必须保持 `persist_gate_decision`/`stage_audit` 为 FUNC 导入。
- `plan_state/state.py` 落位冲突（R5）。
- gate 转换不同步导致运行时路由断裂（必须单 commit 全链翻转）。
- `defer=True` 拓扑不得改变（否则触发 #5182/#6005 类 bug）。
