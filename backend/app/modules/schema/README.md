# Schema Layer - 类型契约

> **定位**: 四层架构底层 (`Schema ← Data ← KG ← Agent`)，定义空间要素类型、编码体系、输出规范。
> **零依赖**: 不 import Data / KG / Agent / Tools 中的任何模块。
> **Updated: 2026-07-25 (v4.3 落地)** — v4.3 形态重组: GISDataBundle/GeoFeature/ProviderLandParcel/GISMetadata 废弃, VillageBundle 统一容器 + 6 个形态 Group 类 (PointLayerGroup/LineLayerGroup/PolygonLayerGroup/RasterLayerGroup/TableLayerGroup/DocumentGroup), _assign_to_bundle 改为 isinstance 类型分发 (33 个具体子类全覆盖), inferred 列表收容推断图层, constraint_polygons 聚合约束面。

> **Status: v4.3 落地完成。** 所有设计类型已实现, 下游已迁移到形态视图。

---

## 一、设计原则：四形态结构优先

空间与非空间数据的第一性特征是**数据形态**。本层按四种形态分型定义，先于语义角色：

| 形态           | 第一性特征                              | L1 抽象                                             | L2 语义子类示例                        |
| -------------- | --------------------------------------- | --------------------------------------------------- | -------------------------------------- |
| **矢量** | 几何结构 (Point/Line/Polygon)           | `PointFeature`/`LineFeature`/`PolygonFeature` | CurrentLandUseParcel, CurrentRoad, ... |
| **栅格** | 波段与值域 (单波段连续/多波段影像/分类) | `RasterDataset`                                   | DEMInput, DOMInput, SlopeRaster, ...   |
| **表格** | 列结构 (非空间结构化行列)               | `TableDataset`                                    | PopulationTable, ControlRuleTable, ... |
| **文档** | 半结构化文本                            | `Document`                                        | PlanningText, L3Report                 |

```
L0  SpatialFeature                  矢量基类: geometry + bsm + ysdm + _raw
 ├── L1  PointFeature / LineFeature / PolygonFeature
 └── L2  矢量语义子类

L0  RasterDataset                   栅格基类: path + crs + bounds + bands
 └── L1  栅格语义子类 (DEMInput / DOMInput / ...)

L0  TableDataset                    表格基类: rows + columns + schema      [v4.1 新增]
 └── L1  表格语义子类 (PopulationTable / ControlRuleTable / ...)

L0  Document                        文档基类: text + doc_type + source      [v4.1 新增]
 └── L1  文档语义子类 (PlanningText / L3Report)
```

**为什么四形态而非三形态**：旧版只有"矢量 + 栅格 + 文档"，把人口结构、产业经济、管制规则表等结构化非空间表格塞进"文档"当文本处理，丢失列结构。而规划成果"一图一表一规则"的"表"与"规则"恰恰是表格。`TableDataset` 让汇交成果的表格产出有类型化落点。

**为什么分形态而非扁平**：

1. **类型层面设防**：L1 中间层在 field 上加 validator，形态不匹配在构造时 fail-fast（旧版 `geometry_type` 只是运行时 property，传错不报错）。
2. **支撑 Data 层按形态分桶**：智能推断管道第一步按形态分流，再桶内语义匹配。无 L1 抽象，分桶无类型可挂。
3. **解决"双倍地块"**：`VillageBundle` 现状/规划地块分字段存放，不混装。
4. **栅格/表格一等公民**：DEM/DOM/坡度、人口/管制规则表等有独立类型层级与数据视图字段，不再当附属。

---

## 二、类型层级

### 2.1 矢量分支

#### L0 `SpatialFeature`

```python
@dataclass
class SpatialFeature:
    geometry: Dict[str, Any]          # GeoJSON geometry (必选)
    bsm: str = ""                     # 标识码
    ysdm: str = ""                    # 要素代码 (10位)
    layer_type: str = ""              # [v4.1] 所属图层 (嵌入图层身份, 不靠外部 registry 反查)
    _raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def geometry_type(self) -> str:
        return self.geometry.get("type", "Unknown")
```

