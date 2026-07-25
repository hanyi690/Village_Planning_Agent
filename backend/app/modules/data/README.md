# Data Module - 统一数据获取与管理层

> **Status: [PRODUCTION]** | **Type: Architecture** | **Created: 2026-07-24** | **Updated: 2026-07-25 (v4.1)**
> **Scope**: 所有空间数据（矢量/栅格/瓦片）、非空间表格（人口/产业/管制规则）、文档（规划文本/L3报告）进入系统的唯一边界
> **gis/ 已删除**: 旧 `backend/app/modules/gis/` 整体移除，无 shim 无兼容层
> **v4.1 变更**: 数据视图上移 `ProjectDataView -> VillageBundle` 两层；新增 TableDataset 第四形态双轨；项目配置与数据源配置分离

---

## 一、为什么需要这个模块

### 1.1 旧版两个病灶（已解决）

**病灶一：三套并行抽象** -- `providers/` + `drivers/` + `fetcher` 重叠。已统一为 `Catalog + Source + Connection`，`gis/` 已删除。

**病灶二：僵化纯语义注册表** -- 28 个 layer_type 扁平硬编码，新增图层必须改代码部署。已由双轨接入（显式注册 + 智能推断）解决。

### 1.2 v4.1 新诊：bundle "一村一包"断层

旧版 `GISDataBundle` 隐含"一村一包"假设（`village_name` 写死 metadata、boundary 是单村边界）。实际规划中：

- 一个项目涉及多个自然村（行政村下辖村民小组）
- 一个会话可能同时分析多村（对比/联合布局）
- 用户上传数据可能跨村范围
- 跨村图层（县域道路、水系）和共享栅格（DEM/DOM）无归属

**v4.1 解法**：数据视图上移为 `ProjectDataView`（项目级）-> `VillageBundle`（村庄级子视图）两层。村庄只是项目视图的一个维度。详见 `schema/README.md` §三。

### 1.3 v4.1 新诊：非空间表格形态缺失

旧版只有"矢量 + 栅格 + 文档"，把人口结构、产业经济、管制规则表塞进"文档"当文本处理，丢失列结构。而汇交成果"一图一表一规则"的"表"与"规则"恰恰是表格。**v4.1 引入 `TableDataset` 第四形态**，与矢量/栅格/文档并列。

---

## 二、设计理念：双轨接入 + 四形态 + 项目级视图

### 2.1 双轨：显式注册 + 智能推断

| 轨道 | 适用 | 行为 |
|---|---|---|
| **显式注册轨** | 关键规划图层（已知、业务依赖） | layer_type 在 `LAYER_TYPE_REGISTRY` 注册，走严格 `ingest` 端口，编码/元数据校验前置 |
| **智能推断轨** | 临时上传、探索性数据、新来源 | 未注册 layer_type 自动进入推断管道，按形态分流 + 语义匹配 + 动态模型生成 |

两轨最终都产出 `ProjectDataView` 的类型化字段。推断轨的动态图层放入 `village.extra_layers`（矢量）、`project.extra_rasters`（栅格）、`project.tables`（表格），不污染核心字段但可被下游访问。

### 2.2 四形态结构优先

数据进入系统时按**数据形态**分层判定，而非直接猜语义：

```
第一性: 数据形态
  ├── 矢量 -> 几何结构 (Point/Line/Polygon)        -> schema L1 几何基类
  ├── 栅格 -> 波段与值域 (单波段/多波段/分类)       -> schema RasterDataset 子类
  ├── 表格 -> 列结构 (非空间结构化行列)             -> schema TableDataset 子类   [v4.1]
  └── 文档 -> 半结构化文本 (规划文本/L3报告)        -> schema Document 子类       [v4.1]

第二性: 语义角色
  └── 形态桶内按字段名/编码/元数据匹配具体语义子类
```

### 2.3 项目级视图

数据容器绑定**项目**（持久配置单位），会话是项目的运行时实例。`DataCatalog` 接受 `project_id`，加载该项目的全部空间与非空间数据到 `ProjectDataView`。规划师"打开一个项目"，系统一次性加载所有数据，而非逐村加载。

### 2.4 与专业 GIS 软件的差异

