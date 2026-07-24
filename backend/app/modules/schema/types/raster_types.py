"""栅格输入层类型定义 — DEM/DOM 辅助分析数据。

不进入 GDB 汇交成果，仅用于地形分析。
分析结果以属性形式体现在矢量输出图层中。

参照: docs/gis/OUTPUT_ARCHITECTURE.md §1.2.1
      《实用性村庄规划编制手册》(李巍等) 第2章 §2.1.3/§2.5
      CH/T 9008.2-2010 数字高程模型标准
      广东省村庄规划编制基本技术指南(试行)(2019)

类型分组:
  RasterInput        — 栅格数据基类 (DEM/DOM 共享)
  DEMInput           — 数字高程模型
  DOMInput           — 数字正射影像图
  TerrainAnalysisResult — 地形分析结果容器

与 SpatialFeature (矢量基类) 平行，但不继承。
栅格数据没有 geometry dict，而是有栅格路径和元数据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


# ============================================================
# 栅格数据基类
# ============================================================


@dataclass
class RasterInput:
    """栅格输入基类 — 所有栅格数据的共享属性。

    与 SpatialFeature (矢量基类) 平行，但不继承。
    栅格数据没有 geometry dict，而是有栅格路径和元数据。
    """

    path: str = ""                        # GeoTIFF 文件路径
    crs: str = "EPSG:4490"                # 坐标系 (CGCS2000 地理坐标系)
    resolution: float = 0.0               # 空间分辨率 (米/像素)
    nodata: Optional[float] = None        # NoData 值
    elevation_datum: str = ""              # 高程基准 (1985国家高程基准)
    _meta: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def filename(self) -> str:
        return Path(self.path).name if self.path else ""

    @property
    def exists(self) -> bool:
        return Path(self.path).exists() if self.path else False


# ============================================================
# DEM — 数字高程模型
# ============================================================


@dataclass
class DEMInput(RasterInput):
    """数字高程模型 (DEM) — 地形分析基础数据。

    规范依据:
      广东省技术指南: 比例尺不低于1:2000地形图
      CH/T 9008.2-2010: 1:2000 DEM格网1m*1m, 高程中误差<=0.30m(山地)
    数据源:
      GDEMV3 30M / ALOS 12.5m / 天地图DEM / 地方1:10000 / 无人机航测
    用途:
      坡度/坡向/汇水/建设适宜性/洪涝风险 (6种派生分析)
    """

    elevation_datum: str = "1985国家高程基准"  # 高程基准
    grid_size: float = 0.0                     # 格网尺寸 (米, 如 1.0/5.0/30.0)
    elevation_rmse: float = 0.0                # 高程中误差 (米)
    source: str = ""                           # 数据源 (GDEMV3/ALOS/天地图/地方/无人机)


# ============================================================
# DOM — 数字正射影像图
# ============================================================


@dataclass
class DOMInput(RasterInput):
    """数字正射影像图 (DOM) — 现状判读基础数据。

    规范依据:
      广东省技术指南: 国土数字正射影像图
    数据源:
      Landsat 8 / Sentinel-2 / 天地图影像 / 高分辨率卫星
    用途:
      现状判读/房屋轮廓提取/地类识别
    """

    source: str = ""                 # 数据源 (Landsat8/Sentinel2/天地图/高分)
    acquisition_date: str = ""       # 获取日期 (YYYY-MM-DD)
    cloud_cover: float = 0.0         # 云量百分比


# ============================================================
# 地形分析结果
# ============================================================


@dataclass
class TerrainAnalysisResult:
    """地形分析结果 -- DEM 派生数据的统一容器。

    由 TerrainAnalyzer 产出，不持久化为独立文件，
    而是写入矢量要素属性或用于规划决策。
    """

    slope_path: str = ""             # 坡度栅格路径 (度, 0-90)
    aspect_path: str = ""            # 坡向栅格路径 (度, 0-360)
    slope_class_path: str = ""       # 坡度分级栅格路径 (1-4级)
    suitability_path: str = ""       # 建设适宜性栅格路径
    flood_risk_path: str = ""        # 洪涝淹没范围路径

    # 坡度分级面积占比 (%)
    slope_area_pct: Dict[str, float] = field(default_factory=dict)
    # {"0-6": 25.3, "6-15": 40.1, "15-25": 28.5, ">25": 6.1}

    # 坡向面积占比 (%)
    aspect_area_pct: Dict[str, float] = field(default_factory=dict)
    # {"N": 12.5, "NE": 10.2, "E": 15.3, ...}

    # 建设适宜性面积占比 (%)
    suitability_area_pct: Dict[str, float] = field(default_factory=dict)
    # {"suitable": 30.0, "moderate": 35.0, "marginal": 25.0, "unsuitable": 10.0}


# ============================================================
# 坡度分级常量
# ============================================================

SLOPE_CLASSES = {
    "0-6": {"code": 1, "label": "平缓", "construction": "适宜"},
    "6-15": {"code": 2, "label": "缓坡", "construction": "较适宜"},
    "15-25": {"code": 3, "label": "中坡", "construction": "限制建设"},
    ">25": {"code": 4, "label": "陡坡", "construction": "禁止建设"},
}

ASPECT_CLASSES = {
    "N": {"code": 1, "label": "北坡", "residence": "不适宜"},
    "NE": {"code": 2, "label": "东北坡", "residence": "较不适宜"},
    "E": {"code": 3, "label": "东坡", "residence": "一般"},
    "SE": {"code": 4, "label": "东南坡", "residence": "较适宜"},
    "S": {"code": 5, "label": "南坡", "residence": "最适宜"},
    "SW": {"code": 6, "label": "西南坡", "residence": "较适宜"},
    "W": {"code": 7, "label": "西坡", "residence": "一般"},
    "NW": {"code": 8, "label": "西北坡", "residence": "较不适宜"},
}


__all__ = [
    "RasterInput",
    "DEMInput",
    "DOMInput",
    "TerrainAnalysisResult",
    "SLOPE_CLASSES",
    "ASPECT_CLASSES",
]