> **v4.1 变更**：`SpatialFeature` 加 `layer_type` 字段，把图层身份嵌入要素本身（对标 pynspd 的 `layer_meta` 嵌入），确保要素不脱离图层归属。

#### L1 几何中间抽象

```python
@dataclass
class PointFeature(SpatialFeature):
    """点要素: geometry ∈ {Point, MultiPoint}."""

@dataclass
class LineFeature(SpatialFeature):
    """线要素: geometry ∈ {LineString, MultiLineString}."""

@dataclass
class PolygonFeature(SpatialFeature):
    """面要素: geometry ∈ {Polygon, MultiPolygon}."""
```

每个中间基类在 `geometry` 上加 `field_validator`，构造时校验 `geometry["type"]`，不匹配抛 `ValueError`。

#### L2 矢量语义子类（按 Group A–E + 阶段抽象 + 实体/表达分离）

```
SpatialFeature
├── PointFeature
│   ├── BaseFacility                       [v4.2] 设施基类 (空间实体)
│   │   ├── CurrentFacility                现状设施 (基础设施+公共服务设施)
│   │   └── PlannedFacility                规划设施 (从旧 PlannedAnnotation 拆出)
│   ├── GeologicalHazardPoint, ElevationPoint
│   └── HistoricalProtectionPoint
├── LineFeature
│   ├── BaseRoad                           [v4.2] 道路基类 (空间实体)
│   │   ├── CurrentRoad                    现状道路
│   │   └── PlannedRoad                    规划道路
│   ├── AdminBoundaryLine, ContourLine
│   └── WaterLine
├── PolygonFeature
│   ├── BaseLandUseParcel                  地块基类 (现状/规划共同)
│   │   ├── CurrentLandUseParcel
│   │   └── PlannedLandUseParcel
│   ├── BaseControlZone                    [v4.2] 管控区基类 (共同管控语义: protection_level/control_measure/引用条款)
│   │   ├── ThreeZoneItem                  三区 (生态/农业/建设空间, 引用层) [v4.2 新增, 纠正"KG独有"误标]
│   │   ├── ControlLine -> FarmlandProtection/EcologicalRedline/CultivatedLandTarget/
│   │   │                UrbanDevBoundary/VillageDevBoundary/HazardControlLine/FloodControlLine  (三线+其他控制线)
│   │   ├── ConstructionCtrlZone, ConditionalConstructionZone
│   │   └── LandUseZone
│   ├── AdminArea (+admin_level/parent_code)  [v4.2] 5级行政区划
│   ├── PlanningScope                      规划村范围 (范围定义, 非管控)
│   ├── WaterArea, CurrentBuilding, HistoricalProtectionArea
│   └── [v4.2] SoilType, SoilErosion, Watershed, NatureReserve, HydrogeologyZone  (Group F 自然资源)
└── AnnotationFeature                      [v4.2] 表达要素基类 (非空间实体)
    ├── CurrentAnnotation                  现状注记 (村名等文字标注, 不入 KG, 不参与空间分析)
    └── PlannedAnnotation                  规划注记 (文字标注)
```

