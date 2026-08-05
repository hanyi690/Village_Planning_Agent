# agent/bootstrap 子包（图装配与编排骨架）

> 图的**装配中枢**：`create_unified_planning_graph`（上游 L1/L2/L3 分析主图）+ `build_post_l3_chain`（下游 PARSE→GROUND→SELECT→EXECUTE→VALIDATE→RECONCILE→DELIVER 链，含门重试环 + HITL `human_review`）。
> 本目录不实现任何阶段算法，只负责把各 stage 子包接线成可运行的 LangGraph 图。

---

## 职责边界

**做**：`graph.create_unified_planning_graph` 装配上游主图（conversation / execute_tools / layer_router / l1/l2/l3_worker / layer_completion_check / layer_aggregate / advance_phase / gis_agent）；`layer_router` 按 `phase` 用 `Command(goto=[Send])` 转发维度负载到对应 worker；`phase_machine` 提供 `PlanningPhase` 枚举与 层/相位/波次转换；`layer_aggregate_node` 在层完成时调用对应 `l{1,2,3}_aggregate`（独立节点，避免 `interrupt()` 重放导致重复执行）；`post_l3_chain.build_post_l3_chain` 装配下游链并加门重试环；`post_l3_nodes` 实现链上各节点（各阶段 aggregate + gate + artifact 持久化 + `human_review_node` 的 `interrupt()` 暂停）；`post_l3_state.PostL3ChainState` 定义链状态；`gis_agent_entry.gis_agent_node` 作为主图 → post-L3 链的入口（构建 `PlanningContext`、编译 `PlanningProgram`、跑链、处理 `GraphInterrupt`、SSE 推送）。

**不做**：不实现维度分析 / 意图编译 / 接地 / 选址 / 执行 / 校验 / 对账 / 交付算法（全部委托各 stage 子包）。

### 目录文件

| 文件 | 职责 |
|---|---|
| `graph.py` | `create_unified_planning_graph`：上游主图工厂（含节点级 `error_handler` / `RetryPolicy`） |
| `layer_router.py` | `layer_router_node` / `l1|l2|l3_worker_node` / `advance_phase_node` / `route_by_phase` / `_ready_dispatch` |
| `layer_aggregate_node.py` | `layer_aggregate_node`：层完成 → 调用 l1/l2/l3 aggregate |
| `phase_machine.py` | `PlanningPhase` 枚举 + `LAYER_DIMENSIONS` / `WAVE_DIMENSIONS` / 相位转换 |
| `gis_agent_entry.py` | `gis_agent_node`：主图 → post-L3 链入口（构建 context / 编译 program / 跑链 / HITL 处理） |
| `post_l3_chain.py` | `build_post_l3_chain`：下游链 + 门重试环路由 |
| `post_l3_nodes.py` | `parse_node`…`deliver_node` / `human_review_node` / `_retry_patch` / `_persist_artifact` |
| `post_l3_state.py` | `PostL3ChainState`：链状态（typed artifact refs + retry_counts + human_review_items） |

### 两张图拓扑（来自 graph.py / post_l3_chain.py 实际边）

**上游主图 `create_unified_planning_graph`（AgentState）**

```
 START → conversation ──► layer_router ──(Send)──► l1_worker | l2_worker | l3_worker
            │  ▲                ▲                        │（每个维度一个 Send）
            │  │                │                        ▼
            │  └── execute_tools（工具执行 → 回 conversation）
            │                                          layer_completion_check（层完成检测）
            │                                                  ▼
            │                                          layer_aggregate（调 l1/l2/l3 aggregate + 门）
            │                                                  ▼
            └── gis_agent（GIS 入口，→ END）       after_analysis ──┬─ layer_router（同层再分发）
                                              advance_phase（门 PASS → 下一层/END）
                                              conversation / END
```

**下游 post-L3 链 `build_post_l3_chain`（PostL3ChainState，M2 重试拓扑）**

