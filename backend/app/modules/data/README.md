# Data Module — 统一数据获取与管理层

> **Status: [DESIGN]** | **Type: Architecture** | **Created: 2026-07-24**
> **Scope**: 所有空间数据（矢量/栅格/瓦片）与非空间文档（规划文本/L3 报告）进入系统的唯一边界
> **Predecessor**: `backend/app/modules/gis/data/`（将逐步迁移并入本模块）

---

## 一、为什么需要这个模块

### 1.1 现状诊断

当前 `backend/app/modules/gis/data/` 存在 **三套并行的数据访问抽象**，职责重叠、边界模糊：

| 抽象 | 位置 | 接口风格 | 实际状态 |
|------|------|----------|----------|
| **Providers** | `providers/` | `GISProvider` ABC，async，产出 Pydantic | 只有 `orchestrator.py` 在用，**无 driver 调用** |
| **Drivers** | `drivers/` + `catalog/` | `DataSourceDriver` ABC，sync，YAML 驱动 | 新架构骨架，但 `load_all()` 仍 fallback 到 legacy |
| **Fetcher** | `fetcher.py` | `GISDataFetcher`，sync，直接调 provider | 被 `tools/gis_data/` 和 `session_routes` 使用 |

衍生问题：

- **`GeoProviderResult` 在两处定义**（`providers/base.py` 与 `providers/base_types.py`），签名不一致。
- **`loader.py` 是 638 行的"杂物间"**：GeoJSON 加载 + L3 报告加载 + intent 解析 + LLM 调用 + 约束构建 + 参数计算 + dataclass 工具，七个不相关的抽象层级混在一个文件。
- **`intent_cache.py` 引用断裂**：import `.data_loader` / `.planning_text_loader`，但实际模块名为 `.loader` / `.text_loader`——缓存路径在实际调用中多半走不到。
- **数据入口不统一**：规划文本从 `text_loader` 进，L3 报告从 `loader.load_l3_reports` 进，GeoJSON 从 `loader` 或 `catalog/loaders` 进，API 数据从 `fetcher` 或 `orchestrator` 进，上传文件从 DB（写在 fetcher 里）。没有一个"所有数据从这里进入"的边界。
- **API 凭据散落**：`TIANDITU_API_KEY` / `AMAP_API_KEY` / `GD_TIANDITU_TOKEN` / rate_limit / timeout 分散在 `settings.py`，各 provider 自行读取，无统一连接管理、无健康检查、无凭据隔离。
- **`providers/` 与 `drivers/` 关系混乱**：`TiandituVectorDriver` 内部直接 `import providers.tianditu.gd_service`；`GISProvider`(async) 与 `DataSourceDriver`(sync) 是两个世界，却包装同一批底层服务。
- **非空间文档无统一管理**：规划 markdown、L3 报告 JSON 这类"文档类数据"散落在 `loader.py` 和 `text_loader.py`，与 GIS 数据混在一起却又自成体系。

### 1.2 用户痛点

> "目前的实现很复杂还不好用"

核心矛盾：**P0/P1/P2 重构产出了新的 catalog/drivers 骨架，但旧的 providers/fetcher/loader 没有被替换，三者并存导致认知负担远大于收益。** 新代码不知道该用哪套，旧代码不敢删。

---

## 二、设计理念

参考专业 GIS 软件（QGIS / ArcGIS）的数据管理分层，适配 Agent 场景：

### 2.1 核心概念

| 概念 | QGIS/ArcGIS 类比 | 本模块职责 |
|------|------------------|-----------|
| **Connection** | Data Source / Data Store | API/DB 的连接配置：端点、凭据、rate limit、重试、健康检查。**与读取逻辑解耦**——凭据管理是一等公民 |
| **Source** (Driver) | Data Provider | 知道"如何从某类源读原始字节"：本地文件 / WFS / MapServer REST / WMTS / 栅格文件 |
| **Layer** | Layer | 语义化图层：绑定一个 Source，声明 `layer_type`、CRS、字段映射。是配置的最小单元 |
| **Catalog** | Browser / Layer Tree | 声明式图层目录：YAML 配置注册所有 Layer，提供按名/按 `layer_type` 查询 |
| **Dataset** | Feature Class / Raster Dataset | 获取后的数据集，对接 `gis.schema.canonical` 模型，是 schema 层的输入 |

