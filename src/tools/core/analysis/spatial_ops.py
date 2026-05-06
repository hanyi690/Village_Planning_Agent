"""
Spatial Operations - 空间分析（合并模块）

整合 spatial_analysis 和 gis_core，提供完整的空间分析功能。

功能：
- GeoJSON/GeoDataFrame 转换（从 utils 导入）
- 空间叠加分析（intersect, union, difference, clip）
- 土地利用分析
- 土壤分析
- 水文分析
"""

import json
from typing import Dict, Any, List, Optional, Literal
from src.utils.logger import get_logger

# Import GeoJSON utilities from centralized utils module
from ..utils.geojson_utils import geojson_to_geodataframe, geodataframe_to_geojson

logger = get_logger(__name__)

# Check geopandas availability
try:
    import geopandas as gpd
    import shapely.geometry as geom
    from shapely.ops import nearest_points
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    logger.warning("[spatial_ops] geopandas/shapely not available")


# ============================================
# Spatial Overlay Analysis (from spatial_analysis)
# ============================================

def run_spatial_overlay(
    operation: Literal["intersect", "union", "difference", "clip"],
    layer_a: Dict[str, Any],
    layer_b: Dict[str, Any],
    **kwargs
) -> Dict[str, Any]:
    """
    执行空间叠加分析

    Args:
        operation: 叠加操作类型
        layer_a: 图层 A (GeoJSON)
        layer_b: 图层 B (GeoJSON)
        **kwargs: 其他参数

    Returns:
        Dict[str, Any]: 分析结果
    """
    if not GEOPANDAS_AVAILABLE:
        return {"success": False, "error": "需要 geopandas 库"}

    try:
        gdf_a = geojson_to_geodataframe(layer_a)
        gdf_b = geojson_to_geodataframe(layer_b)

        if gdf_a is None or gdf_b is None:
            return {"success": False, "error": "GeoJSON 转换失败"}

        # 执行叠加操作
        if operation == "intersect":
            result_gdf = gpd.overlay(gdf_a, gdf_b, how="intersection")
        elif operation == "union":
            result_gdf = gpd.overlay(gdf_a, gdf_b, how="union")
        elif operation == "difference":
            result_gdf = gpd.overlay(gdf_a, gdf_b, how="difference")
        elif operation == "clip":
            result_gdf = gpd.clip(gdf_a, gdf_b)
        else:
            return {"success": False, "error": f"不支持的操作: {operation}"}

        result_geojson = geodataframe_to_geojson(result_gdf)

        return {
            "success": True,
            "data": {
                "geojson": result_geojson,
                "feature_count": len(result_gdf),
                "operation": operation,
            }
        }

    except Exception as e:
        logger.error(f"[spatial_ops] Overlay analysis failed: {e}")
        return {"success": False, "error": str(e)}


# ============================================
# GIS Analysis (from gis_core)
# ============================================

