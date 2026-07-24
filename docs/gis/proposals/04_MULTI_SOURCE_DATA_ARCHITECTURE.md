# GIS 多源数据管理架构设计

> **Status: [PROPOSAL]** | **Type: Architecture Design** | **Updated: 2026-07-24**
> **Scope**: 统一矢量+栅格双轨数据管理，覆盖本地文件/API服务/WMTS瓦片/远程栅格
> **References**: 04_DATA_ACQUISITION_PLAN.md, gd_service.py, tiles.py, dem_provider.py
> **Related**: raster_types.py, loader.py, ingestion.py
>
> 本文档定义 GIS 数据模块的多源统一管理架构。核心目标：用声明式配置（YAML）
> + 统一驱动接口（DriverRegistry）管理所有数据源，消除脚本中 5+ 处重复的加载逻辑。

---

## 一、问题诊断

### 1.1 当前数据获取能力碎片

| 数据源 | 现有封装 | 能力 | 缺失 |
|--------|---------|------|------|
| **矢量-本地** | `loader.py` | GeoJSON 文件加载 | 无统一入口 |
| **矢量-WFS** | `GDSpecializedService._fetch_wfs_data()` | 天地图 WFS | 仅广东，无通用化 |
| **矢量-MapServer** | `GDSpecializedService.get_service_rest_url()` | 仅返回 URL | **无查询实现** |
| **栅格-WMTS** | `TileService` | 瓦片 URL 生成 | **无批量下载/拼接** |
| **栅格-本地** | `DEMProvider` | DEM/DOM 文件发现 | **无远程下载** |
| **配置管理** | 无 | — | **无声明式配置** |

### 1.2 重复加载代码（5+ 处）

```python
# run_parse_pipeline.py:75-131
# run_layout_pipeline.py:95-147
# test_kg_parse_integration.py:25-50
# test_parse_agent_llm.py:47-68
# test_parse_agent.py:299-315
```

全部重复：`glob("*.geojson")` → `json.load()` → `gis_data[key]`。

### 1.3 关键认知：天地图栅格能力

```
天地图 WMTS 瓦片服务:
  ├── img_c / img_w     → 影像底图 (DOM)
  ├── vec_c / vec_w     → 矢量底图
  ├── ter_c / ter_w     → 地形晕渲 (可视化用，非原始DEM)
  ├── cia_c / cia_w     → 影像注记
  └── ibo_c / ibo_w     → 全球境界

广东省天地图专题服务:
  ├── dom2023           → 2023年影像电子地图 (WMS/WMTS)
  └── SQSXWPSJ          → 三区三线 (MapServer REST → 矢量GeoJSON)
```

> **重要区分**：`ter_c` 是**地形晕渲图**（可视化用的彩色地形图），不是原始高程数据。原始 DEM 仍需从地理空间数据云/ALOS 获取。

---

## 二、目标架构：三层抽象

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 3: Data Catalog (YAML/JSON declarative config)       │
│  ── 定义有哪些数据源、什么格式、在哪里、如何获取              │
├─────────────────────────────────────────────────────────────┤
│  Layer 2: Data Source Drivers (统一接口)                     │
│  ── FileVectorDriver (GeoJSON/Shapefile/GDB)                │
│  ── TiandituVectorDriver (WFS/MapServer REST)              │
│  ── TiandituTileDriver (WMTS瓦片批量下载拼接)               │
│  ── LocalRasterDriver (本地GeoTIFF)                         │
│  ── RemoteRasterDriver (外部下载指引)                        │
├─────────────────────────────────────────────────────────────┤
│  Layer 1: Storage & Cache (本地管理)                        │
│  ── 瓦片缓存、矢量缓存、栅格缓存、元数据索引、格式转换       │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、模块结构

