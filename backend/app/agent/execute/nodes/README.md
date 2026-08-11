# EXECUTE nodes

`nodes/` 是 EXECUTE 空间执行子图的节点实现。图结构在上层 `execute_agent.py` 装配；这里按单一职责实现 worker、输入准备、结果合并、几何物化和交付前审查。

## 主流程

```text
route_tasks → prepare_inputs → project_worker → zone_worker
  → facility_worker ∥ axis_worker → road_worker → action_worker
  → merge_worker_results → geometry_materialize → planned_state_builder
  → execution_review
```

## 主要边界

- 输入是 PARSE/SELECT 产生的类型化意图、`SiteSelectionDecision`、`ExecutionPlan` 和版本化 `PlanningContext`。
- worker 只生成 `WorkerResult`、`ParcelChangeSet` 或确定性的派生结果，不修改规划意图。
- `execution_review` 只负责 EXECUTE 内部结果检查；跨阶段问题由 VALIDATE/RECONCILE 负责。
- 几何算法必须调用 `app.modules.spatial_ops`；当前部分 worker 仍依赖 `tools/gis/_generation` 私有函数，这是 P1 迁移断点。
- 节点可能在 LangGraph 重放或重试时再次执行，外部写入必须幂等并带有稳定 artifact/target 标识。

## 验证

重点测试：`backend/tests/e2e/test_target_bound_execute_e2e.py`、`backend/tests/e2e/test_delivery_terminal_semantics_e2e.py` 以及 `backend/tests/core/` 中的契约测试。