### 2.2 设计原则

1. **单一入口**：所有数据（矢量/栅格/瓦片/文档）通过 `DataCatalog` 进入系统。`gis.tools` 与 `agent` 只依赖 `data` 模块，不直接碰 provider/fetcher。
2. **连接与源分离**：API 凭据归 `Connection`，读取逻辑归 `Source`。一个 Connection 可被多个 Source 共享（如天地图连接被 WFS/瓦片/广东专题共用）。
3. **配置驱动**：`catalog/sources.yaml` 声明所有数据源，新增数据源不改代码。
4. **CRS 统一**：所有输出 WGS84（EPSG:4326），CRS 转换在 Source 层完成，下游永不处理坐标系。
5. **对接 schema**：Source 产出 `canonical` 模型（`GeoFeature`/`GISDataBundle`），通过 `ingest.py` 端口校验编码并转为类型化对象。
6. **不抛异常**：统一 `DataResult` 封装，`success` 为假时携带 `error`，调用方先判 `success` 再取 `data`。
7. **文档也是数据**：规划文本、L3 报告等非空间文件纳入 `documents/` 子模块，走同样的 Catalog/Source 抽象。

### 2.3 与专业 GIS 软件的差异

- **无渲染层**：本模块只管"读进来"，不管"画出来"（渲染在 `tools/gis/_rendering/`）。
- **Agent 友好**：所有接口返回 `DataResult`（dict-like），便于 LangGraph tool 包装；关键路径有缓存。
- **编码校验前置**：中国国土空间规划有多套地类编码（GB/T 21010 / 土规 / 附录5 / 用地用海），编码校验在 `ingest` 端口完成，脏数据不进管道。

---

## 三、架构总览

### 3.1 分层

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 4: Catalog (声明式编排)                               │
│  sources.yaml -> DataCatalog -> 按 layer_type 查询           │
├─────────────────────────────────────────────────────────────┤
│  Layer 3: Source / Driver (读取逻辑)                         │
│  file_vector | api_vector | wmts_tile | local_raster | ...  │
│  每个 Source 绑定一个 Connection（API 类）或路径（文件类）    │
├─────────────────────────────────────────────────────────────┤
│  Layer 2: Connection (连接管理)                              │
│  tianditu | amap | osm | gd_tianditu                        │
│  凭据 / rate_limit / 重试 / 健康检查                          │
├─────────────────────────────────────────────────────────────┤
│  Layer 1: Storage & Cache (本地管理)                        │
│  瓦片缓存 / 矢量缓存 / 元数据索引                            │
└─────────────────────────────────────────────────────────────┘
         │
         ▼  (DataResult → canonical models)
┌─────────────────────────────────────────────────────────────┐
│  gis.schema.canonical (数据契约，消费者)                     │
│  BBox | GeoFeature | ProviderLandParcel | GISDataBundle     │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 数据流（单向，无回流）

```
外部源 ──► Connection(凭据) ──► Source(读取+CRS规范化)
                                      │
                                      ▼
                              DataResult{data, metadata}
                                      │
                                      ▼
                              ingest.py(编码校验)
                                      │
                                      ▼
                          canonical models (GeoFeature / GISDataBundle)
                                      │
                                      ▼
                          gis.tools / agent (消费)
```

### 3.3 依赖方向

```
app.modules.data  ──►  app.modules.gis.schema  (canonical 类型定义)
app.modules.gis.tools  ──►  app.modules.data  (获取数据)
app.modules.gis.schema  ──✕──►  app.modules.data  (无反向依赖，避免循环)
```

> **canonical 模型留在 `gis/schema/canonical.py`**：它们是 GIS 语义容器，改动它们影响面大且收益低。`data` 模块仅 import 类型，不引入循环。

---

## 四、目录结构

