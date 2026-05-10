"""
GIS 工具包装器

将 services/modules/gis/ 中的实际实现包装为 ToolRegistry 可调用的函数。
每个包装器接受 context: Dict[str, Any] 返回 str。
"""
import json
from typing import Dict, Any

from app.services.modules.gis.fetcher import get_fetcher
from app.services.modules.gis.coverage import calculate_gis_coverage
from app.services.modules.gis.accessibility import run_accessibility_analysis
from app.services.modules.gis.providers.poi import POIProvider
from app.utils.logger import get_logger

logger = get_logger(__name__)


def gis_data_fetch_wrapper(context: Dict[str, Any]) -> str:
    """GIS 数据获取工具

    从 context 中提取 location, buffer_km, max_features 参数，
    调用 GISDataFetcher.fetch_all_gis_data() 获取水系、道路、居民地等数据。
    """
    location = context.get("location", "")
    buffer_km = context.get("buffer_km", 5.0)
    max_features = context.get("max_features", 500)

    if not location:
        return json.dumps({"success": False, "error": "缺少 location 参数"}, ensure_ascii=False)

    fetcher = get_fetcher()
    result = fetcher.fetch_all_gis_data(location, buffer_km, max_features)

    summary = {
        "location": result.get("location"),
        "is_village_level": result.get("is_village_level", False),
        "layers": {},
    }
    for layer_key in ("water", "road", "residential"):
        layer_data = result.get(layer_key, {})
        if layer_data.get("success") and layer_data.get("geojson"):
            feature_count = len(layer_data["geojson"].get("features", []))
            summary["layers"][layer_key] = feature_count
        else:
            summary["layers"][layer_key] = 0

    return json.dumps({"success": True, "data": summary}, ensure_ascii=False)


def gis_coverage_calculator_wrapper(context: Dict[str, Any]) -> str:
    """GIS 数据覆盖率计算工具

    从 context 中提取 location, buffer_km 等参数，
    调用 calculate_gis_coverage() 计算数据覆盖率和完整性。
    """
    location = context.get("location", "")
    buffer_km = context.get("buffer_km", 5.0)
    user_uploaded_data = context.get("user_uploaded_data")
    max_features = context.get("max_features", 100)

    if not location:
        return json.dumps({"success": False, "error": "缺少 location 参数"}, ensure_ascii=False)

    result = calculate_gis_coverage(
        location=location,
        buffer_km=buffer_km,
        user_uploaded_data=user_uploaded_data,
        max_features=max_features,
    )

    return json.dumps(result, ensure_ascii=False)


def accessibility_analysis_wrapper(context: Dict[str, Any]) -> str:
    """可达性分析工具

    从 context 中提取 analysis_type, origin, destinations, center 等参数，
    调用 run_accessibility_analysis() 执行可达性分析。
    """
    analysis_type = context.get("analysis_type", "driving_accessibility")
    origin = context.get("origin")
    destinations = context.get("destinations")
    center = context.get("center")

    if origin and isinstance(origin, list):
        origin = tuple(origin)
    if center and isinstance(center, list):
        center = tuple(center)
    if destinations and isinstance(destinations, list):
        destinations = [tuple(d) if isinstance(d, list) else d for d in destinations]

    result = run_accessibility_analysis(
        analysis_type=analysis_type,
        origin=origin,
        destinations=destinations,
        center=center,
        **{k: v for k, v in context.items() if k not in ("analysis_type", "origin", "destinations", "center")}
    )

    return json.dumps(result, ensure_ascii=False)


def poi_search_wrapper(context: Dict[str, Any]) -> str:
    """POI 搜索工具

    从 context 中提取 keyword, center, radius 等参数，
    调用 POIProvider 进行高德优先的 POI 搜索。
    """
    keyword = context.get("keyword", "")
    center = context.get("center")
    radius = context.get("radius", 1000)
    page_size = context.get("page_size", 20)

    if not keyword:
        return json.dumps({"success": False, "error": "缺少 keyword 参数"}, ensure_ascii=False)
    if not center:
        return json.dumps({"success": False, "error": "缺少 center 参数"}, ensure_ascii=False)

    if isinstance(center, list):
        center = tuple(center)

    result = POIProvider.search_poi_nearby(
        keyword=keyword,
        center=center,
        radius=radius,
        page_size=page_size,
    )

    return json.dumps(result, ensure_ascii=False)


# 工具名称到包装函数的映射
GIS_TOOL_WRAPPERS: Dict[str, Any] = {
    "gis_data_fetch": gis_data_fetch_wrapper,
    "gis_coverage_calculator": gis_coverage_calculator_wrapper,
    "accessibility_analysis": accessibility_analysis_wrapper,
    "poi_search": poi_search_wrapper,
}