def run_gis_analysis(
    analysis_type: str,
    geo_data_path: Optional[str] = None,
    soil_data_path: Optional[str] = None,
    hydrology_data_path: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    执行GIS空间分析

    Args:
        analysis_type: 分析类型
            - land_use_analysis: 土地利用分析
            - soil_analysis: 土壤分析
            - hydrology_analysis: 水文分析
        geo_data_path: 土地利用数据文件路径
        soil_data_path: 土壤数据文件路径
        hydrology_data_path: 水文数据文件路径

    Returns:
        Dict[str, Any]: 分析结果
    """
    if not GEOPANDAS_AVAILABLE:
        return {"success": False, "error": "GIS分析需要 geopandas 库"}

    if analysis_type == "land_use_analysis":
        return _analyze_land_use(geo_data_path, **kwargs)
    elif analysis_type == "soil_analysis":
        return _analyze_soil(soil_data_path, **kwargs)
    elif analysis_type == "hydrology_analysis":
        return _analyze_hydrology(hydrology_data_path, **kwargs)
    else:
        return {"success": False, "error": f"不支持的分析类型: {analysis_type}"}


def _analyze_land_use(geo_data_path: Optional[str], **kwargs) -> Dict[str, Any]:
    """土地利用分析"""
    if not geo_data_path:
        return {"success": False, "error": "缺少 geo_data_path 参数"}

    try:
        gdf = gpd.read_file(geo_data_path)
        total_area = gdf.geometry.area.sum() / 1_000_000

        land_use_column = kwargs.get("land_use_column", "land_use_type")
        land_use_stats = gdf.groupby(land_use_column).agg({'geometry': 'area'}).reset_index()

        land_use_types = []
        for _, row in land_use_stats.iterrows():
            area_km2 = row['geometry'].sum() / 1_000_000
            land_use_types.append({
                "type": row[land_use_column],
                "area": round(area_km2, 2),
                "percentage": round((area_km2 / total_area) * 100, 2)
            })

        return {
            "success": True,
            "data": {
                "total_area": round(total_area, 2),
                "land_use_types": land_use_types,
                "pending_metrics": {
                    "land_use_efficiency": "pending",
                    "development_intensity": "pending"
                },
                "note": "土地效率指标需结合自然资源数据计算"
            }
        }
    except Exception as e:
        return {"success": False, "error": f"土地利用分析失败: {str(e)}"}


def _analyze_soil(soil_data_path: Optional[str], **kwargs) -> Dict[str, Any]:
    """土壤分析"""
    if not soil_data_path:
        return {"success": False, "error": "缺少 soil_data_path 参数"}

    try:
        gdf = gpd.read_file(soil_data_path)
        soil_column = kwargs.get("soil_type_column", "soil_type")
        soil_stats = gdf.groupby(soil_column).agg({'geometry': 'area'}).reset_index()

        soil_types = []
        for _, row in soil_stats.iterrows():
            area_km2 = row['geometry'].sum() / 1_000_000
            soil_types.append({
                "type": row[soil_column],
                "area": round(area_km2, 2),
                "suitability": "pending",
                "note": "土壤适宜性需结合土壤理化性质数据评估"
            })

        return {
            "success": True,
            "data": {
                "soil_types": soil_types,
                "pending_metrics": {
                    "soil_quality_index": "pending",
                    "erosion_risk": "pending"
                },
                "note": "土壤质量指标需结合土壤理化性质数据计算"
            }
        }
    except Exception as e:
        return {"success": False, "error": f"土壤分析失败: {str(e)}"}


def _analyze_hydrology(hydrology_data_path: Optional[str], **kwargs) -> Dict[str, Any]:
    """水文分析"""
    if not hydrology_data_path:
        return {"success": False, "error": "缺少 hydrology_data_path 参数"}

    try:
        gdf = gpd.read_file(hydrology_data_path)
        water_systems = []

        for _, row in gdf.iterrows():
            water_system = {
                "name": row.get("name", "未命名水体"),
                "type": row.get("type", "其他"),
                "water_quality": row.get("quality", "III类")
            }

            if row.geometry.geom_type == "LineString":
                water_system["length"] = round(row.geometry.length / 1000, 2)
            elif row.geometry.geom_type in ["Polygon", "MultiPolygon"]:
                water_system["area"] = round(row.geometry.area / 1_000_000, 2)

            water_systems.append(water_system)

        buffer_distance = kwargs.get("flood_buffer_distance", 100)
        flood_risk_areas = []

        for _, row in gdf.iterrows():
            if row.geometry.geom_type in ["LineString", "Polygon", "MultiPolygon"]:
                try:
                    buffer_geom = row.geometry.buffer(buffer_distance)
                    flood_area_km2 = buffer_geom.area / 1_000_000

                    flood_risk_areas.append({
                        "water_name": row.get("name", "未命名水体"),
                        "water_type": row.get("type", "其他"),
                        "buffer_distance_m": buffer_distance,
                        "risk_area_km2": round(flood_area_km2, 4),
                        "risk_level": "pending"
                    })
                except Exception:
                    pass

        return {
            "success": True,
            "data": {
                "water_systems": water_systems,
                "flood_risk_areas": flood_risk_areas,
                "analysis_params": {
                    "buffer_distance": buffer_distance,
                    "note": "洪水风险等级需结合地形高程和降雨数据进一步评估"
                }
            }
        }
    except Exception as e:
        return {"success": False, "error": f"水文分析失败: {str(e)}"}


# ============================================
# Formatting Functions
# ============================================

def format_gis_result(result: Dict[str, Any]) -> str:
    """格式化GIS分析结果为字符串"""
    if not result.get("success"):
        return f"GIS分析失败: {result.get('error', '未知错误')}"

    data = result.get("data", {})
    lines = ["GIS空间分析结果："]

    if "total_area" in data:
        lines.append(f"- 总面积: {data['total_area']} km²")

    if "land_use_types" in data:
        lines.append("- 土地利用类型分布:")
        for t in data["land_use_types"]:
            lines.append(f"  * {t['type']}: {t['area']} km² ({t['percentage']}%)")

    if "soil_types" in data:
        lines.append("- 土壤类型分布:")
        for s in data["soil_types"]:
            lines.append(f"  * {s['type']}: {s['area']} km², 适宜性: {s['suitability']}")

    if "water_systems" in data:
        lines.append("- 水系分布:")
        for w in data["water_systems"]:
            if "length" in w:
                lines.append(f"  * {w['name']}: {w['length']} km, 水质: {w['water_quality']}")
            elif "area" in w:
                lines.append(f"  * {w['name']}: {w['area']} km², 水质: {w['water_quality']}")

    return "\n".join(lines)


__all__ = [
    'geojson_to_geodataframe',
    'geodataframe_to_geojson',
    'run_spatial_overlay',
    'run_gis_analysis',
    'format_gis_result',
]