```
backend/app/modules/gis/data/
├── __init__.py
├── catalog/                    # Layer 3 - 数据目录
│   ├── __init__.py
│   ├── catalog.py              # DataCatalog - 主入口
│   ├── config.py               # Pydantic models for YAML config
│   └── sources.yaml            # 数据源配置文件
├── drivers/                    # Layer 2 - 驱动层
│   ├── __init__.py
│   ├── base.py                 # DataSourceDriver ABC + DataSourceResult
│   ├── registry.py             # DriverRegistry (装饰器注册)
│   ├── file_vector_driver.py   # GeoJSON/Shapefile/GDB
│   ├── tianditu_vector_driver.py  # 封装 GDSpecializedService
│   ├── tianditu_tile_driver.py    # WMTS瓦片批量下载拼接
│   ├── local_raster_driver.py     # 本地GeoTIFF
│   └── remote_raster_driver.py    # 外部下载指引
├── storage/                    # Layer 1 - 存储缓存
│   ├── __init__.py
│   ├── cache.py                # 下载缓存管理
│   ├── index.py                # 元数据索引 (SQLite)
│   └── converter.py            # 格式转换 (CRS/瓦片拼接)
└── providers/                  # EXISTING (底层封装，驱动依赖它们)
    ├── base.py
    ├── tianditu/
    │   ├── provider.py
    │   ├── wfs.py
    │   ├── tiles.py              # TileService - 瓦片URL生成
    │   ├── gd_service.py         # GDSpecializedService - WFS/WMS/MapServer
    │   └── gd_constants.py
    ├── osm/
    └── amap/
```

---

## 四、核心接口

### 4.1 数据源驱动基类

```python
# drivers/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from app.modules.gis.schema.canonical import BBox


@dataclass
class DataSourceResult:
    """统一结果封装 — 所有驱动返回此类型。"""
    
    success: bool
    data: Any = None           # GeoJSON dict | 瓦片列表 | 栅格路径
    data_type: str = ""        # "geojson" | "tiles" | "mosaic" | "raster"
    metadata: dict = field(default_factory=dict)
    error: Optional[str] = None
    cache_path: Optional[str] = None


@dataclass
class DataSourceMetadata:
    """统一元数据。"""
    
    name: str
    driver: str
    crs: str
    bbox: Optional[BBox] = None
    resolution: Optional[float] = None   # 栅格分辨率
    feature_count: Optional[int] = None  # 矢量要素数
    update_time: Optional[str] = None
    source_url: Optional[str] = None


class DataSourceDriver(ABC):
    """所有数据源驱动的统一基类。"""
    
    @property
    @abstractmethod
    def driver_type(self) -> str:
        """驱动类型: vector | raster_tile | raster_file。"""
        ...
    
    @abstractmethod
    def fetch(self, bbox: BBox = None, **kwargs) -> DataSourceResult:
        """获取数据。"""
        ...
    
    @abstractmethod
    def get_metadata(self) -> DataSourceMetadata:
        """获取元数据。"""
        ...
    
    @property
    @abstractmethod
    def supports_bbox_query(self) -> bool:
        """是否支持空间查询。"""
        ...
    
    @property
    def is_cached(self) -> bool:
        """是否有本地缓存。"""
        return False
```

### 4.2 驱动注册表

```python
# drivers/registry.py
from typing import Dict, Type

from .base import DataSourceDriver


class DriverRegistry:
    """驱动注册表 — 装饰器模式自动注册。"""
    
    _drivers: Dict[str, Type[DataSourceDriver]] = {}
    
    @classmethod
    def register(cls, name: str):
        """装饰器: @DriverRegistry.register("file_vector")"""
        def decorator(driver_cls: Type[DataSourceDriver]):
            cls._drivers[name] = driver_cls
            return driver_cls
        return decorator
    
    @classmethod
    def get(cls, name: str) -> Type[DataSourceDriver]:
        if name not in cls._drivers:
            raise KeyError(f"Unknown driver: {name}. Registered: {list(cls._drivers.keys())}")
        return cls._drivers[name]
    
    @classmethod
    def list_drivers(cls) -> Dict[str, Type[DataSourceDriver]]:
        return dict(cls._drivers)
```

