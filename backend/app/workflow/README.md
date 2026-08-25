# Workflow 编排层

`app.workflow` 是唯一的 LangGraph 根图与阶段节点入口。它负责路由、Gate、重试、HUMAN
interrupt 和 checkpoint 边界；数据层、空间层和交付 adapter 不反向依赖它。

## 文件职责

- `root_graph.py`：`create_unified_planning_graph`、主图边和条件路由。
- `stages/target_projection.py`：唯一 TARGET_PROJECTION 阶段服务，将 PlanningProgram 投影为可验证的空间引用。
- `stages/ground.py`：唯一 GROUND 阶段服务，将空间引用绑定到数据层证据和候选集。
- `stages/select.py`：唯一 SELECT 阶段服务，产出 solver decision、portfolio artifacts 和 ExecutionPlan。
- `stages/execute.py`：唯一 EXECUTE 阶段服务，调用真实 worker 子图并把结果收敛为 typed artifacts。
- `stages/validate.py`：唯一 VALIDATE 阶段服务，只读取 EXECUTE typed artifacts。
- `stages/reconcile.py`：唯一 RECONCILE 阶段服务，检查目标到交付输入的完整链路。
- `application/interrupts.py`：唯一 HUMAN review projection；DELIVER 直接由根图接线。
- `stages/deliver.py`：唯一 DELIVER 阶段入口；从 typed artifacts 和 data-owned workspace 构建快照并持久化交付引用。
- `stages/support.py`：阶段中立的 checkpoint/context/ref/gate 辅助函数；阶段 adapter 不互相导入。
- `stage_adapter.py`：统一 `StageCommand`、`StageCompletion` 和 CAS artifact 持久化入口。
- `state.py`：根图使用的 ref-only `WorkflowState`；阶段局部载荷只能通过
  checkpoint 的 `runtime` channel 传递，禁止新模块继续扩展旧的并行状态模型。
- `stage_audit.py`：阶段输入审计和 provenance。

DELIVER 的空间质量规则由数据层和交付层共同执行：

- `SpatialWorkspace` 是 Agent 的唯一空间入口；完整 GIS 只在 DELIVER 的 snapshot builder 中读取。
- snapshot builder 会修复可恢复的源几何拓扑错误；规划 overlay 的 `(0, 0)` 无坐标占位会被省略，
  不会被 renderer 当作真实定位点。
- `DeliverySpatialSnapshot` 生成后，PNG、HTML、土地平衡和 export package 只读取它，不存在第二份
  `current/planned/render/export` GIS 来源。
- `planning_preview.png` 必须是一个双面板图：左侧现状、右侧规划；规划地类使用快照字段着色并有
  细边界，项目/设施定位点作为独立小点图层。

## 真实运行语义

```text
START → conversation → L1/L2/L3 → layer_completion_check → layer_aggregate
  → TARGET_PROJECTION → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER
```

`human_review_prepare → human_review_publish → human_review_wait → human_review_apply` 使用真实
LangGraph interrupt；resume 必须针对当前 checkpoint 的 event ID，不得从文件夹扫描 latest 产物或伪造恢复状态。

## 迁移边界

根图和 CAS artifact runtime 已从 `agent/bootstrap` 迁入 `workflow` 与 `infrastructure/artifacts`，旧生产导入路径已删除。
根图已将业务阶段拆分为独立 stage service；HUMAN projection 已迁入 application interrupt service，`stages/` 不再混入应用查询职责。

根 checkpoint 只保存 `WorkflowState` 控制字段、artifact refs 和当前的 `runtime`
channel。`runtime_adapter.py` 的 materialized stage view 是内部调用边界，不是公开
状态；旧阶段 carrier 不再由生产图读取，历史 checkpoint 必须先在
离线迁移流程中转换为当前 runtime channel。

目标目录和完成标准见 [00_SYSTEM_DESIGN.md](../../../docs/design/00_SYSTEM_DESIGN.md)。
