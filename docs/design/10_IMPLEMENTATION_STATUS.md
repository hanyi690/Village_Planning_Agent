# 实现状态台账

> 本表区分当前代码和目标设计，不把目录存在误认为职责已经实现。

状态：`CURRENT` 当前存在；`PARTIAL` 部分满足；`TARGET` 目标设计；`DEPRECATED` 待删除。

| 能力 | 状态 | 当前代码 / 说明 |
|---|---|---|
| 统一 PlanningContext | TARGET | 当前 runtime、completion、gis 仍可能重复构建 Bundle/KG |
| L1 并行分析 | CURRENT / PARTIAL | 维度并行和 reducer 已存在，产物仍以报告和扁平 State 为主 |
| L2 Strategy snapshot | PARTIAL | 有阶段和波次，但 KG 认知与策略 Gate 不完整 |
| L3 PlanningIntent | PARTIAL | 有 `SpatialPlanningIntent`，但仍混有旧 parse 路径 |
| EXPLORE EvidenceBundle | PARTIAL | 当前 `ExplorationInstruction` 仍携带候选 BSM，需拆分 |
| IntentCompiler | PARTIAL | `agent/gis/parse/agent.py` 是主要实现，旧 `tools/gis/parse.py` 待清理 |
| GROUND 子图 | TARGET | 当前 grounding 分散在 Explore、Parse 和 spatial_ops |
| SELECT 子图 | TARGET | 当前项目节点按候选顺序选第一个可用地块 |
| EXECUTE Worker 子图 | PARTIAL | 有 layout/facility/road 等 Worker，但道路存在重复实现 |
| Validation Router | PARTIAL | 有 validation loop，但错误仍存在全局 fallback 和宽泛异常捕获 |
| IntentGraph | PARTIAL | L3 写 KG 已有入口，生命周期和提交边界尚未统一 |
| PlannedState | PARTIAL | L4 回写和导出存在，需要接入统一 Reconcile |
| Delivery Gate | PARTIAL | 有 DeliveryGate 契约和导出校验，未成为所有输出的唯一门槛 |
| KG 命名重构 | TARGET | 当前文档和代码仍使用 KG L1/L2/L3/L4 |
| import boundary tests | TARGET | 当前存在 modules、services、agent、tools 反向依赖 |

## 当前实现的事实入口

- 主图：`backend/app/agent/graph.py`
- 层级路由：`backend/app/agent/routing.py`
- GIS 管线：`backend/app/agent/gis/layout_pipeline.py`
- 空间接地：`backend/app/modules/spatial_ops/grounding.py`
- 项目执行：`backend/app/agent/gis/execute/agent.py`
- Session Bundle：`backend/app/services/session_bundle.py`

这些入口是迁移对象，不是目标架构的永久边界。
