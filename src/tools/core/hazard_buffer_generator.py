"""
Hazard Buffer Generator Tool

生成地质灾害缓冲区，用于避灾约束分析。

功能：
- 根据地质灾害点生成缓冲区
- 计算受影响面积
- 识别安全区（规划可用区域）
- 支持不同灾害类型的缓冲距离设置

输入：
- hazard_points: 地质灾害点 GeoJSON (geological_hazard_points.geojson)

输出：
- buffer_zones: 缓冲区范围 GeoJSON
- affected_area_km2: 受影响面积
- safe_zones: 安全区 GeoJSON
- hazard_summary: 灾害类型汇总
"""

from typing import Dict, Any, List, Optional, Tuple
from ...utils.logger import get_logger

logger = get_logger(__name__)

# Check geopandas availability
try:
    import geopandas as gpd
    from shapely.geometry import shape, mapping, Polygon, MultiPolygon
    from shapely.ops import unary_union
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    logger.warning("[hazard_buffer_generator] geopandas/shapely not available")


# 默认灾害类型缓冲距离（米）
DEFAULT_HAZARD_BUFFERS = {
    "滑坡": 200,
    "崩塌": 150,
    "泥石流": 300,
    "地面塌陷": 100,
    "地裂缝": 50,
    "地面沉降": 50,
    "unknown": 200,
}