> **v4.2 三项修正**：
>
> 1. **阶段抽象系统化**：现状/规划两态的要素都有 Base 基类（`BaseLandUseParcel`/`BaseRoad`/`BaseFacility`/`BaseAnnotation`），共享字段上提。非两态类型（AdminArea/ControlLine）不强制 Base。
> 2. **注记/设施分离**：设施是空间实体（有功能/服务半径/规模），注记是表达要素（文字标注）。旧版 `CurrentFacility.from_annotation_feature` 把设施从注记派生、且规划设施点混在 `PlannedAnnotation` 里--v4.2 拆出 `PlannedFacility`，设施统一为空间要素，注记降为表达层（`AnnotationFeature`，不入 KG，不参与空间分析）。`AnnotationFeature` 可继承 `PointFeature` 复用几何用于渲染，但 `geometry_kind="annotation"` 区分。
> 3. **规范覆盖补全**：补 Group F 自然资源 5 类型（SoilType/SoilErosion/Watershed/NatureReserve/HydrogeologyZone）+ AdminArea 扩展字段（admin_level/parent_code），对齐 `01_DATA_ACQUISITION_PLAN.md` §4。栅格类 PopulationGrid/GDPGrid 见 raster_types.py。
> 4. **三区三线管控抽象** [v4.2]：纠正 `01_DATA_ACQUISITION_PLAN` 把 ThreeZone/ThreeLine 标为"KG独有"的误导--三区三线是矢量图层（面，引用层，中央审批成果）。新增 `BaseControlZone` 管控区基类，统一三区+三线+管制区+用途分区的共同管控语义（protection_level/control_measure/引用条款）；新增 `ThreeZoneItem`（三区：生态/农业/建设空间）；三线由现有 `FarmlandProtection`/`EcologicalRedline`/`UrbanDevBoundary`（ControlLine 子类）体现。`ControlRule` 仍是表格（`ControlRuleTable`），非 spatial。
> 5. **v4.3 待补类型** [v4.3]（基于 21 文档审计，见 `docs/gis/diagnostics/SCHEMA_COVERAGE_AUDIT_2026-07-25.md`）：设施 8 子类型（`WaterSupply`/`Drainage`/`Waste`/`Sanitary`/`Fire`/`EvacuationShelter`/`Energy`/`Lighting` Facility，继承 `BaseFacility`）、防灾（`SeismicFortificationCategory` 枚举/`SecondaryHazardSource`/`FloodSafetyFacility`）、自然环境（`ClimateRaster`/`EngineeringGeologyZone`）、权属（`LandRightConfirmation`）、表格（`PlotControlTable`）。字段扩展（QMDLTB 10 字段/ControlRuleTable 二元组/PlannedRoad 红线宽度等）与编码修正（sddlbm->GB/T21010, dlbm->tugui）见 `OPTIMIZATION_TASKS` S11。

### 2.2 栅格分支

```python
@dataclass
class RasterDataset:
    """栅格数据集基类."""
    path: str
    crs: str = "EPSG:4326"
    bounds: Optional[BBox] = None
    width: int = 0
    height: int = 0
    transform: Optional[Any] = None
    band_count: int = 1
    dtype: str = "Float32"
    layer_type: str = ""               # [v4.1] 所属图层
    _meta: Dict[str, Any] = field(default_factory=dict, repr=False)
```

```
RasterDataset
├── DEMInput              数字高程模型 (单波段 Float32, 值域 ~0-9000m)
├── DOMInput              数字正射影像 (3波段 Byte RGB)
├── SlopeRaster           坡度 (单波段 Float32, 0-90°)
├── AspectRaster          坡向 (单波段 Float32, 0-360°)
├── SuitabilityRaster     适宜性评价结果 (单波段 Int16 分类)
└── (TerrainAnalysisResult 独立类型, DEM 衍生聚合, 非单栅格)
```

### 2.3 表格分支 [v4.1 新增]

```python
@dataclass
class TableDataset:
    """表格数据集基类 -- 非空间结构化行列数据.

    覆盖规划输入侧调查表与输出侧汇交表 (一图一表一规则的'表'与'规则').
    共享字段:
      - rows: List[Dict[str, Any]]  行数据 (每行一个 dict)
      - columns: List[ColumnSpec]   列定义 (name + dtype + 语义)
      - table_type: str             表格类型标识
      - layer_type: str             所属图层 (表格也是一种 layer)
      - _meta: Dict[str, Any]       原始元数据
    """
    rows: List[Dict[str, Any]]
    columns: List["ColumnSpec"]
    table_type: str = ""
    layer_type: str = ""
    _meta: Dict[str, Any] = field(default_factory=dict, repr=False)
```

表格子类分**输入型**（现状调查）与**输出型**（汇交成果）：