### 4.3 数据目录

```python
# catalog/catalog.py
from typing import Dict, Any
from pathlib import Path

from app.modules.gis.schema.canonical import BBox, GISDataBundle
from ..drivers.base import DataSourceDriver
from ..drivers.registry import DriverRegistry


class DataCatalog:
    """GIS数据目录 — 统一入口。"""
    
    def __init__(self, config_path: str = None):
        self.config = self._load_config(config_path)
        self._sources: Dict[str, DataSourceDriver] = {}
        self._init_sources()
    
    def _load_config(self, config_path: str) -> dict:
        """加载YAML配置。"""
        import yaml
        path = Path(config_path) if config_path else Path(__file__).parent / "sources.yaml"
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    
    def _init_sources(self):
        """根据配置初始化所有数据源驱动。"""
        for name, cfg in self.config.get("sources", {}).items():
            driver_cls = DriverRegistry.get(cfg["driver"])
            self._sources[name] = driver_cls(cfg)
    
    def get_source(self, name: str) -> DataSourceDriver:
        """获取数据源实例。"""
        if name not in self._sources:
            raise KeyError(f"Unknown source: {name}. Available: {list(self._sources.keys())}")
        return self._sources[name]
    
    def query_by_bbox(self, bbox: BBox, layer_types: list[str]) -> Dict[str, DataSourceResult]:
        """按边界框查询多个图层。"""
        results = {}
        for lt in layer_types:
            source = self._find_source_by_layer_type(lt)
            results[lt] = source.fetch(bbox)
        return results
    
    def load_village_data(self, village_name: str, bbox: BBox) -> GISDataBundle:
        """加载村庄全部相关数据。"""
        # 根据村庄名称和bbox自动加载所有配置的数据源
        ...
    
    def _find_source_by_layer_type(self, layer_type: str) -> DataSourceDriver:
        """根据layer_type查找对应的数据源。"""
        for name, source in self._sources.items():
            cfg = self.config["sources"][name]
            if cfg.get("layer_type") == layer_type:
                return source
            # 检查多层配置
            layers = cfg.get("layers", [])
            for layer in layers:
                if layer.get("layer_type") == layer_type:
                    return source
        raise KeyError(f"No source configured for layer_type: {layer_type}")
```

---

## 五、驱动实现

### 5.1 矢量驱动

#### FileVectorDriver

```python
# drivers/file_vector_driver.py
import json
from pathlib import Path

from .base import DataSourceDriver, DataSourceResult, DataSourceMetadata
from .registry import DriverRegistry
from app.modules.gis.schema.canonical import BBox


@DriverRegistry.register("file_vector")
class FileVectorDriver(DataSourceDriver):
    """本地矢量文件驱动 — GeoJSON/Shapefile/GDB。"""
    
    driver_type = "vector"
    
    def __init__(self, config: dict):
        self.path = Path(config["path"])
        self.format = config.get("format", "geojson")
        self.crs = config.get("crs", "EPSG:4326")
        self.encoding = config.get("encoding", "")
        self.layer_type = config.get("layer_type", "")
    
    def fetch(self, bbox: BBox = None, **kwargs) -> DataSourceResult:
        if not self.path.exists():
            return DataSourceResult(
                success=False,
                error=f"File not found: {self.path}"
            )
        
        try:
            if self.format == "geojson":
                with open(self.path, "r", encoding="utf-8") as f:
                    geojson = json.load(f)
                return DataSourceResult(
                    success=True,
                    data=geojson,
                    data_type="geojson",
                    metadata={
                        "path": str(self.path),
                        "format": self.format,
                        "feature_count": len(geojson.get("features", [])),
                    }
                )
            else:
                # Shapefile/GDB via geopandas
                import geopandas as gpd
                gdf = gpd.read_file(self.path)
                geojson = gdf.__geo_interface__
                return DataSourceResult(
                    success=True,
                    data=geojson,
                    data_type="geojson",
                    metadata={
                        "path": str(self.path),
                        "format": self.format,
                        "feature_count": len(gdf),
                    }
                )
        except Exception as e:
            return DataSourceResult(success=False, error=str(e))
    
    def get_metadata(self) -> DataSourceMetadata:
        return DataSourceMetadata(
            name=self.path.stem,
            driver="file_vector",
            crs=self.crs,
        )
    
    @property
    def supports_bbox_query(self) -> bool:
        return False  # 本地文件不支持bbox查询（可扩展）
```

