"""
GIS 样式配置

集中管理 GIS 图层的样式定义，确保前后端样式一致。
与前端 frontend/src/lib/constants/gis.ts PLANNING_COLORS 同步。

提供：
- PLANNING_STYLES: 规划图层样式定义
- export_styles_json(): 导出 JSON 格式供前端 API 使用
- 图层类型几何类型映射
"""

from typing import Dict, Any, List, Literal, TypedDict, Optional
import json

from ..utils.logger import get_logger

logger = get_logger(__name__)


class FillStyle(TypedDict, total=False):
    """Polygon feature style"""
    fill_color: str
    fill_opacity: float
    border_color: str


class LineStyle(TypedDict, total=False):
    """Line feature style"""
    color: str
    width: int
    opacity: float


class MarkerStyle(TypedDict, total=False):
    """Point feature style"""
    color: str
    icon: str
    icon_color: str


# Layer geometry type mapping
LAYER_GEOMETRY_TYPES: Dict[str, str] = {
    "function_zone": "polygon",
    "facility_point": "point",
    "development_axis": "line",
    "sensitivity_zone": "polygon",
    "isochrone": "polygon",
    "boundary": "line",
    "settlement_zone": "polygon",
    "infrastructure": "line",
}

# Planning symbol styles (standardized color scheme)
# Synchronized with frontend/src/lib/constants/gis.ts PLANNING_COLORS
PLANNING_STYLES: Dict[str, Dict[str, Dict[str, Any]]] = {
    # Function zone styles (polygon fill)
    "function_zone": {
        "居住用地": {"fill_color": "#FFD700", "fill_opacity": 0.6, "border_color": "#B8860B"},
        "产业用地": {"fill_color": "#FF6B6B", "fill_opacity": 0.6, "border_color": "#CC0000"},
        "公共服务用地": {"fill_color": "#4A90D9", "fill_opacity": 0.6, "border_color": "#1E3A5F"},
        "生态绿地": {"fill_color": "#90EE90", "fill_opacity": 0.6, "border_color": "#228B22"},
        "交通用地": {"fill_color": "#808080", "fill_opacity": 0.5, "border_color": "#404040"},
        "水域": {"fill_color": "#87CEEB", "fill_opacity": 0.7, "border_color": "#4169E1"},
        "农业用地": {"fill_color": "#8B4513", "fill_opacity": 0.5, "border_color": "#654321"},
        "商业用地": {"fill_color": "#FFA500", "fill_opacity": 0.6, "border_color": "#CC8400"},
        "村庄建设区": {"fill_color": "#FFC0CB", "fill_opacity": 0.6, "border_color": "#FF69B4"},
        "农业生产区": {"fill_color": "#F4A460", "fill_opacity": 0.6, "border_color": "#D2691E"},
        "生态保护区": {"fill_color": "#98FB98", "fill_opacity": 0.6, "border_color": "#32CD32"},
    },

    # Facility point styles (marker icons)
    "facility_point": {
        "现状保留": {"color": "#00AA00", "icon": "home", "icon_color": "white"},
        "规划新建": {"color": "#0000FF", "icon": "plus-circle", "icon_color": "white"},
        "规划改扩建": {"color": "#FFA500", "icon": "edit", "icon_color": "white"},
        "规划迁建": {"color": "#9370DB", "icon": "move", "icon_color": "white"},
    },

    # Facility type icons
    "facility_type_icons": {
        "幼儿园": {"icon": "child", "color": "#FF69B4"},
        "小学": {"icon": "education", "color": "#FFD700"},
        "中学": {"icon": "bank", "color": "#DAA520"},
        "医院": {"icon": "hospital", "color": "#FF0000"},
        "诊所": {"icon": "medkit", "color": "#FF6347"},
        "公园": {"icon": "leaf", "color": "#228B22"},
        "超市": {"icon": "shopping-cart", "color": "#FFA500"},
        "菜市场": {"icon": "shopping-bag", "color": "#FF4500"},
        "健身设施": {"icon": "dumbbell", "color": "#00CED1"},
        "垃圾收集点": {"icon": "trash", "color": "#808080"},
        "公交站": {"icon": "bus", "color": "#1E90FF"},
        "候车亭": {"icon": "bus", "color": "#1E90FF"},
        "养老设施": {"icon": "heart", "color": "#FF1493"},
        "文化站": {"icon": "book", "color": "#8B4513"},
    },

    # Development axis styles (line styles)
    "development_axis": {
        "发展主轴": {"color": "#FF0000", "width": 3, "opacity": 0.8},
        "发展副轴": {"color": "#00AA00", "width": 2, "opacity": 0.6},
        "交通主轴": {"color": "#0000FF", "width": 3, "opacity": 0.7},
        "景观轴线": {"color": "#00FF00", "width": 2, "opacity": 0.5},
    },

    # Sensitivity zone styles (polygon)
    "sensitivity_zone": {
        "高敏感区": {"fill_color": "#FF0000", "fill_opacity": 0.4, "border_color": "#CC0000"},
        "中敏感区": {"fill_color": "#FFFF00", "fill_opacity": 0.3, "border_color": "#CCCC00"},
        "低敏感区": {"fill_color": "#00FF00", "fill_opacity": 0.2, "border_color": "#00CC00"},
        "缓冲区": {"fill_color": "#FFA500", "fill_opacity": 0.25, "border_color": "#CC8400"},
    },

    # Isochrone styles (polygon - time-based accessibility)
    "isochrone": {
        "5min": {"fill_color": "#00FF00", "fill_opacity": 0.5, "border_color": "#00CC00"},
        "10min": {"fill_color": "#FFFF00", "fill_opacity": 0.4, "border_color": "#CCCC00"},
        "15min": {"fill_color": "#FFA500", "fill_opacity": 0.3, "border_color": "#CC8400"},
        "30min": {"fill_color": "#FF0000", "fill_opacity": 0.25, "border_color": "#CC0000"},
    },

    # Boundary styles (line)
    "boundary": {
        "行政边界": {"color": "#333333", "width": 2, "opacity": 0.9},
        "规划边界": {"color": "#666666", "width": 1, "opacity": 0.8},
        "自然村边界": {"color": "#999999", "width": 1, "opacity": 0.7},
    },

    # Settlement zone styles (polygon) - Village classification
    # NEW: Added for settlement_planning dimension
    "settlement_zone": {
        "中心村": {"fill_color": "#FF4500", "fill_opacity": 0.6, "border_color": "#CC3700"},
        "保留发展类": {"fill_color": "#32CD32", "fill_opacity": 0.6, "border_color": "#228B22"},
        "搬迁撤并类": {"fill_color": "#FF6347", "fill_opacity": 0.6, "border_color": "#CC5240"},
        "整治提升类": {"fill_color": "#1E90FF", "fill_opacity": 0.6, "border_color": "#1873CC"},
    },

    # Infrastructure styles (line) - Roads, waterways, utilities
    # NEW: Added for real GIS data rendering
    "infrastructure": {
        "道路": {"color": "#666666", "width": 2, "opacity": 0.8},
        "乡道": {"color": "#808080", "width": 1.5, "opacity": 0.8},
        "县道": {"color": "#555555", "width": 2, "opacity": 0.8},
        "水系": {"color": "#4169E1", "width": 2, "opacity": 0.7},
        "河流": {"color": "#00BFFF", "width": 2.5, "opacity": 0.7},
    },
}