| 类型                         | 角色 | 示例字段                    | 汇交归属              |
| ---------------------------- | ---- | --------------------------- | --------------------- |
| `PopulationTable`          | 输入 | 年龄结构/户数/劳动力/迁出率 | -                     |
| `IndustryTable`            | 输入 | 产业类型/产值/就业/用地需求 | -                     |
| `FacilityInventory`        | 输入 | 设施名/类型/规模/服务人口   | -                     |
| `ConstructionProjectTable` | 输出 | 项目名/位置/规模/投资/时序  | 一表 (近期建设项目表) |
| `ControlRuleTable`         | 输出 | 分区/管制要求/引用条款      | 一规则 (管制规则)     |
| `PlanningIndicatorTable`   | 输出 | 指标名/现状值/目标值/属性   | 附表1 (规划指标表)    |
| `LandUseStructureTable`    | 输出 | 地类/现状面积/规划面积/增减 | 附表 (用地结构表)     |

### 2.4 文档分支 [v4.1 新增]

```python
@dataclass
class Document:
    """半结构化文本文档基类."""
    text: str
    doc_type: str = ""
    source: str = ""
    _meta: Dict[str, Any] = field(default_factory=dict, repr=False)
```

```
Document
├── PlanningText          规划说明文本 (markdown)
└── L3Report              L3 维度报告 (JSON, 含结构化摘要 + 原文)
```

---

## 三、数据视图：ProjectDataView -> VillageBundle 两层 [v4.1 重构]

旧版 `GISDataBundle` 隐含"一村一包"假设（`village_name` 写死、boundary 是单村边界），无法表达多自然村、跨村对比、跨村图层、共享栅格。v4.1 上移为项目/会话级数据视图，村庄下沉为子视图。

### 3.1 VillageBundle（村庄级，形态优先统一容器）[v4.3]

废弃旧的 `GISDataBundle`（按文件来源分桶的扁平 Pydantic 模型），统一为形态优先的 `VillageBundle`：

```python
@dataclass
class VillageBundle:
    """单个村庄的空间数据束 — 形态优先组织.

    [v4.3] 取代 GISDataBundle + 旧 VillageBundle.
    下游通过 morphology groups 访问数据，不依赖文件来源.
    """
    village_name: str

    # 四形态视图（一等公民）
    points: PointLayerGroup       # 设施/建筑/注记/高程点/灾害点/推断点
    lines: LineLayerGroup         # 道路/等高线/行政界线/推断线
    polygons: PolygonLayerGroup   # 地块/保护/管控/水系/自然资源/推断面
    rasters: RasterLayerGroup     # DEM/DOM/坡度/坡向/适宜性

    # 表格与文档
    tables: TableLayerGroup       # 人口/产业/管制规则/规划指标
    documents: DocumentGroup      # 规划文本/L3 报告

    metadata: VillageMetadata
    standard_version: str = "4.3"

    # 便捷属性（从形态 Group 推导）
    boundary: PolygonFeature      # 从 admin_areas 或 planning_scope 推导
    all_features: List[SpatialFeature]  # 跨形态聚合（不含注记）
    parcel_count: int
    total_area_ha: float

    def to_geojson_dict() -> dict  # 过渡期兼容 spatial_ops
```

**形态 Group 类结构**（以 PolygonLayerGroup 为例）：

```python
@dataclass
class PolygonLayerGroup:
    # 地类图斑
    landuse_current: List[CurrentLandUseParcel]
    landuse_planned: List[PlannedLandUseParcel]

    # 保护与控制（9 种约束面）
    farmland_protection / ecological_redline / historical_protection /
    cultivated_land_target / urban_dev_boundary / village_dev_boundary /
    hazard_control_lines / flood_control_lines / construction_zone

    # 区划与管控（5 种）
    admin_areas / planning_scope / land_use_zones /
    construction_ctrl_zones / three_zones

    # 自然要素（6 种）
    water_bodies / soil_types / soil_erosions /
    watersheds / nature_reserves / hydrogeology_zones

    # 推断图层（动态模型，PolygonFeature 子类但语义未知）
    inferred: List[PolygonFeature]

    # 聚合视图
    constraint_polygons  # 所有不可占用的约束面
    all_features          # 所有面要素
    parcels               # 所有地类图斑
```

**关键变更**：

