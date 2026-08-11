# bootstrap：图装配与阶段编排

`graph.py` 装配唯一根图。它包含 20 个显式业务节点：对话/工具、L1–L3 worker、层级编排、七个 post-L3 阶段，以及四个 HITL 节点；`END_DIAGNOSTIC` 是终止诊断节点。

## 关键文件

- `graph.py`：`create_unified_planning_graph`、边与条件路由。
- `post_l3_main_nodes.py`：PARSE、GROUND、SELECT、EXECUTE、VALIDATE、RECONCILE、DELIVER。
- `artifact_runtime.py`：artifact ref 的持久化、加载、类型与 checksum 校验。
- `stage_audit.py`：阶段审计记录。

## 运行语义

```text
START → conversation → L1/L2/L3 → layer_completion_check → layer_aggregate
  → advance_phase → parse → ground → select → execute → validate → reconcile → deliver → END
```

每个 Gate 通过条件边决定前进、回退重试或进入：

```text
human_review_prepare → human_review_publish → human_review_wait → human_review_apply
```

`human_review_wait` 是 post-L3 interrupt 点，step-mode 的 `layer_completion_check` 是另一条业务 interrupt 频道；两者必须使用同一 `HumanInterrupt` contract。发布和准备节点不得写入不可重放的副作用。业务 Gate 重试使用 `retry_counts`，LangGraph `RetryPolicy` 只面向暂态基础设施异常。

## 当前限制

- 根图通过 `post_l3_main_nodes.execute_node` 调用 EXECUTE，而非直接挂载已编译的子图；该调用当前没有继承父图 checkpoint。
- artifact 加载严格校验 context version；PARSE 前必须确保上下文已建立，否则 post-L3 重放会失败。
- `ArtifactStore` 的默认路径和测试 session 必须显式隔离，避免不同运行重用 `.run-tmp` 产物。

更多当前/目标差异见 [agent-graph.md](../../../../docs/architecture/agent-graph.md)。
