# 编码体系参考

> 本文档为编码体系的快速参考索引。详细实现见 `backend/app/modules/schema/encodings/`。

## 六套编码体系

| 编码体系 | 全称 | 用途 | 实现位置 |
|----------|------|------|----------|
| GB/T 21010 | 土地利用现状分类 | 三调国标编码 | `encodings/dicts/encodings/` |
| TUGUI | 国土空间调查用地用海分类指南 | 自然资发〔2023〕234号 | `encodings/dicts/encodings/tugui.yaml` |
| APPENDIX5 | 附录5编码 | 金田村现状层实际编码 | `encodings/dicts/encodings/appendix5.yaml` |
| GHFLBM | 规划用地分类编码 | 规划用地分类 | `encodings/dicts/encodings/ghflbm.yaml` |
| YDYHFL | 用地用海分类 | 统一用地分类 | - |
| VNE | 村庄规划用地分类 | V/N/E 三分类（住建部2014） | `encodings/dicts/encodings/vne.yaml` |

## 编码映射

映射文件位于 `encodings/dicts/mappings/`，采用统一 schema（`source_system`/`target_system`/`decision`）：

| 映射 | 文件 |
|------|------|
| GB/T21010 -> 规划分区 | `gbt21010_to_planning_zones.yaml` |
| GB/T21010 -> 主空间分区 | `gbt21010_to_primary_zones.yaml` |
| GB/T21010 -> 三分类 | `gbt21010_to_three_categories.yaml` |
| GB/T21010 -> 附录5分区 | `gbt21010_to_zone_types_appendix5.yaml` |
| GHFLBM -> 附录5分区 | `ghflbm_to_zone_types_appendix5.yaml` |
| VNE -> 三分类 | `vne_to_three_categories.yaml` |
| 规划分区 -> 控制码 | `planning_zones_to_control_code.yaml` |
| 规划分区 -> 主空间分区 | `planning_zones_to_primary_zones.yaml` |

## 新增编码（2026-07-31）

| 编码 | 文件 | 说明 |
|------|------|------|
| planning_zones | `planning_zones.yaml` | 五区规划用途分区 |
| primary_zones | `primary_zones.yaml` | 主空间分区 |
| three_categories | `three_categories.yaml` | V/N/E 三分类 |
| zone_types_appendix5 | `zone_types_appendix5.yaml` | 附录5分区类型 |
| zone_types_gbt50137 | `zone_types_gbt50137.yaml` | GB/T 50137 分区类型 |
| zone_types_town | `zone_types_town.yaml` | 乡镇分区类型 |
| zone_types_village | `zone_types_village.yaml` | 村庄分区类型 |

## 相关文档

- [Schema 层 README](../../backend/app/modules/schema/README.md) - 类型层级与设计原则
- [Schema encodings README](../../backend/app/modules/schema/encodings/README.md) - 编码体系详细设计
- [成果合规](../design/08_DELIVERABLES_COMPLIANCE.md) - 编码与汇交标准对齐
