# 村庄字段参考

> 本文档为村庄规划系统字段定义的快速参考索引。详细实现见 `backend/app/modules/schema/types/` 和 `backend/app/config/document_types.py`。

## 空间要素类型层级

```
L0  SpatialFeature                  矢量基类: geometry + bsm + ysdm + layer_type
 ├── L1  PointFeature / LineFeature / PolygonFeature
 └── L2  矢量语义子类 (CurrentLandUseParcel, CurrentRoad, ...)

L0  RasterDataset                   栅格基类: path + crs + bounds + bands
 └── L1  栅格语义子类 (DEMInput / DOMInput / SlopeRaster / ...)

L0  TableDataset                    表格基类: rows + columns + schema
 └── L1  表格语义子类 (PopulationTable / ControlRuleTable / ...)

L0  Document                        文档基类: text + doc_type + source
 └── L1  文档语义子类 (PlanningText / L3Report)
```

## 核心字段

### 矢量要素通用字段

| 字段 | 类型 | 说明 |
|------|------|------|
| bsm | str | 要素标识码（Biao Shi Ma） |
| ysdm | str | 要素代码（编码体系相关） |
| layer_type | str | 图层类型（GIS_LAYER_REGISTRY 映射） |
| geometry | dict | GeoJSON 几何 |

### VillageBundle 形态分组

| 形态 | 字段 | 内容 |
|------|------|------|
| points | PointLayerGroup | 设施/建筑/注记/高程/灾害 |
| lines | LineLayerGroup | 道路/等高线/行政界线 |
| polygons | PolygonLayerGroup | 地块/保护/管控/水系 |
| rasters | RasterLayerGroup | DEM/DOM/坡度/坡向 |
| tables | TableLayerGroup | 人口/管制规则/指标 |
| documents | DocumentGroup | 规划文本/L3报告 |

## GDB 输出图层

GDB_LAYER_REGISTRY 定义 12 层（`modules/schema/output/gdb.py`）：

| 图层 | 几何类型 | 说明 |
|------|----------|------|
| current_landuse | Polygon | 现状地类图斑 |
| planned_landuse | Polygon | 规划地类图斑 |
| boundary | Polygon | 村界 |
| current_road | Line | 现状道路 |
| planned_road | Line | 规划道路 |
| facility | Point | 公共服务设施 |
| ... | ... | ... |

## 相关文档

- [Schema 层 README](../../backend/app/modules/schema/README.md) - 类型层级详解
- [Schema types README](../../backend/app/modules/schema/types/README.md) - 类型定义
- [数据源规范](../data/data-source.md) - 金田村数据源字段结构
- [成果合规](../design/08_DELIVERABLES_COMPLIANCE.md) - GDB 汇交图层规范