```
backend/app/modules/data/
├── README.md                    # 本文档
├── __init__.py                  # 公共 API 出口
├── contracts.py                 # 数据契约：DataResult, DataSourceMetadata, LayerSpec
├── connections/                 # Layer 2 - 连接管理
│   ├── __init__.py
│   ├── base.py                  # Connection ABC + ConnectionRegistry
│   ├── tianditu.py              # 天地图（key, rate_limit, base_url, 健康检查）
│   ├── amap.py                  # 高德（key, rate_limit, GCJ02 标记）
│   ├── osm.py                   # OSM（Overpass 端点, 无 key）
│   └── gd_tianditu.py           # 广东省天地图专题服务（token, IP 白名单）
├── sources/                     # Layer 3 - 数据源驱动
│   ├── __init__.py
│   ├── base.py                  # DataSourceDriver ABC
│   ├── registry.py              # DriverRegistry（装饰器注册）
│   ├── file_vector.py           # 本地矢量：GeoJSON / Shapefile / GDB
│   ├── api_vector.py            # API 矢量：WFS / MapServer REST
│   ├── wmts_tile.py             # WMTS 瓦片：批量下载 + 拼接
│   ├── local_raster.py          # 本地栅格：GeoTIFF / IMG
│   ├── remote_raster.py         # 远程栅格：下载指引 + 本地落地检查
│   └── document.py              # 文档文件：markdown / json / txt
├── catalog/                     # Layer 4 - 声明式目录
│   ├── __init__.py
│   ├── catalog.py               # DataCatalog 主入口
│   ├── config.py                # Pydantic 配置模型
│   └── sources.yaml             # 数据源配置（单一真相源）
├── documents/                   # 非空间文档管理
│   ├── __init__.py
│   ├── loader.py                # 规划文本 / L3 报告加载
│   └── intent_cache.py          # 意图缓存（迁移自 gis/data/intent_cache.py）
├── cache/                       # Layer 1 - 存储与缓存
│   ├── __init__.py
│   ├── tile_cache.py            # 瓦片缓存
│   └── metadata_index.py        # 元数据索引
└── ingest.py                    # 数据摄入端口（DataResult -> canonical models）
```

### 4.1 与旧路径的对应关系

| 旧路径 (`gis/data/`) | 新路径 (`data/`) | 说明 |
|----------------------|------------------|------|
| `providers/base.py` (GISProvider) | 删除，合并入 `sources/base.py` | async ABC 未被使用，统一为 sync |
| `providers/base_types.py` | 删除 | 重复的 `GeoProviderResult` |
| `providers/orchestrator.py` | `catalog/catalog.py` 的编排能力 | 编排逻辑上移到 Catalog |
| `providers/rate_limiter.py` | `connections/rate_limiter.py` 独立 | 限流是 Connection 的职责 |
| `providers/tianditu/` | `connections/tianditu.py` + `sources/api_vector.py` + `sources/wmts_tile.py` | 拆分：连接 vs 读取 |
| `providers/amap/` | `connections/amap.py` + `sources/api_vector.py` | 同上 |
| `providers/osm/` | `connections/osm.py` + `sources/api_vector.py` | 同上 |
| `providers/poi.py` | `sources/api_vector.py` 的 POI 查询 | POI 是矢量点查询 |
| `providers/dem_provider.py` | `sources/local_raster.py` + `sources/remote_raster.py` | DEM 即栅格 |
| `drivers/` | `sources/` | 改名，更贴合专业 GIS 术语 |
| `catalog/` | `catalog/` | 保留，增强 |
| `fetcher.py` | 删除 | 能力被 Catalog + api_vector 取代 |
| `loader.py` (GeoJSON 部分) | `sources/file_vector.py` + `catalog/loaders.py` | 拆分 |
| `loader.py` (L3 报告) | `documents/loader.py` | 文档归位 |
| `loader.py` (intent/LLM) | 迁回 `tools/gis/parse` | 属于工具层，不是数据层 |
| `text_loader.py` | `documents/loader.py` | 文档归位 |
| `intent_cache.py` | `documents/intent_cache.py` | 修复引用断裂 |

---

## 五、核心接口

