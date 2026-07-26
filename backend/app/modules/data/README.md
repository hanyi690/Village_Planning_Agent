# Data Module - 统一数据获取与管理层

> **Status: [PRODUCTION]** | **Type: Architecture** | **Updated: 2026-07-26 (v4.6)**
> **Scope**: 所有空间数据（矢量/栅格/瓦片）和文档（规划文本/L3报告）进入系统的唯一边界
>
> **v4.6 变更**: ControlRule/PlanningIndicator 移入 bundle.tables（类型已定义，ingest 管道未实现）；KG 不再存储非空间要素；bundle 形态分组直连 KG builder，不再通过 ContextBlock 中转

---

## 一、为什么需要这个模块

### 1.1 已解决的旧病灶

**病灶一：三套并行抽象** — 旧版 `providers/` + `drivers/` + `fetcher` 三套重叠的数据获取路径。

- ✅ 已统一为 `Catalog + Source + Connection` 三层抽象
- ✅ `fetcher.py` 已删除，`providers/orchestrator/base/base_types` 已删除
- ✅ 所有数据走单一入口 `DataCatalog`

**病灶二：僵化纯语义注册表** — 28 个 layer_type 硬编码在 Python 中。

- ✅ 已由 `LAYER_TYPE_REGISTRY` + `DriverRegistry` 双注册解决
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
| **显式注册轨** | 已知关键图层     | ✅`ingest.py` + `LAYER_TYPE_REGISTRY` |
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
         ▼  (_assign_to_bundle: isinstance dispatch -> morphology groups)
┌─────────────────────────────────────────────────────────┐
│  VillageBundle (v4.3 形态优先 dataclass)                 │
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
└── providers/             # LEGACY — 逐步淘汰，新代码走 Catalog
    ├── tianditu/          # 仍被 _analytics 工具使用
    ├── amap/              # 仍被 POIProvider 使用
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

# 加载村庄完整 typed 数据束 (v4.3 形态优先)
bundle = catalog.load_village_bundle("金田村委会")

# 通过形态 Group 访问数据
print(bundle.polygons.landuse_current[0].dlbm)      # CurrentLandUseParcel
print(bundle.polygons.landuse_planned[0].ghytbm)    # PlannedLandUseParcel
print(bundle.polygons.constraint_polygons)           # 所有约束面 (96 个)
print(bundle.lines.roads)                            # 所有道路 (现状+规划)
print(bundle.boundary)                               # AdminArea (从 admin_areas 推导)

# 空间认知卡片生成 (v4.3 ContextBlock)
from app.modules.spatial_ops import compute_context_blocks
context_blocks = compute_context_blocks(bundle)
# 下游按 block_type 筛选、按 priority 排序、按 token 预算截断
```

**`_assign_to_bundle` 分发逻辑** [v4.3]：基于 `isinstance` 而非 `layer_type` 字符串匹配：

```python
# 每个 SpatialFeature 子类通过 isinstance 链路由到正确的 Group 字段
# 33 个具体子类全覆盖, 推断类型通过基类兜底进入 inferred 列表
for feat in features:
    if isinstance(feat, CurrentLandUseParcel):
        bundle.polygons.landuse_current.append(feat)
    elif isinstance(feat, FarmlandProtection):
        bundle.polygons.farmland_protection.append(feat)
    # ... 31 more concrete subclasses ...
    elif isinstance(feat, PolygonFeature):
        bundle.polygons.inferred.append(feat)  # 推断图层兜底
```

### 4.2 Ingest (raw -> typed)

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
    data_type: str = ""       # "geojson"|"tiles"|"raster"|"document"
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

---

## 六、数据流（完整链路）

```
1. DataCatalog()
   ├── _load_config()      -> 读 sources.yaml, 校验 Pydantic config models
   ├── _init_connections() -> 实例化 Connection, 注册到 ConnectionRegistry
   └── _init_sources()     -> 遍历 sources, DriverRegistry 实例化 Driver

2. catalog.load_village_bundle("金田村委会")
   ├── _load_boundary()           -> FileVectorDriver.fetch() -> boundary.geojson
   ├── _derive_bbox_from_boundary -> BBox 从边界几何计算
   ├── query_by_bbox(bbox, layer_types) -> 加载所有图层
   └── 按 layer_type + ingest_port 分派:
       ├── result_to_parcels() / result_to_features() -> typed SpatialFeature[]
       └── _assign_to_bundle(bundle, features) -> isinstance 分发
           ├── CurrentLandUseParcel -> bundle.polygons.landuse_current
           ├── FarmlandProtection  -> bundle.polygons.farmland_protection
           ├── CurrentRoad         -> bundle.lines.roads_current
           ├── CurrentAnnotation   -> bundle.points.annotations_current
           └── PolygonFeature      -> bundle.polygons.inferred (推断兜底)
   -> VillageBundle (v4.3 形态优先, 33 子类全覆盖)

3. 下游消费
   直接访问形态视图: bundle.polygons.landuse_current / bundle.lines.roads
   compute_context_blocks(bundle) -> List[ContextBlock] (v4.3 空间认知卡片)
                                  -> PARSE Agent (按需消费卡片)
                                  -> LAYOUT Pipeline (按 block_type 筛选)
                                  -> KG builder (typed features from morphology groups)
```

---

## 七、不做的事（范围边界）

- **不做渲染**: `tools/gis/_rendering/`
- **不做 LLM 调用**: `tools/gis/parse`
- **不做空间分析**: `tools/gis/_analytics/`
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
| `GISDataBundle` (Pydantic)                 | 已删除 | `VillageBundle` (v4.3 形态优先)            |
| `GeoFeature` / `ProviderLandParcel`      | 已删除 | 直接使用`SpatialFeature` 子类              |
| `GISMetadata` (旧 Pydantic)                | 已删除 | `VillageMetadata` (精简 dataclass)         |

---

## 九、当前实现状态

### 9.1 数据形态状态

| 形态 | 实现状态 | 说明 |
|------|---------|------|
| 矢量 (Point/Line/Polygon) | ✅ 完整实现 | 33 个子类全覆盖，`_assign_to_bundle` isinstance 分发 |
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
| 智能推断管道 `ingest_inference.py` | ⏳ 设计中 |
| 项目级加载 `load_project_data_view()` | ⏳ 设计中 |
| 表格驱动 `sources/table.py` | ⏳ 待实现 |
| 项目配置分离 `projects.yaml` | ⏳ 待实现 |
| bundle.tables 的 ingest 管道 | ⏳ 待实现（ControlRule, PlanningIndicator 等） |

## 相关文件

| 模块             | 路径                                                                          |
| ---------------- | ----------------------------------------------------------------------------- |
| 类型定义（矢量） | `backend/app/modules/schema/types/spatial_types.py`                         |
| 类型定义（栅格） | `backend/app/modules/schema/types/raster_types.py`                          |
| 数据视图         | `backend/app/modules/schema/types/canonical.py`                             |
| 图层注册表       | `backend/app/modules/schema/types/layer_registry.py`                        |
| 摄入端口         | `backend/app/modules/data/ingest.py`                                        |
| 数据源配置       | `backend/app/modules/data/catalog/sources.yaml`                             |
| 位置解析         | `backend/app/utils/location_parser.py`                                      |
| 空间上下文计算   | `backend/app/modules/spatial_ops/context.py` (compute_context_blocks, v4.3) |
| 输出 Bundle 缓存 | `output/bundle_cache/jintian_bundle.pkl`                                    |
