"""DEM 栅格数据 Provider — 从公开数据源获取数字高程模型。

数据源优先级:
  1. 地理空间数据云 (gscloud.cn) — GDEMV3 30M / ASTER GDEM V3 (免费)
  2. ALOS World 3D (JAXA) — 12.5m (免费, 科研)
  3. 天地图关联的全国地理信息资源目录服务系统 (mulu.gov.cn) — 需审批
  4. 地方1:10000 DEM — 需申请
  5. 无人机航测 — 自备

注意: 天地图 WMTS 瓦片服务仅提供地形晕渲 (ter_c)，不是原始高程数据。
DEM GeoTIFF 需从地理空间数据云等渠道获取。

参照: docs/gis/OUTPUT_ARCHITECTURE.md §1.2.1
      《实用性村庄规划编制手册》(李巍等) 第2章 §2.1.3
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.modules.schema.types.raster_types import RasterInput, DEMInput, DOMInput
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ============================================================
# DEM 数据源配置
# ============================================================

DEM_SOURCES = {
    "srtm": {
        "name": "SRTM 1-arc-sec",
        "resolution": 30.0,
        "source_url": "https://earthexplorer.usgs.gov/",
        "format": "GeoTIFF",
        "cost": "free",
        "note": "USGS EarthExplorer, 30m global",
    },
    "gdem_v3": {
        "name": "ASTER GDEM V3",
        "resolution": 30.0,
        "source_url": "https://search.earthdata.nasa.gov/",
        "format": "GeoTIFF",
        "cost": "free",
        "note": "地理空间数据云 gscloud.cn 可下载",
    },
    "alos_aw3d30": {
        "name": "ALOS World 3D",
        "resolution": 12.5,
        "source_url": "https://www.eorc.jaxa.jp/ALOS/en/aw3d30/",
        "format": "GeoTIFF",
        "cost": "free(research)",
        "note": "JAXA, 12.5m global",
    },
    "tianditu_catalog": {
        "name": "全国地理信息资源目录服务系统",
        "resolution": 5.0,
        "source_url": "https://mulu.gov.cn/",
        "format": "GeoTIFF",
        "cost": "approval",
        "note": "1:10000 DEM, 需审批",
    },
    "local_survey": {
        "name": "地方1:10000 DEM",
        "resolution": 5.0,
        "source_url": "",
        "format": "GeoTIFF/IMG",
        "cost": "apply",
        "note": "省测绘院, 需申请",
    },
    "uav_photogrammetry": {
        "name": "无人机航测",
        "resolution": 0.5,
        "source_url": "",
        "format": "GeoTIFF",
        "cost": "equipment+labor",
        "note": "自主航飞, 最高精度",
    },
}


# ============================================================
# DEM Provider
# ============================================================


class DEMProvider:
    """DEM 栅格数据提供者 — 管理本地 DEM 文件的发现和加载。

    与 GISProvider (矢量基类) 不同, DEM 不走 API 拉取,
    而是从本地文件加载或提示用户从公开数据源下载。

    使用方式:
      1. 确认本地 DEM 文件: provider.find_dem(data_dir)
      2. 加载元数据: provider.load_dem(filepath)
      3. 检查下载指引: provider.get_download_guide()
    """

    def __init__(self, data_dir: Optional[str] = None):
        """初始化 DEM Provider.

        Args:
            data_dir: GIS 数据根目录, 默认 data/gis/jintian/
        """
        self.data_dir = Path(data_dir) if data_dir else None

    def find_dem(self, data_dir: Optional[str] = None) -> Optional[str]:
        """在数据目录中查找 DEM 文件.

        搜索路径: {data_dir}/terrain/dem.tif
                   {data_dir}/terrain/dem.tiff
                   {data_dir}/current/terrain/dem.tif

        Args:
            data_dir: 覆盖初始化时的 data_dir

        Returns:
            找到的 DEM 文件路径, 或 None
        """
        base = Path(data_dir) if data_dir else self.data_dir
        if not base:
            return None

        candidates = [
            base / "terrain" / "dem.tif",
            base / "terrain" / "dem.tiff",
            base / "current" / "terrain" / "dem.tif",
            base / "current" / "terrain" / "dem.tiff",
        ]

        for path in candidates:
            if path.exists():
                logger.info("[DEMProvider] Found DEM: %s", path)
                return str(path)

        logger.info("[DEMProvider] No DEM file found in %s", base)
        return None

    def find_dom(self, data_dir: Optional[str] = None) -> Optional[str]:
        """在数据目录中查找 DOM 文件.

        Args:
            data_dir: 覆盖初始化时的 data_dir

        Returns:
            找到的 DOM 文件路径, 或 None
        """
        base = Path(data_dir) if data_dir else self.data_dir
        if not base:
            return None

        candidates = [
            base / "terrain" / "dom.tif",
            base / "terrain" / "dom.tiff",
            base / "current" / "terrain" / "dom.tif",
        ]

        for path in candidates:
            if path.exists():
                logger.info("[DEMProvider] Found DOM: %s", path)
                return str(path)

        return None

    def load_dem(self, filepath: str) -> DEMInput:
        """加载 DEM 元数据 (不加载栅格数据本身).

        Args:
            filepath: GeoTIFF DEM 文件路径

        Returns:
            DEMInput 对象, 包含元信息
        """
        from app.modules.data import ingest_raster
        return ingest_raster(filepath, raster_type="dem")

    def load_dom(self, filepath: str) -> DOMInput:
        """加载 DOM 元数据.

        Args:
            filepath: GeoTIFF DOM 文件路径

        Returns:
            DOMInput 对象, 包含元信息
        """
        from app.modules.data import ingest_raster
        return ingest_raster(filepath, raster_type="dom")

    def get_download_guide(self) -> dict:
        """返回 DEM 下载指引.

        Returns:
            包含各数据源信息和步骤的字典
        """
        return {
            "title": "DEM 数据获取指引",
            "sources": DEM_SOURCES,
            "recommended": "gdem_v3",
            "steps": [
                "1. 访问地理空间数据云 https://www.gscloud.cn/",
                "2. 注册并登录账号",
                "3. 点击高级检索, 选择数据集 GDEMV3 30M",
                "4. 按行政区选择规划村庄所在区域",
                "5. 下载 GeoTIFF 格式 DEM 数据",
                "6. 将文件放置到 data/gis/jintian/terrain/dem.tif",
            ],
            "placement": "data/gis/jintian/terrain/dem.tif",
        }

    def is_available(self, data_dir: Optional[str] = None) -> bool:
        """检查 DEM 数据是否可用."""
        return self.find_dem(data_dir) is not None


__all__ = ["DEMProvider", "DEM_SOURCES"]
