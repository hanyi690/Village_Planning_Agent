# 优化可执行任务清单 v2.3

> **Based on**: `schema/README.md` + `data/README.md` v4.3 设计 + `gis/` 删除后的架构
> **原则**: 设计已定（四形态 + 阶段抽象 + 实体/表达分离 + ProjectDataView/VillageBundle 两层 + 双轨接入），本表聚焦代码落地与 parse/kg/layout 大修
> **旧表状态**: 旧 T1-T28 基于 `gis.data` 渐进迁移，已随 `gis/` 目录删除失效
> **Updated: 2026-07-25 (v4.3)** -- Schema 覆盖度审计（21 文档）+ 字段扩展/编码修正/设施子类型化/防灾减灾/自然环境新类型

---

## 设计基线（已完成）

| 交付物 | 状态 | 位置 |
| --- | --- | --- |
| Schema 四形态类型层级（矢量/栅格/表格/文档） | ✅ | `backend/app/modules/schema/README.md` |
| ProjectDataView -> VillageBundle 两层数据视图 | ✅ | `schema/README.md` §三 |
| TableDataset 第四形态（汇交"一表一规则"类型化） | ✅ | `schema/README.md` §2.3 |
| Data 双轨接入（显式注册 + 智能推断，含表格分支） | ✅ | `backend/app/modules/data/README.md` |
| 项目配置与数据源配置分离（projects.yaml vs sources.yaml） | ✅ | `data/README.md` §七 |
| `gis/` 目录删除 + 生产引用清理 | ✅ | gis_test_routes dev helpers、zone_generator 断链修复 |
| 系统设计文档 v4.1 摘要 | ✅ | `docs/gis/00_SYSTEM_DESIGN.md` 头部 |
| Exa 调研验证（305 sources） | ✅ | `exa-results/layer-architecture-2026-07-25.md` |
| 阶段抽象 + 注记/设施分离 + 规范覆盖（Group F + AdminArea 扩展） | ✅ | `schema/README.md` §2.1/§五 (v4.2) |
| Schema 覆盖度审计（21 文档调研）+ v4.3 补全任务 S11-S15 | ✅ | `diagnostics/SCHEMA_COVERAGE_AUDIT_2026-07-25.md` |

---

## 执行顺序与关键路径

```
Schema 落地:  S1 -> S2 -> S3 -> S4a -> S4b -> S5 -> S6
                                │      │
                              ST1-ST3 (表格/文档类型, 与 S4 并行)
                                │
Data 双轨:    D1 -> D2 -> D3 -> D4 -> D5 -> D6 ; D7 -> D8 -> D9
                                │
清理:         C1, C2 ; C3, C4 ; C5
                                │
KG 大修:      K1 -> K2(项目级) -> K3 -> K4 -> K5
                     │
PARSE 大修:   P1 -> P2 ; P3 ; P4 ; P5
                     │
LAYOUT 大修:  L1 -> L2 -> L3 -> L4 -> L5 ; L6
```

**关键路径**: `S1(base.py) -> S4a(VillageBundle) -> S4b(ProjectDataView) -> D5(load_project_data_view) -> K2(项目级KG) -> L1(zone_generator 适配)`
**前置约束**: 所有下游（KG/PARSE/LAYOUT）依赖 S4a+S4b（新数据视图结构）落地。`current_landuse`/`planned_landuse` 分离 + 项目级聚合是破坏性变更。

---

## 一、Schema 抽象层落地

### S1 新建 `types/base.py` -- 几何中间抽象 + 栅格基类 [M]
- **文件**: `backend/app/modules/schema/types/base.py`（新建）
- **改动**:
  - `SpatialFeature` 迁入，**加 `layer_type: str` 字段**（嵌入图层身份，对标 pynspd layer_meta）
  - 新增 `PointFeature`/`LineFeature`/`PolygonFeature`，`geometry` field 加 `field_validator` 校验几何类型
  - 新增 `RasterDataset` 基类（path/crs/bounds/width/height/transform/band_count/dtype/layer_type/_meta）
- **验收**: `PointFeature(geometry={"type":"Polygon",...})` 抛 `ValueError`
- **依赖**: 无