#### TiandituVectorDriver

```python
# drivers/tianditu_vector_driver.py
from .base import DataSourceDriver, DataSourceResult, DataSourceMetadata
from .registry import DriverRegistry
from app.modules.gis.data.providers.tianditu.gd_service import GDSpecializedService


@DriverRegistry.register("tianditu_vector")
class TiandituVectorDriver(DataSourceDriver):
    """天地图矢量服务驱动 — WFS/MapServer REST。"""
    
    driver_type = "vector"
    
    def __init__(self, config: dict):
        self.service_id = config["service_id"]
        self.protocol = config.get("protocol", "mapserver_rest")
        self.layers = config.get("layers", [])
        self.crs = config.get("crs", "EPSG:4490")
        self.gd = GDSpecializedService()
    
    def fetch(self, bbox: BBox = None, layer_type: str = None, **kwargs) -> DataSourceResult:
        """获取指定图层类型的数据。"""
        # 查找layer_type对应的layer_id
        layer_config = None
        for layer in self.layers:
            if layer.get("layer_type") == layer_type:
                layer_config = layer
                break
        
        if not layer_config:
            return DataSourceResult(
                success=False,
                error=f"Layer type '{layer_type}' not found in service {self.service_id}"
            )
        
        layer_id = layer_config["id"]
        
        # 优先使用MapServer REST查询
        if self.protocol == "mapserver_rest":
            result = self.gd.query_mapserver_layer(
                self.service_id, layer_id, bbox
            )
            if result.success:
                return DataSourceResult(
                    success=True,
                    data=result.data.get("geojson"),
                    data_type="geojson",
                    metadata={
                        "service_id": self.service_id,
                        "layer_id": layer_id,
                        "layer_name": layer_config.get("name", ""),
                    }
                )
        
        # Fallback to WFS
        result = self.gd.fetch_constraint_data(layer_type, bbox)
        if result.success and result.data.get("geojson"):
            return DataSourceResult(
                success=True,
                data=result.data["geojson"],
                data_type="geojson",
                metadata={"source": "wfs"}
            )
        
        return DataSourceResult(
            success=False,
            error="Failed to fetch vector data from all protocols"
        )
    
    def get_metadata(self) -> DataSourceMetadata:
        return DataSourceMetadata(
            name=self.service_id,
            driver="tianditu_vector",
            crs=self.crs,
        )
    
    @property
    def supports_bbox_query(self) -> bool:
        return True
```

### 5.2 栅格瓦片驱动

