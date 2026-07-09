"""GIS data acquisition tools."""

import json
from typing import Dict, Any, List, Optional
from langchain_core.tools import tool

from app.utils.logger import get_logger

logger = get_logger(__name__)


def _make_result(success: bool, data: Any = None, error: str = "") -> str:
    payload: Dict[str, Any] = {"success": success}
    if data is not None:
        payload["data"] = data
    if error:
        payload["error"] = error
    return json.dumps(payload, ensure_ascii=False)


@tool
def fetch_gis_data(location: str, buffer_km: float = 5.0, max_features: int = 500) -> str:
    """获取 GIS 基础数据（水系、道路、居民点）。
    从天地图 WFS 和 OSM 自动获取指定位置周边的地理数据。

    Args:
        location: 地名或地址（如"金田村"）
        buffer_km: 搜索缓冲区半径（公里），默认5km
        max_features: 最大返回要素数量，默认500
    """
    from app.services.modules.gis.fetcher import get_fetcher

    if not location:
        return _make_result(False, error="缺少 location 参数")

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

    return _make_result(True, data=summary)


@tool
def calculate_gis_coverage(location: str, buffer_km: float = 5.0, max_features: int = 100) -> str:
    """计算 GIS 数据覆盖率和完整性。
    评估指定位置的数据获取情况，支持用户上传数据的合并。

    Args:
        location: 地名或地址
        buffer_km: 搜索缓冲区半径（公里）
        max_features: 最大返回要素数量
    """
    from app.services.modules.gis.coverage import calculate_gis_coverage

    if not location:
        return _make_result(False, error="缺少 location 参数")

    result = calculate_gis_coverage(
        location=location,
        buffer_km=buffer_km,
        max_features=max_features,
    )

    return json.dumps(result, ensure_ascii=False)


@tool
def analyze_accessibility(
    analysis_type: str = "driving_accessibility",
    origin: Optional[list] = None,
    destinations: Optional[list] = None,
    center: Optional[list] = None,
) -> str:
    """可达性分析（驾车/步行/服务覆盖/等时圈/POI覆盖）。
    基于天地图 API 进行真实道路网络计算。

    Args:
        analysis_type: 分析类型 - driving_accessibility, walking_accessibility, service_coverage, poi_coverage, isochrone
        origin: 起点坐标 [lon, lat]
        destinations: 目标点列表 [[lon, lat], ...]
        center: 中心坐标 [lon, lat]
    """
    from app.services.modules.gis.accessibility import run_accessibility_analysis

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
    )

    return json.dumps(result, ensure_ascii=False)


@tool
def search_poi(keyword: str, center: list, radius: int = 1000, page_size: int = 20) -> str:
    """POI 周边搜索（高德优先）。
    搜索指定位置周边的兴趣点（学校、医院、商店等）。

    Args:
        keyword: 搜索关键词（如"学校"、"卫生站"）
        center: 中心坐标 [lon, lat]
        radius: 搜索半径（米），默认1000m
        page_size: 每页结果数，默认20
    """
    from app.services.modules.gis.providers.poi import POIProvider

    if not keyword:
        return _make_result(False, error="缺少 keyword 参数")
    if not center:
        return _make_result(False, error="缺少 center 参数")

    if isinstance(center, list):
        center = tuple(center)

    result = POIProvider.search_poi_nearby(
        keyword=keyword,
        center=center,
        radius=radius,
        page_size=page_size,
    )

    return json.dumps(result, ensure_ascii=False)
