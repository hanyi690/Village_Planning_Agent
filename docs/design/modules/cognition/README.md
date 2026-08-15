# 认知层（L1/L2/L3）设计

> 模块：`backend/app/domain/{assessment,objectives,program}`、`workflow/layers/`
> 实现盘点：[24_MODULE_OUTPUT_INVENTORY.md](../../24_MODULE_OUTPUT_INVENTORY.md)

| 文档 | 内容 | 状态 |
|---|---|---|
| [04_PLANNING_PIPELINE.md](04_PLANNING_PIPELINE.md) | L1/L2/L3 认知层与空间决策闭环的总体管线 | TARGET |
| [11_EXPLORE_KG_ENRICHMENT.md](11_EXPLORE_KG_ENRICHMENT.md) | EXPLORE 与 KG 的证据富化 | TARGET |

当前事实：L1=12 维并行、L2=4 维 wave、L3=12 维 wave（`config/phases.yaml`）；L3 输出类型化
`PlanningClaimSet`，`PlanningProgram` 由 `domain/program/assembler.py` 确定性组装。