```python
# drivers/tianditu_tile_driver.py
from pathlib import Path
from typing import List, Tuple

from .base import DataSourceDriver, DataSourceResult, DataSourceMetadata
from .registry import DriverRegistry
from app.modules.gis.data.providers.tianditu.tiles import TileService
from app.modules.gis.schema.canonical import BBox


@DriverRegistry.register("tianditu_tile")
class TiandituTileDriver(DataSourceDriver):
    """天地图WMTS瓦片驱动 — 批量下载、拼接、缓存。"""
    
    driver_type = "raster_tile"
    
    def __init__(self, config: dict):
        self.layer = config.get("layer", "img_c")
        self.projection = config.get("projection", "c")
        self.zoom_range = config.get("zoom_range", [1, 18])
        self.format = config.get("format", "png")
        self.crs = config.get("crs", "EPSG:4326")
        self.layer_type = config.get("layer_type", "dom")
        self.service_id = config.get("service_id")  # 专题服务ID（如dom2023）
        
        self.tile_service = TileService()
        self.cache_dir = Path(config.get("cache_dir", "data/cache/tiles"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def fetch(self, bbox: BBox = None, zoom: int = 16, **kwargs) -> DataSourceResult:
        """下载指定bbox范围内的瓦片。
        
        Args:
            bbox: 边界框
            zoom: 缩放级别
            mosaic: 是否拼接为单张大图 (默认False)
        """
        if bbox is None:
            return DataSourceResult(success=False, error="bbox required for tile fetch")
        
        # 1. 计算瓦片坐标范围
        tiles = self._bbox_to_tiles(bbox, zoom)
        
        # 2. 批量下载（带缓存）
        downloaded = []
        for x, y, z in tiles:
            tile_path = self._get_cached_tile(x, y, z)
            if not tile_path.exists():
                tile_path = self._download_tile(x, y, z)
            if tile_path:
                downloaded.append(tile_path)
        
        if not downloaded:
            return DataSourceResult(success=False, error="No tiles downloaded")
        
        # 3. 可选：拼接为单张大图
        if kwargs.get("mosaic", False):
            mosaic_path = self._mosaic_tiles(downloaded, bbox, zoom)
            return DataSourceResult(
                success=True,
                data=str(mosaic_path),
                data_type="mosaic",
                cache_path=str(mosaic_path),
                metadata={
                    "tile_count": len(downloaded),
                    "zoom": zoom,
                    "layer": self.layer,
                }
            )
        
        return DataSourceResult(
            success=True,
            data=[str(p) for p in downloaded],
            data_type="tiles",
            metadata={
                "tile_count": len(downloaded),
                "zoom": zoom,
                "layer": self.layer,
            }
        )
    
    def _bbox_to_tiles(self, bbox: BBox, zoom: int) -> List[Tuple[int, int, int]]:
        """将边界框转换为瓦片坐标列表。"""
        import math
        
        def latlon_to_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
            n = 2.0 ** zoom
            x = int((lon + 180.0) / 360.0 * n)
            y = int((1.0 - math.log(math.tan(math.radians(lat)) + 
                     (1 / math.cos(math.radians(lat)))) / math.pi) / 2.0 * n)
            return x, y
        
        min_x, min_y = latlon_to_tile(bbox[1], bbox[0], zoom)
        max_x, max_y = latlon_to_tile(bbox[3], bbox[2], zoom)
        
        tiles = []
        for x in range(min_x, max_x + 1):
            for y in range(min_y, max_y + 1):
                tiles.append((x, y, zoom))
        return tiles
    
    def _get_cached_tile(self, x: int, y: int, z: int) -> Path:
        """获取缓存路径。"""
        return self.cache_dir / self.layer / str(z) / str(x) / f"{y}.png"
    
    def _download_tile(self, x: int, y: int, z: int) -> Path:
        """下载单个瓦片。"""
        import requests
        
        url = self.tile_service.get_tile_url(
            layer=self.layer,
            projection=self.projection,
            x=x, y=y, z=z
        )
        
        tile_path = self._get_cached_tile(x, y, z)
        tile_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 200:
                tile_path.write_bytes(resp.content)
                return tile_path
        except Exception:
            pass
        
        return None
    
    def _mosaic_tiles(self, tiles: List[Path], bbox: BBox, zoom: int) -> Path:
        """拼接瓦片为单张GeoTIFF（使用rasterio/gdal）。"""
        # 实现：使用 rasterio.merge 或 gdal_merge
        # 返回拼接后的本地路径
        ...
    
    def get_metadata(self) -> DataSourceMetadata:
        return DataSourceMetadata(
            name=f"tianditu_{self.layer}",
            driver="tianditu_tile",
            crs=self.crs,
        )
    
    @property
    def supports_bbox_query(self) -> bool:
        return True
```

### 5.3 栅格文件驱动

