"""
GIS空间分析核心逻辑

从 GISAnalysisAdapter 提取的核心功能，提供土地利用、土壤、水文分析。
"""

from typing import Dict, Any, List, Optional
from ...utils.logger import get_logger

logger = get_logger(__name__)

# 检查 geopandas 是否可用
try:
    import geopandas as gpd
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    logger.warning("[gis_core] geopandas 不可用")


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
        return {
            "success": False,
            "error": "GIS分析需要 geopandas 库。请安装: pip install geopandas"
        }

    if analysis_type == "land_use_analysis":
        return _analyze_land_use(geo_data_path, **kwargs)
    elif analysis_type == "soil_analysis":
        return _analyze_soil(soil_data_path, **kwargs)
    elif analysis_type == "hydrology_analysis":
        return _analyze_hydrology(hydrology_data_path, **kwargs)
    else:
        return {
            "success": False,
            "error": f"不支持的分析类型: {analysis_type}"
        }


def _analyze_land_use(geo_data_path: Optional[str], **kwargs) -> Dict[str, Any]:
    """土地利用分析"""
    if not geo_data_path:
        return {
            "success": False,
            "error": "缺少 geo_data_path 参数"
        }

    try:
        gdf = gpd.read_file(geo_data_path)
        total_area = gdf.geometry.area.sum() / 1_000_000

        land_use_column = kwargs.get("land_use_column", "land_use_type")
        land_use_stats = gdf.groupby(land_use_column).agg({
            'geometry': 'area'
        }).reset_index()

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
                "land_use_efficiency": 0.75,
                "development_intensity": 0.35
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
        soil_stats = gdf.groupby(soil_column).agg({
            'geometry': 'area'
        }).reset_index()

        soil_types = []
        for _, row in soil_stats.iterrows():
            area_km2 = row['geometry'].sum() / 1_000_000
            soil_types.append({
                "type": row[soil_column],
                "area": round(area_km2, 2),
                "suitability": "适宜"
            })

        return {
            "success": True,
            "data": {
                "soil_types": soil_types,
                "soil_quality_index": 0.68,
                "erosion_risk": "中等"
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

        return {
            "success": True,
            "data": {
                "water_systems": water_systems,
                "flood_risk_areas": []
            }
        }
    except Exception as e:
        return {"success": False, "error": f"水文分析失败: {str(e)}"}


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