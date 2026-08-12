# Agent 编排层

`app.agent` 包含 LangGraph 主图和 EXECUTE 子图。当前根图有 **20 个显式业务节点**，另有 `END_DIAGNOSTIC` 终止诊断节点；隐式 `START` 不计入业务阶段。

## 当前主路径

```text
conversation → L1/L2/L3 worker → layer_completion_check → layer_aggregate
  → advance_phase → PARSE → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER
```

`conversation` 还可路由到 `execute_tools`；L1、L2、L3 worker 汇入完成检查。人工审核是独立的四个节点：

```text
prepare_human_review → publish_human_review_pause → await_human_review → apply_human_review_decision
```

`await_human_review` 和 step-mode 的 `layer_completion_check` 是两条业务频道，但都使用 `HumanInterrupt` canonical payload；各自中断点之前的节点必须保持幂等。

## 入口与边界

- `../workflow/root_graph.py`：根图与路由接线。
- `../workflow/root_graph.py`：根图和阶段路由；各 post-L3 节点位于 `../workflow/stages/`。
- `plan_state/state.py`：`AgentState` 与初始化函数。
- `execute/execute_agent.py`：EXECUTE 子图定义。

工作流层负责编排、Gate、重试和 HITL；领域算法归属各阶段 aggregate 及 `app.modules`。阶段产物应优先经 artifact ref 交接，算法模块不得反向依赖 API 或 LangGraph。

## 已知实现边界

- `AgentState` 仍是根图的迁移中内部 schema；对外查询必须使用 `app.workflow.state.WorkflowState`。
- StepReport 已迁移到 `app.modules.evidence`，agent 层不得拥有第二份审计实现。
- 当前 `execute_node` 在调用时构建并执行子图，尚非直接挂载到父图的持久化子图。
- 后端发布 `human_review_paused`，前端已接入消费（`SSEEventType` / `planning-api.ts` 注册、`planningStore` 处理、`HumanReviewPanel` 渲染与 `resolveHumanReview` 提交），HITL 暂停已形成 UI 闭环。
- `context_version` 在直接启动 post-L3 链时可能晚于 PARSE 产物写入；完整恢复链应以集成测试为准。
- HUMAN payload 的 canonical 字段为 `event_id/channel/reason/items/paused_stage`；旧字段只在兼容边界保留，避免前端直接依赖 graph 分支名称。

目标设计与迁移取舍见 [14_BACKEND_MODULE_BLUEPRINT.md](../../../docs/design/14_BACKEND_MODULE_BLUEPRINT.md)。
