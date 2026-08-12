# 术语表

本文只保留当前代码和设计中仍使用的术语。路径以当前 `backend/app/` 为准；旧术语只在
审计文档中作为历史记录出现。

| 术语 | 含义 |
|---|---|
| `WorkflowState` | 根图 checkpoint 中的控制状态和 artifact 引用，不是完整业务对象。 |
| `ArtifactDescriptor` | 带 schema、digest、parents、producer 和 provenance 的不可变结果身份。 |
| `SessionDataSnapshot` | 一次会话输入资料及其来源、结构、CRS 和质量信息的冻结视图。 |
| `SpatialWorkspace` | data-owned 的空间查询/几何工作边界；不等于 graph state。 |
| `EvidenceBundle` | 带来源和 provenance 的证据集合；不直接等于规划决定。 |
| `PlanningClaimSet` | LLM/分析层产生的带证据 claims；必须经过领域组装。 |
| `PlanningProgram` | 领域层组装的规划程序；是 target projection 的输入。 |
| `TARGET_PROJECTION` | 将已组装规划程序确定性投影为空间引用和目标的阶段。 |
| `GROUND` | 将空间引用接到实体、候选几何和查询证据的阶段。 |
| `SELECT` | 应用硬约束、评分和冲突分配形成选址决定的阶段。 |
| `EXECUTE` | 将显式决定物化为 worker 结果、变化集和 planned state 的阶段。 |
| `DeliverySpatialSnapshot` | 所有地图、报告、导出和土地平衡共享的交付空间真相。 |
| `partial` | 运行有产物但仍有延期、未决、质量或法定完整性缺口的交付状态。 |
| `diagnostic_only` | 只生成诊断/审计，不得被前端当作规划成果。 |
| `HUMAN` | 需要人工输入、确认或延期后才能继续的显式工作流状态。 |

## 代码入口

- 根图：`backend/app/workflow/root_graph.py`
- API contracts：`backend/app/api/v1/contracts.py`
- artifact contracts/runtime：`backend/app/contracts/artifacts/`、`backend/app/infrastructure/artifacts/`
- 阶段节点：`backend/app/workflow/stages/`
- 领域决定：`backend/app/domain/`
- 当前状态：`docs/design/10_IMPLEMENTATION_STATUS.md`
