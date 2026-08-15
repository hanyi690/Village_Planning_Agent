# 空间决策链设计（TARGET_PROJECTION / GROUND / SELECT / EXECUTE）

> 模块：`backend/app/workflow/stages/`、`backend/app/domain/{ground,allocation,materialization,suitability,demand}`、
> `backend/app/spatial/`
> 实现盘点：[24_MODULE_OUTPUT_INVENTORY.md](../../24_MODULE_OUTPUT_INVENTORY.md)

| 文档 | 内容 | 状态 |
|---|---|---|
| [06_TARGET_PROJECTION_EXECUTE.md](06_TARGET_PROJECTION_EXECUTE.md) | 四个阶段边界与目标设计 | TARGET |

当前事实：阶段节点在 `workflow/stages/`；`gate_policy.py::GATE_ROUTE_POLICY` 是路由策略表，
EXECUTE 是 gate 路由显式豁免（A4）。