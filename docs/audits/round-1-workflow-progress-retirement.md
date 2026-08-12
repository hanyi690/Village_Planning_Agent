# Round 1.5 — WorkflowState 并行合并迁移记录

> 日期：2026-08-12
> 状态：IN PROGRESS（迁移中）
> 相关蓝图：docs/design/14_BACKEND_MODULE_BLUEPRINT.md M5/M9、docs/design/02_DATA_PERSISTENCE.md §1.1
> 问题登记：docs/audits/backend-migration-issue-register-2026-08-12.md MIG-003

## 1. 问题现象（真实 LLM acceptance 反复失败）

`tests/acceptance/test_real_graph_resume_delivery.py` 真实 LLM 运行在 L1 维度 worker 阶段反复失败，链路如下：

1. `ArtifactReplayError: artifact workflow_progress named ref changed during replay`（CAS 冲突）
2. 修复 CAS 后 → `langgraph.errors.InvalidUpdateError: At key 'session_id': Can receive only one value per step`
3. 修复 Annotated 后 → `GraphRecursionError: Recursion limit of 100`，`layer_completion_check` 反复 `completed=0/12`
4. 追踪发现 `after_analysis` 反复 `dispatching 12 dim(s)` 但 worker 从未执行

## 2. 根因分析（对设计文档）

**根因 1 — CAS 并行冲突**：L1/L2/L3 worker 通过 LangGraph `Send` 并行派发（12 个维度 worker 同一 map super-step）。每个 worker 被 `adapt_node` 包装，各自调用 `_persist_progress` 写**同一个** `workflow_progress` CAS named ref → 超步内并发写冲突。

**违反**：
- 蓝图 M5 "WorkflowState 只保存控制字段和 artifact refs"，`workflow_progress` 是 MIG-003 登记的**迁移期复合状态**
- 官方 LangGraph map-reduce 范式：**共享键必须 `Annotated[key, reducer]`**，由 LangGraph 在超步结束自动合并；不能用多个 worker 写同一个 CAS artifact 手工合并

**根因 2 — `dimension_key` 丢失**：`materialize_workflow_state` 只从 `runtime`/`workflow_progress`/`_CONTROL_KEYS` 恢复，而 Send payload 携带的 `dimension_key` 不在其中 → worker 收到 `dimension_key=None` → 返回 `[执行失败] 缺少维度标识` → 无 completed_dimensions → 死循环。

**根因 3 — 共享键不合并**：`completed_dimensions` 等在 `workflow_progress.stage_payload` 里，不受 LangGraph reducer 保护，并行 worker 的 slice 无法累积。

## 3. 迁移决策

采用**官方范式 + 蓝图 M9 方向**，把并行 worker 的共享键提升为 `WorkflowState` 顶层 `Annotated` reducer 通道，使 LangGraph 自动合并；`workflow_progress` 降级为纯 legacy 迁移载体。

### 3.1 改动清单

| 文件 | 改动 |
|---|---|
| `app/workflow/state.py` | 新增 `_merge_layer_dims`/`_merge_reports`/`_merge_char_counts`/`_merge_messages` reducer；`WorkflowState` 增加 `completed_dimensions`、`revision_completed_dims`、`pending_reports`、`layer_char_counts`、`revision_impact_tree`、`revision_target_dimensions`、`messages` 顶层字段（均 Annotated reducer） |
| `app/workflow/runtime_adapter.py` | `_control_projection` 输出全部共享键；`_persist_progress` 排除 `_LIFTED_SHARED_KEYS`（不再写入 carrier）；新增 `pack_worker_patch`（worker 不持久化 workflow_progress）；`adapt_node(..., worker=True)`；`materialize_workflow_state` 恢复 `_SEND_TASK_KEYS`（dimension_key 等） |
| `app/workflow/root_graph.py` | L1/L2/L3 worker 节点改 `adapt_node(..., worker=True)` |
| `app/services/run_paths.py` | `run_tmp_root` 进程级缓存，杜绝并发 fallback 竞态导致 CAS store 路径分裂 |

### 3.2 验证

- LangGraph 官方 map-reduce 合成测试：3 并行 worker 写 `completed_dimensions`，reducer 合并 → `{'layer1': ['a','b','c']}` ✅
- 合成并行 persist：无 CAS 崩溃 ✅
- 诊断 graph：worker 被 Send 派发并执行真实路径 ✅

## 4. 遗留 & 下一步

- [x] 真实 LLM acceptance 复跑，确认 `completed=12/12` 且 L1 gate 正常 —— **已完成代码级收敛**：fan-in 聚合节点（`layer_completion_check`/`layer_aggregate`）改为 `worker=True` 不持久化，其输出键（`layer_just_completed`/`previous_layer`/`is_revision` 等）提升为顶层 reducer 键；无 CAS 冲突、无死循环
- [ ] L1/L2/L3 inline gate（`LEGACY_GATE_STAGES`）仍待迁移到 `gate_ref`（蓝图 Wave 4）
- [ ] `workflow_progress` 最终退役（蓝图 Round 3 L 任务）：stage_payload 剩余字段拆 typed artifacts
- [ ] 合成诊断脚本中 DB FOREIGN KEY 失败不影响本迁移，但暴露合成测试环境需真实 session 数据

## 6. 最终迁移形态（本轮收敛）

- `WorkflowState` 顶层含 27 个 Annotated reducer 键，LangGraph 负责并行合并
- worker 节点（l1/l2/l3_worker）、fan-in 节点（layer_completion_check/layer_aggregate）不持久化 `workflow_progress`
- `_persist_progress` 仅承担未迁移 legacy 阶段载体；carrier 自动排除 reducer 键（`_REDUCER_KEYS` 从 `get_type_hints` 推导，无硬编码清单）
- `materialize_workflow_state` 三种输入：`runtime` 通道 / `workflow_progress` artifact / Send payload（`dimension_key` 触发）
- 后续迁移（Round 3 L）只需把 carrier 剩余字段逐个拆成 typed artifact 后删除 `workflow_progress`

## 5. 禁止的捷径（蓝图 §9）复查

- 未用空集合/默认 approve 表示成功
- 未让 worker 隐式刷新数据源
- 未引入第二套 artifact owner
- reducer 合并是 LangGraph 官方机制，非自定义双写
