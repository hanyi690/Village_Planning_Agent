"""Pure conversion from backend GIS layers to the frontend map contract."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.utils.sse_events import GISLayerConfig


def build_map_layers(
    layout_configs: Optional[List[Dict[str, Any]]],
    gis_data: Dict[str, Optional[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Build frontend MapLibre layers without Agent or LangChain dependencies."""
    layers: List[Dict[str, Any]] = []

    if gis_data.get("landuse_current_geojson"):
        layers.append({
            "geojson": gis_data["landuse_current_geojson"],
            "layer_type": "current_landuse",
            "layer_name": "current_landuse",
            "color": "#d1d5db",
            "semantic_group": "现状底图",
            "default_visible": True,
        })

    for config in layout_configs or []:
        if not isinstance(config, dict):
            continue
        geojson = config.get("data") or config.get("geojson")
        if geojson is None and config.get("features") is not None:
            geojson = {
                "type": "FeatureCollection",
                "features": config.get("features") or [],
            }
        if not geojson:
            continue
        layer_type = (
            config.get("layerType")
            or config.get("layer_type")
            or "function_zone"
        )
        display_type = "planned_landuse_parcel" if layer_type == "land_use_zone" else layer_type
        semantics = {
            "custom_planning_zone": ("规划主分区", True, "空间分区生成"),
            "planning_zone": ("规划主分区", True, "L3分区目标"),
            "custom_functional_zone": ("规划主分区", True, "L3自定义分区"),
            "function_zone": ("功能分析", False, "规则聚合"),
            "planned_landuse_parcel": ("逐地块规划分类", False, "地块分配"),
            "space_control_zone": ("空间管制", False, "管制规则"),
            "infrastructure": ("发展轴线", True, "L3轴线目标"),
        }
        semantic_group, default_visible, source_label = semantics.get(
            display_type, ("规划分析", False, "执行结果")
        )
        layers.append({
            "geojson": geojson,
            "layer_type": display_type,
            "layer_name": config.get("layer_name") or display_type,
            "color": config.get("color"),
            "style": config.get("style"),
            "semantic_group": semantic_group,
            "default_visible": default_visible,
            "source_label": source_label,
        })

    if gis_data.get("road_geojson"):
        layers.append({
            "geojson": gis_data["road_geojson"],
            "layer_type": "current_road",
            "layer_name": "current_road",
            "color": "#64748b",
            "semantic_group": "现状底图",
            "default_visible": True,
        })

    if gis_data.get("annotation_geojson"):
        layers.append({
            "geojson": gis_data["annotation_geojson"],
            "layer_type": "current_annotation",
            "layer_name": "current_annotation",
            "color": "#dc2626",
            "semantic_group": "现状底图",
            "default_visible": True,
        })

    for key, name, color in (
        ("ecological_protection_geojson", "生态保护限制区", "#15803d"),
        ("farmland_protection_geojson", "永久基本农田", "#ca8a04"),
        ("historical_protection_geojson", "历史文化保护范围", "#7c3aed"),
        ("construction_boundary_geojson", "建设边界", "#dc2626"),
    ):
        if gis_data.get(key):
            layers.append({
                "geojson": gis_data[key],
                "layer_type": "input_constraint",
                "layer_name": name,
                "color": color,
                "semantic_group": "输入管制层",
                "default_visible": False,
                "source_label": "上传 GIS 限制区",
            })

    if gis_data.get("boundary_geojson"):
        layers.append({
            "geojson": gis_data["boundary_geojson"],
            "layer_type": "boundary",
            "layer_name": "boundary",
            "color": "#3388ff",
            "semantic_group": "现状底图",
            "default_visible": True,
        })

    result = []
    for layer in layers:
        normalized = GISLayerConfig(**layer).model_dump(by_alias=True)
        for key in ("semantic_group", "default_visible", "source_label"):
            if key in layer:
                normalized[key] = layer[key]
        result.append(normalized)
    return result


__all__ = ["build_map_layers"]