### S2 `spatial_types.py` 类型重排继承 [L]
- **文件**: `spatial_types.py`
- **改动**: 30+ 类型重排到 L1 几何基类（Point/Line/Polygon 分组见 `schema/README.md` §2.1）；所有子类继承对应 L1 基类，保留 `layer_type` 字段
- **验收**: `issubclass(CurrentLandUseParcel, PolygonFeature)` 为 True
- **依赖**: S1

### S3 `raster_types.py` 补栅格子类 [S]
- **文件**: `raster_types.py`
- **改动**: 新增 `SlopeRaster`/`AspectRaster`/`SuitabilityRaster`；`DEMInput`/`DOMInput` 改继承 `RasterDataset`
- **验收**: 5 个栅格子类可实例化
- **依赖**: S1

### S4a `canonical.py` VillageBundle 分桶重组 [L]（破坏性，关键路径）
- **文件**: `canonical.py`
- **现状**: `GISDataBundle.landuse: List[Any]` 混装现状+规划（双倍地块根因）
- **改动**:
  - `GISDataBundle` 重命名为 `VillageBundle`（村庄级子视图）
  - 删除 `landuse` 字段（不保留兼容视图）
  - 新增 `current_landuse`/`planned_landuse` 分离字段
  - `roads: List[LineFeature]`/`annotations: List[PointFeature]` 等类型注解升级到 L1 基类
  - 新增 `water_lines`/`water_areas`/`buildings`/`protection_zones`/`admin_areas`
  - 新增 `extra_layers: Dict[str, List[SpatialFeature]]`
  - 新增 `parcels_by_phase(phase)` 方法
- **验收**: `village.current_landuse`/`planned_landuse` 分离；无 `landuse` 属性
- **依赖**: S2, S3
- **风险**: 破坏性，所有下游 `bundle.landuse` 访问必须改造

### S4b `canonical.py` ProjectDataView 项目级外壳 [L]（关键路径）
- **文件**: `canonical.py`
- **改动**:
  - 新增 `ProjectDataView`（项目级）：`villages: Dict[str, VillageBundle]` + `cross_village_layers` + `rasters`/`extra_rasters` + `tables` + `documents` + `project_metadata`
  - 新增 `get_village(name) -> VillageBundle` 便利方法
  - 新增 `layer_tree` property（列出所有图层 name/source/geometry_kind/feature_count，对标 QGIS QgsLayerTree）
  - 新增 `ProjectMetadata`（project_id/bbox/crs/参与村庄/推断警告汇总）
- **验收**: `project.get_village("金田村")` 返回 VillageBundle；`project.layer_tree` 列出全部图层
- **依赖**: S4a, ST1（tables 字段类型）, ST2（documents 字段类型）
- **风险**: 数据视图从村庄级上移项目级，KG/PARSE/LAYOUT 全部需适配（见 K5/P5/L1）

### S5 `layer_registry.py` 扩展 [S]
- **文件**: `layer_registry.py`
- **改动**: `LayerTypeEntry` 加 `geometry_kind`（含 `"table"`/`"document"`）+ `is_reference_layer: bool`；28 现有项补 geometry_kind；新增 dem/dom/slope 等栅格 + population/industry/control_rules 等表格 layer_type 注册；三区三线（farmland_protection/ecological_protection/urban_dev_boundary）标 `is_reference_layer=True`
- **验收**: `get_layer_entry("population").geometry_kind == "table"`；三区三线 `is_reference_layer == True`
- **依赖**: S3, ST1

### S6 混合几何类型拆分 [S]
- **文件**: `spatial_types.py`
- **改动**: `WaterFeature` 拆 `WaterLine`/`WaterArea`；`HistoricalProtection` 拆 Point/Area
- **验收**: 每个具体类型有唯一主几何
- **依赖**: S2

### S7 阶段抽象系统化 [M] [v4.2 新增]
- **文件**: `spatial_types.py`
- **现状**: 仅 `BaseLandUseParcel` 是现状/规划共同基类；道路/设施/注记的现状与规划无共同 Base
- **改动**:
  - 新增 `BaseRoad`（shape_length/road_level/road_width/road_name）-> CurrentRoad/PlannedRoad 继承
  - 新增 `BaseFacility`（facility_type/facility_name/scale/service_radius/category）-> CurrentFacility/PlannedFacility 继承
  - 新增 `BaseAnnotation`（text/category）-> CurrentAnnotation/PlannedAnnotation 继承
  - 新增 `PlannedFacility` 类型（从 PlannedAnnotation 拆出规划设施点）