```
 START → parse → ground → select → execute → validate → reconcile → deliver → END
            │        │        │                  │            │          │
            │REPAIR/ │EXPLORE │RETRY_GROUND      │RETRY_*      │RETRY_     │RETRY_VALIDATE
            │REVISE  └───▲────┘                  ├─EXECUTE     │EXECUTE   └──► validate
            └─────────► parse                    ├─SELECT      └──► execute
                                                  ├─GROUND / PARSE
                                                  └─RETRY_L3 → human_review（HITL）
            human_end / 重试耗尽 / 非重试路由 → human_review（interrupt() 暂停 → 恢复后 END）
```

**接线要点**：
- `layer_router` 是转发节点：`Send` 负载不经过共享 noop（否则 `dimension_key` 丢失），因此 `layer_router_node` 用 `Command(goto=[Send(worker, state)])` 重发完整负载。
- `advance_phase_node` 是真实节点（条件边不能返回 `Command`），门 PASS 时推进 `phase` 并 `Send` 下一层就绪维度。
- post-L3 链编译时传 `checkpointer`（`get_global_checkpointer`）才能让 `human_review` 的 `interrupt()` 暂停可恢复；`context` 不可序列化，从图输入剥离（`gis_agent_entry` 置 `None`），节点经会话 context 缓存恢复。

## 输入/输出契约

| 契约 | 文件 | 关键类型 |
|---|---|---|
| 上游主图状态 | `app/agent/plan_state/state.py` | `AgentState`（TypedDict）、`create_initial_state`、`state_to_ui_status` |
| 下游链状态 | `app/agent/bootstrap/post_l3_state.py` | `PostL3ChainState`（`planning_program`/`intent`/`grounding_result`/`site_selection`/`planned_state`/`parcel_changeset`/`validation_report`/`reconciliation_report`/`delivery_manifest` + 各 `*_gate`） |
| 门决定 | `app/modules/schema/contracts/workflow_contracts.py` | `GateDecision`、`PendingRequest` |
| 阶段产物 | `l1_contracts.py`…`delivery_manifest_contracts.py` | 见各 stage 子包 README |
| artifact ref | `app/modules/ports/artifact_store.py` | `ArtifactRef`（`_persist_artifact` 写入 `FilesystemArtifactStore`） |

## 依赖方向

**可导入**：`app/agent/plan_state`、`app/agent/conversation_router`、`app/agent/tools`、`app/agent/l1_observe` / `l2_strategize` / `l3_plan` / `parse` / `ground` / `select` / `execute` / `validate` / `reconcile` / `deliver`（作为图节点消费者）、`app/modules/schema/contracts/*`、`app/modules/context/planning_context`（`build_planning_context`）、`app/services/*`（artifact_store / step_report / sse_publisher）。

**禁止导入**：任何下游 stage 不得反向导入 bootstrap 的内部实现细节（`bootstrap` 是装配层，只被入口/服务调用）；`post_l3_nodes` 不得 import 各 stage 的私有 worker（只调用其公开 aggregate/gate）。

## 禁止行为

- 不得把阶段算法内联到 bootstrap（`post_l3_nodes` 只包装 aggregate + gate，算法留在各 stage）。
- 不得让 `layer_router` 变成共享 noop（会丢 `dimension_key`）。
- 不得在无 checkpointer 时依赖 `human_review` 的可恢复暂停（`interrupt()` 无持久化则暂停不可恢复）。
- 不得在链状态里塞不可序列化对象（`context` 必须剥离，经缓存恢复）。
- 重试计数归节点所有（`_retry_patch`），路由器只决策目标、绝不写状态。

---

## 相关文档

- `../README.md` — agent 编排层总览（主图节点表 + 路由）
- `../plan_state/README.md` — `AgentState` / 完成检测
- `../conversation_router/README.md` — `after_conversation` / `after_analysis`
- 各 stage 子包 README — 被装配的算法
- `docs/architecture/agent-graph.md` — 工作流图（当前实现与目标子图）+ 迁移目录归属