- **无渲染层**：渲染在 `tools/gis/_rendering/`。
- **Agent 友好**：`DataResult` dict-like，便于 LangGraph tool 包装；关键路径缓存。
- **编码/元数据校验前置**：矢量编码、栅格波段值域、表格列结构在 `ingest` 端口校验，脏数据不进管道。

---

## 三、智能推断管道

未注册 layer_type 自动启动推断。管道按形态分**矢量、栅格、表格**三条分支，并可利用**项目上下文**校准。

### 3.1 矢量分支（五步）

```
raw GeoJSON
  ▼ Step1 几何类型检测 -> Point/Line/Polygon 分桶
  ▼ Step2 字段名语义匹配 (mappings/field_aliases.yaml)
  ▼ Step3 编码系统自动探测 (DictionaryCenter 抽样匹配)
  ▼ Step4 动态模型生成 (make_dataclass 继承 L1 几何基类; 完全未知时降级为
  │                     Point/Line/PolygonFeature + Dict properties, 对标 geojson-pydantic Feature[Geometry, Dict])
  ▼ Step5 包装 -> village.extra_layers[layer_type], 字段带 confidence
```

### 3.2 栅格分支（四步）

```
raw raster (GeoTIFF/IMG/COG)
  ▼ Step1 GDAL 元数据 (band_count + dtype + 值域 + CRS + 分辨率)
  ▼ Step2 类型匹配 (单波段Float32值域0-9000->DEM, 3波段Byte->DOM, ...)
  ▼ Step3 CRS/分辨率校验
  ▼ Step4 包装 -> project.rasters[layer_type] 或 project.extra_rasters
```

### 3.3 表格分支 [v4.1 新增]（四步）

```
raw table (CSV/Excel/JSON/L3报告内嵌表)
  ▼ Step1 列结构读取 (列名 + dtype + 样本值)
  ▼ Step2 列名语义匹配 (mappings/table_column_aliases.yaml)
  │    "人口数/户数/劳动力" -> PopulationTable 列
  │    "项目名/投资/时序"   -> ConstructionProjectTable 列
  │    "分区/管制要求/条款" -> ControlRuleTable 列
  ▼ Step3 类型匹配 (列组合命中已知 TableDataset 子类 -> 用该子类; 否则动态生成)
  ▼ Step4 包装 -> project.tables[layer_type], 列带 confidence
```

### 3.4 项目上下文校准 [v4.1 新增]

推断管道利用项目内已有数据校准新图层的推断：

- 若项目已注册 `landuse_current` 用 `appendix5` 编码，用户上传的相似结构图层默认推断为同体系，置信度更高。
- 若项目已有 `dem` 栅格（12.5m 分辨率），用户上传的坡度图可关联到该 DEM 源。
- 项目级映射累积到 `mappings/user_field_mappings.yaml`，跨会话复用。

### 3.5 安全性保障

- **置信度标注**：每个自动映射字段带 `confidence`（0.0-1.0），低于阈值（0.8）保留原字段名并记 `project_metadata.inference_warnings`。
- **人工确认回路**：Agent 关键决策时可询问用户确认映射（"我将 `DLBM` 理解为附录5编码，是否正确？"），确认后升级为高置信度并记入 user mappings。
- **强制注册开关**：`require_registered=True` 拒绝推断结果，关键决策场景强制显式注册。

### 3.6 为什么不纯智能解析

保留显式注册的**确定性内核**，推断层是辅助性的：降低使用门槛，但允许用户通过注册表"锁定"关键图层解释。避免"自动化越多，调试越难"的陷阱。

---

## 四、架构总览

### 4.1 分层

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 4: Catalog (声明式编排 + 推断调度 + 项目加载)         │
│  sources.yaml (物理源) + projects.yaml (项目逻辑)            │
│  DataCatalog.load_project_data_view(project_id)              │
├─────────────────────────────────────────────────────────────┤
│  Layer 3: Source / Driver (四形态读取)                       │
│  file_vector | api_vector | wmts_tile | local_raster |       │
│  remote_raster | document | table                            │
├─────────────────────────────────────────────────────────────┤
│  Layer 2: Connection (连接管理)                              │
│  tianditu | amap | osm | gd_tianditu                        │
├─────────────────────────────────────────────────────────────┤
│  Layer 1: Storage & Cache                                    │
└─────────────────────────────────────────────────────────────┘
         │
         ▼  (DataResult -> ingest/inference -> typed models)
