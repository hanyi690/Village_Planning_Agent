"""
Landuse Change Analysis Tool

分析现状用地与规划用地之间的变化。

功能：
- 统计各用地类型的变化量
- 计算面积变化
- 生成变化热力图
- 识别新增和减少的用地区域

输入：
- landuse_current.geojson: 现状用地数据
- landuse_planned.geojson: 规划用地数据

输出：
- change_statistics: 各类用地变化统计
- change_heatmap: 变化热力图 GeoJSON
- increase_areas: 新增用地
- decrease_areas: 减少用地
"""

from typing import Dict, Any, List, Optional, Literal
from ...utils.logger import get_logger

logger = get_logger(__name__)

# Check geopandas availability
try:
    import geopandas as gpd
    from shapely.geometry import shape, mapping
    from shapely.ops import unary_union
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    logger.warning("[landuse_change_analysis] geopandas/shapely not available")


def analyze_landuse_change(
    current_landuse: Dict[str, Any],
    planned_landuse: Dict[str, Any],
    change_threshold: float = 0.1,
    **kwargs
) -> Dict[str, Any]:
    """
    分析现状用地与规划用地之间的变化。

    Args:
        current_landuse: 现状用地 GeoJSON FeatureCollection
        planned_landuse: 规划用地 GeoJSON FeatureCollection
        change_threshold: 变化识别阈值（百分比）
        **kwargs: 其他参数
            - group_by_field: 用地类型字段名
            - area_unit: 面积单位 (km2, m2, ha)
            - include_heatmap: 是否生成变化热力图

    Returns:
        Dict with:
        - success: bool
        - data: 变化分析结果
    """
    if not GEOPANDAS_AVAILABLE:
        return {
            "success": False,
            "error": "landuse_change_analysis requires geopandas. Install: pip install geopandas shapely"
        }

    if not current_landuse.get("features") or not planned_landuse.get("features"):
        return {
            "success": False,
            "error": "Input GeoJSON must contain features"
        }

    try:
        from .spatial_analysis import geojson_to_geodataframe, geodataframe_to_geojson

        # 转换为 GeoDataFrame
        gdf_current = geojson_to_geodataframe(current_landuse)
        gdf_planned = geojson_to_geodataframe(planned_landuse)

        if gdf_current is None or gdf_planned is None:
            return {"success": False, "error": "GeoJSON conversion failed"}

        # 确保相同 CRS
        if gdf_current.crs != gdf_planned.crs:
            gdf_planned = gdf_planned.to_crs(gdf_current.crs)

        # 获取用地类型字段名
        group_by_field = kwargs.get("group_by_field", "用地类型")
        area_unit = kwargs.get("area_unit", "km2")

        # 尝试找到合适的用地类型字段
        possible_fields = ["用地类型", "type", "landuse_type", "用地性质", "类别", "用地代码"]
        actual_field = None
        for field in possible_fields:
            if field in gdf_current.columns and field in gdf_planned.columns:
                actual_field = field
                break

        if actual_field is None:
            # 使用第一个非几何字段
            non_geom_cols = [c for c in gdf_current.columns if c != "geometry"]
            actual_field = non_geom_cols[0] if non_geom_cols else "unknown"

        logger.info(f"[landuse_change] 使用用地类型字段: {actual_field}")

        # 投影到适合计算面积的 CRS
        try:
            gdf_current_proj = gdf_current.to_crs(epsg=3857) if gdf_current.crs.to_epsg() == 4326 else gdf_current
            gdf_planned_proj = gdf_planned.to_crs(epsg=3857) if gdf_planned.crs.to_epsg() == 4326 else gdf_planned
        except Exception:
            gdf_current_proj = gdf_current
            gdf_planned_proj = gdf_planned

        # 计算面积
        area_divisor = 1_000_000 if area_unit == "km2" else (10_000 if area_unit == "ha" else 1)

        gdf_current["area"] = gdf_current_proj.geometry.area / area_divisor
        gdf_planned["area"] = gdf_planned_proj.geometry.area / area_divisor

        # 统计现状用地类型
        current_stats = gdf_current.groupby(actual_field)["area"].sum().to_dict()
        current_counts = gdf_current.groupby(actual_field).size().to_dict()

        # 统计规划用地类型
        planned_stats = gdf_planned.groupby(actual_field)["area"].sum().to_dict()
        planned_counts = gdf_planned.groupby(actual_field).size().to_dict()

        # 计算变化
        all_types = set(current_stats.keys()) | set(planned_stats.keys())
        change_statistics = {}

        for type_name in all_types:
            current_area = current_stats.get(type_name, 0)
            planned_area = planned_stats.get(type_name, 0)
            current_count = current_counts.get(type_name, 0)
            planned_count = planned_counts.get(type_name, 0)

            area_change = planned_area - current_area
            count_change = planned_count - current_count
            change_rate = (area_change / max(current_area, 0.001)) * 100 if current_area > 0 else 100

            change_statistics[type_name] = {
                "current_area": round(current_area, 4),
                "planned_area": round(planned_area, 4),
                "area_change": round(area_change, 4),
                "change_rate": round(change_rate, 2),
                "current_count": current_count,
                "planned_count": planned_count,
                "count_change": count_change,
                "status": "增加" if area_change > 0 else ("减少" if area_change < 0 else "不变"),
            }

        # 总面积统计
        total_current_area = sum(current_stats.values())
        total_planned_area = sum(planned_stats.values())

        # 识别显著变化区域
        significant_changes = {
            t: stats for t, stats in change_statistics.items()
            if abs(stats["change_rate"]) >= change_threshold * 100
        }

        # 生成变化热力图（可选）
        include_heatmap = kwargs.get("include_heatmap", False)
        change_heatmap = None

        if include_heatmap:
            change_heatmap = _generate_change_heatmap(
                gdf_current, gdf_planned, actual_field, change_statistics
            )

        return {
            "success": True,
            "data": {
                "change_statistics": change_statistics,
                "total_current_area": round(total_current_area, 4),
                "total_planned_area": round(total_planned_area, 4),
                "total_area_change": round(total_planned_area - total_current_area, 4),
                "significant_changes": significant_changes,
                "change_heatmap": change_heatmap,
                "increase_types": [t for t, s in change_statistics.items() if s["area_change"] > 0],
                "decrease_types": [t for t, s in change_statistics.items() if s["area_change"] < 0],
                "unchanged_types": [t for t, s in change_statistics.items() if s["area_change"] == 0],
                "field_used": actual_field,
                "area_unit": area_unit,
                "metadata": {
                    "current_features": len(gdf_current),
                    "planned_features": len(gdf_planned),
                    "unique_types_count": len(all_types),
                }
            }
        }

    except Exception as e:
        logger.error(f"[landuse_change] Analysis failed: {e}")
        return {"success": False, "error": f"Landuse change analysis failed: {str(e)}"}


