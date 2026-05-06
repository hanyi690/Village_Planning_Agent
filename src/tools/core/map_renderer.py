"""
Map Renderer Core Logic

Provides symbolization and rendering for planning maps.
Creates visualization-ready map outputs from vector layers.

Reference: Planning workflow requires thematic maps with
standardized symbols and styles.
"""

from typing import Dict, Any, List, Optional, Tuple, Literal
import json
from ...utils.logger import get_logger
from ...config.gis_styles import (
    PLANNING_STYLES,
    LAYER_GEOMETRY_TYPES,
    get_style_for_feature,
    export_legend_json,
)

logger = get_logger(__name__)

try:
    import folium
    FOLIUM_AVAILABLE = True
except ImportError:
    FOLIUM_AVAILABLE = False
    logger.warning("[map_renderer] folium not available")


# Planning symbol styles (standardized color scheme)
PLANNING_STYLES = {
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
    },
    # Facility point styles (marker icons)
    "facility_point": {
        "现状保留": {"color": "green", "icon": "home", "icon_color": "white"},
        "规划新建": {"color": "blue", "icon": "plus-circle", "icon_color": "white"},
        "规划改扩建": {"color": "orange", "icon": "edit", "icon_color": "white"},
        "规划迁建": {"color": "purple", "icon": "move", "icon_color": "white"},
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
    },
    # Development axis styles (line styles)
    "development_axis": {
        "发展主轴": {"color": "#FF0000", "width": 3, "opacity": 0.8},
        "发展副轴": {"color": "#00AA00", "width": 2, "opacity": 0.6},
        "交通主轴": {"color": "#0000FF", "width": 3, "opacity": 0.7},
        "景观轴线": {"color": "#00FF00", "width": 2, "opacity": 0.5},
    },
    # Infrastructure styles (line) - Roads, waterways
    "infrastructure": {
        "道路": {"color": "#666666", "width": 2, "opacity": 0.8},
        "乡道": {"color": "#808080", "width": 1.5, "opacity": 0.8},
        "县道": {"color": "#555555", "width": 2, "opacity": 0.8},
        "水系": {"color": "#4169E1", "width": 2, "opacity": 0.7},
        "河流": {"color": "#00BFFF", "width": 2.5, "opacity": 0.7},
    },
    # Sensitivity zone styles
    "sensitivity_zone": {
        "高敏感区": {"fill_color": "#FF0000", "fill_opacity": 0.4},
        "中敏感区": {"fill_color": "#FFFF00", "fill_opacity": 0.3},
        "低敏感区": {"fill_color": "#00FF00", "fill_opacity": 0.2},
        "缓冲区": {"fill_color": "#FFA500", "fill_opacity": 0.25},
    },
}


def get_style_for_feature(
    feature: Dict[str, Any],
    layer_type: Literal["function_zone", "facility_point", "development_axis", "sensitivity_zone", "infrastructure"]
) -> Dict[str, Any]:
    """
    Get style for a feature based on its type

    Args:
        feature: GeoJSON feature
        layer_type: Type of layer

    Returns:
        Style dict with color, opacity, icon etc.
    """
    properties = feature.get("properties", {})
    styles = PLANNING_STYLES.get(layer_type, {})

    # Determine subtype
    if layer_type == "function_zone":
        subtype = properties.get("zone_type", "居住用地")
    elif layer_type == "facility_point":
        subtype = properties.get("status", "规划新建")
    elif layer_type == "development_axis":
        subtype = properties.get("axis_type", "发展主轴")
    elif layer_type == "sensitivity_zone":
        subtype = properties.get("sensitivity_level", "中敏感区")
    elif layer_type == "infrastructure":
        # Infrastructure subtype from properties
        infra_type = properties.get("infrastructure_type", "")
        if infra_type:
            subtype = infra_type
        elif "RN" in properties:  # WFS road data
            rn = properties.get("RN", "")
            if rn.startswith("Y"):
                subtype = "乡道"
            elif rn.startswith("X"):
                subtype = "县道"
            else:
                subtype = "道路"
        else:
            subtype = "道路"
    else:
        subtype = "default"

    # Get style or default
    style = styles.get(subtype, {
        "fill_color": "#CCCCCC",
        "fill_opacity": 0.5,
        "border_color": "#666666",
    })

    # Allow property override
    if "color" in properties:
        style["fill_color"] = properties["color"]
    if "opacity" in properties:
        style["fill_opacity"] = properties["opacity"]

    return style


