from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from .base import RasterDataset


class DEMInput(RasterDataset):
    elevation_datum: str = "1985国家高程基准"
    grid_size: float = 0.0
    elevation_rmse: float = 0.0
    source: str = ""


class DOMInput(RasterDataset):
    source: str = ""
    acquisition_date: str = ""
    cloud_cover: float = 0.0


class TerrainAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    slope_path: str = ""
    aspect_path: str = ""
    slope_class_path: str = ""
    suitability_path: str = ""
    flood_risk_path: str = ""

    slope_area_pct: Dict[str, float] = Field(default_factory=dict)
    aspect_area_pct: Dict[str, float] = Field(default_factory=dict)
    suitability_area_pct: Dict[str, float] = Field(default_factory=dict)


class SlopeRaster(RasterDataset):
    slope_unit: str = "degree"


class AspectRaster(RasterDataset):
    pass


class SuitabilityRaster(RasterDataset):
    classification: Dict[str, int] = Field(default_factory=dict)


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
    "RasterDataset",
    "DEMInput",
    "DOMInput",
    "SlopeRaster",
    "AspectRaster",
    "SuitabilityRaster",
    "TerrainAnalysisResult",
    "SLOPE_CLASSES",
    "ASPECT_CLASSES",
]