- **验收**: 现状/规划两态要素都有 Base；`issubclass(CurrentRoad, BaseRoad)` 为 True
- **依赖**: S2

### S8 注记/设施分离 [M] [v4.2 新增]
- **文件**: `spatial_types.py`、`ingest.py`、`layer_registry.py`
- **现状**: `CurrentFacility.from_annotation_feature` 从 annotation 图层派生设施点；规划设施点混在 `PlannedAnnotation`（category="规划设施点"）。设施（空间实体）与注记（表达要素）混淆且现状/规划不对称
- **改动**:
  - `CurrentFacility`/`PlannedFacility` 独立为空间要素（PointFeature 子类，完整业务字段），删 `from_annotation_feature`，改独立 ingest 路径
  - 新增 `AnnotationFeature` 表达要素基类（继承 PointFeature 复用几何），`CurrentAnnotation`/`PlannedAnnotation` 继承它
  - `layer_registry`: annotation 的 `geometry_kind` 改 `"annotation"`（区别于 `"point"` 实体）
  - ingest: annotation 图层的"现状/规划设施点"分类 ingest 为 CurrentFacility/PlannedFacility（空间要素），纯文字标注（村名等）ingest 为 Current/PlannedAnnotation（表达要素）
  - KG: 设施入库，注记不入库
- **验收**: 设施是空间要素入 KG，注记是表达要素不入 KG；现状/规划设施对称
- **依赖**: S7, S5

### S9 规范覆盖补全（Group F + AdminArea 扩展）[M] [v4.2 新增]
- **文件**: `spatial_types.py`、`raster_types.py`、`layer_registry.py`
- **现状**: `01_DATA_ACQUISITION_PLAN.md` §4.1 的 7 新类型全部缺失；AdminArea 缺 admin_level/parent_code
- **改动**:
  - 新增 Group F 自然资源 5 矢量类型: `SoilType`/`SoilErosion`/`Watershed`/`NatureReserve`/`HydrogeologyZone`（字段见 01_DATA_ACQUISITION_PLAN §4.1）
  - 新增 2 栅格类型: `PopulationGrid`/`GDPGrid`（继承 RasterDataset）
  - `AdminArea` 扩展 `admin_level`(village/town/county/city/province) + `parent_code`
  - `layer_registry` 注册 7 新 layer_type + 更新 admin_area
- **验收**: 7 新类型可实例化；AdminArea 5 级可表达；layer_registry 覆盖规范 §4
- **依赖**: S2, S3, S5

### S10 三区三线管控抽象 [M] [v4.2 新增]
- **文件**: `spatial_types.py`、`layer_registry.py`
- **现状**: `01_DATA_ACQUISITION_PLAN` 把 ThreeZone/ThreeLine 误标"KG独有"（实际是矢量引用层）；三区（生态/农业/建设空间）无类型；三线/管制区/用途分区分散无共同抽象
- **改动**:
  - 新增 `BaseControlZone` 管控区基类（protection_level/control_measure/引用条款），统一管控语义
  - 新增 `ThreeZoneItem`（三区：生态/农业/建设空间，面，引用层）
  - `ControlLine`/`ConstructionCtrlZone`/`ConditionalConstructionZone`/`LandUseZone` 重排继承 `BaseControlZone`
  - `PlanningScope` 移出管控区（范围定义，非管控）
  - `layer_registry` 注册 `three_zone`（polygon, is_reference_layer=True）
- **验收**: `issubclass(ThreeZoneItem, BaseControlZone)` 为 True；三区三线作为矢量引用层注册；管控区共享 protection_level
- **依赖**: S2, S5