- **废弃 `GISDataBundle`/`GeoFeature`/`ProviderLandParcel`/`GISMetadata`**。旧代码全部迁移到形态视图。
- **推断图层自动归入形态 Group**：`points.inferred` / `lines.inferred` / `polygons.inferred`。即使语义未知，下游仍可通过 `isinstance` 获得基础几何能力。
- **`boundary` 从 polygons 推导**（`admin_areas[0]` 或 `planning_scope[0]`），不再独立存储。
- **注记放在 `points.annotations_*`**（形态上属于点），但 `points.all_features` 排除注记（语义上非空间实体）。

### 3.2 ProjectDataView（项目级数据视图）

```python
class ProjectDataView:
    """项目/会话级数据视图 -- 一个规划项目的全部数据.

    取代旧 GISDataBundle 的'一村一包'定位. 持有多村、跨村图层、
    共享栅格、表格、文档, 与规划师'打开一个项目'的工作流对齐.
    """
    project_id: str
    villages: Dict[str, VillageBundle] = {}               # 按村庄名索引
    cross_village_layers: Dict[str, List[SpatialFeature]] = {}  # 跨村图层 (县域道路/水系)
    rasters: Dict[str, RasterDataset] = {}                # 共享栅格 (DEM/DOM/坡度)
    extra_rasters: Dict[str, RasterDataset] = {}          # 推断的动态栅格
    tables: Dict[str, TableDataset] = {}                  # 非空间表格 (人口/产业/管制规则)
    documents: Dict[str, Document] = {}                   # 规划文本/L3报告
    project_metadata: ProjectMetadata = ProjectMetadata()

    def get_village(self, village_name: str) -> VillageBundle:
        """便利方法: 从项目视图取单村 VillageBundle (非兼容 shim, 是正经查询 API)."""

    @property
    def layer_tree(self) -> List["LayerNode"]:
        """图层树: 列出所有图层 (核心+extra, 矢量+栅格+表格) 的 name/source/geometry_kind/feature_count.
        让分析工具'发现'图层而非硬编码 (对标 QGIS QgsLayerTree / GeoServer Catalog)."""
```

`ProjectMetadata`：项目范围 bbox、统一 CRS、参与村庄清单、数据源覆盖映射、推断警告汇总。

### 3.3 与 KG 的连锁

数据视图上移项目级后，KG 同步上移为 `ProjectKG`（多村实体 + 跨村关系：村间邻接、共享水系、道路连通）。否则数据是项目级、KG 是村庄级，再造断层。见 `OPTIMIZATION_TASKS.md` K2。

---

## 四、子包结构

```
schema/
├── types/
│   ├── base.py              # ✅ SpatialFeature + PointFeature/LineFeature/PolygonFeature + RasterDataset
│   ├── spatial_types.py     # ✅ Group A~F 矢量语义子类 (含阶段抽象 Base* + 实体/表达分离)
│   ├── raster_types.py      # ✅ DEMInput, DOMInput, SlopeRaster, AspectRaster, SuitabilityRaster, TerrainAnalysisResult
│   ├── table_types.py       # ✅ [v4.1] TableDataset + 7 子类 (输入型+输出型)
│   ├── document_types.py    # ✅ [v4.1] Document + PlanningText + L3Report
│   ├── canonical.py         # ✅ BBox, CRS, VillageBundle (v4.3 形态优先), PointLayerGroup, LineLayerGroup, PolygonLayerGroup, RasterLayerGroup, TableLayerGroup, DocumentGroup, VillageMetadata, ProjectDataView
│   ├── layer_registry.py    # ✅ LAYER_TYPE_REGISTRY (42 条目, geometry_kind 覆盖四形态)
│   └── __init__.py
├── encodings/               # ✅ 编码体系 (6套 YAML + DictionaryCenter)
├── contracts/               # ✅ 跨层契约 (parse/execution/validation/layout/context)
├── output/
│   ├── gdb.py               # ✅ 矢量汇交 (GDB 12层)
│   ├── tables.py            # ✅ [v4.1] 表格汇交导出 (4 函数)
│   └── colors.py            # ✅ 8 套调色板
└── utils/
    └── metrics.py           # ✅ 用地指标计算
```