### 5.1 数据契约（`contracts.py`）

```python
from dataclasses import dataclass, field
from typing import Any, Optional, Dict
from app.modules.gis.schema.canonical import BBox


@dataclass
class DataResult:
    """统一结果封装 - 所有 Source 返回此类型，不抛异常。"""

    success: bool
    data: Any = None                          # GeoJSON dict | 瓦片列表 | 栅格路径 | 文档文本
    data_type: str = ""                       # "geojson" | "tiles" | "mosaic" | "raster" | "document"
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    cache_path: Optional[str] = None

    @classmethod
    def ok(cls, data: Any, data_type: str = "", **metadata) -> "DataResult":
        return cls(success=True, data=data, data_type=data_type, metadata=metadata)

    @classmethod
    def fail(cls, error: str, **metadata) -> "DataResult":
        return cls(success=False, error=error, metadata=metadata)


@dataclass
class DataSourceMetadata:
    """数据源元数据。"""

    name: str
    driver: str
    crs: str = "EPSG:4326"
    layer_type: str = ""
    bbox: Optional[BBox] = None
    resolution: Optional[float] = None
    feature_count: Optional[int] = None
    update_time: Optional[str] = None
    source_url: Optional[str] = None
```

### 5.2 连接基类（`connections/base.py`）

```python
from abc import ABC, abstractmethod
from app.modules.data.providers.rate_limiter import RateLimiter  # 迁移后路径


class Connection(ABC):
    """外部 API 连接 - 管理凭据、限流、重试、健康检查。

    一个 Connection 实例可被多个 Source 共享。
    例如 TiandituConnection 被 api_vector / wmts_tile / 广东专题 共用。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """连接唯一标识: 'tianditu' | 'amap' | 'osm' | 'gd_tianditu'。"""
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        """凭据是否就绪（不发起网络请求）。"""
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """发起轻量请求验证连接可用性。"""
        ...

    @property
    @abstractmethod
    def rate_limiter(self) -> RateLimiter:
        """该连接的共享限流器。"""
        ...
```

### 5.3 数据源基类（`sources/base.py`）

```python
from abc import ABC, abstractmethod
from typing import Any, Optional
from app.modules.gis.schema.canonical import BBox
from app.modules.data.contracts import DataResult, DataSourceMetadata


class DataSourceDriver(ABC):
    """数据源驱动 - 知道如何从某类源读数据。

    分类:
      - vector:       GeoJSON / Shapefile / GDB / WFS / MapServer REST
      - raster_tile:  WMTS 瓦片
      - raster_file:  GeoTIFF / IMG
      - document:     markdown / json / txt
    """

    @property
    @abstractmethod
    def driver_type(self) -> str:
        """vector | raster_tile | raster_file | document。"""
        ...

    @abstractmethod
    def fetch(self, bbox: Optional[BBox] = None, **kwargs) -> DataResult:
        """获取数据，返回 DataResult（不抛异常）。"""
        ...

    @abstractmethod
    def get_metadata(self) -> DataSourceMetadata:
        """返回数据源元数据。"""
        ...

    @property
    def supports_bbox_query(self) -> bool:
        return False

    @property
    def is_cached(self) -> bool:
        return False
```

### 5.4 目录入口（`catalog/catalog.py`）

```python
class DataCatalog:
    """数据目录 - 所有数据进入系统的唯一入口。

    用法:
        from app.modules.data import DataCatalog

        catalog = DataCatalog()

        # 按名获取单个数据源
        result = catalog.get_source("jintian_current_landuse").fetch()

        # 按 layer_type 批量查询
        results = catalog.query_by_bbox(bbox, ["landuse_current", "road"])

        # 加载村庄全量数据（对接 schema）
        bundle = catalog.load_village_data("金田村", bbox)
    """

    def __init__(self, config_path: Optional[str] = None): ...

    def get_source(self, name: str) -> DataSourceDriver: ...

    def list_sources(self) -> list[str]: ...

    def query_by_bbox(
        self, bbox: BBox, layer_types: list[str]
    ) -> dict[str, DataResult]: ...

    def load_village_data(
        self, village_name: str, bbox: BBox, layer_types: Optional[list[str]] = None
    ) -> "GISDataBundle":
        """加载村庄数据并经 ingest 校验，返回 canonical GISDataBundle。"""
        ...
```

