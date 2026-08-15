# KG 语义桥与地名解析设计

> 模块：`backend/app/infrastructure/kg/`、`backend/app/spatial/grounding/`
> 实现盘点：[24_MODULE_OUTPUT_INVENTORY.md](../../24_MODULE_OUTPUT_INVENTORY.md)

| 文档 | 内容 | 状态 |
|---|---|---|
| [03_KG_SEMANTIC_BRIDGE.md](03_KG_SEMANTIC_BRIDGE.md) | KG 语义与空间桥接 | TARGET |
| [12_PLACE_NAME_RESOLUTION.md](12_PLACE_NAME_RESOLUTION.md) | 地名解析与 L1/KG 事实融合设计 | TARGET |

当前事实：KG 由 `infrastructure/kg/builder/`（layer1-4）构建，查询走
`infrastructure/kg/queries/`；地名解析在 `spatial/grounding/`（resolver / village_cluster_mapper /
flash_mention_extractor）。