```python
# drivers/local_raster_driver.py
from pathlib import Path

from .base import DataSourceDriver, DataSourceResult, DataSourceMetadata
from .registry import DriverRegistry


@DriverRegistry.register("local_raster")
class LocalRasterDriver(DataSourceDriver):
    """本地栅格文件驱动 — GeoTIFF/IMG。"""
    
    driver_type = "raster_file"
    
    def __init__(self, config: dict):
        self.path = Path(config["path"])
        self.format = config.get("format", "GeoTIFF")
        self.crs = config.get("crs", "EPSG:4326")
        self.layer_type = config.get("layer_type", "")
    
    def fetch(self, bbox=None, **kwargs) -> DataSourceResult:
        if not self.path.exists():
            return DataSourceResult(
                success=False,
                error=f"File not found: {self.path}"
            )
        
        try:
            from app.modules.gis.schema.ingestion import ingest_raster
            raster = ingest_raster(str(self.path), raster_type=kwargs.get("raster_type"))
            
            return DataSourceResult(
                success=True,
                data=str(self.path),
                data_type="raster",
                metadata={
                    "crs": raster.crs,
                    "resolution": raster.resolution,
                    "path": str(self.path),
                }
            )
        except Exception as e:
            return DataSourceResult(success=False, error=str(e))
    
    def get_metadata(self) -> DataSourceMetadata:
        return DataSourceMetadata(
            name=self.path.stem,
            driver="local_raster",
            crs=self.crs,
        )
    
    @property
    def supports_bbox_query(self) -> bool:
        return False


@DriverRegistry.register("remote_raster")
class RemoteRasterDriver(DataSourceDriver):
    """远程栅格下载驱动 — 返回下载指引。"""
    
    driver_type = "raster_file"
    
    def __init__(self, config: dict):
        self.provider = config["provider"]
        self.resolution = config.get("resolution", "")
        self.download_guide = config.get("download_guide", {})
        self.local_path = Path(config.get("local_path", ""))
        self.layer_type = config.get("layer_type", "")
    
    def fetch(self, bbox=None, **kwargs) -> DataSourceResult:
        # 检查本地是否已有
        if self.local_path.exists():
            return LocalRasterDriver({
                "path": str(self.local_path),
                "layer_type": self.layer_type
            }).fetch(bbox)
        
        return DataSourceResult(
            success=False,
            error=f"Raster not available locally. Provider: {self.provider}",
            metadata={
                "provider": self.provider,
                "resolution": self.resolution,
                "download_guide": self.download_guide,
            }
        )
    
    def get_metadata(self) -> DataSourceMetadata:
        return DataSourceMetadata(
            name=self.provider,
            driver="remote_raster",
            crs="EPSG:4326",
        )
    
    @property
    def supports_bbox_query(self) -> bool:
        return False
```

---

## 六、配置文件 (`sources.yaml`)