---

## 五、`layer_registry`：YAML 单一真相源 [v4.4 重构]

### 5.1 设计理念

图层注册表采用 **YAML-only** 架构（v4.4 移除了 Python 侧的 `_TYPE_BINDINGS` 字典）：

| 维度     | YAML (`gis_layer_registry.yaml`)                                             | Python (`ingest.py::_infer_model_class()`)                |
| -------- | ----------------------------------------------------------------------------- | ----------------------------------------------------------- |
| 管什么   | **全部声明性元数据**：geometry_kind, group, ingest.adapter, bundle_target, kg.entity_type, validation | **模型类名推断**：layer_type -> Schema 类名（仅当需要 Python 模型时） |
| 谁维护   | 运营/配置人员可编辑，不懂 Python 也可以                                       | 开发者维护，仅在新增带 Python 类型的图层时修改               |
| 变更频率 | 中（新增图层类型、调整描述）                                                  | 低（仅新增需要 Schema 类的图层时）                            |
| 运行时   | 应用启动时由 `build_registry_from_yaml()` 加载，import 时自动执行            | ingest 时按需查询                                            |

```yaml
# gis_layer_registry.yaml - 单一真相源（完整元数据示例）
layer_types:
  farmland_protection:
    geometry_kind: polygon
    group: protection
    is_reference_layer: true
    description: "Farmland protection zone (永久基本农田保护红线)"
    ingest:
      adapter: features            # 对应 adapters/__init__.py 注册名
      feature_type: farmland_protection
    bundle_target:
      group: polygons
      key: farmland_protection
    kg:
      entity_type: FarmlandProtection
      uri_policy: "L1:farmland_protection_{bsm}"
    validation:
      required_fields: [bsm]
      geometry: { must_be_valid: true, dlq_on_error: true }
```

`layer_registry.py` 在 import 时执行 `build_registry_from_yaml()`，把每条 YAML 条目实例化为 `GisLayerTypeEntry` 并注册到 `GIS_LAYER_REGISTRY`。YAML 中所有 layer_type 都会注册（即使没有 Python 类绑定），保证 `DataCatalog` 能发现所有已知图层。无 Python 类绑定的图层走推断管道（`ingest.py::_infer_model_class()` 返回空字符串）。

### 5.2 添加新图层类型

> **权威指南**：详见 [`docs/gis/HOW_TO_ADD_LAYER.md`](../../../../docs/gis/HOW_TO_ADD_LAYER.md)

**标准图层（90% 场景，YAML 条目即可）**：

1. 在 `gis_layer_registry.yaml` 加条目（含 `geometry_kind` / `group` / `ingest.adapter` / `bundle_target` / `kg.entity_type`）
2. 重启 -- 注册表在 import 时从 YAML 自动重建

**需要 Python 模型类的图层（少数场景）**：

1. `gis_layer_registry.yaml` 加条目
2. 在 `backend/app/modules/data/ingest.py::_infer_model_class()` 的 `_CLASS_MAP` 中加一行 `layer_type -> ClassName`
3. 重启 -- 注册表自动构建，ingest 按 `_infer_model_class()` 解析类型

**临时/推断图层（无专用 Schema 类）**：

1. `gis_layer_registry.yaml` 加条目即可
2. 系统自动识别为推断图层，`_infer_model_class()` 返回空字符串，要素以基类（如 `PolygonFeature`）兜底进入 `bundle.*.inferred`

### 5.3 当前注册表统计

- **40+ 个 layer_type** 已注册（含矢量/栅格/表格/文档/注记）
- **5 个引用层**（三区三线，`is_reference_layer=true`）
- **5 个 Group F 自然资源**（无 ingest 端口，无数据源配置）

> **引用层标注**：三区三线（永久基本农田/生态红线/城镇边界）是中央审批成果的引用层，村庄规划不重新创建。`is_reference_layer: true` 让下游知道这些图层是只读引用。

---

## 六、契约文件职责

