# Data Module - 统一数据获取与管理层

> **Status: [PRODUCTION]** | **Type: Architecture** | **Updated: 2026-07-29 (v4.9)**
> **Scope**: 所有空间数据（矢量/栅格/瓦片）和文档（规划文本/L3报告）进入系统的唯一边界
>
> **当前边界**: `adapters/` 策略模式正式化 — 内置适配器接管 ingest，`DataCatalog.load_village_bundle()` 通过 `ADAPTERS` 注册表分发；数据层不提供 DLBM→GHYTBM 推导。
> **v4.8.1 变更**: DEM 栅格图层完整接入（clip 脚本 + sources.yaml + 适配器）
> **v4.6 变更**: ControlRule/PlanningIndicator 移入 bundle.tables（类型已定义，ingest 未实现）；KG 不再存储非空间要素；bundle 形态分组直连 KG builder

---

## 一、为什么需要这个模块

### 1.1 已解决的旧病灶

**病灶一：三套并行抽象** — 旧版 `providers/` + `drivers/` + `fetcher` 三套重叠的数据获取路径。

- ✅ 已统一为 `Catalog + Source + Connection` 三层抽象
- ✅ `fetcher.py` 已删除，`providers/orchestrator/base/base_types` 已删除
- ✅ 所有数据走单一入口 `DataCatalog`

**病灶二：僵化纯语义注册表** — 28 个 layer_type 硬编码在 Python 中。

- ✅ 已由 `GIS_LAYER_REGISTRY` + `DriverRegistry` 双注册解决
- ✅ YAML 混合模式已实现 — 见 `schema/README.md` §五

### 1.2 设计理念：双轨接入 + 四形态 + 项目级视图

**四形态结构优先**：数据进入系统时按形态分桶，而非直接猜语义：

```
第一性: 数据形态
  ├── 矢量 -> 几何结构 (Point/Line/Polygon)   -> schema L1 几何基类
  ├── 栅格 -> 波段与值域 (单波段/多波段)        -> schema RasterDataset
  ├── 表格 -> 列结构 (非空间结构化行列)          -> schema TableDataset ⏳
  └── 文档 -> 半结构化文本                       -> schema Document ⏳

第二性: 语义角色
  └── 形态桶内按 field name/编码/元数据匹配具体 schema 子类
```

**双轨接入**：

| 轨道                 | 适用             | 状态                                      |
| -------------------- | ---------------- | ----------------------------------------- |
| **显式注册轨** | 已知关键图层     | ✅`ingest.py` + `GIS_LAYER_REGISTRY` |
| **智能推断轨** | 临时上传、新来源 | ⏳`ingest_inference.py` 未编码          |

**项目级视图**：

- ✅ `VillageBundle` (v4.3 形态优先) — 单村 typed 数据束（已实现, 四形态 Group）
- ⏳ `ProjectDataView -> VillageBundle` 两层 — 多村/跨村支持（类型已定义，加载未实现）

---

## 二、架构总览

### 2.1 分层

```
┌─────────────────────────────────────────────────────────┐
│  Layer 3: Catalog (声明式编排)                           │
│  sources.yaml -> DataCatalog.load_village_bundle()       │
├─────────────────────────────────────────────────────────┤
│  Layer 2: Source / Driver (形态驱动读取)                  │
│  file_vector | api_vector | wmts_tile | local_raster    │
│  | remote_raster | document                              │
├─────────────────────────────────────────────────────────┤
│  Layer 1: Connection (连接管理)                          │
│  tianditu | amap | osm | gd_tianditu                     │
└─────────────────────────────────────────────────────────┘
         │
         ▼  (DataResult -> ingest -> typed models)
         ▼  (bundle.add() -> _bundle_key_for() -> _layers[key])
┌─────────────────────────────────────────────────────────┐
│  VillageBundle (v4.4 Pydantic v2 BaseModel, 形态优先)    │
│  ├── points:   PointLayerGroup (设施/建筑/注记/高程/灾害)│
│  ├── lines:    LineLayerGroup (道路/等高线/行政界线)     │
│  ├── polygons: PolygonLayerGroup (地块/保护/管控/水系)   │
│  ├── rasters:  RasterLayerGroup (DEM/DOM/坡度/坡向)     │
│  ├── tables:   TableLayerGroup (人口/管制规则/指标)      │
│  ├── documents: DocumentGroup (规划文本/L3 报告)          │
│  └── compute_context_blocks(bundle) -> List[ContextBlock] │
└─────────────────────────────────────────────────────────┘
```