### S11 字段扩展与编码修正 [L] [v4.3 新增]（高优先级，汇交合规）
- **文件**: `spatial_types.py`、`table_types.py`、`layer_registry.py`
- **依据**: `diagnostics/SCHEMA_COVERAGE_AUDIT_2026-07-25.md` §三
- **改动**:
  - `PlannedLandUseParcel` 补 QMDLTB 10 字段: TBH/DLMJ/QMDLBM/LYYSDM/LSYSXZB1-3/LSZBMJ1-3
  - `ControlRuleTable` 补: 允许用途/禁止用途/管控级别(约束性/引导性)
  - `ConstructionProjectTable` 补: 资金筹措方式/责任主体/建设方式/用地面积/建筑面积
  - `PlanningIndicatorTable` 补: 基期年/变化量
  - `LandUseStructureTable` 补: 比重
  - `BaseFacility` 补: 配置级别(中心村/基层村)/服务人口
  - `CurrentBuilding` 补: building_status(空置/废弃/未建)/抗震设防分类/建筑风貌
  - `PlannedRoad` 补: 红线宽度/车行道宽度/人行道宽度/设计速度/路面材料
  - `GeologicalHazardPoint` 补: 治理措施/工程投资/治理时限
  - `WaterLine`/`WaterArea` 补: 整治措施/水位控制/水质标准
  - `HistoricalProtection` 补: 保护措施类型/保护对象细类
  - `ConstructionCtrlZone.tdkjgzfqdm` 长度 Char(2)->Char(4)
  - 编码修正: `CurrentLandUseParcel.sddlbm` 改 GB/T21010；`PlannedLandUseParcel.dlbm` 改 tugui
  - 6 套编码补枚举校验（gbt21010/tugui/appendix5/ghflbm/ydyhfldm/vne 值域）
  - 图层补: 宅基地建设范围线、永久基本农田储备区
- **验收**: PlannedLandUseParcel 字段覆盖 QMDLTB 表2；编码体系与规范对齐
- **依赖**: S2, S5, ST1

### S12 设施子类型化 [M] [v4.3 新增]
- **文件**: `spatial_types.py`、`layer_registry.py`
- **依据**: GB50445 整治设施 + GB50188 公共设施配置
- **改动**: `BaseFacility` 下增 8 子类（PointFeature/面）:
  - `WaterSupplyFacility`（水源/处理/规模/管网/服务人口）
  - `DrainageFacility`（排水体制/处理/规模/排放标准）
  - `WasteFacility`（收集/处理/服务半径）
  - `SanitaryFacility`（公厕/户厕/无害化方式）
  - `FireFacility`（消防站/水池/消火栓/通道/水源）
  - `EvacuationShelter`（广场/学校/绿地/有效面积/容纳人数/应急设施）
  - `EnergyFacility`（沼气/太阳能/生物质）
  - `LightingFacility`（照明类型）
- **验收**: 8 设施子类可实例化；CurrentFacility/PlannedFacility 继承 BaseFacility 保留为通用回退
- **依赖**: S7

### S13 防灾减灾要素 [M] [v4.3 新增]
- **文件**: `spatial_types.py`、`raster_types.py`
- **依据**: GB50223 抗震 + GB50188 防灾 + GB50445 安全防灾
- **改动**:
  - `SeismicFortificationCategory` 枚举（特殊/重点/标准/适度设防），作 CurrentBuilding/PlannedFacility 字段
  - `SecondaryHazardSource` 类型（次生灾害源: 火灾/爆炸/毒物，点）
  - `FloodSafetyFacility`（围埝/安全台/避水台，面）或并入 FloodControlLine
- **验收**: 防灾减灾覆盖率 15%->60%+
- **依赖**: S2, S12

### S14 自然环境新类型 [M] [v4.3 新增]
- **文件**: `raster_types.py`、`spatial_types.py`
- **依据**: 教材 06-§4/01-§10 基础资料要求
- **改动**:
  - `ClimateRaster`（温度/降水/风向/风速/日照/蒸发，栅格）或 `MeteorologicalTable`（表格）
  - `EngineeringGeologyZone`（地基承载力/地质构造/不良工程地质，面，Group F 扩展）
- **验收**: 自然环境要素覆盖建设适宜性评价所需基础
- **依赖**: S3, S9

