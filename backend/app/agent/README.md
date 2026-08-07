# Agent 编排层

`app.agent` 包含 LangGraph 主图和 EXECUTE 子图。当前根图有 **19 个显式执行节点**；LangGraph 图视图将隐式 `START` 一并计数时显示为 20 个。

## 当前主路径

```text
conversation → L1/L2/L3 worker → layer_completion_check → layer_aggregate
  → advance_phase → PARSE → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER
```

`conversation` 还可路由到 `execute_tools`；L1、L2、L3 worker 汇入完成检查。人工审核是独立的四个节点：

```text
prepare_human_review → publish_human_review_pause → await_human_review → apply_human_review_decision
```

只有 `await_human_review` 调用 `interrupt()`；因此其前置节点必须保持幂等。

## 入口与边界

- `bootstrap/graph.py`：根图与路由接线。
- `bootstrap/post_l3_main_nodes.py`：PARSE 至 DELIVER 的主图节点、产物加载和 Gate 路由。
- `plan_state/state.py`：`AgentState` 与初始化函数。
- `execute/execute_agent.py`：EXECUTE 子图定义。

工作流层负责编排、Gate、重试和 HITL；领域算法归属各阶段 aggregate 及 `app.modules`。阶段产物应优先经 artifact ref 交接，算法模块不得反向依赖 API 或 LangGraph。

## 已知实现边界

- `AgentState` 仍含 legacy 完整产物和图层字段，尚未实现完全 ref-only checkpoint。
- 当前 `execute_node` 在调用时构建并执行子图，尚非直接挂载到父图的持久化子图。
- 后端发布 `human_review_paused`，前端已接入消费（`SSEEventType` / `planning-api.ts` 注册、`planningStore` 处理、`HumanReviewPanel` 渲染与 `resolveHumanReview` 提交），HITL 暂停已形成 UI 闭环。
- `context_version` 在直接启动 post-L3 链时可能晚于 PARSE 产物写入；完整恢复链应以集成测试为准。

目标设计与迁移取舍见 [agent-graph.md](../../../docs/architecture/agent-graph.md)。