### 2.2 依赖方向

```
app.modules.data  ──►  app.modules.schema
app.modules.spatial_ops  ──►  app.modules.schema (consumes VillageBundle)
app.modules.schema  ──✕──►  app.modules.data  (无反向依赖)
```

---

## 三、目录结构

```
backend/app/modules/data/
├── README.md
├── __init__.py
├── contracts.py           # DataResult, DataSourceMetadata
├── ingest.py              # raw GeoJSON -> typed schema models
├── catalog/
│   ├── catalog.py         # DataCatalog
│   ├── config.py          # Pydantic 配置模型
│   └── sources.yaml       # 数据源物理配置（单一真相源）
├── adapters/              # [v4.9] IngestAdapter 策略模式
│   ├── __init__.py        # IngestAdapter Protocol + ADAPTERS 注册表
│   ├── parcels.py         # ParcelsAdapter — 用地 parcels 编码校验
│   ├── features.py        # FeaturesAdapter — 通用矢量要素
│   ├── raster.py          # RasterAdapter — GeoTIFF -> RasterDataset
│   ├── table.py           # TableAdapter — CSV/Excel -> TableDataset
│   ├── document.py        # DocumentAdapter — Markdown -> Document
│   └── README.md          # 适配器使用指南
├── sources/
│   ├── base.py            # DataSourceDriver ABC
│   ├── registry.py        # DriverRegistry (装饰器自动发现)
│   ├── file_vector.py     # 本地 GeoJSON/Shapefile
│   ├── api_vector.py      # WFS/MapServer REST
│   ├── wmts_tile.py       # WMTS 瓦片下载+缓存
│   ├── local_raster.py    # 本地 GeoTIFF
│   ├── remote_raster.py   # 远程栅格下载指引
│   └── document.py        # Markdown/JSON/TXT
├── connections/
│   ├── base.py            # Connection ABC + ConnectionRegistry
│   ├── rate_limiter.py    # 线程安全全局速率限制器
│   ├── tianditu.py        # 天地图 API
│   ├── amap.py            # 高德地图 API
│   ├── gd_tianditu.py     # 广东省天地图专题服务
│   └── osm.py             # OpenStreetMap (osmnx)
├── documents/
│   └── loader.py          # 规划文本/L3 报告加载
└── providers/             # 外部事实提供器，仅由 data/KG 按显式 capability 使用
    ├── tianditu/          # 天地图 API 封装
    ├── amap/              # 高德地图 API 封装
    └── poi.py             # POI 统一搜索接口
```

---

## 四、核心接口

### 4.1 DataCatalog — 唯一数据入口

```python
from app.modules.data import DataCatalog

catalog = DataCatalog()

# 按名称取数据源
source = catalog.get_source("jintian_current_landuse")
result = source.fetch()  # -> DataResult

# 加载村庄完整 typed 数据束 (v4.4 形态优先)
bundle = catalog.load_village_bundle("金田村委会")

# 通过形态 Group 访问数据（PolygonLayerGroup/LineLayerGroup 均使用 .get() 而非属性）
print(bundle.polygons.get("landuse_current")[0].dlbm)      # CurrentLandUseParcel
print(bundle.polygons.get("landuse_planned")[0].ghytbm)    # PlannedLandUseParcel
print(bundle.polygons.constraint_polygons)                   # 所有约束面
print(bundle.lines.roads)                                    # 所有道路 (现状+规划)  ← .roads 为 property 快捷
print(bundle.boundary)                                       # AdminArea (从 admin_areas 推导)  ← .boundary 为 property

# 空间认知卡片生成 (v4.3 ContextBlock)
from app.modules.spatial_ops import compute_context_blocks
context_blocks = compute_context_blocks(bundle)
# 下游按 block_type 筛选、按 priority 排序、按 token 预算截断
```