┌─────────────────────────────────────────────────────────────┐
│  ProjectDataView (项目级)                                    │
│  ├── villages: Dict[str, VillageBundle]                      │
│  ├── cross_village_layers / rasters / extra_rasters          │
│  ├── tables / documents                                      │
│  └── project_metadata (含 layer_tree, inference_warnings)    │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 数据流（单向，无回流）

```
外部源 ──► Connection ──► Source(读取+CRS规范化)
                               │
                               ▼
                       DataResult{data, metadata}
                               │
                   ┌───────────┴───────────┐
                   ▼                       ▼
            已注册 layer_type?         未注册
                   │                       │
            ingest.py                ingest_inference.py
            (严格校验)                (形态分流+语义匹配+动态模型)
                   │                       │
                   └───────────┬───────────┘
                               ▼
                   ProjectDataView (typed)
                               │
                               ▼
                   gis.tools / agent (消费)
```

### 4.3 依赖方向

```
app.modules.data  ──►  app.modules.schema
app.tools.gis     ──►  app.modules.data
app.modules.schema  ──✕──►  app.modules.data  (无反向依赖)
```

---

## 五、目录结构

```
backend/app/modules/data/
├── README.md
├── __init__.py
├── contracts.py                 # DataResult, DataSourceMetadata
├── ingest.py                    # 显式注册轨摄入 (矢量/栅格/表格/文档)
├── ingest_inference.py          # 智能推断管道 (矢量五步+栅格四步+表格四步)
├── connections/                 # 连接管理 (不变)
├── sources/                     # 数据源驱动
│   ├── file_vector.py
│   ├── api_vector.py
│   ├── wmts_tile.py
│   ├── local_raster.py
│   ├── remote_raster.py
│   ├── document.py
│   └── table.py                 # [v4.1] 表格源: CSV/Excel/JSON/L3内嵌表
├── catalog/
│   ├── catalog.py               # DataCatalog (加 load_project_data_view)
│   ├── config.py
│   ├── sources.yaml             # 数据源物理配置 (单一真相源)
│   └── projects.yaml            # [v4.1] 项目逻辑配置 (参与村庄/源覆盖/上传数据)
├── documents/                   # 文档加载 (不变)
├── mappings/                    # 智能推断配置与学习
│   ├── field_aliases.yaml       # 矢量字段名知识库
│   ├── table_column_aliases.yaml # [v4.1] 表格列名知识库
│   └── user_field_mappings.yaml # 用户确认的映射 (跨会话累积)
└── cache/
```

---

## 六、核心接口

### 6.1 目录入口

```python
class DataCatalog:
    """数据目录 - 所有数据进入系统的唯一入口."""

    def load_project_data_view(
        self,
        project_id: str,
        require_registered: bool = False,
    ) -> "ProjectDataView":
        """加载项目全量数据, 返回 ProjectDataView.

        流程:
          1. 读 projects.yaml 取项目配置 (参与村庄 + 源覆盖 + 上传数据)
          2. 加载共享栅格 (DEM/DOM) -> project.rasters
          3. 加载跨村图层 (县域道路/水系) -> project.cross_village_layers
          4. 加载表格 (人口/产业/管制规则) -> project.tables
          5. 加载文档 (规划文本/L3报告) -> project.documents
          6. 逐村加载 VillageBundle (boundary -> current/planned -> ...)
          7. 已注册走 ingest, 未注册走 ingest_inference
          8. 汇总 layer_tree + inference_warnings 到 project_metadata
        """
        ...

    def load_village_bundle(
        self,
        village_name: str,
        project_id: Optional[str] = None,
    ) -> "VillageBundle":
        """便利方法: 取单村 VillageBundle.

        若 project_id 给定且项目视图已加载, 从中取该村庄;
        否则按需加载单村 (向后查询 API, 非兼容 shim).
        """
        ...
```

### 6.2 数据契约

```python
@dataclass
class DataResult:
    success: bool
    data: Any = None
    data_type: str = ""              # "geojson"|"raster"|"table"|"tiles"|"document"
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    cache_path: Optional[str] = None
    spatial_extent: Optional[BBox] = None
    crs: str = "EPSG:4326"
    bands: Optional[List[str]] = None
    columns: Optional[List[str]] = None   # [v4.1] 表格列名 (显式)
```

---