### S15 权属与地块控制表 [S] [v4.3 新增]
- **文件**: `spatial_types.py`、`table_types.py`
- **依据**: 教材 05-§2.1.2 宅基地确权 + 永安村案例 附表2
- **改动**:
  - `LandRightConfirmation`（宅基地确权: 权属/面积/位置，面）
  - `PlotControlTable`（重要地块控制指标: 编码/用地代码/层数/高度/风貌，TableDataset）
- **验收**: 权属与地块控制有类型化落点
- **依赖**: S2, ST1

---

## 一·补、表格与文档类型落地 [v4.1 新增]

### ST1 `types/table_types.py` -- TableDataset + 子类 [M]
- **文件**: `table_types.py`（新建）
- **改动**: `TableDataset` 基类（rows/columns/table_type/layer_type/_meta）+ `ColumnSpec`；输入型子类（`PopulationTable`/`IndustryTable`/`FacilityInventory`）；输出型子类（`ConstructionProjectTable`/`ControlRuleTable`/`PlanningIndicatorTable`/`LandUseStructureTable`）
- **验收**: 7 个表格子类可实例化
- **依赖**: S1（layer_type 字段模式）

### ST2 `types/document_types.py` -- Document + 子类 [S]
- **文件**: `document_types.py`（新建）
- **改动**: `Document` 基类（text/doc_type/source/_meta）+ `PlanningText`/`L3Report`
- **验收**: 2 个文档子类可实例化
- **依赖**: 无

### ST3 `output/tables.py` -- 表格汇交导出 [M]
- **文件**: `output/tables.py`（新建）
- **改动**: 表格汇交导出规范（近期建设项目表/管制规则/规划指标表/用地结构表 -> Excel/MDB 表），对标 `gdb.py` 之于矢量
- **验收**: `export_tables(project.tables)` 产出汇交表格文件
- **依赖**: ST1

---

## 二、Data 双轨落地

### D1 `ingest_inference.py` 矢量推断管道 [L]
- **文件**: `ingest_inference.py`（新建）
- **改动**: 矢量五步推断（几何检测->字段匹配->编码探测->动态模型->包装）；完全未知时降级为 `Point/Line/PolygonFeature + Dict properties`（对标 geojson-pydantic `Feature[Geometry, Dict]`）
- **验收**: 未注册野 GeoJSON 产出动态模型 + confidence
- **依赖**: S1, S2

### D2 `ingest_inference.py` 栅格推断管道 [M]
- **文件**: `ingest_inference.py`
- **改动**: 栅格四步推断（GDAL元数据->波段值域匹配->CRS校验->包装）
- **验收**: 未知 GeoTIFF 推断为 DEMInput/DOMInput/动态 RasterDataset
- **依赖**: S3, D1

### D3 `mappings/field_aliases.yaml` 矢量字段知识库 [S]
- **文件**: `mappings/field_aliases.yaml`（新建）
- **改动**: 字段名 -> 标准属性映射（含中英文别名）
- **验收**: D1 Step2 可查表匹配
- **依赖**: D1

### D4 `mappings/user_field_mappings.yaml` 用户学习 [S]
- **文件**: `mappings/user_field_mappings.yaml`（新建）
- **改动**: 用户确认映射累积；推断优先查 user mappings
- **验收**: 用户确认后下次复用
- **依赖**: D1, D3

### D5 `catalog.load_project_data_view` 项目级加载 [L]（关键路径）
- **文件**: `catalog/catalog.py`
- **改动**:
  - 新增 `load_project_data_view(project_id, require_registered=False) -> ProjectDataView`
  - 读 `projects.yaml` 取项目配置（参与村庄 + 源覆盖 + 上传数据）
  - 加载共享栅格 -> `project.rasters`；跨村图层 -> `project.cross_village_layers`；表格 -> `project.tables`；文档 -> `project.documents`
  - 逐村加载 `VillageBundle`（boundary -> current/planned -> ...）
  - 已注册走 `ingest`，未注册走 `ingest_inference`，推断结果填 `extra_layers`/`extra_rasters`
  - 汇总 `layer_tree` + `inference_warnings` 到 `project_metadata`
  - 推断利用项目上下文校准（同项目同编码体系提高置信度）
  - `load_village_bundle` 保留为便利方法（从项目视图取单村）
- **验收**: `load_project_data_view("jintian_2026")` 返回完整 ProjectDataView
- **依赖**: S4a, S4b, D1, D2, D7, D8