**Bundle 分发逻辑** [v4.4]：基于 YAML registry 而非 `isinstance` 链：

```python
# canonical.py::_bundle_key_for(feature) 查 GIS_LAYER_REGISTRY 获取 bundle_target.key
# VillageBundle.add(feature) -> LayerGroup.add(feature) -> _layers[key].append(feature)
# 42 个 bundle_target 全覆盖, 推断类型通过 "inferred" 兜底
for feat in features:
    bundle.add(feat)  # 自动路由到正确的 morphology group + _layers key
```

### 4.2 Ingest (raw -> typed)

**适配器策略（主推）** — 通过 `ADAPTERS` 注册表按 `gis_layer_registry.yaml` 中的 `ingest.adapter` 分发：

```python
from app.modules.data.adapters import ADAPTERS

adapter = ADAPTERS["parcels"]                       # 查注册表
result = adapter.load(data, entry)                  # -> AdapterResult(features, warnings, dlq)
for feat in result.features:
    bundle.add(feat)                                 # 自动路由到 morphology group
```

**直接 ingest 函数（兼容）** — 旧接口，仍可用：

```python
from app.modules.data import result_to_parcels, result_to_features, result_to_raster

# DataResult -> typed parcels (编码校验前置)
parcels, warnings = result_to_parcels(result, layer_type="current_landuse")

# DataResult -> typed spatial features
features, warnings = result_to_features(result, feature_type="current_road")
```

### 4.3 DataResult — 统一结果封装

```python
@dataclass
class DataResult:
    success: bool
    data: Any = None
    data_type: str = ""       # "geojson"|"tiles"|"mosaic"|"raster"|"url"|"document"
    metadata: dict = {}
    error: Optional[str] = None
    cache_path: Optional[str] = None
```

---

## 五、配置规范

### `sources.yaml` — 数据源物理配置

```yaml
version: "2.0"
connections:
  tianditu: { type: tianditu, rate_limit: 5.0, timeout: 30 }

sources:
  jintian_current_landuse:
    driver: file_vector
    path: "data/gis/jintian/current/landuse.geojson"
    layer_type: landuse_current

  jintian_farmland_protection:
    driver: file_vector
    path: "data/gis/jintian/planned/farmland_protection.geojson"
    layer_type: farmland_protection
    crs: EPSG:4326
```

### 5.1 示例：添加 DEM 栅格图层

DEM（数字高程模型）是村庄规划地形分析的基础输入。完整接入流程见 [`docs/guides/how-to-add-layer.md`](../../../../docs/guides/how-to-add-layer.md) 工作示例，此处给出关键步骤。

**Step 1 - 裁剪省域 DEM 到村庄 AOI**

省域 DEM（如 NASA ASTGTM v3, 30m）体积过大，需先裁剪到村庄边界。使用 `backend/scripts/clip_dem_to_aoi.py`：

```bash
python backend/scripts/clip_dem_to_aoi.py \
    --input data/gis/广东DEM30M.zip \
    --aoi data/gis/jintian/current/boundary.geojson \
    --output data/gis/jintian/terrain/dem.tif
```

脚本读取 AOI bbox，选取覆盖该 bbox 的 ASTGTM 瓦片，用 `rasterio.mask` 裁剪（或单瓦片直接复制），输出 EPSG:4326 GeoTIFF。

**Step 2 - sources.yaml 数据源声明**

```yaml
sources:
  dem_local:
    driver: local_raster
    path: "data/gis/jintian/terrain/dem.tif"
    format: GeoTIFF
    crs: EPSG:4326
    layer_type: dem              # 对应 gis_layer_registry.yaml 中的 dem 条目
```

**Step 3 - 适配器分发（已内置）**

`gis_layer_registry.yaml` 中 `dem` 条目已配置 `ingest.adapter: raster` + `bundle_target: { group: rasters, key: dem }`。`adapters/raster.py::RasterAdapter.load()` 通过 `entry.ingest.feature_type` 映射 `"dem" -> DEMInput`。无需额外 Python 修改。