```yaml
version: "1.0"

# ── 矢量数据源 ──
sources:
  # 本地现状数据
  jintian_current_landuse:
    driver: file_vector
    path: "data/gis/jintian/current/landuse.geojson"
    format: geojson
    crs: EPSG:4326
    layer_type: landuse_current
    encoding: appendix5

  jintian_planned_landuse:
    driver: file_vector
    path: "data/gis/jintian/planned/landuse.geojson"
    format: geojson
    crs: EPSG:4326
    layer_type: landuse_planned
    encoding: tugui

  # 广东省天地图 - 三区三线 (MapServer REST)
  gd_three_zones:
    driver: tianditu_vector
    service_id: SQSXWPSJ
    protocol: mapserver_rest
    layers:
      - id: 0
        name: 永久基本农田保护
        layer_type: farmland_protection
      - id: 1
        name: 城镇开发边界
        layer_type: urban_dev_boundary
    crs: EPSG:4490

  # 广东省天地图 - 生态红线
  gd_ecological:
    driver: tianditu_vector
    service_id: GDSTBHHX
    protocol: mapserver_rest
    layers:
      - id: 0
        name: 生态保护红线
        layer_type: ecological_protection
    crs: EPSG:4490

  # 广东省天地图 - 地质灾害点
  gd_hazard:
    driver: tianditu_vector
    service_id: DZZHD
    protocol: mapserver_rest
    layers:
      - id: 0
        name: 地质灾害隐患点
        layer_type: geological_hazard_points
    crs: EPSG:4490

  # ── 栅格瓦片数据源 ──
  # 天地图影像底图
  tianditu_img_base:
    driver: tianditu_tile
    layer: img_c
    projection: c
    zoom_range: [1, 18]
    format: png
    crs: EPSG:4326
    layer_type: dom

  # 天地图地形晕渲
  tianditu_terrain:
    driver: tianditu_tile
    layer: ter_c
    projection: c
    zoom_range: [1, 18]
    format: png
    crs: EPSG:4326
    layer_type: terrain_visual

  # 广东省2023年影像
  gd_dom_2023:
    driver: tianditu_tile
    service_id: dom2023
    protocol: wms
    layer: dom2023
    crs: EPSG:4490
    layer_type: dom

  # ── 栅格文件数据源 ──
  dem_alos:
    driver: remote_raster
    source_type: dem
    provider: alos
    resolution: 12.5m
    format: GeoTIFF
    crs: EPSG:4326
    layer_type: dem
    download_guide:
      url: "https://www.eorc.jaxa.jp/ALOS/en/aw3d30/"
      steps: ["注册JAXA账号", "选择区域", "下载GeoTIFF"]
    local_path: "data/gis/jintian/terrain/dem_alos.tif"

  dem_local:
    driver: local_raster
    path: "data/gis/jintian/terrain/dem.tif"
    format: GeoTIFF
    crs: EPSG:4326
    layer_type: dem

  dom_sentinel2:
    driver: remote_raster
    source_type: dom
    provider: sentinel2
    resolution: 10m
    format: GeoTIFF
    crs: EPSG:4326
    layer_type: dom
    download_guide:
      url: "https://scihub.copernicus.eu/"
      steps: ["注册Copernicus账号", "按区域搜索", "下载L2A产品"]
    local_path: "data/gis/jintian/terrain/dom_sentinel2.tif"
```

---

## 七、与现有代码整合

```
现有代码 → 新驱动封装

GDSpecializedService (gd_service.py)
  ├── WFS查询 → TiandituVectorDriver.fetch() [矢量]
  ├── MapServer REST → TiandituVectorDriver.fetch() [矢量]
  └── WMS/WMTS URL生成 → TiandituTileDriver.fetch() [栅格瓦片]

TileService (tiles.py)
  ├── 瓦片URL生成 → TiandituTileDriver._download_tile() [栅格瓦片]
  └── 批量下载能力 → TiandituTileDriver.fetch() [栅格瓦片]

DEMProvider (dem_provider.py)
  ├── 本地DEM发现 → LocalRasterDriver.fetch() [栅格文件]
  └── 下载指引 → RemoteRasterDriver.fetch() [栅格文件]

loader.py
  └── GeoJSON文件加载 → FileVectorDriver.fetch() [矢量]
```

---

## 八、使用示例

```python
from app.modules.gis.data.catalog import DataCatalog

# 加载数据目录
catalog = DataCatalog()

# ── 获取矢量数据 ──
result = catalog.get_source("gd_three_zones").fetch(
    bbox=(115.5, 24.0, 116.5, 25.0),
    layer_type="farmland_protection"
)
# result.data = GeoJSON FeatureCollection dict

# ── 获取栅格瓦片 ──
result = catalog.get_source("tianditu_img_base").fetch(
    bbox=(115.5, 24.0, 116.5, 25.0),
    zoom=16,
    mosaic=True
)
# result.data = "data/cache/tiles/tianditu_img_c/merged_xxx.tif"

# ── 获取本地栅格 ──
result = catalog.get_source("dem_local").fetch()
# result.data = "data/gis/jintian/terrain/dem.tif"

# ── 批量获取村庄数据 ──
bundle = catalog.load_village_data(
    village_name="金田村",
    bbox=(115.5, 24.0, 116.5, 25.0)
)
```