---

## 六、配置规范（`catalog/sources.yaml`）

YAML 是数据源的**单一真相源**。结构沿用现有 `sources.yaml`，新增 `connection` 字段绑定连接：

```yaml
version: "2.0"

# ── 连接声明（新增）──
connections:
  tianditu:
    api_key: "${TIANDITU_API_KEY}"        # 环境变量引用
    rate_limit: 5.0                       # QPS
    timeout: 30
    max_retries: 3
  amap:
    api_key: "${AMAP_API_KEY}"
    rate_limit: 30.0
    timeout: 30
  gd_tianditu:
    token: "${GD_TIANDITU_TOKEN}"
    base_url: "https://guangdong.tianditu.gov.cn"

# ── 数据源声明 ──
sources:
  # 本地矢量
  jintian_current_landuse:
    driver: file_vector
    path: "data/gis/jintian/current/landuse.geojson"
    layer_type: landuse_current
    crs: EPSG:4326

  # 天地图 WFS 矢量（绑定连接）
  tianditu_water:
    driver: api_vector
    connection: tianditu
    protocol: wfs
    layer: HYDA
    layer_type: water
    crs: EPSG:4490

  # 广东天地图专题（绑定连接）
  gd_three_zones:
    driver: api_vector
    connection: gd_tianditu
    service_id: SQSXWPSJ
    protocol: mapserver_rest
    layers:
      - {id: 0, layer_type: farmland_protection}
      - {id: 1, layer_type: urban_dev_boundary}
      - {id: 2, layer_type: ecological_protection}

  # WMTS 瓦片
  tianditu_img:
    driver: wmts_tile
    connection: tianditu
    layer: img_c
    zoom_range: [1, 18]
    layer_type: dom

  # 本地栅格
  dem_local:
    driver: local_raster
    path: "data/gis/jintian/terrain/dem.tif"
    layer_type: dem

  # 文档（新增类型）
  jintian_planning_text:
    driver: document
    path: "docs/MinerU_markdown_*村庄规划*文本*.md"
    doc_type: planning_markdown
    layer_type: planning_text
```

---

## 七、与 schema 层对接

`ingest.py` 是 raw 数据到 schema 类型化模型的**唯一转换端口**，就住在 data 层内部（从 `schema/ingestion.py` 迁入）。data 层既负责读取，也负责校验和类型化；schema 层只提供类型定义和编码查表。

```python
# data/ingest.py - raw GeoJSON -> typed schema models
from app.modules.gis.schema.spatial_types import (
    SpatialFeature, CurrentLandUseParcel, PlannedLandUseParcel, ...
)
from app.modules.gis.schema import get_zone_type_for_dlbm, dlbm_to_planning_zone

def ingest_current_landuse(filepath): ...          # filepath -> typed parcels
def result_to_parcels(result, layer_type): ...     # DataResult -> typed parcels
def result_to_features(result, feature_type): ...  # DataResult -> typed features
```

**关键约束**：
- 编码校验在 **data 层 ingest 端口**完成（`_EncodingValidator` 调用 schema 的 `dicts/` 查表），脏数据不进管道。
- data 层 import `schema.spatial_types` 的类型定义 + `schema` 的查表函数，单向依赖，无循环。
- `ProviderLandParcel`（外部 API 地块）经 `provider_to_parcel` 转为管道类型，与文件输入走同一条校验路径。
- `DataCatalog.load_village_bundle()` 返回已类型化的 `GISDataBundle`，下游（kg / parse / tools）**不接触 raw dict**。

参见 [`gis/schema/README.md`](../gis/schema/README.md) 二节 依赖规则。


## 八、迁移计划

分四个阶段，每阶段可独立验证、可回滚。**旧路径在所有引用迁移完成前不删除**，通过 `gis/data/__init__.py` 的 re-export 保持兼容。

### Phase 1：骨架与文档（本次）