### D6 `ingest.py` 加 result_to_raster 端口 [S]
- **文件**: `ingest.py`
- **改动**: 新增 `result_to_raster(result, layer_type) -> DEMInput|DOMInput|...`，栅格元数据校验
- **验收**: 已注册栅格经 `result_to_raster` 类型化
- **依赖**: S3, S5

### D7 `ingest_inference.py` 表格推断管道 [M] [v4.1 新增]
- **文件**: `ingest_inference.py`
- **改动**: 表格四步推断（列结构读取->列名语义匹配->类型匹配->包装）；读 `mappings/table_column_aliases.yaml`
- **验收**: 未知 CSV 推断为 PopulationTable/ControlRuleTable/动态 TableDataset
- **依赖**: ST1, D1

### D8 `ingest.py` 加 result_to_table 端口 [S] [v4.1 新增]
- **文件**: `ingest.py`
- **改动**: 新增 `result_to_table(result, layer_type) -> PopulationTable|ControlRuleTable|...`，列结构校验
- **验收**: 已注册表格经 `result_to_table` 类型化
- **依赖**: ST1, S5

### D9 `sources/table.py` + `projects.yaml` 项目配置 [M] [v4.1 新增]
- **文件**: `sources/table.py`（新建）、`catalog/projects.yaml`（新建）、`catalog/config.py`
- **改动**: `TableDriver`（CSV/Excel/JSON/L3内嵌表读取）；`projects.yaml` 项目逻辑配置（参与村庄/源覆盖/上传/跨村引用）；`config.py` 加 `ProjectConfig` Pydantic 模型
- **验收**: `projects.yaml` 配置可加载；表格源经 TableDriver 读取
- **依赖**: ST1, D8

---

## 三、死脚本/测试清理（gis/ 删除残留）

> 这些脚本/测试引用已删的 `gis.data.*`/`gis.layout.*`，本就是断链状态。

### C1 `run_layout_pipeline.py` 重写 [M]
- **现状**: `:100 from app.modules.gis.data.catalog.loaders import load_gis_data_full`（断链）
- **改动**: `load_gis_data()` 改用 `DataCatalog().load_project_data_view()`；适配 ProjectDataView/VillageBundle
- **验收**: 脚本可运行
- **依赖**: S4a, S4b, D5

### C2 `run_parse_pipeline.py` 重写 [M]
- **现状**: `:80` 同 C1 断链
- **改动**: 同 C1
- **验收**: 脚本可运行
- **依赖**: S4a, S4b, D5

### C3 `render_*.py` 归档或重写 [S]
- **现状**: 引用 `gis.layout.*`（断链死脚本）
- **改动**: 归档 `scripts/archive/` 或重写用 `tools/gis/_generation/` + `tools/gis/_rendering/`
- **验收**: 归档或 import 正确
- **依赖**: 无

### C4 `test_gis_unit.py` 重写 [M]
- **现状**: 引用 `gis.data.loader/intent_cache`（断链）
- **改动**: 改用 `data.documents` + `data.catalog`；适配 ProjectDataView
- **验收**: 测试可运行
- **依赖**: S4a, S4b, D5

### C5 `gis_test_routes.py` dev helpers 清理 [S]
- **现状**: 已加 dev helpers 解除 gis/ 依赖
- **改动**: 路由改用 `load_project_data_view`，删除 dev helpers
- **验收**: 路由直接消费 ProjectDataView
- **依赖**: S4b, D5

---

## 四、PARSE 大修

### P1 `parse/agent.py` 拆子包 + extractor 注册表 [L]（原 T28）
- **文件**: `parse/agent.py`（1451 行）-> `parse/` 子包
- **改动**: `agent.py` -> graph 编排器；`extractors/` 每维度一模块 + `ExtractorRegistry`
- **验收**: 加新抽取维度 = 加 extractor 模块 + 注册一行
- **依赖**: P2

### P2 `SpatialContext` 迁 `parse_contracts` [S]（原 T17）
- **改动**: `SpatialContext` 从 `layout_contracts` 迁 `parse_contracts`
- **依赖**: 无