def _generate_change_heatmap(
    gdf_current: gpd.GeoDataFrame,
    gdf_planned: gpd.GeoDataFrame,
    field: str,
    change_stats: Dict[str, Dict]
) -> Optional[Dict[str, Any]]:
    """
    生成变化热力图 GeoJSON。

    热力图展示用地变化的空间分布。
    """
    try:
        from .spatial_analysis import geodataframe_to_geojson

        # 为每个规划地块计算变化强度
        heatmap_features = []

        for idx, row in gdf_planned.iterrows():
            type_name = row.get(field, "unknown")
            change_info = change_stats.get(type_name, {})

            # 变化强度（0-1）
            change_rate = abs(change_info.get("change_rate", 0))
            intensity = min(change_rate / 100, 1.0)  # 转换为 0-1

            feature = {
                "type": "Feature",
                "geometry": row.geometry.__geo_interface__,
                "properties": {
                    "type": type_name,
                    "change_status": change_info.get("status", "未知"),
                    "area_change": change_info.get("area_change", 0),
                    "change_rate": change_info.get("change_rate", 0),
                    "intensity": intensity,
                }
            }
            heatmap_features.append(feature)

        return {
            "type": "FeatureCollection",
            "features": heatmap_features,
            "properties": {
                "layerType": "heatmap",
                "layerName": "用地变化热力图",
                "intensityField": "intensity",
            }
        }

    except Exception as e:
        logger.warning(f"[landuse_change] Heatmap generation failed: {e}")
        return None


def get_increase_areas(
    current_landuse: Dict[str, Any],
    planned_landuse: Dict[str, Any],
    **kwargs
) -> Dict[str, Any]:
    """
    获取新增用地区域。

    返回规划中新增的用地区域（不在现状中存在的）。
    """
    from .spatial_analysis import run_spatial_overlay, geojson_to_geodataframe

    if not GEOPANDAS_AVAILABLE:
        return {"success": False, "error": "geopandas not available"}

    try:
        # 差异分析：规划 - 现状
        result = run_spatial_overlay(
            operation="difference",
            layer_a=planned_landuse,
            layer_b=current_landuse,
        )

        if result.get("success"):
            return {
                "success": True,
                "data": {
                    "increase_geojson": result.get("data", {}).get("geojson"),
                    "feature_count": result.get("data", {}).get("feature_count", 0),
                    "total_area_km2": result.get("data", {}).get("total_area_km2", 0),
                }
            }

        return {"success": False, "error": result.get("error", "Difference analysis failed")}

    except Exception as e:
        return {"success": False, "error": str(e)}


def get_decrease_areas(
    current_landuse: Dict[str, Any],
    planned_landuse: Dict[str, Any],
    **kwargs
) -> Dict[str, Any]:
    """
    获取减少用地区域。

    返回现状中不再保留的用地区域。
    """
    from .spatial_analysis import run_spatial_overlay, geojson_to_geodataframe

    if not GEOPANDAS_AVAILABLE:
        return {"success": False, "error": "geopandas not available"}

    try:
        # 差异分析：现状 - 规划
        result = run_spatial_overlay(
            operation="difference",
            layer_a=current_landuse,
            layer_b=planned_landuse,
        )

        if result.get("success"):
            return {
                "success": True,
                "data": {
                    "decrease_geojson": result.get("data", {}).get("geojson"),
                    "feature_count": result.get("data", {}).get("feature_count", 0),
                    "total_area_km2": result.get("data", {}).get("total_area_km2", 0),
                }
            }

        return {"success": False, "error": result.get("error", "Difference analysis failed")}

    except Exception as e:
        return {"success": False, "error": str(e)}


__all__ = [
    "analyze_landuse_change",
    "get_increase_areas",
    "get_decrease_areas",
]