## 七、配置规范

### 7.1 `sources.yaml` -- 数据源物理配置（单一真相源）

```yaml
version: "2.0"
connections:
  tianditu: { api_key: "${TIANDITU_API_KEY}", rate_limit: 5.0 }
sources:
  jintian_current_landuse:
    driver: file_vector
    path: "data/gis/jintian/current/landuse.geojson"
    layer_type: landuse_current        # geometry_kind 从 registry 读
  dem_local:
    driver: local_raster
    path: "data/gis/jintian/terrain/dem.tif"
    layer_type: dem
    expected_bands: 1
    expected_dtype: Float32
  jintian_population:                  # [v4.1] 表格源
    driver: table
    path: "data/gis/jintian/survey/population.csv"
    layer_type: population
```

### 7.2 `projects.yaml` -- 项目逻辑配置 [v4.1 新增]

```yaml
version: "1.0"
projects:
  jintian_2026:
    name: "金田村 2026 村庄规划"
    crs: EPSG:4490
    villages:
      - name: "金田村"
        boundary_source: jintian_boundary
        layer_overrides:               # 覆盖默认 sources
          landuse_current: jintian_current_landuse_v2
      - name: "银田村"                 # 多村项目
        boundary_source: yintian_boundary
    shared_rasters:                    # 跨村共享栅格
      - { layer_type: dem, source: dem_local }
      - { layer_type: dom, source: dom_local }
    cross_village_layers:              # 跨村图层
      - { layer_type: road, source: county_road_network }
    tables:
      - { layer_type: population, source: jintian_population }
      - { layer_type: industry, source: jintian_industry }
    documents:
      - { layer_type: planning_text, source: jintian_planning_text }
    uploads:                           # 用户上传 (未注册, 走推断)
      - { path: "uploads/user_parcels.geojson", layer_type: user_upload_1 }
```

> **配置分离原则**：`sources.yaml` = 数据源**物理配置**（端点/凭据/路径/CRS），相对稳定；`projects.yaml` = 项目**逻辑配置**（参与村庄/源覆盖/上传/跨村引用），随项目变动。两者关注点不同，不混在一起。

---

## 八、与 schema 层对接（四形态分桶）

`ingest.py`（显式轨）与 `ingest_inference.py`（推断轨）是 raw 到 typed 的两个转换端口。schema 层提供四形态类型定义与编码查表。

```python
# 显式轨
def result_to_parcels(result, layer_type): ...     # -> List[CurrentLandUseParcel | PlannedLandUseParcel]
def result_to_features(result, feature_type): ...  # -> List[具体 SpatialFeature 子类]
def result_to_raster(result, layer_type): ...      # -> DEMInput | DOMInput | ...
def result_to_table(result, layer_type): ...       # [v4.1] -> PopulationTable | ControlRuleTable | ...

# 推断轨
def infer_vector_layer(result, layer_type): ...    # -> List[动态 Point/Line/PolygonFeature 子类]
def infer_raster_layer(result, layer_type): ...    # -> 动态 RasterDataset 子类
def infer_table_layer(result, layer_type): ...     # [v4.1] -> 动态 TableDataset 子类
```

**关键约束**：
- 矢量编码、栅格波段值域、表格列结构在 `ingest` 端口校验，脏数据不进管道。
- `load_project_data_view()` 返回 `ProjectDataView`，下游不接触 raw dict。
- 现状/规划地块分别填入 `village.current_landuse` / `village.planned_landuse`，不混装。

---

## 九、使用示例

```python
from app.modules.data import DataCatalog

catalog = DataCatalog()

# 加载项目全量数据 (多村 + 跨村 + 栅格 + 表格 + 文档)
project = catalog.load_project_data_view("jintian_2026")

# 单村访问
jintian = project.get_village("金田村")
print(jintian.current_landuse[0].dlbm)       # CurrentLandUseParcel
print(jintian.planned_landuse[0].ghytbm)     # PlannedLandUseParcel

# 共享栅格
print(project.rasters["dem"].band_count)     # DEMInput

# 表格 (输入 + 输出)
print(project.tables["population"].rows[0])  # PopulationTable
# 产出时: project.tables["construction_projects"] = ConstructionProjectTable(...)

# 图层树 (发现所有图层, 不硬编码)
for node in project.layer_tree:
    print(f"{node.name}: {node.geometry_kind}, {node.feature_count} features")

# 推断警告
for w in project.project_metadata.inference_warnings:
    print(f"[WARN] {w}")
```