- [x] 创建 `app/modules/data/` 目录
- [x] 本 README 设计文档
- [x] `contracts.py` — DataResult, DataSourceMetadata
- [x] `sources/base.py` + `registry.py` — ABC 与注册表
- [x] `connections/base.py` — Connection ABC
- [x] `catalog/catalog.py` 骨架 — 从旧 `catalog.py` 迁移

### Phase 2：连接层抽取

- [x] `connections/tianditu.py` — 整合 `providers/tianditu/provider.py` 的凭据/限流/重试
- [x] `connections/amap.py` — 整合 `providers/amap/provider.py`
- [x] `connections/gd_tianditu.py` — 整合 `providers/tianditu/gd_service.py` 的凭据
- [x] `connections/osm.py` — 整合 `providers/osm/`
- [x] 迁移 `providers/rate_limiter.py` -> `connections/rate_limiter.py`（独立文件，base.py import）

### Phase 3：数据源迁移

- [x] `sources/file_vector.py` ← `drivers/file_vector_driver.py` + `loader.py` 文件加载
- [x] `sources/api_vector.py` ← `drivers/tianditu_vector_driver.py` + `providers/poi.py`
- [x] `sources/wmts_tile.py` ← `drivers/tianditu_tile_driver.py` + `providers/tianditu/tiles.py`
- [x] `sources/local_raster.py` ← `drivers/local_raster_driver.py` + `providers/dem_provider.py`
- [x] `sources/remote_raster.py` ← `drivers/remote_raster_driver.py`
- [x] `sources/document.py` ← `text_loader.py` + `loader.py` 的 L3 报告部分

### Phase 4：兼容层与测试迁移（已完成）

- [x] `gis/data/__init__.py` 加注释指向新模块（re-export 因循环依赖不可行：app.modules.data 依赖 gis.schema，触发 gis/__init__ -> gis.data）
- [x] `scripts/test_data_drivers.py` 迁移到 `app.modules.data`（8 测试通过）
- [x] 回归验证：`load_gis_data_full` 旧路径仍工作（13 layers, 34 annotations, 131 roads）

### Phase 5：深度迁移与清理（部分完成）

- [x] `documents/loader.py` ← `loader.py` 的 L3 报告 + `text_loader.py`（load_l3_reports 12 reports, load_planning_text 44737 chars）
- [x] `documents/intent_cache.py` ← `intent_cache.py`（引用断裂已修复：.data_loader->documents.loader，LLM 逻辑经 legacy bridge 桥接）
- [ ] `loader.py` 的 intent/LLM 部分 -> `tools/gis/parse`（属工具层）
- [ ] 40+ 引用点迁移到 `app.modules.data`（fetcher/providers 功能需先在新模块重现）
- [ ] 删除 `gis/data/fetcher.py`（能力被 Catalog.load_village_data 取代后）
- [ ] 删除 `gis/data/providers/` 旧目录（新 driver 不再依赖 gd_service/tiles 后）

### 迁移顺序的原则

1. **先建后拆**：新模块就绪、引用迁移完成，再删旧代码。
2. **兼容期 re-export**：`gis/data/__init__.py` 在迁移期 re-export 新模块，避免一次性改 40+ 引用。
3. **每阶段可验证**：每个 Phase 结束跑 `run_layout_pipeline.py` + `test_gis_unit.py` 确认无回归。

---

## 九、使用示例

### 9.1 基本查询

```python
from app.modules.data import DataCatalog
from app.modules.gis.schema.canonical import BBox

catalog = DataCatalog()

# 按名获取
result = catalog.get_source("jintian_current_landuse").fetch()
if result.success:
    geojson = result.data  # FeatureCollection dict

# 按 layer_type 批量
bbox = BBox(west=115.5, south=24.0, east=116.5, north=25.0)
results = catalog.query_by_bbox(bbox, ["landuse_current", "road", "water"])
for layer_type, res in results.items():
    if res.success:
        print(f"{layer_type}: {res.metadata.get('feature_count')} features")
```

### 9.2 加载村庄全量数据（对接 schema）

