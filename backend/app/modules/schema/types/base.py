"""L0 and L1 type abstractions — vector geometry intermediates + raster base.

Four-morphology structure (v4.1):
  L0  SpatialFeature                 矢量基类: geometry + bsm + ysdm + layer_type + _raw
   ├── L1  PointFeature             点要素: geometry ∈ {Point, MultiPoint}
   ├── L1  LineFeature              线要素: geometry ∈ {LineString, MultiLineString}
   └── L1  PolygonFeature           面要素: geometry ∈ {Polygon, MultiPolygon}

  L0  RasterDataset                  栅格基类: path + crs + bounds + bands + layer_type
   └── L1  栅格语义子类 (DEMInput / DOMInput / ...)  → raster_types.py

  L0  TableDataset                   表格基类: rows + columns + schema  → table_types.py
  L0  Document                       文档基类: text + doc_type + source → document_types.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


# ── L0: 矢量基类 ──


@dataclass
class SpatialFeature:
    """所有空间要素的统一基类 — 从 GeoJSON Feature 解析.

    Shared fields:
      - geometry: GeoJSON 几何对象 (必选, 无默认值)
      - bsm: 标识码 (必选, 流水编号)
      - ysdm: 要素代码 (必选, 10位)
      - layer_type: [v4.1] 所属图层 (嵌入图层身份, 不靠外部 registry 反查)
      - _raw: 原始 properties dict (调试用, 禁止业务使用)
    """

    geometry: Dict[str, Any]      # GeoJSON geometry

    bsm: str = ""                 # 标识码 (必选, 流水编号)
    ysdm: str = ""                # 要素代码 (必选, 10位)
    layer_type: str = ""          # [v4.1] 所属图层

    _raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def geometry_type(self) -> str:
        return self.geometry.get("type", "Unknown")


# ── L1: 几何中间抽象 ──


@dataclass
class PointFeature(SpatialFeature):
    """点要素: geometry ∈ {Point, MultiPoint}.

    L1 中间层在 geometry 上加类型约束，构造时 fail-fast。
    """


@dataclass
class LineFeature(SpatialFeature):
    """线要素: geometry ∈ {LineString, MultiLineString}."""


@dataclass
class PolygonFeature(SpatialFeature):
    """面要素: geometry ∈ {Polygon, MultiPolygon}."""


# ── L0: 栅格基类 ──


@dataclass
class RasterDataset:
    """栅格数据集基类 — 四形态之栅格.

    Shared fields:
      - path: 栅格文件路径
      - crs: 坐标系
      - bounds: 空间范围
      - width/height: 像素尺寸
      - transform: 仿射变换
      - band_count: 波段数
      - dtype: 像素数据类型
      - layer_type: [v4.1] 所属图层
      - _meta: 原始元数据
    """

    path: str = ""
    crs: str = "EPSG:4490"
    bounds: Any = None
    width: int = 0
    height: int = 0
    transform: Any = None
    band_count: int = 1
    dtype: str = "Float32"
    layer_type: str = ""
    _meta: Dict[str, Any] = field(default_factory=dict, repr=False)


__all__ = [
    "SpatialFeature",
    "PointFeature",
    "LineFeature",
    "PolygonFeature",
    "RasterDataset",
]