def generate_hazard_buffers(
    hazard_points: Dict[str, Any],
    buffer_meters: Optional[int] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    生成地质灾害缓冲区。

    Args:
        hazard_points: 地质灾害点 GeoJSON FeatureCollection
        buffer_meters: 默认缓冲距离（米），None 则根据灾害类型自动设置
        **kwargs: 其他参数
            - hazard_type_field: 灾害类型字段名
            - custom_buffers: 自定义缓冲距离 {类型: 米}
            - dissolve: 是否合并重叠缓冲区
            - study_area: 研究区域边界（用于计算安全区）
            - exclude_types: 排除的灾害类型列表

    Returns:
        Dict with:
        - success: bool
        - data: 缓冲区生成结果
    """
    if not GEOPANDAS_AVAILABLE:
        return {
            "success": False,
            "error": "hazard_buffer_generator requires geopandas. Install: pip install geopandas shapely"
        }

    if not hazard_points.get("features"):
        return {
            "success": False,
            "error": "hazard_points must contain features"
        }

    try:
        from .spatial_analysis import (
            geojson_to_geodataframe,
            geodataframe_to_geojson,
            calculate_buffer_zones,
            run_spatial_overlay,
        )

        # 转换为 GeoDataFrame
        gdf_hazard = geojson_to_geodataframe(hazard_points)
        if gdf_hazard is None:
            return {"success": False, "error": "Failed to convert hazard_points"}

        # 参数处理
        hazard_type_field = kwargs.get("hazard_type_field", "灾害类型")
        custom_buffers = kwargs.get("custom_buffers", {})
        dissolve = kwargs.get("dissolve", True)
        study_area = kwargs.get("study_area")
        exclude_types = kwargs.get("exclude_types", [])

        # 尝试找到灾害类型字段
        possible_fields = ["灾害类型", "hazard_type", "type", "类型", "灾害类别", "隐患类型"]
        actual_field = None
        for field in possible_fields:
            if field in gdf_hazard.columns:
                actual_field = field
                break

        if actual_field is None:
            logger.info("[hazard_buffer] 使用默认缓冲距离，未找到灾害类型字段")
            actual_field = "hazard_type"
            gdf_hazard["hazard_type"] = "unknown"

        logger.info(f"[hazard_buffer] 使用灾害类型字段: {actual_field}")

        # 过滤排除的灾害类型
        if exclude_types:
            gdf_hazard = gdf_hazard[~gdf_hazard[actual_field].isin(exclude_types)]

        if len(gdf_hazard) == 0:
            return {
                "success": True,
                "data": {
                    "buffer_zones": None,
                    "affected_area_km2": 0,
                    "hazard_count": 0,
                    "message": "无有效灾害点数据",
                }
            }

        # 按灾害类型分组生成缓冲区
        buffer_results = []
        hazard_summary = {}

        hazard_types = gdf_hazard[actual_field].unique()
        for hazard_type in hazard_types:
            # 获取该类型的灾害点
            type_gdf = gdf_hazard[gdf_hazard[actual_field] == hazard_type]

            # 确定缓冲距离
            if buffer_meters is not None:
                buffer_dist = buffer_meters
            else:
                buffer_dist = custom_buffers.get(hazard_type, DEFAULT_HAZARD_BUFFERS.get(hazard_type, 200))

            logger.info(f"[hazard_buffer] 类型 {hazard_type}: {len(type_gdf)} 点, 缓冲 {buffer_dist}m")

            # 生成缓冲区
            type_geojson = geodataframe_to_geojson(type_gdf)
            buffer_result = calculate_buffer_zones(
                layer=type_geojson,
                buffer_distance=buffer_dist,
                dissolve=dissolve,
            )

            if buffer_result.get("success"):
                buffer_data = buffer_result.get("data", {})
                buffer_results.append({
                    "hazard_type": hazard_type,
                    "buffer_geojson": buffer_data.get("geojson"),
                    "buffer_distance_m": buffer_dist,
                    "feature_count": buffer_data.get("feature_count", 0),
                    "area_km2": buffer_data.get("total_area_km2", 0),
                })

                hazard_summary[hazard_type] = {
                    "point_count": len(type_gdf),
                    "buffer_distance_m": buffer_dist,
                    "buffer_area_km2": buffer_data.get("total_area_km2", 0),
                }

        # 合并所有缓冲区
        total_buffer_geojson = None
        total_affected_area = 0

        if buffer_results:
            # 合并缓冲区几何
            all_buffer_geoms = []
            for br in buffer_results:
                if br.get("buffer_geojson"):
                    br_gdf = geojson_to_geodataframe(br["buffer_geojson"])
                    if br_gdf is not None:
                        all_buffer_geoms.extend(br_gdf.geometry.tolist())

            if all_buffer_geoms:
                merged_geom = unary_union(all_buffer_geoms)

                # 创建合并后的 GeoJSON
                if merged_geom.geom_type == "Polygon":
                    merged_features = [{
                        "type": "Feature",
                        "geometry": mapping(merged_geom),
                        "properties": {
                            "layerType": "sensitivity_zone",
                            "layerName": "地质灾害缓冲区",
                            "hazard_types": list(hazard_summary.keys()),
                        }
                    }]
                elif merged_geom.geom_type == "MultiPolygon":
                    merged_features = [{
                        "type": "Feature",
                        "geometry": mapping(merged_geom),
                        "properties": {
                            "layerType": "sensitivity_zone",
                            "layerName": "地质灾害缓冲区",
                            "hazard_types": list(hazard_summary.keys()),
                        }
                    }]
                else:
                    merged_features = []

                total_buffer_geojson = {
                    "type": "FeatureCollection",
                    "features": merged_features,
                }

                # 计算总面积
                try:
                    merged_gdf = gpd.GeoDataFrame(
                        {"geometry": [merged_geom]},
                        crs="EPSG:4326"
                    )
                    merged_proj = merged_gdf.to_crs(epsg=3857)
                    total_affected_area = merged_proj.geometry.area.sum() / 1_000_000
                except Exception:
                    total_affected_area = sum(br.get("area_km2", 0) for br in buffer_results)

        # 计算安全区（如果提供了研究区域）
        safe_zones = None
        safe_area_km2 = 0

        if study_area and study_area.get("features") and total_buffer_geojson:
            safe_result = run_spatial_overlay(
                operation="difference",
                layer_a=study_area,
                layer_b=total_buffer_geojson,
            )

            if safe_result.get("success"):
                safe_zones = safe_result.get("data", {}).get("geojson")
                safe_area_km2 = safe_result.get("data", {}).get("total_area_km2", 0)

        return {
            "success": True,
            "data": {
                "buffer_zones": total_buffer_geojson,
                "affected_area_km2": round(total_affected_area, 4),
                "safe_zones": safe_zones,
                "safe_area_km2": round(safe_area_km2, 4),
                "hazard_summary": hazard_summary,
                "hazard_count": len(gdf_hazard),
                "buffer_details": buffer_results,
                "buffer_parameters": {
                    "default_buffer_m": buffer_meters,
                    "custom_buffers": custom_buffers,
                    "dissolve": dissolve,
                },
                "metadata": {
                    "field_used": actual_field,
                    "excluded_types": exclude_types,
                }
            }
        }

    except Exception as e:
        logger.error(f"[hazard_buffer] Buffer generation failed: {e}")
        return {"success": False, "error": f"Hazard buffer generation failed: {str(e)}"}


def get_hazard_risk_level(
    hazard_points: Dict[str, Any],
    location: Tuple[float, float],
    buffer_meters: int = 200,
) -> Dict[str, Any]:
    """
    评估特定位置的灾害风险等级。

    Args:
        hazard_points: 地质灾害点 GeoJSON
        location: 待评估位置坐标 (lon, lat)
        buffer_meters: 评估缓冲距离

    Returns:
        Dict with risk level and nearest hazards
    """
    from .spatial_analysis import run_spatial_query
    from shapely.geometry import Point

    try:
        # 创建查询几何
        query_geom = {"type": "Point", "coordinates": list(location)}

        # 查询附近的灾害点
        result = run_spatial_query(
            query_type="nearest",
            geometry=query_geom,
            target_layer=hazard_points,
            max_distance=buffer_meters * 10,  # 扩大搜索范围
            limit=10,
        )

        if result.get("success"):
            match_count = result.get("data", {}).get("match_count", 0)
            nearby_geojson = result.get("data", {}).get("geojson")

            # 计算距离和风险等级
            risk_level = "low"
            if match_count > 0:
                # 计算最近距离
                try:
                    point = Point(location)
                    nearby_gdf = geojson_to_geodataframe(nearby_geojson)
                    if nearby_gdf is not None:
                        min_distance = nearby_gdf.geometry.distance(point).min()
                        min_distance_m = min_distance * 111000  # 近似转换

                        if min_distance_m <= buffer_meters:
                            risk_level = "high"
                        elif min_distance_m <= buffer_meters * 2:
                            risk_level = "medium"
                        else:
                            risk_level = "low"
                except Exception:
                    risk_level = "medium" if match_count > 3 else "low"

            return {
                "success": True,
                "data": {
                    "location": location,
                    "risk_level": risk_level,
                    "nearby_hazard_count": match_count,
                    "buffer_meters": buffer_meters,
                    "nearby_hazards": nearby_geojson,
                }
            }

        return {"success": False, "error": result.get("error")}

    except Exception as e:
        return {"success": False, "error": str(e)}


def generate_hazard_avoidance_zones(
    hazard_points: Dict[str, Any],
    study_area: Dict[str, Any],
    buffer_meters: int = 200,
) -> Dict[str, Any]:
    """
    生成灾害避让区域（可用于规划约束）。

    Args:
        hazard_points: 地质灾害点 GeoJSON
        study_area: 研究区域边界 GeoJSON
        buffer_meters: 避让距离

    Returns:
        Dict with avoidance zones and recommendation
    """
    return generate_hazard_buffers(
        hazard_points=hazard_points,
        buffer_meters=buffer_meters,
        study_area=study_area,
        dissolve=True,
    )


__all__ = [
    "generate_hazard_buffers",
    "get_hazard_risk_level",
    "generate_hazard_avoidance_zones",
    "DEFAULT_HAZARD_BUFFERS",
]