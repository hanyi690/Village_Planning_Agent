"""
GeoJSON Utilities - GeoJSON 转换工具函数

提供 GeoJSON 与 GeoDataFrame 之间的转换工具。
"""

import json
from typing import Dict, Any, Optional, List

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Check geopandas availability
try:
    import geopandas as gpd
    import shapely.geometry as geom
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    logger.warning("[geojson_utils] geopandas/shapely not available")


def geojson_to_geodataframe(geojson: Dict[str, Any]) -> Optional[gpd.GeoDataFrame]:
    """
    将 GeoJSON FeatureCollection 转换为 GeoDataFrame

    Args:
        geojson: GeoJSON FeatureCollection 字典

    Returns:
        GeoDataFrame 或 None（转换失败时）
    """
    if not GEOPANDAS_AVAILABLE:
        return None

    try:
        features = geojson.get("features", [])
        if not features:
            return None

        geometries = []
        properties = []

        for feature in features:
            geom_data = feature.get("geometry", {})
            props = feature.get("properties", {})

            geom_type = geom_data.get("type", "")
            coords = geom_data.get("coordinates", [])

            try:
                if geom_type == "Point":
                    geometries.append(geom.Point(coords))
                elif geom_type == "LineString":
                    geometries.append(geom.LineString(coords))
                elif geom_type == "Polygon":
                    # Polygon coords is [shell, hole1, hole2, ...]
                    geometries.append(geom.Polygon(coords[0], coords[1:]))
                elif geom_type == "MultiPoint":
                    geometries.append(geom.MultiPoint(coords))
                elif geom_type == "MultiLineString":
                    geometries.append(geom.MultiLineString(coords))
                elif geom_type == "MultiPolygon":
                    geometries.append(geom.MultiPolygon(coords))
                else:
                    geometries.append(None)
            except Exception as e:
                logger.warning(f"[geojson_utils] Failed to create geometry: {e}")
                geometries.append(None)

            properties.append(props)

        # 过滤掉 None 几何对象
        valid_indices = [i for i, g in enumerate(geometries) if g is not None]
        if not valid_indices:
            return None

        geometries = [geometries[i] for i in valid_indices]
        properties = [properties[i] for i in valid_indices]

        gdf = gpd.GeoDataFrame(properties, geometry=geometries)
        if gdf.crs is None:
            gdf.set_crs("EPSG:4326", inplace=True)

        return gdf

    except Exception as e:
        logger.error(f"[geojson_utils] GeoJSON conversion failed: {e}")
        return None


def geodataframe_to_geojson(gdf: gpd.GeoDataFrame) -> Dict[str, Any]:
    """
    将 GeoDataFrame 转换为 GeoJSON FeatureCollection

    Args:
        gdf: GeoDataFrame

    Returns:
        GeoJSON FeatureCollection 字典
    """
    features = []

    for idx, row in gdf.iterrows():
        geometry = row.geometry
        if geometry is None:
            continue

        geom_type = geometry.geom_type
        coords = _get_geometry_coords(geometry)

        props = {k: v for k, v in row.items() if k != 'geometry'}
        # 转换不可序列化的值
        for k, v in props.items():
            if hasattr(v, '__iter__') and not isinstance(v, (str, list, dict)):
                props[k] = list(v) if hasattr(v, '__iter__') else str(v)

        feature = {
            "type": "Feature",
            "properties": props,
            "geometry": {
                "type": geom_type,
                "coordinates": coords
            }
        }
        features.append(feature)

    return {"type": "FeatureCollection", "features": features}


def _get_geometry_coords(geometry) -> List:
    """从 Shapely 几何对象提取坐标"""
    return json.loads(json.dumps(geometry.__geo_interface__))["coordinates"]


__all__ = ['geojson_to_geodataframe', 'geodataframe_to_geojson']