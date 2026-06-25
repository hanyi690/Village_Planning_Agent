"""
MapRenderer - converts GeoJSON layers to GISLayerConfig format.

Produces the data structure that the frontend MapView component expects,
matching the TypeScript GISLayerConfig interface exactly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger
from .colors import get_zone_color, ZONE_TYPE_COLORS, FACILITY_STATUS_COLORS

logger = get_logger(__name__)


# Layer type priority for rendering order (matches frontend LAYER_PRIORITY)
LAYER_PRIORITY = {
    "boundary": 0,
    "sensitivity_zone": 1,
    "isochrone": 2,
    "function_zone": 3,
    "planning_zone": 4,       # KG-driven 4-zone planning layer
    "development_axis": 5,
    "infrastructure": 6,
    "facility_point": 7,
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
        - function_zone: reads 'color' from feature.properties
        - facility_point: reads 'status' and maps to FACILITY_STATUS_COLORS
        - Other layers: uses layer-level style
        """
        for feature in geojson.get("features", []):
            if not feature.get("properties"):
                feature["properties"] = {}

            props = feature["properties"]

            if layer_type == "function_zone":
                # Use the color already injected by ZoneGenerator
                # If not present, derive from land_use
                if "color" not in props:
                    zone_type = props.get("land_use", "")
                    color_info = get_zone_color(zone_type)
                    props["color"] = color_info["fill"]
                    props["stroke"] = color_info["stroke"]

                # Set zone_type for frontend PLANNING_COLORS lookup
                if "zone_type" not in props:
                    props["zone_type"] = props.get("land_use", "")

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


__all__ = ["MapRenderer", "LAYER_PRIORITY"]
