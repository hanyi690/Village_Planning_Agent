# Workflow 路由重构：策略表化实施记录（A1–A7 / B1–B2）

> 对应重构蓝图《工作流图结构（backend/app/workflow/）》。目标：把散落的
> 路由 if-else 收敛成声明式策略表，保持行为逐字节不变，并确保优化后可实际
> 执行（`backend/tests/contracts` + `backend/tests/core` 全量回归通过）。

## 已落地

### A1（P0）post-L3 路由策略表化
- 新增 `backend/app/workflow/gate_policy.py`：`GATE_ROUTE_POLICY`（
  `(source_stage, gate_route) -> (action, *args)`）+ `DEFAULT_GATE_ROUTE_POLICY`
  兜底表 + `GATE_ROUTED_STAGES`。
- `root_graph.py` 里 7 个 `route_after_*` 收敛为 `_evaluate_gate_policy`
  查表 + 特例；`route_after_execute` 保留（见 A4）。
- 策略 action：`forward` / `retry` / `retry_from_route` / `human` / `end` /
  `end_diagnostic` / `revision_or_human`。

### A2（P0）HITL resume 路由表化
- `route_after_human_review` 拆成：哨兵（provider resume / gate 加载失败 /
  diagnostic_only / fatal_error）+ `(paused_stage, action)` 分派表
  `_APPROVE_ROUTE_HANDLERS` + `_route_retry`。
- 语义逐分支保留（含 `_approve_ground` 先查 unresolved target、validate/
  reconcile 的 END_DIAGNOSTIC 字面量表项等特例）。

### A3（P1）END_DIAGNOSTIC 哨兵收口
- `normalize_gate_route`：所有 post-L3 gate 路由的唯一入口；
  `GATE_LOAD_FAILED` 在 `_evaluate_gate_policy` 统一折叠为 END_DIAGNOSTIC。
- `conditional_map(*targets, aliases=...)`：构造 path_map 时自动带
  END_DIAGNOSTIC，消除 20+ 处 `END_DIAGNOSTIC: END_DIAGNOSTIC` 样板；
  `aliases` 处理 `human_review -> human_review_prepare` 特例。
- 注意：validate/reconcile 的 feedback_route 字面量 `END_DIAGNOSTIC`（重试
  耗尽后继续产出诊断清单）是合法表项，与加载失败语义不同，**不能**折叠混淆。

### A4（P1）EXECUTE 无 gate 豁免注释
- `route_after_execute` docstring + `state.py` 的 `GATE_STAGES` 注释明确：
  EXECUTE 阶段不产出 gate artifact，路由只看 fatal_error，是有意豁免。

### A7（P2）per-dispatch 超时
- `settings.DIMENSION_TIMEOUT_S`（JSON map，`{"<dimension_key>": 秒}`，默认空）。
- `layer_router._send_worker`：命中配置时
  `Send(worker, payload, timeout=TimeoutPolicy(idle_timeout=...))`（官方 API），
  未命中时与旧 `Send(worker, payload)` 完全一致。
- 接入点：`_ready_dispatch` / `revision_dispatch_node` /
  `provider_resume_dispatch_node` / `after_conversation` /
  `after_analysis`（revision/explore/rework）/ `_dispatch_current`。

### B1（P1）文档化“为什么不能合并节点”
- `root_graph.py` 节点注册处注释：layer_completion_check（defer=True 屏障）/
  layer_aggregate / advance_phase（Command(update+Send)）三节点不可合并，
  理由含 interrupt 整节点重跑语义（LangGraph 官方推荐“interrupt 与副作用
  分节点”）。

### B2（P0）after_analysis 瘦身
- `conversation/edges.py` 的 `after_analysis` 收敛为纯编排，分支抽到：
  `_route_revision` / `_terminal_failure_route` / `_route_explore` /
  `_route_gate_rework` / `_route_layer_gate` / `_route_dimension_dispatch`。

## 测试

- 新增 `backend/tests/core/test_gate_route_policy.py`（A1/A2/A3 策略表钉死）。
- 新增 `backend/tests/core/test_after_analysis_policy.py`（B2 处理器钉死）。
- `python -m pytest tests/contracts tests/core -m "not slow"`：463 passed。
- `create_unified_planning_graph()` 编译通过（25 节点）。

## 暂缓（有依据，非遗漏）

### A5（P1，可选）子图化（已设计 + 已去风险，未落地）
- 完整设计见 `docs/design/21_WORKFLOW_SUBGRAPH_DESIGN.md`（拓扑图、四段
  映射、跨段出口契约、出口授权适配、建议实施顺序）。
- `tests/contracts/test_langgraph_primitives.py` 实测钉死所需原语：编译
  子图直接当节点、子图内 interrupt + 父图 `Command(resume=)` 恢复、
  `Command(graph=Command.PARENT)` 跨图跳转、output_schema 不过滤 values 流。
- 生产图保持单层扁平；落地前置门禁是真实 LLM 验收测试
  （`tests/acceptance/test_real_graph_resume_delivery*`），本环境无 key 不执行。

### A6（P2）多 Schema 隔离 ✅
- `state.py` 新增 `WorkflowOutput`（应用可见的控制投影）；图工厂显式
  `StateGraph(WorkflowState, input_schema=WorkflowState, output_schema=WorkflowOutput)`。
- 实测确认：`output_schema` 不过滤 runtime 依赖的
  `stream_mode=["values","checkpoints"]` values 流（checkpoint 保留全量）；
  `aupdate_state(as_node="__start__")` 会被 `input_schema` 过滤，因此
  input_schema 必须保留完整 WorkflowState（不能收窄），已在代码注释说明。
- 契约测试：`tests/contracts/test_workflow_schema_visibility.py`。