### P3 枚举改注册表 [M]（原 T25）
- **改动**: `section_type`/`action`/`constraint.type` 硬编码 Literal 改注册表
- **依赖**: 无

### P4 PARSE state 注入 KG [M]（原 T18）
- **改动**: `ParseAgentState` 加 `kg` 字段；工具调用从 state 取
- **依赖**: K2, K3

### P5 PARSE 适配 ProjectDataView [M]
- **改动**: 所有 `bundle.landuse` 访问改 `village.current_landuse`/`planned_landuse`；`compute_spatial_context` 收 ProjectDataView（多村上下文）
- **验收**: PARSE 不访问 `bundle.landuse`
- **依赖**: S4a, S4b

---

## 五、KG 大修

### K1 `builder.py` 拆子包 [L]（原 T24）
- **文件**: `kg/builder.py`（2124 行）-> `kg/builder/` 子包
- **改动**: 按实体组分文件（base/parcels/protection/infrastructure/planning/natural/intent）
- **验收**: `PlanningKG` 行为不变
- **依赖**: 无

### K2 项目级 KG + 类型化摄入 [L]（原 T7/T8/T9，关键路径）
- **文件**: `kg/builder/`、`kg/manager.py`
- **改动**:
  - KG 上移为项目级 `ProjectKG`（多村实体 + 跨村关系：村间邻接、共享水系、道路连通）
  - 新 `build_from_project(project: ProjectDataView)`，遍历 `project.villages` + `cross_village_layers`
  - 新 `add_parcels(List[CurrentLandUseParcel])` 等类型化 API，收 `current_landuse`/`planned_landuse` 分离列表
  - 删 `KGInputParcels.from_geojson` + KG data import
  - `KGManager` 缓存 key 改 hash 类型化字段，项目级缓存
- **验收**: 新 API 签名拒绝 dict；从 ProjectDataView 构建的 KG 含多村 + 跨村关系
- **依赖**: S4a, S4b, K1
- **注**: 数据视图上移项目级，KG 必须同步上移，否则数据项目级/KG 村庄级断层

### K3 ConstraintCompiler [L]（原 T10-T13，关键路径）
- **文件**: `kg/constraint_compiler.py`（新建）
- **改动**: `ConstraintCompiler.compile(intent, project, kg) -> MIPModel`；硬约束（保护地块/三线）+ 软约束（目标/邻接）；补齐 KG 读 API；`layout_pipeline` 用 ConstraintCompiler 替代 `tools/gis/kg.py` 拍平
- **验收**: MIP 从 MIPModel 取约束；回归通过
- **依赖**: K2

### K4 KG 入库扩展 [L]（原 T22）
- **改动**: `add_protection_zones`/`add_control_lines`/`add_natural_features`/`add_terrain` 类型化实现 + 实际数据接入
- **验收**: KG 入库率 4/29 -> 15+/29
- **依赖**: K2, S3

### K5 KG 适配 ProjectDataView [M]
- **改动**: KG 从 `project.villages[name].current_landuse`/`planned_landuse` 读取，跨村关系从 `cross_village_layers` 计算
- **验收**: KG 构建不访问旧 `bundle.landuse`
- **依赖**: S4a, S4b, K2

---

## 六、LAYOUT 大修

### L1 `zone_generator` 适配 ProjectDataView [M]
- **现状**: 已修 `gis.optimizer` 断链 import
- **改动**: 从 `village.current_landuse` 读取地块；MIP 结果写回 `village.planned_landuse`
- **验收**: zone 生成使用类型化地块
- **依赖**: S4a, K3

### L2 `facility_placer` 适配 [S]
- **改动**: 从 `village.annotations`/`extra_layers` 读取设施锚点
- **依赖**: S4a

### L3 `axis_builder` 适配 [S]
- **改动**: 适配 ProjectDataView
- **依赖**: S4a

### L4 规划道路生成器 [M]
- **文件**: `tools/gis/_generation/`（新建 road 模块）
- **改动**: 实现 `PlannedRoad` 生成器（图搜索 + 最短路径），从 `village.roads` + `project.cross_village_layers["road"]` 读取
- **依赖**: S4a, S4b

