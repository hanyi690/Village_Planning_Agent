"""
Coverage Calculator - GIS 覆盖率计算（从 wrapper 分离）

提供 GIS 数据覆盖率计算功能，支持用户上传数据和自动获取数据的合并。
"""

from typing import Dict, Any, Optional
import json

from .fetcher import get_fetcher
from app.utils.logger import get_logger

logger = get_logger(__name__)


def calculate_gis_coverage(
    location: str,
    buffer_km: float = 5.0,
    user_uploaded_data: Optional[Dict[str, Any]] = None,
    max_features: int = 100
) -> Dict[str, Any]:
    """
    计算 GIS 数据覆盖率

    数据获取优先级：用户上传 > 会话缓存 > 自动获取（天地图 WFS）

    Args:
        location: 村庄名称/位置
        buffer_km: 缓冲区半径（公里）
        user_uploaded_data: 用户上传数据字典 {"boundary": geojson, "water": geojson, ...}
        max_features: 最大特征数

    Returns:
        Dict[str, Any]: 覆盖率计算结果
    """
    fetcher = get_fetcher()

    if not location:
        return {"success": False, "error": "缺少 location 参数"}

    # 数据来源追踪
    data_sources = {}

    # 从 user_uploaded_data 获取用户上传数据
    user_uploaded_data = user_uploaded_data or {}
    user_boundary_geojson = user_uploaded_data.get("boundary")
    user_water_geojson = user_uploaded_data.get("water")
    user_road_geojson = user_uploaded_data.get("road")
    user_residential_geojson = user_uploaded_data.get("residential")

    # 如果有用户数据，记录日志
    if user_boundary_geojson or user_water_geojson or user_road_geojson or user_residential_geojson:
        logger.info(f"[CoverageCalculator] 使用用户上传数据: {location}")

    # 自动获取数据（补充缺失类型）
    auto_result = fetcher.fetch_all_gis_data(location, buffer_km, max_features=max_features)

    # 合并数据源：用户数据覆盖自动获取数据
    def get_geojson_with_source(data_type: str, user_data: Optional[Dict], auto_data: Optional[Dict]) -> tuple:
        """获取 GeoJSON 数据并标记来源"""
        if user_data:
            return user_data, "user_upload"
        if auto_data and auto_data.get("success") and auto_data.get("geojson"):
            return auto_data.get("geojson"), "auto_fetch"
        return None, "missing"

    boundary_geojson, boundary_source = get_geojson_with_source("boundary", user_boundary_geojson, auto_result.get("boundary"))
    water_geojson, water_source = get_geojson_with_source("water", user_water_geojson, auto_result.get("water"))
    road_geojson, road_source = get_geojson_with_source("road", user_road_geojson, auto_result.get("road"))
    residential_geojson, residential_source = get_geojson_with_source("residential", user_residential_geojson, auto_result.get("residential"))

    data_sources = {
        "boundary": boundary_source,
        "water": water_source,
        "road": road_source,
        "residential": residential_source,
    }

    # 统计可用数据和特征数
    water_success = water_geojson is not None
    road_success = road_geojson is not None
    residential_success = residential_geojson is not None
    boundary_success = boundary_geojson is not None

    water_count = len(water_geojson.get("features", [])) if water_geojson else 0
    road_count = len(road_geojson.get("features", [])) if road_geojson else 0
    residential_count = len(residential_geojson.get("features", [])) if residential_geojson else 0

    coverage_rate = sum([water_success, road_success, residential_success]) / 3

    # 构建图层列表
    layers = []
    type_mapping = {
        "boundary": {"layerType": "boundary", "layerName": "行政边界", "color": "#333333"},
        "water": {"layerType": "sensitivity_zone", "layerName": "水系", "color": "#87CEEB"},
        "road": {"layerType": "development_axis", "layerName": "道路", "color": "#FF6B6B"},
        "residential": {"layerType": "function_zone", "layerName": "居民地", "color": "#FFD700"},
    }

    # 添加边界层
    if boundary_success and boundary_geojson and boundary_geojson.get("features"):
        layers.append({
            "geojson": boundary_geojson,
            "layerType": "boundary",
            "layerName": "行政边界",
            "color": "#333333",
            "source": boundary_source,
        })

    # 添加其他图层
    for category, mapping in type_mapping.items():
        if category == "boundary":
            continue

        geojson = None
        source = data_sources.get(category, "missing")

        if category == "water":
            geojson = water_geojson
        elif category == "road":
            geojson = road_geojson
        elif category == "residential":
            geojson = residential_geojson

        if geojson and geojson.get("features"):
            layers.append({
                "geojson": geojson,
                "layerType": mapping["layerType"],
                "layerName": mapping["layerName"],
                "color": mapping["color"],
                "source": source,
            })

    return {
        "success": True,
        "data": {
            "location": location,
            "coverage_rate": coverage_rate,
            "layers_available": {
                "water": water_success,
                "road": road_success,
                "residential": residential_success,
                "boundary": boundary_success,
            },
            "feature_counts": {
                "water": water_count,
                "road": road_count,
                "residential": residential_count,
            },
            "center": auto_result.get("center"),
            "layers": layers,
            "data_sources": data_sources,
        }
    }


def format_coverage_result(result: Dict[str, Any]) -> str:
    """格式化覆盖率计算结果"""
    if not result.get("success"):
        return f"覆盖率计算失败: {result.get('error', '未知错误')}"

    data = result.get("data", {})
    lines = ["GIS 数据覆盖率："]
    lines.append(f"- 位置: {data.get('location')}")
    lines.append(f"- 覆盖率: {data.get('coverage_rate', 0):.2%}")

    layers = data.get("layers_available", {})
    lines.append("- 图层可用性:")
    for layer, available in layers.items():
        status = "✓" if available else "✗"
        lines.append(f"  * {layer}: {status}")

    data_sources = data.get("data_sources", {})
    lines.append("- 数据来源:")
    for layer, source in data_sources.items():
        lines.append(f"  * {layer}: {source}")

    return "\n".join(lines)


__all__ = ['calculate_gis_coverage', 'format_coverage_result']