def render_planning_map(
    layers: List[Dict[str, Any]],
    title: str = "村庄规划图",
    center: Optional[Tuple[float, float]] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Render planning thematic map

    Creates interactive folium map with all layers properly styled.

    Args:
        layers: List of layer definitions
            [{"geojson": dict, "layer_type": str, "layer_name": str}, ...]
        title: Map title
        center: Optional map center [lon, lat]
        **kwargs: Additional parameters
            - zoom_start: Initial zoom level (default: 14)
            - show_legend: Whether to show legend (default: True)
            - output_format: 'html' or 'dict' (default: 'html')

    Returns:
        Dict with success status and map output
    """
    if not FOLIUM_AVAILABLE:
        return {
            "success": False,
            "error": "Map rendering requires folium. Install: pip install folium"
        }

    try:
        zoom_start = kwargs.get("zoom_start", 14)
        show_legend = kwargs.get("show_legend", True)
        output_format = kwargs.get("output_format", "html")

        # Determine center from first layer if not provided
        if center is None and layers:
            first_geojson = layers[0].get("geojson", {})
            features = first_geojson.get("features", [])
            if features:
                first_geom = features[0].get("geometry", {})
                if first_geom.get("type") == "Point":
                    center = tuple(first_geom.get("coordinates", [0, 0]))
                else:
                    # Calculate centroid from coordinates
                    coords = first_geom.get("coordinates", [[]])
                    if coords and coords[0]:
                        center = (coords[0][0][0], coords[0][0][1])

        if center is None:
            center = (0, 0)

        # Create folium map
        m = folium.Map(
            location=[center[1], center[0]],  # folium uses [lat, lon]
            zoom_start=zoom_start,
            tiles="OpenStreetMap",
        )

        # Add title
        title_html = f'''
        <div style="position: fixed; top: 10px; left: 50%; transform: translateX(-50%);
                    z-index: 9999; font-size: 24px; font-weight: bold;
                    background-color: white; padding: 10px 20px;
                    border-radius: 5px; box-shadow: 0 0 10px rgba(0,0,0,0.3);">
            {title}
        </div>
        '''
        m.get_root().html.add_child(folium.Element(title_html))

        # Add layers
        layer_info = []
        for layer in layers:
            geojson = layer.get("geojson", {})
            layer_type = layer.get("layer_type", "function_zone")
            layer_name = layer.get("layer_name", "Unnamed Layer")

            if not geojson.get("features"):
                continue

            # Add styled GeoJSON layer
            style_function = _create_style_function(layer_type)
            tooltip_fields = _get_tooltip_fields(layer_type)

            geojson_layer = folium.GeoJson(
                geojson,
                style_function=style_function,
                tooltip=folium.GeoJsonTooltip(fields=tooltip_fields),
                name=layer_name,
            )
            geojson_layer.add_to(m)

            layer_info.append({
                "name": layer_name,
                "type": layer_type,
                "feature_count": len(geojson.get("features", [])),
            })

        # Add legend
        if show_legend:
            legend_html = _create_legend_html(layers)
            m.get_root().html.add_child(folium.Element(legend_html))

        # Add layer control
        folium.LayerControl().add_to(m)

        # Output
        if output_format == "html":
            map_html = m._repr_html_()
            return {
                "success": True,
                "data": {
                    "map_html": map_html,
                    "layer_info": layer_info,
                    "center": center,
                    "title": title,
                }
            }
        else:
            return {
                "success": True,
                "data": {
                    "map_object": m,
                    "layer_info": layer_info,
                }
            }

    except Exception as e:
        logger.error(f"[map_renderer] Map rendering failed: {e}")
        return {"success": False, "error": f"Map rendering failed: {str(e)}"}


def _create_style_function(layer_type: str):
    """Create folium style function for layer type"""
    def style_function(feature):
        style = get_style_for_feature(feature, layer_type)

        if feature["geometry"]["type"] in ["Point", "MultiPoint"]:
            return {
                "radius": 8,
                "fillColor": style.get("color", style.get("fill_color", "#000")),
                "color": style.get("border_color", "#000"),
                "weight": 1,
                "opacity": style.get("fill_opacity", 0.8),
                "fillOpacity": style.get("fill_opacity", 0.8),
            }
        elif feature["geometry"]["type"] in ["LineString", "MultiLineString"]:
            return {
                "color": style.get("color", "#FF0000"),
                "weight": style.get("width", 2),
                "opacity": style.get("opacity", 0.8),
            }
        else:  # Polygon
            return {
                "fillColor": style.get("fill_color", "#CCCCCC"),
                "color": style.get("border_color", "#666666"),
                "weight": 2,
                "fillOpacity": style.get("fill_opacity", 0.5),
            }

    return style_function


def _get_tooltip_fields(layer_type: str) -> List[str]:
    """Get tooltip fields for layer type"""
    # Use basic fields that are likely to exist in data
    if layer_type == "function_zone":
        return ["name", "zone_type"]
    elif layer_type == "facility_point":
        return ["name", "facility_type", "status"]
    elif layer_type == "development_axis":
        return ["name", "axis_type"]
    elif layer_type == "sensitivity_zone":
        return ["zone_type", "sensitivity_level"]
    elif layer_type == "infrastructure":
        return ["name", "infrastructure_type"]
    else:
        return ["name"]


def _create_legend_html(layers: List[Dict[str, Any]]) -> str:
    """Create legend HTML for map with all layer types"""
    legend_items = []
    processed_types = set()

    for layer in layers:
        layer_type = layer.get("layer_type", "")
        layer_name = layer.get("layer_name", "")

        if layer_type in processed_types:
            continue

        # Skip facility_type_icons (not a display layer)
        if layer_type == "facility_type_icons":
            continue

        styles = PLANNING_STYLES.get(layer_type, {})
        if not styles:
            continue

        geom_type = LAYER_GEOMETRY_TYPES.get(layer_type, "polygon")

        # Add layer group header
        legend_items.append(
            f'<div style="font-weight: bold; margin-top: 10px; margin-bottom: 5px;">{layer_name}</div>'
        )

        # Add legend items for each subtype
        for subtype, style in styles.items():
            if geom_type == "line":
                # Line style legend
                color = style.get("color", "#000")
                width = style.get("width", 2)
                legend_items.append(
                    f'<div style="margin: 5px 0;">'
                    f'<span style="background: {color}; '
                    f'width: {10 + width * 2}px; height: {width}px; '
                    f'display: inline-block; '
                    f'border-radius: 2px;"></span> '
                    f'<span style="margin-left: 5px;">{subtype}</span>'
                    f'</div>'
                )
            elif geom_type == "point":
                # Point style legend
                color = style.get("color", "#000")
                legend_items.append(
                    f'<div style="margin: 5px 0;">'
                    f'<span style="background: {color}; '
                    f'width: 16px; height: 16px; display: inline-block; '
                    f'border: 2px solid {color}; '
                    f'border-radius: 50%;"></span> '
                    f'<span style="margin-left: 5px;">{subtype}</span>'
                    f'</div>'
                )
            else:
                # Polygon style legend
                fill_color = style.get("fill_color", "#CCC")
                border_color = style.get("border_color", "#666")
                legend_items.append(
                    f'<div style="margin: 5px 0;">'
                    f'<span style="background: {fill_color}; '
                    f'opacity: {style.get("fill_opacity", 0.5)}; '
                    f'width: 20px; height: 20px; display: inline-block; '
                    f'border: 1px solid {border_color}; '
                    f'border-radius: 3px;"></span> '
                    f'<span style="margin-left: 5px;">{subtype}</span>'
                    f'</div>'
                )

        processed_types.add(layer_type)

    legend_html = f'''
    <div style="position: fixed; bottom: 50px; right: 50px; z-index: 9999;
                background-color: white; padding: 10px 15px; border-radius: 5px;
                box-shadow: 0 0 10px rgba(0,0,0,0.3); max-height: 400px;
                overflow-y: auto;">
        <div style="font-weight: bold; margin-bottom: 10px; font-size: 14px;">图例</div>
        {"".join(legend_items)}
    </div>
    '''

    return legend_html


def create_static_map_image(
    layers: List[Dict[str, Any]],
    title: str = "村庄规划图",
    **kwargs
) -> Dict[str, Any]:
    """
    Create static map image (placeholder for matplotlib-based rendering)

    Args:
        layers: List of layer definitions
        title: Map title
        **kwargs: Additional parameters
            - dpi: Image DPI (default: 150)
            - figsize: Figure size tuple

    Returns:
        Dict with success status
    """
    # Placeholder - would require matplotlib implementation
    return {
        "success": True,
        "data": {
            "note": "Static map rendering not yet implemented",
            "layers_count": len(layers),
            "title": title,
        },
        "implementation_needed": "matplotlib-based static map rendering"
    }


def export_geojson_with_styles(
    geojson: Dict[str, Any],
    layer_type: str,
    **kwargs
) -> Dict[str, Any]:
    """
    Export GeoJSON with style properties embedded

    Adds style properties directly to features for use in GIS software.

    Args:
        geojson: Input GeoJSON FeatureCollection
        layer_type: Layer type for style lookup
        **kwargs: Additional parameters

    Returns:
        Dict with styled GeoJSON
    """
    try:
        styled_features = []

        for feature in geojson.get("features", []):
            style = get_style_for_feature(feature, layer_type)

            # Add style to properties
            styled_feature = feature.copy()
            properties = styled_feature.get("properties", {})
            properties["_style"] = style
            styled_feature["properties"] = properties

            styled_features.append(styled_feature)

        styled_geojson = {
            "type": "FeatureCollection",
            "features": styled_features,
            "_metadata": {
                "layer_type": layer_type,
                "style_source": "planning_standards",
            }
        }

        return {
            "success": True,
            "data": {
                "geojson": styled_geojson,
                "feature_count": len(styled_features),
            }
        }

    except Exception as e:
        logger.error(f"[map_renderer] Style export failed: {e}")
        return {"success": False, "error": f"Style export failed: {str(e)}"}


def create_map_composition(
    base_map: Dict[str, Any],
    overlay_layers: List[Dict[str, Any]],
    **kwargs
) -> Dict[str, Any]:
    """
    Create layered map composition

    Combines base map with multiple overlay layers.

    Args:
        base_map: Base layer (typically land use or boundary)
        overlay_layers: Overlay layers
        **kwargs: Additional parameters

    Returns:
        Dict with composition result
    """
    all_layers = [base_map] + overlay_layers

    return render_planning_map(
        layers=all_layers,
        title=kwargs.get("title", "村庄规划综合图"),
        center=kwargs.get("center"),
        **kwargs
    )


def format_renderer_result(result: Dict[str, Any]) -> str:
    """Format renderer result to string"""
    if not result.get("success"):
        return f"Map rendering failed: {result.get('error', 'Unknown error')}"

    data = result.get("data", {})
    lines = ["Map Rendering Result:"]

    if "title" in data:
        lines.append(f"- Map title: {data['title']}")

    if "layer_info" in data:
        lines.append(f"- Layers: {len(data['layer_info'])}")
        for layer in data["layer_info"]:
            lines.append(f"  * {layer['name']}: {layer['feature_count']} features")

    if "map_html" in data:
        lines.append("- Output: HTML map generated")
        lines.append(f"- HTML length: {len(data['map_html'])} chars")

    return "\n".join(lines)


__all__ = [
    "render_planning_map",
    "create_static_map_image",
    "export_geojson_with_styles",
    "create_map_composition",
    "get_style_for_feature",
    "format_renderer_result",
    "PLANNING_STYLES",
]