### L5 验证闭环完善 [M]
- **改动**: 8 项检查 + 8 条硬约束自动化；从 `village.current_landuse`/`planned_landuse` + KG 约束读取；表格产出（ConstructionProjectTable/ControlRuleTable）写入 `project.tables`
- **依赖**: S4a, K3, ST1

### L6 ANALYZE 层骨架 [L]（原 T26）
- **文件**: `agent/gis/analyze/`（新建子包）
- **改动**: `dem_analysis.py`（DEM -> TerrainAnalysisResult）+ `double_evaluation.py`（双评价）；链路: `project.rasters["dem"]` -> analyze -> TerrainAnalysisResult -> SpatialContext/KG
- **依赖**: S3, D2, K4

---

## 验收回归（每个任务完成后跑）

```bash
python backend/scripts/run_layout_pipeline.py          # C1 完成后
python -m pytest backend/tests/unit/test_gis_unit.py    # C4 完成后
python -m pytest backend/tests/unit/test_schema_promotion.py  # test_old_path_removed 已通过
```

---

## 建议批次

| 批次 | 任务 | 目标 | 预估 | 状态 |
|---|---|---|---|---|
| 批次 0 | 设计基线 | schema/data README v4.1 + gis 删除 + 系统设计 v4.1 + Exa 调研 | - | ✅ 完成 2026-07-25 |
| 批次 1 | S1, S2, S3, S5, S6, S7, S8, S9, S10, ST1, ST2 | Schema 类型层级 + 阶段抽象 + 注记设施分离 + 规范覆盖 + 三区三线管控 + 表格/文档 | 5 天 | ⏳ |
| 批次 1.5 | S11, S12, S13, S14, S15 | v4.3 规范覆盖补全（字段扩展+编码修正+设施8子类型+防灾减灾+自然环境+权属） | 4 天 | ⏳ |
| 批次 2 | S4a, S4b, ST3 | VillageBundle 分桶 + ProjectDataView 外壳（破坏性，关键路径） | 3 天 | ⏳ |
| 批次 3 | D1-D9 | 双轨接入（矢量/栅格/表格三分支 + 项目配置 + 项目级加载） | 5 天 | ⏳ |
| 批次 4 | C1, C2, C4, C5 | 死脚本/测试清理 | 2 天 | ⏳ |
| 批次 5 | K1, K2, K5 | KG 拆包 + 项目级化 + 适配 ProjectDataView | 3 天 | ⏳ |
| 批次 6 | K3, K4 | ConstraintCompiler + KG 入库扩展（关键路径终点） | 3 天 | ⏳ |
| 批次 7 | P1-P5 | PARSE 大修 | 4 天 | ⏳ |
| 批次 8 | L1-L5 | LAYOUT 大修（含表格产出写入） | 4 天 | ⏳ |
| 批次 9 | L6, C3 | ANALYZE 骨架 + render 归档（远期） | 3 天 | ⏳ |

---

## 与旧任务（T1-T28）的对应关系

| 旧任务 | 新任务 | 说明 |
| --- | --- | --- |
| T1-T4 (Data 接线) | D5 + C1/C2 | gis/ 已删，DataCatalog 项目级加载 |
| T5/T6/T23 (shim/注册表/文档) | ✅ 已完成 | 批次 0 |
| T7/T8/T9 (KG 类型化) | K2 | 升级为项目级 KG |
| T10-T13 (ConstraintCompiler) | K3 | 收 ProjectDataView |
| T14-T16 (Schema 补类型) | S3 + S5 + ST1 | 栅格 + geometry_kind + 表格 |
| T17 (SpatialContext 迁移) | P2 | |
| T18 (PARSE state 注入 KG) | P4 | |
| T19-T21 (GeoPackage/capabilities/STAC) | 远期 | 本表暂不规划 |
| T22 (KG 入库扩展) | K4 | |
| T24 (拆 builder) | K1 | |
| T25 (枚举注册表) | P3 | |
| T26 (ANALYZE 骨架) | L6 | |
| T27a-T27e (gis 清理) | ✅ 已完成 | gis/ 已删 |
| T28 (拆 parse/agent) | P1 | |
| (v4.1 新增) | S4b, ST1-ST3, D7-D9, K2 项目级 | ProjectDataView + TableDataset + 项目配置 |
