"""
MapRenderer - converts GeoJSON layers to GISLayerConfig format.

Produces the data structure that the frontend MapView component expects,
matching the TypeScript GISLayerConfig interface exactly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger
from app.modules.schema import get_zone_color, ZONE_TYPE_COLORS, FACILITY_STATUS_COLORS, PLANNING_ZONE_COLORS
from app.utils.geojson_utils import reduce_coordinate_precision
from app.tools.gis._generation.optimizer.procedural import simplify_boundary

logger = get_logger(__name__)

from app.modules.schema.output.colors import INFRA_COLORS, ISOCHRONE_COLORS, get_infra_color


# Layer type priority for rendering order (matches frontend LAYER_PRIORITY)
LAYER_PRIORITY = {
    "boundary": 0,
    "sensitivity_zone": 1,
    "isochrone": 2,
    "function_zone": 3,
    "planning_zone": 4,       # KG-driven 6-zone planning layer
    "development_axis": 5,
    "infrastructure": 6,
    "facility_point": 7,
}

# Whitelist of feature properties to keep per layer type.
# All other properties are stripped to reduce SSE payload size.
PROPERTIES_WHITELIST: Dict[str, List[str]] = {
    "function_zone": ["color", "stroke", "zone_type", "DLBM", "land_use", "layer_role"],
    "planning_zone": ["color", "stroke", "zone_type", "assigned_zone", "changed", "direction", "layer_role", "area_ha", "DLBM"],
    "facility_point": ["color", "stroke", "status", "name", "facility_type", "layer_role"],
    "sensitivity_zone": ["color", "stroke", "sensitivity_level", "protection_type", "layer_role"],
    "infrastructure": ["infra_type", "color", "weight", "RN", "layer_role"],
    "development_axis": ["axis_type", "color", "weight", "layer_role"],
    "isochrone": ["color", "stroke", "time_minutes", "layer_role"],
    "boundary": ["layer_role"],
}


class MapRenderer:
    """Convert GeoJSON layer dicts to GISLayerConfig format for frontend.

    Each GISLayerConfig matches the TypeScript interface:
      {
        geojson: GeoJsonFeatureCollection,
        layerType: 'boundary' | 'function_zone' | 'facility_point' | ...,
        layerName: string,
        color?: string,
        style?: { fillColor?, fillOpacity?, color?, weight? }
      }
    """

    def render(
        self,
        layers: Dict[str, Dict[str, Any]],
        boundary_geojson: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Convert all GeoJSON layers to GISLayerConfig list.

        Args:
            layers: Dict of {layer_type: GeoJSON FeatureCollection}
            boundary_geojson: Optional boundary GeoJSON to include

        Returns:
            List of GISLayerConfig dicts, sorted by rendering priority
        """
        configs = []

        # Add boundary if provided
        if boundary_geojson:
            configs.append({
                "geojson": boundary_geojson,
                "layerType": "boundary",
                "layerName": "village_boundary",
                "color": "#333333",
                "style": {
                    "color": "#333333",
                    "weight": 2,
                    "fillOpacity": 0,
                },
            })

        # Process each layer type
        for layer_type, geojson in layers.items():
            if not geojson or not geojson.get("features"):
                continue

            # Inject per-feature style based on layer type
            self._inject_feature_styles(geojson, layer_type)

            # Determine top-level style
            top_style = self._get_layer_style(layer_type)

            config = {
                "geojson": geojson,
                "layerType": layer_type,
                "layerName": f"{layer_type}_layer",
            }

            if top_style and top_style.get("color"):
                config["color"] = top_style["color"]
            if top_style:
                config["style"] = top_style

            configs.append(config)

        # Optimize GeoJSON for network transfer (MapLibre best practices)
        for config in configs:
            geojson = config.get("geojson")
            layer_type = config.get("layerType", "")
            if geojson:
                reduce_coordinate_precision(geojson, decimals=6)
                simplify_boundary(geojson, tolerance_m=5)
                self._strip_properties(geojson, layer_type)

        # Sort by priority
        configs.sort(key=lambda c: LAYER_PRIORITY.get(c["layerType"], 99))

        logger.info(f"[MapRenderer] Rendered {len(configs)} layer configs")
        return configs

    def _inject_feature_styles(
        self,
        geojson: Dict[str, Any],
        layer_type: str,
    ) -> None:
        """Inject color and style into each feature's properties.

        The frontend MapView uses data-driven rendering:
        - function_zone: reads 'color' from feature.properties OR 'zone_type' for DLBM-based lookup
        - facility_point: reads 'status' and maps to FACILITY_STATUS_COLORS
        - Other layers: uses layer-level style
        """
        for feature in geojson.get("features", []):
            if not feature.get("properties"):
                feature["properties"] = {}

            props = feature["properties"]

            if layer_type == "function_zone":
                # Use the color already injected by ZoneGenerator
                # If not present, derive from land_use or DLBM
                if "color" not in props:
                    # Try land_use first (from ZoneGenerator)
                    zone_type = props.get("land_use", "")
                    # If no land_use, derive from DLBM (for landuse_current)
                    if not zone_type:
                        from app.modules.schema import get_zone_type_for_dlbm
                        dlbm = props.get("DLBM", "")
                        zone_type = get_zone_type_for_dlbm(dlbm)

                    color_info = get_zone_color(zone_type)
                    props["color"] = color_info["fill"]
                    props["stroke"] = color_info["stroke"]

                # Set zone_type for frontend PLANNING_COLORS lookup
                if "zone_type" not in props:
                    if props.get("land_use"):
                        props["zone_type"] = props.get("land_use", "")
                    elif props.get("DLBM"):
                        from app.modules.schema import get_zone_type_for_dlbm
                        props["zone_type"] = get_zone_type_for_dlbm(props.get("DLBM", ""))
                    else:
                        props["zone_type"] = "居住用地"

            elif layer_type == "facility_point":
                # Map facility status to color
                status = props.get("status", "existing")
                status_colors = FACILITY_STATUS_COLORS.get(status, {"fill": "blue", "stroke": "#00008B"})
                props["color"] = status_colors["fill"]
                props["stroke"] = status_colors["stroke"]

            elif layer_type == "development_axis":
                # Axis types: primary/secondary/corridor
                axis_type = props.get("axis_type", "secondary")
                axis_colors = {
                    "primary": {"color": "#FF0000", "weight": 3},
                    "secondary": {"color": "#00AA00", "weight": 2},
                    "corridor": {"color": "#00FF00", "weight": 2},
                    "traffic": {"color": "#0000FF", "weight": 3},
                }
                props.update(axis_colors.get(axis_type, {"color": "#00AA00", "weight": 2}))

            elif layer_type == "planning_zone":
                if "zone_type" not in props:
                    props["zone_type"] = props.get("assigned_zone", "")
                if "direction" not in props:
                    props["direction"] = "center"
                # Highlight changed parcels with red stroke
                if props.get("changed") and "stroke" not in props:
                    props["stroke"] = "#FF0000"
                elif "stroke" not in props:
                    props["stroke"] = props.get("color", "#666666")

            elif layer_type == "sensitivity_zone":
                level = props.get("sensitivity_level", "medium")
                level_colors = {
                    "high": {"fill": "#FF0000", "stroke": "#CC0000"},
                    "medium": {"fill": "#FFFF00", "stroke": "#CCCC00"},
                    "low": {"fill": "#00FF00", "stroke": "#00CC00"},
                    "buffer": {"fill": "#FFA500", "stroke": "#CC8400"},
                }
                colors = level_colors.get(level, {"fill": "#CCCCCC", "stroke": "#666666"})
                props["color"] = colors["fill"]
                props["stroke"] = colors["stroke"]

            elif layer_type == "infrastructure":
                if "color" not in props:
                    infra_type = str(props.get("infrastructure_type", "")).strip()
                    rn = str(props.get("RN", "")).strip()
                    name = str(props.get("name", "")).strip()
                    road_key = "道路"
                    if infra_type in ("河流", "水系"):
                        road_key = "河流"
                    elif rn.startswith("X") or "县道" in name:
                        road_key = "县道"
                    elif rn.startswith("Y") or "乡道" in name or "村道" in name:
                        road_key = "乡道"
                    color_info = INFRA_COLORS.get(road_key, INFRA_COLORS["道路"])
                    props["color"] = color_info["fill"]
                    props["stroke"] = color_info["stroke"]

            elif layer_type == "isochrone":
                if "color" not in props:
                    mins = props.get("time_minutes", 10)
                    props["color"] = ISOCHRONE_COLORS.get(mins, "#FFA500")
                    props["stroke"] = props["color"]

    def _get_layer_style(self, layer_type: str) -> Optional[Dict[str, Any]]:
        """Get default style for a layer type. Returns None if no layer-level style."""
        styles = {
            "function_zone": {
                "fillOpacity": 0.4,
                "weight": 1,
            },
            "planning_zone": {
                "fillOpacity": 0.35,
                "weight": 2.5,
            },
            "sensitivity_zone": {
                "fillOpacity": 0.3,
                "weight": 1,
            },
            "isochrone": {
                "fillOpacity": 0.2,
                "weight": 1,
            },
            "infrastructure": {
                "weight": 2,
            },
        }
        return styles.get(layer_type)

    def _strip_properties(
        self,
        geojson: Dict[str, Any],
        layer_type: str,
    ) -> None:
        """Strip unused feature properties to reduce SSE payload size.

        Only keeps properties in the PROPERTIES_WHITELIST for each layer type.
        This can reduce GeoJSON size by 15-20% by removing backend-only fields
        like DLBM area codes, SHAPE_Area, TBYBH, etc.
        """
        whitelist = PROPERTIES_WHITELIST.get(layer_type)
        if not whitelist:
            return
        whitelist_set = set(whitelist)
        for feature in geojson.get("features", []):
            props = feature.get("properties")
            if not props:
                continue
            feature["properties"] = {k: v for k, v in props.items() if k in whitelist_set}


__all__ = ["MapRenderer", "LAYER_PRIORITY"]