**结果**：`catalog.load_village_bundle()` 通过 `LocalRasterDriver` 加载 `dem.tif`，`ADAPTERS["raster"].load()` 构造 `DEMInput` 实例，`bundle.add()` 放入 `bundle.rasters._layers["dem"]`，`kg.build_from_bundle()` 调用 `@kg_builder("dem")` 生成 `RasterDataset` RDF 实体。

---

## 六、数据流（完整链路）

```
1. DataCatalog()
   ├── _init_sources()     -> 遍历 sources, DriverRegistry 实例化 Driver
   └── _init_connections() -> 实例化 Connection, 注册到 ConnectionRegistry

2. catalog.load_village_bundle("金田村委会")
   ├── _load_boundary()           -> FileVectorDriver.fetch() -> boundary.geojson
   ├── _derive_bbox_from_boundary -> BBox 从边界几何计算
   ├── query_by_bbox(bbox, layer_types) -> 加载所有图层
   └── 按 entry.ingest.adapter 分派 (ADAPTERS 注册表):
       ├── adapter.load(data, entry) -> AdapterResult(features, warnings, dlq)
       └── bundle.add(feature) -> _bundle_key_for() 查 registry 路由
           ├── layer_type="landuse_current" -> bundle.polygons._layers["landuse_current"]
           ├── layer_type="farmland_protection" -> bundle.polygons._layers["farmland_protection"]
           ├── layer_type="current_road" -> bundle.lines._layers["roads_current"]
           └── 未知 layer_type -> _layers["inferred"] (推断兜底)
   -> VillageBundle (v4.4 形态优先, YAML-driven routing, 42 个 bundle_target 全覆盖)

3. 下游消费
   直接访问形态视图: bundle.polygons.get("landuse_current") / bundle.lines.roads
   compute_context_blocks(bundle) -> List[ContextBlock] (v4.3 空间认知卡片)
                                  -> PARSE Agent (按需消费卡片)
                                  -> LAYOUT Pipeline (按 block_type 筛选)
                                  -> KG builder (typed features from morphology groups)
```

---

## 七、不做的事（范围边界）

- **不做渲染**: `tools/gis/_rendering/`
- **不做 LLM 调用**: `tools/gis/parse`
- **不做空间分析**: 空间分析统一由 `modules/spatial_ops/` 负责
- **不做栅格计算**: `agent/gis/analyze/`

---

## 八、已删除的遗留模块

| 模块                                         | 状态   | 替代方案                                     |
| -------------------------------------------- | ------ | -------------------------------------------- |
| `fetcher.py` (GISDataFetcher)              | 已删除 | `DataCatalog.load_village_bundle()`        |
| `providers/base.py` (GISProvider)          | 已删除 | `sources/base.py` DataSourceDriver         |
| `providers/orchestrator.py`                | 已删除 | DataCatalog                                  |
| `providers/osm/`                           | 已删除 | OSM 数据走 api_vector 驱动                   |
| `providers/rate_limiter.py`                | 已删除 | `connections/rate_limiter.py` (统一单例池) |
| `providers/base_types.py`                  | 已删除 | 内联到各 types 文件                          |
| `providers/dem_provider.py`                | 已删除 | `LocalRasterDriver` + `result_to_raster` |
| `providers/{amap,osm,tianditu}/adapter.py` | 已删除 | 死代码                                       |
| `documents/intent_cache.py`                | 已删除 | 直接调用`tools/gis/parse`                  |
| `_bundle_to_compat_dict()`                 | 已删除 | `bundle.to_geojson_dict()`                 |
| `GISDataBundle` (Pydantic)                 | 已删除 | `VillageBundle` (v4.4 Pydantic v2 BaseModel)  |
| `GeoFeature` / `ProviderLandParcel`      | 已删除 | 直接使用`SpatialFeature` 子类              |
| `GISMetadata` (旧 Pydantic)                | 已删除 | `VillageMetadata` (Pydantic v2 BaseModel)  |

