"""GIS 数据契约 — Pydantic v2 模型，统一前后端字段名。

使用 alias_generator=to_camel 自动将 Python snake_case 字段名
转换为 JavaScript camelCase，消除手动映射和 undefined bug。

后端序列化时使用 model_dump(by_alias=True) 输出 camelCase JSON，
前端 TypeScript 接口直接匹配 camelCase 字段名，无需转换。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _GISBase(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class GISAnalysisData(_GISBase):
    """GIS 分析评分数据 — 从 analysis_data 中提取。

    前端 GisResultCard 使用 message.analysisData.overallScore，
    后端输出 JSON 字段名自动为 camelCase。
    """
    overall_score: Optional[float] = None
    suitability_level: Optional[str] = None
    sensitivity_class: Optional[str] = None
    recommendations: Optional[List[str]] = None


class GISLayerConfig(_GISBase):
    """GIS 图层配置 — SSE layers 数组中的每个元素。

    前端 GISLayerConfig 接口期望 layerType (camelCase)，
    后端输出 JSON 字段名自动为 camelCase。
    """
    geojson: Dict[str, Any]
    layer_type: str
    layer_name: str
    color: Optional[str] = None
    style: Optional[Dict[str, Any]] = None


class GISMapOptions(_GISBase):
    """GIS 地图选项 — center 和 zoom。"""
    center: Optional[List[float]] = None
    zoom: Optional[float] = None


class GisResultEvent(_GISBase):
    """GIS 分析结果事件 — SSE gis_result 事件的完整数据结构。

    使用 model_dump(by_alias=True) 序列化后输出:
      dimensionKey, dimensionName, summary, layers, mapOptions, analysisData
    与前端 GisResultMessage TypeScript 接口完全匹配。
    """
    dimension_key: str
    dimension_name: str
    summary: str
    layers: List[GISLayerConfig] = []
    map_options: Optional[GISMapOptions] = None
    analysis_data: Optional[GISAnalysisData] = None


class GisLayerUpdateEvent(_GISBase):
    """GIS 图层增量更新事件 — SSE gis_layer_update。"""
    layer: Optional[int] = None
    dimension_key: str
    dimension_name: str
    layers: List[GISLayerConfig] = []
    map_options: Optional[GISMapOptions] = None
    analysis_data: Optional[GISAnalysisData] = None
