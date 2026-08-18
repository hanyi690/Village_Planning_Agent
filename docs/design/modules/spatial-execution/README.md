# 空间决策链设计（TARGET_PROJECTION / GROUND / SELECT / EXECUTE）

> 模块：`backend/app/workflow/stages/`、`backend/app/domain/{ground,allocation,materialization,suitability,demand}`、
> `backend/app/spatial/`
> 实现盘点：[24_MODULE_OUTPUT_INVENTORY.md](../../24_MODULE_OUTPUT_INVENTORY.md)

| 文档 | 内容 | 状态 |
|---|---|---|
| [06_TARGET_PROJECTION_EXECUTE.md](06_TARGET_PROJECTION_EXECUTE.md) | 四个阶段边界与目标设计 | TARGET |
| [28_RELATION_AWARE_SPATIAL_PLAN_GENERATION.md](28_RELATION_AWARE_SPATIAL_PLAN_GENERATION.md) | L1 证据、设施 KG、目标关系、联合场景与 GIS 物化 | TARGET / NORTH STAR |

当前事实：阶段节点在 `workflow/stages/`；`gate_policy.py::GATE_ROUTE_POLICY` 是路由策略表，
EXECUTE 是 gate 路由显式豁免（A4）。

28 号文档扩展 06 号文档：06 定义阶段边界，28 定义跨阶段不得丢失的地点证据、目标关系、
候选几何、约束因子、场景和关系满足度契约。两者冲突时，以 28 的关系感知模型为目标设计。