---

## 九、实现优先级

| 优先级 | 内容 | 文件 | 理由 |
|--------|------|------|------|
| **P0** | `DataSourceDriver` ABC + `DataSourceResult` | `drivers/base.py` | 核心骨架 |
| **P0** | `DriverRegistry` | `drivers/registry.py` | 驱动注册 |
| **P0** | `FileVectorDriver` | `drivers/file_vector_driver.py` | 覆盖现有全部本地数据 |
| **P0** | `TiandituVectorDriver` | `drivers/tianditu_vector_driver.py` | 覆盖广东专题服务 |
| **P1** | `DataCatalog` + Pydantic config | `catalog/catalog.py`, `catalog/config.py` | 声明式配置入口 |
| **P1** | `sources.yaml` | `catalog/sources.yaml` | 配置文件 |
| **P1** | `TiandituTileDriver` | `drivers/tianditu_tile_driver.py` | 栅格瓦片能力 |
| **P2** | `LocalRasterDriver` + `RemoteRasterDriver` | `drivers/local_raster_driver.py` | DEM/DOM管理 |
| **P2** | `StorageManager` (cache + index) | `storage/cache.py`, `storage/index.py` | 避免重复下载 |
| **P3** | 脚本去重 | `run_parse_pipeline.py` 等 | 统一使用 `catalog.load_village_data()` |

---

## 十、验证方案

### 单元测试
1. `DriverRegistry` — 注册、获取、列出驱动
2. `FileVectorDriver.fetch()` — 加载GeoJSON返回正确结构
3. `TiandituVectorDriver.fetch()` — mock MapServer REST返回GeoJSON
4. `TiandituTileDriver._bbox_to_tiles()` — bbox→瓦片坐标计算正确
5. `DataCatalog._find_source_by_layer_type()` — 按layer_type查找source

### 集成测试
1. 完整配置加载 → 所有source初始化成功
2. 天地图MapServer REST查询 → 返回真实GeoJSON（需token）
3. 瓦片下载+拼接 → 生成有效GeoTIFF

### 手动验证
```bash
cd backend
python -c "
from app.modules.gis.data.catalog import DataCatalog
catalog = DataCatalog()
print('Sources:', list(catalog._sources.keys()))

# 测试本地矢量
result = catalog.get_source('jintian_current_landuse').fetch()
print('Landuse features:', result.metadata.get('feature_count'))
"
```

---

## 十一、参考

| 库/模式 | 用途 | 本项目应用 |
|---------|------|-----------|
| **Intake** | 声明式数据目录 | YAML配置风格参考 |
| **fsspec** | 文件系统抽象 | 缓存路径管理参考 |
| **HydroMT DataSource** | Pydantic栅格配置 | `RemoteRasterDriver`设计参考 |
| **GeoPandas IO** | 统一矢量读写 | `FileVectorDriver`底层使用 |
| **rasterio** | 栅格读写/拼接 | `TiandituTileDriver._mosaic_tiles()`使用 |
| **DriverRegistry装饰器** | 自动注册模式 | 新驱动零配置发现 |

---

## 相关文件

| 模块 | 路径 |
|------|------|
| 现有瓦片服务 | `backend/app/modules/gis/data/providers/tianditu/tiles.py` |
| 现有广东专题服务 | `backend/app/modules/gis/data/providers/tianditu/gd_service.py` |
| 现有DEM Provider | `backend/app/modules/gis/data/providers/dem_provider.py` |
| 现有加载器 | `backend/app/modules/gis/data/loader.py` |
| 栅格类型定义 | `backend/app/modules/gis/schema/raster_types.py` |
| 注入层 | `backend/app/modules/gis/schema/ingestion.py` |
| 数据获取计划 | `docs/gis/04_DATA_ACQUISITION_PLAN.md` |