def get_style_for_layer(
    layer_type: Literal["function_zone", "facility_point", "development_axis",
                        "sensitivity_zone", "isochrone", "boundary", "settlement_zone"],
    subtype: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get style for a layer type and subtype

    Args:
        layer_type: Type of layer
        subtype: Optional subtype (e.g., "居住用地" for function_zone)

    Returns:
        Style dict with color, opacity, etc.
    """
    styles = PLANNING_STYLES.get(layer_type, {})

    if subtype:
        return styles.get(subtype, _get_default_style(layer_type))

    return styles


def get_style_for_feature(
    feature: Dict[str, Any],
    layer_type: Literal["function_zone", "facility_point", "development_axis",
                        "sensitivity_zone", "isochrone", "boundary", "settlement_zone"]
) -> Dict[str, Any]:
    """
    Get style for a feature based on its properties

    Args:
        feature: GeoJSON feature
        layer_type: Type of layer

    Returns:
        Style dict with color, opacity, icon etc.
    """
    properties = feature.get("properties", {})
    styles = PLANNING_STYLES.get(layer_type, {})

    # Determine subtype from properties
    subtype = _get_subtype_from_properties(layer_type, properties)

    # Get style or default
    style = styles.get(subtype, _get_default_style(layer_type))

    # Allow property override
    if "color" in properties:
        if "fill_color" in style:
            style["fill_color"] = properties["color"]
        elif "color" in style:
            style["color"] = properties["color"]
    if "opacity" in properties:
        style["fill_opacity"] = properties["opacity"]

    return style


def _get_subtype_from_properties(layer_type: str, properties: Dict[str, Any]) -> str:
    """Extract subtype from feature properties"""
    subtype_map = {
        "function_zone": ["zone_type", "居住用地"],
        "facility_point": ["status", "规划新建"],
        "development_axis": ["axis_type", "发展主轴"],
        "sensitivity_zone": ["sensitivity_level", "中敏感区"],
        "isochrone": ["time_minutes", "10min"],
        "boundary": ["boundary_type", "行政边界"],
        "settlement_zone": ["zone_type", "中心村"],
        "infrastructure": ["infrastructure_type", "道路"],
    }

    if layer_type in subtype_map:
        prop_key, default = subtype_map[layer_type]
        value = properties.get(prop_key)
        if value:
            # Handle isochrone time_minutes (convert to string like "10min")
            if layer_type == "isochrone" and isinstance(value, (int, float)):
                return f"{int(value)}min"
            return str(value)
        return default

    return "default"


def _get_default_style(layer_type: str) -> Dict[str, Any]:
    """Get default style for unknown layer type"""
    geom_type = LAYER_GEOMETRY_TYPES.get(layer_type, "polygon")

    if geom_type == "line":
        return {"color": "#CCCCCC", "width": 2, "opacity": 0.5}
    elif geom_type == "point":
        return {"color": "#CCCCCC", "icon": "circle", "icon_color": "white"}
    else:
        return {"fill_color": "#CCCCCC", "fill_opacity": 0.5, "border_color": "#666666"}


def export_styles_json() -> str:
    """
    Export styles as JSON string for frontend API

    Returns:
        JSON string of PLANNING_STYLES
    """
    # Convert to frontend-compatible format
    frontend_styles: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for layer_type, styles in PLANNING_STYLES.items():
        if layer_type == "facility_type_icons":
            # Skip facility type icons for frontend (used only by backend folium)
            continue

        frontend_styles[layer_type] = {}

        for subtype, style in styles.items():
            geom_type = LAYER_GEOMETRY_TYPES.get(layer_type, "polygon")

            if geom_type == "line":
                # Line style
                frontend_styles[layer_type][subtype] = {
                    "stroke": style.get("color", "#000000"),
                    "width": style.get("width", 2),
                }
            elif geom_type == "point":
                # Point style (facility_point)
                frontend_styles[layer_type][subtype] = {
                    "fill": style.get("color", "#000000"),
                    "stroke": style.get("color", "#000000"),
                }
            else:
                # Polygon style
                frontend_styles[layer_type][subtype] = {
                    "fill": style.get("fill_color", "#CCCCCC"),
                    "stroke": style.get("border_color", "#666666"),
                }

    return json.dumps(frontend_styles, indent=2)


def export_legend_json(layer_types: Optional[List[str]] = None) -> str:
    """
    Export legend items as JSON for frontend

    Args:
        layer_types: Optional list of layer types to export (default: all)

    Returns:
        JSON string of legend items grouped by layer type
    """
    if layer_types is None:
        layer_types = list(PLANNING_STYLES.keys())

    legend_data: Dict[str, List[Dict[str, Any]]] = {}

    for layer_type in layer_types:
        if layer_type == "facility_type_icons":
            continue

        styles = PLANNING_STYLES.get(layer_type, {})
        geom_type = LAYER_GEOMETRY_TYPES.get(layer_type, "polygon")

        legend_items = []
        for subtype, style in styles.items():
            item: Dict[str, Any] = {
                "label": subtype,
                "type": geom_type,
            }

            if geom_type == "line":
                item["color"] = style.get("color", "#000000")
                item["lineWidth"] = style.get("width", 2)
            elif geom_type == "point":
                item["color"] = style.get("color", "#000000")
                item["borderColor"] = style.get("color", "#000000")
            else:
                item["color"] = style.get("fill_color", "#CCCCCC")
                item["borderColor"] = style.get("border_color", "#666666")

            legend_items.append(item)

        legend_data[layer_type] = legend_items

    return json.dumps(legend_data, indent=2)


def get_all_layer_types() -> List[str]:
    """Get list of all supported layer types"""
    return [k for k in PLANNING_STYLES.keys() if k != "facility_type_icons"]


def get_geometry_type(layer_type: str) -> str:
    """Get geometry type for a layer type"""
    return LAYER_GEOMETRY_TYPES.get(layer_type, "polygon")


# Export all
__all__ = [
    "PLANNING_STYLES",
    "LAYER_GEOMETRY_TYPES",
    "get_style_for_layer",
    "get_style_for_feature",
    "export_styles_json",
    "export_legend_json",
    "get_all_layer_types",
    "get_geometry_type",
]