| 文件                        | 角色                | 生产者             | 消费者                |
| --------------------------- | ------------------- | ------------------ | --------------------- |
| `parse_contracts.py`      | PARSE 输出契约      | PARSE Agent        | KG, EXECUTE           |
| `execution_contracts.py`  | EXECUTE 输入契约    | ConstraintCompiler | MIP solver, EXECUTE   |
| `validation_contracts.py` | 验证闭环契约        | Evaluator          | Worker-Evaluator loop |
| `layout_contracts.py`     | LAYOUT 工具契约     | LAYOUT tools       | ZoneGenerator, etc.   |
| `context_contracts.py`    | [v4.3] 空间认知契约 | spatial_ops        | PARSE, LAYOUT, KG     |

[v4.3] `context_contracts.py` 定义 `ContextBlockType` / `ContextBlock` + 7 种子类型（`LanduseEntry`/`NaturalVillageAnchor`/`SpatialRelation`/`ConstraintSummary`/`FacilityAnchor`/`TerrainProfile`），从 `layout_contracts.py` 迁出以反映空间认知契约的多消费者性质。`SpatialContext` Pydantic 单体模型已永久删除，由 `List[ContextBlock]` 模块化 dataclass 架构替代。

关键契约类型不变（`SpatialPlanningIntent`/`ZoneTarget`/`SpatialOperation`/`SpatialConstraint`/`MIPModel`/`ExecutionPlan`/`ValidationCheckItem` 等）。

---

## 七、依赖规则

| ✅ 允许                                      | ❌ 禁止                    |
| -------------------------------------------- | -------------------------- |
| 标准库 (typing, dataclasses, functools, ...) | `app.tools`              |
| `pydantic`                                 | `app.agent`              |
| `yaml`                                     | `app.modules.kg`         |
| 内部跨子包引用 (utils->encodings)            | `app.modules.data`       |
|                                              | `geopandas`, `shapely` |

> **`gis/` 目录已整体删除**。所有引用统一走 `app.modules.schema`，无 shim，无兼容层。

---

## 八、设计原则

1. **四形态结构优先**：矢量(Point/Line/Polygon) + 栅格(RasterDataset) + 表格(TableDataset) + 文档(Document) 四形态先于语义子类，类型层面约束形态，支撑 Data 层按形态分桶。
2. **形态优先容器** [v4.3]：`VillageBundle` 按形态 Group 组织（points/lines/polygons/rasters），废弃按文件来源分桶的扁平 `GISDataBundle`。`_assign_to_bundle` 基于 `isinstance` 类型分发，33 个具体子类各有归宿，推断图层通过基类兜底自动归入正确形态 Group。
3. **阶段抽象 + 实体/表达分离** [v4.2]：现状/规划两态的要素都有 Base 基类（BaseLandUseParcel/BaseRoad/BaseFacility/BaseAnnotation）共享字段；设施是空间实体（入 KG、参与分析），注记是表达要素（AnnotationFeature，不入 KG、不参与空间分析，仅渲染），二者不再平级。
4. **项目级数据视图**：`ProjectDataView -> VillageBundle` 两层，取代"一村一包"，对齐"打开一个项目"的规划工作流；跨村图层、共享栅格、表格、文档在项目级聚合。
5. **现状/规划彻底分离**：`VillageBundle` 不混装现状与规划地块，不保留聚合兼容视图，对标国标 209001/209002 划分。
6. **图层身份嵌入要素**：`SpatialFeature.layer_type` 把图层归属嵌入要素本身，不靠外部 registry 反查（对标 pynspd layer_meta）。
7. **图层树可发现**：`ProjectDataView.layer_tree` 列出所有图层元数据，让分析工具发现图层而非硬编码（对标 QGIS/GeoServer）。
8. **栅格/表格一等公民**：DEM/DOM/坡度、人口/管制规则表等有独立类型层级与数据视图字段。
9. **Schema-First + 零依赖 + 契约分离**：先定义类型再编码，下游只消费类型化模型；Schema 不依赖任何其他层；PARSE/EXECUTE/Validation 契约分文件。
10. **破坏性变更不兼容**：类型层级重排、bundle 上移、四形态扩展都是破坏性的，旧下游必须同步改造，不设过渡期。