```python
bundle = catalog.load_village_data("金田村", bbox)
# bundle: GISDataBundle (canonical)
# - bundle.boundary: GeoFeature
# - bundle.landuse: List[BaseLandUseParcel] (经编码校验)
# - bundle.roads: List[GeoFeature]
print(bundle.is_complete(), bundle.parcel_count)
```

### 9.3 文档加载

```python
result = catalog.get_source("jintian_planning_text").fetch()
if result.success:
    markdown_text = result.data  # str
```

### 9.4 连接健康检查

```python
from app.modules.data.connections import ConnectionRegistry

conn = ConnectionRegistry.get("tianditu")
if conn.is_configured() and conn.health_check():
    print("天地图连接正常")
```

---

## 十、不做的事（范围边界）

- **不做渲染**：渲染留在 `tools/gis/_rendering/`。
- **不做 LLM 调用**：intent 解析的 LLM 逻辑迁回 `tools/gis/parse`，数据层只管"读文件/调 API"。
- **不改 canonical 模型**：`gis/schema/canonical.py` 保持原位，避免大面积破坏。
- **不做空间分析**：分析在 `tools/gis/_analytics/`，数据层只提供原料。
- **本期不迁移 KG**：`modules/kg/` 独立，暂不并入。

---

## 十一、参考

| 来源 | 借鉴点 |
|------|--------|
| QGIS Data Source Manager | Connection / Layer / Browser 分层 |
| ArcGIS Data Store | 注册数据源位置、图层引用语义 |
| Intake (Pangeo) | 声明式 YAML 数据目录 |
| HydroMT DataSource | Pydantic 栅格配置 |
| 前序提案 `04_MULTI_SOURCE_DATA_ARCHITECTURE.md` | DriverRegistry / sources.yaml 基础 |

---

## 附录A：数据源规划依据（来自 docs/gis/）

以下内容提炼自 `docs/gis/03_DATA_SOURCE.md`、`docs/gis/04_DATA_ACQUISITION_PLAN.md`、
`docs/gis/diagnostics/03_DATA_GAP_ANALYSIS.md`，作为 `sources.yaml` 配置与数据源
选型的依据。详细字段规范、Schema 映射、缺口诊断见原文档。

### A.1 数据分类与进入方式

| 类别 | 进入方式 | 是否建空间模型 | 示例 |
|------|----------|---------------|------|
| 空间数据 | 本模块 Catalog（file_vector / api_vector / wmts_tile / local_raster） | ✅ canonical models | DEM、地名坐标、宅基地、三区三线 |
| 文本数据 | `documents/` 子模块（document driver）-> parse -> OpSeq/Constraint | ❌ 不建空间模型 | 人口、产业、防灾需求 |

> 核心原则：所有空间数据经本模块单一入口进入，文本数据经 documents 进入后由 parse 解析，
> 两条路径在 schema 层汇合。参见 §2.2 设计原则"单一入口"。

### A.2 P0 数据集获取清单（sources.yaml 配置目标）

12 项立即获取项，对应 `sources.yaml` 中应配置的数据源：

| # | 平台 | 数据集 | 本模块 driver | layer_type |
|---|------|--------|--------------|-----------|
| 1 | 广东 | 三区三线专题图 | api_vector | farmland_protection / ecological_protection / urban_dev_boundary |
| 2 | 广东 | 永久基本农田保护图斑 | api_vector | farmland_protection |
| 3 | 广东 | 生态保护红线 | api_vector | ecological_protection |
| 4 | 广东 | 城镇开发边界 | api_vector | urban_dev_boundary |
| 5 | 广东 | 地质灾害隐患点专题图 | api_vector | geological_hazard_points |
| 6 | 广东 | 2023年影像电子地图 | wmts_tile | dom |
| 7 | 全国 | 2024年行政村边界数据 | file_vector | boundary |
| 8-9 | 全国 | 区县/乡镇行政区划边界 | file_vector | admin_area |
| 10 | 全国 | ALOS 12.5m DEM | remote_raster | dem |
| 11 | 全国 | 哨兵10m多光谱影像 | remote_raster | dom |
| 12 | 全国 | 河流水系空间分布 | file_vector | water |