---

## 九、当前实现状态

### 9.1 数据形态状态

| 形态 | 实现状态 | 说明 |
|------|---------|------|
| 矢量 (Point/Line/Polygon) | 完整实现 | 42 个 bundle_target 全覆盖, `bundle.add()` + `_bundle_key_for()` YAML registry 路由 |
| 栅格 (RasterDataset) | ✅ 完整实现 | DEM/DOM/Slope/Aspect/Suitability，类型定义+加载 |
| 表格 (TableDataset) | ⏳ 类型已定义，ingest 未实现 | 5 种表类型定义在 `table_types.py`，但 `bundle.tables` 所有字段为 None |
| 文档 (Document) | ✅ 基础实现 | 规划文本加载，L3 报告 |

### 9.2 TableDataset 状态（⏳ 待实现）

| 表类型 | 用途 | 状态 |
|--------|------|------|
| `PopulationTable` | 人口结构（输入） | 类型定义 ✅，ingest ❌ |
| `IndustryTable` | 产业经济（输入） | 类型定义 ✅，ingest ❌ |
| `FacilityInventory` | 设施清单（输入） | 类型定义 ✅，ingest ❌ |
| `ControlRuleTable` | 管制规则（输出，从 KG 移入） | 类型定义 ✅，ingest ❌ |
| `PlanningIndicatorTable` | 规划指标（输出，从 KG 移入） | 类型定义 ✅，ingest ❌ |
| `ConstructionProjectTable` | 建设项目表（输出） | 类型定义 ✅，ingest ❌ |
| `LandUseStructureTable` | 用地结构表（输出） | 类型定义 ✅，ingest ❌ |

**注意**：`ControlRule`、`PlanningIndicator` 和 `LandUseCategory`（VNE 编码体系）已从 KG 移出（v4.6）。
`ControlRule` 和 `PlanningIndicator` 通过 `bundle.tables` 承载（计划由 PARSE Agent 填充）。
`LandUseCategory`（VNE 分类树）通过 Schema 层 `encodings/dicts/` 按需查询，不作为 KG 实体或 bundle 表存储。
编码体系（DLBM、GHYTBM、TUGUI 等）统一由 Schema 层 `encodings/code_sets.py` 管理。

### 9.3 待实现

| 能力 | 状态 |
|------|------|
| 智能推断管道（`adapters/` 策略模式） | ✅ 已实现 — 5 个内置适配器, `ADAPTERS` 注册表分发（2026-07 v4.9） |
| 项目级加载 `load_project_data_view()` | ⏳ 待设计 |
| 表格驱动 `sources/table.py` | ⏳ 待实现 |
| 项目配置分离 `projects.yaml` | ⏳ 待实现 |
| bundle.tables 的 ingest 管道（TableAdapter 已注册，数据加载尚未打通） | ⏳ TableAdapter 已实现，`bundle.tables._layers` 通路待接续 |

## 相关文件

| 模块                     | 路径                                                                          |
| ------------------------ | ----------------------------------------------------------------------------- |
| 类型定义（矢量）         | `backend/app/modules/schema/types/spatial_types.py`                         |
| 类型定义（栅格）         | `backend/app/modules/schema/types/raster_types.py`                          |
| 数据视图 & LayerGroup    | `backend/app/modules/schema/types/canonical.py`                             |
| 图层注册表               | `backend/app/modules/schema/types/layer_registry.py`                        |
| 规划分类决定 | `backend/app/domain/program/classification.py`；只接受显式 `ClassificationDecision` |
| 适配器策略               | `backend/app/modules/data/adapters/`                                        |
| 摄入端口（旧）           | `backend/app/modules/data/ingest.py`                                        |
| 数据源配置               | `backend/app/modules/data/catalog/sources.yaml`                             |
| 位置解析                 | `backend/app/utils/location_parser.py`                                      |
| 空间上下文计算           | `backend/app/modules/spatial_ops/context.py` (compute_context_blocks, v4.3) |
| 输出 Bundle 缓存         | `output/bundle_cache/jintian_bundle.pkl`                                    |
