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


def build_trace_layer(
    explore_instructions: Optional[Dict[str, Any]],
    gis_data: Dict[str, Optional[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """构建定位校核图层（EXPLORE grounding 指令的候选 BSM → 点/面标注）。

    反映 L3 空间描述经 KG 拓扑接地后的候选地块分布，供前端核对
    "文本说 X 处" vs "几何落在哪"。Migrated from
    app.agent.execute.layout_pipeline._build_trace_layer (Wave M1).
    """
    explore = explore_instructions or {}
    instructions = explore.get("instructions") or []
    if not instructions:
        return None

    parcel_index: Dict[str, Dict[str, Any]] = {}
    landuse = (gis_data or {}).get("landuse_current_geojson") or {}
    for feature in landuse.get("features", []):
        props = feature.get("properties") or {}
        bsm = str(props.get("BSM") or props.get("bsm") or "")
        geometry = feature.get("geometry")
        if bsm and geometry:
            parcel_index[bsm] = geometry

    features = []
    for instr in instructions:
        bsms = instr.get("candidate_bsms") or []
        if not bsms:
            continue
        for bsm in bsms:
            geometry = parcel_index.get(str(bsm))
            if geometry is None:
                continue
            features.append({
                "type": "Feature",
                "properties": {
                    "name": bsm,
                    "dim": instr.get("dimension_key", ""),
                    "evidence": (instr.get("evidence_text") or "")[:30],
                    "query_path": instr.get("query_path", ""),
                },
                "geometry": geometry,
            })
    if not features:
        return None
    return {
        "layerType": "position_trace",
        "layer_name": "定位校核",
        "data": {"type": "FeatureCollection", "features": features},
        "color": "#7c3aed",
        "style": {"fill-opacity": 0.3},
    }


__all__ = ["build_map_layers", "build_trace_layer"]