> 完整 P1/P2 清单（共 44 项）见 `docs/gis/04_DATA_ACQUISITION_PLAN.md` §五。

### A.3 重复数据集去重原则

| 重复主题 | 推荐选择 | 理由 |
|----------|---------|------|
| DEM（5 版本） | ALOS 12.5m（SRTM 30m 备选） | 精度最优，科研免费 |
| 影像电子地图（10 版本） | 2023 年 + 多时相 | 最新基准 + 长时序 |
| 永久基本农田/城镇边界（墨卡托/非墨卡托） | **非墨卡托** | CGCS2000(EPSG:4490) 与项目坐标系一致，墨卡托面积变形大 |
| 国土变更调查（5 地类 × 2 投影） | 各取非墨卡托 | 同上 |
| 地质灾害隐患点（专题图/墨卡托） | 专题图版本 | 属性更完整 |

> 原则：CRS 优先级 CGCS2000(4490) > WGS84(4326) > Web墨卡托(3857)。墨卡托仅用于可视化，
> 不用于面积计算。CRS 转换在 Source 层完成（参见 §2.2 原则 4）。

### A.4 DEM/栅格数据源选择

| 数据源 | 精度 | 成本 | 适用场景 | 本模块配置 |
|--------|------|------|----------|-----------|
| ALOS World 3D | 12.5m | 免费(科研) | 中精度分析 | remote_raster, provider=alos_aw3d30 |
| ASTER GDEM V3 | 30m | 免费 | 初步分析 | remote_raster, provider=gdem_v3 |
| SRTM 1-arc-sec | 30m | 免费 | 初步分析 | remote_raster, provider=srtm |
| 地方 1:10000 DEM | 5m | 需申请 | 高精度建设边界 | local_raster |
| 无人机航测 | 0.5-2m | 设备+人力 | 最高精度居民点 | local_raster |

> 天地图 WMTS 的 `ter_c` 是地形晕渲图（可视化用），**不是原始 DEM**。原始 DEM 须从
> 地理空间数据云/ALOS 获取，通过 remote_raster driver 落地到 local_path。

### A.5 缺漏根因（数据源管理教训）

| 问题 | 原因 | 教训 |
|------|------|------|
| DEM 未进入输入层 | 技术指南只写"1:2000地形图"，未展开 DEM 规格 | 数据源规划须同时参考技术规范 + 专业教材 + 测绘标准 |
| 地名地址未进入输入层 | 教材列为"公开数据"，技术规范未提及 | 规划指南不覆盖数据获取，须主动纳入 catalog |
| 遥感影像未进入输入层 | 教材列为"公开数据"，规范只提"数字正射影像图" | 同上 |
| 空间锚定断裂 | 缺少地名->坐标映射 | 地名是规划与 GIS 的桥梁，须作为独立 layer_type |
| CRS 混用 | 多源数据坐标系不一 | 统一到 WGS84/CGCS2000，Source 层强制转换 |

> 核心教训：系统设计时只参考了技术规范（输出标准），未参考专业教材（输入实操）和测绘标准
> （数据规格），三层参考缺一不可。本模块的 `sources.yaml` 配置应覆盖三层参考的数据需求。

---

## 相关文件

| 模块 | 路径 |
|------|------|
| 数据契约（消费者） | `backend/app/modules/gis/schema/canonical.py` |
| 编码校验端口 | `backend/app/modules/data/ingest.py`（从 schema 迁入） |
| 前序架构提案 | `docs/gis/proposals/04_MULTI_SOURCE_DATA_ARCHITECTURE.md` |
| 旧实现（待迁移） | `backend/app/modules/gis/data/` |
| 管道入口 | `backend/scripts/run_layout_pipeline.py` |
| 数据源规范（金田村） | `docs/gis/03_DATA_SOURCE.md` |
| 数据集获取计划 | `docs/gis/04_DATA_ACQUISITION_PLAN.md` |
| 数据缺口分析 | `docs/gis/diagnostics/03_DATA_GAP_ANALYSIS.md` |