---

## 十、不做的事（范围边界）

- **不做渲染**：渲染在 `tools/gis/_rendering/`。
- **不做 LLM 调用**：intent 解析 LLM 逻辑在 `tools/gis/parse`。
- **不做空间分析**：分析在 `tools/gis/_analytics/`，数据层只提供原料。
- **不做栅格计算**：坡度/坡向/适宜性在 `agent/gis/analyze/`，数据层只负责栅格摄入与类型化。
- **不做表格计算**：表格指标聚合在 `tools/` 或 `agent/`，数据层只负责表格摄入与类型化。
- **不保留兼容视图**：`VillageBundle` 破坏性重组，旧下游必须改造，不设过渡期。

---

## 附录A：数据源规划依据

### A.1 数据分类与进入方式（四形态）

| 类别 | 进入方式 | schema 类型 | 示例 |
|---|---|---|---|
| 矢量 | Catalog (file_vector/api_vector) | Point/Line/Polygon 子类 | 三调地类、三区三线、宅基地、道路 |
| 栅格 | Catalog (local_raster/remote_raster) | RasterDataset 子类 | DEM、DOM、坡度、适宜性 |
| 表格 | Catalog (table driver) | TableDataset 子类 | 人口结构、产业经济、管制规则、规划指标 |
| 文档 | documents/ (document driver) | Document 子类 | 规划文本、L3报告 |
| 野数据/上传 | Catalog 推断轨 | 动态模型 | 用户上传 GeoJSON/CSV |

### A.2 P0 数据集获取清单（含表格）

| # | 数据集 | driver | layer_type | geometry_kind |
|---|---|---|---|---|
| 1-5 | 三区三线/农田/生态/城镇/灾害点 | api_vector/file_vector | farmland_protection 等 | polygon/point |
| 6 | 2023影像电子地图 | wmts_tile | dom | raster |
| 7-9 | 行政村/区县/乡镇边界 | file_vector | boundary/admin_area | polygon |
| 10-11 | ALOS DEM / 哨兵影像 | remote_raster | dem/dom | raster |
| 12 | 河流水系 | file_vector | water_line/water_area | line/polygon |
| 13 | [v4.1] 人口结构表 | table | population | table |
| 14 | [v4.1] 产业经济表 | table | industry | table |
| 15 | [v4.1] 公服设施详情 | table | facility_inventory | table |

### A.3 DEM/栅格数据源选择

| 数据源 | 精度 | 成本 | 配置 |
|---|---|---|---|
| ALOS World 3D | 12.5m | 免费(科研) | remote_raster, provider=alos_aw3d30 |
| ASTER GDEM V3 | 30m | 免费 | remote_raster, provider=gdem_v3 |
| SRTM 1-arc-sec | 30m | 免费 | remote_raster, provider=srtm |
| 地方 1:10000 DEM | 5m | 需申请 | local_raster |
| 无人机航测 | 0.5-2m | 设备+人力 | local_raster |

> 天地图 WMTS `ter_c` 是地形晕渲图（可视化），**不是原始 DEM**。DEM 衍生（坡度/坡向/适宜性）由 `agent/gis/analyze/dem_analysis.py` 计算，产出 `TerrainAnalysisResult`。

---

## 相关文件

| 模块 | 路径 |
|---|---|
| 类型定义（矢量） | `backend/app/modules/schema/types/spatial_types.py` |
| 类型定义（栅格） | `backend/app/modules/schema/types/raster_types.py` |
| 类型定义（表格） | `backend/app/modules/schema/types/table_types.py` |
| 类型定义（文档） | `backend/app/modules/schema/types/document_types.py` |
| 数据视图（项目/村庄） | `backend/app/modules/schema/types/canonical.py` |
| 图层注册表 | `backend/app/modules/schema/types/layer_registry.py` |
| 显式摄入端口 | `backend/app/modules/data/ingest.py` |
| 智能推断管道 | `backend/app/modules/data/ingest_inference.py` |
| 数据源物理配置 | `backend/app/modules/data/catalog/sources.yaml` |
| 项目逻辑配置 | `backend/app/modules/data/catalog/projects.yaml` |
