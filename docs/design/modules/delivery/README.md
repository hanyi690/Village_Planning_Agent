# 成果 / 合规 / 交付设计

> 模块：`backend/app/domain/delivery/`、`backend/app/spatial/delivery/`、`backend/app/infrastructure/{rendering,export}/`
> 实现盘点：[24_MODULE_OUTPUT_INVENTORY.md](../../24_MODULE_OUTPUT_INVENTORY.md)

| 文档 | 内容 | 状态 |
|---|---|---|
| [08_DELIVERABLES_COMPLIANCE.md](08_DELIVERABLES_COMPLIANCE.md) | 成果、合规与交付门槛 | TARGET |

当前事实：`domain/delivery/` 构建 `DeliveryManifest` / `DeliverySpatialSnapshot`；
PNG/HTML/GeoJSON/导出包都从同一个快照派生。