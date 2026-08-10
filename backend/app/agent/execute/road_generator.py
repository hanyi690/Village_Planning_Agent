"""Road execution adapter for the GIS EXECUTE Agent.

Migrated from agent/gis/execute/road/generator.py per docs/architecture/agent-graph.md §5.

This module bridges the agent-layer ``RoadTarget`` intent contract to the
deterministic road-planning services.  The agent does not draw road geometry
directly; it prepares structured spatial inputs, runs Stage 2.6/3 gates, and
only invokes Stage 4 when the inputs are confirmed enough for automatic routing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.modules.spatial_ops.road import (
    NetworkBuildConfig,
    PlanningNodeBuildConfig,
    RDFLibKGSpatialRetryAdapter,
    RoadPlanningConfig,
    SpatialBindingConfig,
    bind_road_spatial_requirements,
    build_planning_nodes,
    build_planning_nodes_with_kg_retry_adapter,
    build_planning_nodes_with_kg_retry_response,
    build_road_network,
    run_stage4_road_planning,
)
from app.utils.logger import get_logger


logger = get_logger(__name__)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[6]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _normalise(value: Any) -> str:
    return re.sub(r"[\s_（）()、，,。；;:：\-—]+", "", str(value or "")).lower()


def _fc(features: Sequence[Dict[str, Any]], crs: str = "EPSG:4326", name: str = "features") -> Dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "name": name,
        "crs": {"type": "name", "properties": {"name": crs}},
        "features": list(features),
    }


def _as_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return {
        key: getattr(value, key)
        for key in dir(value)
        if not key.startswith("_") and not callable(getattr(value, key))
    }


def _intent_road_targets(intent: Any) -> List[Dict[str, Any]]:
    if intent is None:
        return []
    if isinstance(intent, Mapping):
        raw = intent.get("road_targets") or []
    else:
        raw = getattr(intent, "road_targets", []) or []
    return [_as_dict(item) for item in raw]


def _semantic_text(target: Mapping[str, Any]) -> str:
    semantic = _as_dict(target.get("semantic"))
    candidates = (
        semantic.get("raw_text"),
        semantic.get("natural_language_description"),
        semantic.get("spatial_hint"),
        semantic.get("reasoning_trace"),
    )
    return next((str(item) for item in candidates if str(item or "").strip()), "")


def _infer_action(text: str) -> str:
    if any(keyword in text for keyword in ("拓宽", "扩宽", "加宽")):
        return "widen"
    if any(keyword in text for keyword in ("硬化", "黑化", "铺装")):
        return "harden"
    if any(keyword in text for keyword in ("修复", "修缮", "整治", "提升", "改造", "完善")):
        return "repair"
    return "new"


def _point_geometry(anchor: Any) -> Optional[Dict[str, Any]]:
    if not anchor:
        return None
    coords = list(anchor)
    if len(coords) < 2:
        return None
    return {"type": "Point", "coordinates": [float(coords[0]), float(coords[1])]}


def _road_targets_to_stage2(
    road_targets: Sequence[Mapping[str, Any]],
    output_dir: Path,
    display_crs: str = "EPSG:4326",
) -> Path:
    stage2_dir = output_dir / "stage2_from_parse"
    demands: List[Dict[str, Any]] = []
    projects: List[Dict[str, Any]] = []
    seen_demands: set[str] = set()

    def add_demand(name: str, geometry: Optional[Dict[str, Any]], project_id: str, role: str, evidence: str) -> str:
        key = _normalise(name) or f"{project_id}-{role}"
        demand_id = f"D{len(seen_demands) + 1:04d}"
        if key in seen_demands:
            for feature in demands:
                props = feature.get("properties") or {}
                if _normalise(props.get("place_name") or props.get("name")) == key:
                    return str(props.get("demand_id"))
        seen_demands.add(key)
        demands.append(
            {
                "type": "Feature",
                "id": demand_id,
                "geometry": geometry,
                "properties": {
                    "demand_id": demand_id,
                    "name": name,
                    "place_name": name,
                    "demand_type": "road_access",
                    "priority": "high",
                    "location_status": "resolved" if geometry else "unresolved",
                    "location_confidence": 0.9 if geometry else 0.0,
                    "requires_human_confirmation": geometry is None,
                    "source_role": f"parse_road_target_{role}",
                    "source_intent_ids": [project_id],
                    "evidence": {
                        "source_kind": "parse_agent_road_target",
                        "source_text": evidence,
                        "requires_human_confirmation": geometry is None,
                    },
                },
            }
        )
        return demand_id

    for index, target in enumerate(road_targets, start=1):
        project_id = str(
            target.get("target_id")
            or target.get("source_project_id")
            or target.get("source_instruction_id")
            or f"RP-PARSE-{index:04d}"
        )
        connects = [str(item) for item in target.get("connects") or [] if str(item or "").strip()]
        path_bsms = [str(item) for item in target.get("path_bsms") or [] if str(item or "").strip()]
        candidate_bsms = [str(item) for item in target.get("candidate_bsms") or [] if str(item or "").strip()]
        candidate_bbox = target.get("candidate_bbox") or target.get("bbox")
        start_name = connects[0] if connects else f"{project_id}-start"
        end_name = connects[1] if len(connects) > 1 else f"{project_id}-end"
        start_geometry = _point_geometry(target.get("start_anchor"))
        end_geometry = _point_geometry(target.get("end_anchor"))
        evidence = _semantic_text(target)
        action = _infer_action(evidence)
        start_demand_id = add_demand(start_name, start_geometry, project_id, "start", evidence)
        end_demand_id = add_demand(end_name, end_geometry, project_id, "end", evidence)
        projects.append(
            {
                "project_id": project_id,
                "target_id": target.get("target_id") or project_id,
                "name": evidence or f"{start_name}-{end_name}",
                "action": action,
                "road_class": target.get("road_level") or "village_road",
                "recommended_road_class": target.get("road_level") or "village_road",
                "recommended_width_m": float(target.get("width_m") or 0) or None,
                "start_place": start_name,
                "end_place": end_name,
                "start_demand_id": start_demand_id,
                "end_demand_id": end_demand_id,
                "start_geometry": start_geometry,
                "end_geometry": end_geometry,
                "service_places": connects,
                "path_bsms": path_bsms,
                "candidate_bsms": candidate_bsms,
                "candidate_bbox": candidate_bbox,
                "priority": "high",
                "requires_human_confirmation": bool(target.get("requires_human_confirmation")) or not (start_geometry and end_geometry),
                "planning_status": "parsed_from_agent_road_target",
                "source_project_id": target.get("source_project_id") or "",
                "source_instruction_id": target.get("source_instruction_id") or "",
                "source_report_key": target.get("source_report_key") or "",
                "evidence": {
                    "source_kind": "parse_agent_road_target",
                    "source_text": evidence,
                    "requires_human_confirmation": bool(target.get("requires_human_confirmation")) or not (start_geometry and end_geometry),
                },
            }
        )

    _write_json(stage2_dir / "demand_points.geojson", _fc(demands, display_crs, "parse_road_demand_points"))
    _write_json(
        stage2_dir / "road_projects.json",
        {"type": "RoadProjectCollection", "schema_version": "agent-parse-adapter-v1", "projects": projects},
    )
    _write_json(
        stage2_dir / "road_constraints.json",
        {"type": "RoadConstraintCollection", "schema_version": "agent-parse-adapter-v1", "constraints": []},
    )
    return stage2_dir


def _gis_payload(gis_data: Mapping[str, Any], keys: Sequence[str]) -> Optional[Dict[str, Any]]:
    for key in keys:
        payload = gis_data.get(key)
        if isinstance(payload, Mapping) and payload.get("features"):
            return dict(payload)
    return None


def _write_optional_layer(root: Path, name: str, payload: Optional[Dict[str, Any]]) -> Optional[Path]:
    if not payload:
        return None
    path = root / f"{name}.geojson"
    _write_json(path, payload)
    return path


def _write_optional_json_payload(root: Path, name: str, payload: Any) -> Optional[Path]:
    if payload is None:
        return None
    if not isinstance(payload, (Mapping, list)):
        return None
    path = root / f"{name}.json"
    _write_json(path, payload)
    return path


def _default_kg_retry_adapter(state: Any, gis_data: Mapping[str, Any]) -> Tuple[Optional[Any], Optional[str]]:
    """Create the standard RDFLib retry adapter from the active planning KG.

    A caller-supplied adapter remains the explicit integration point.  This
    fallback makes the existing session KG useful without requiring the road
    workflow to know the team's SPARQL service API.  It intentionally does not
    deserialize ``kg_turtle``: only an already-built KG may confirm a target.
    """

    kg = (
        gis_data.get("planning_kg")
        or gis_data.get("kg")
        or getattr(state, "planning_kg", None)
        or getattr(state, "kg", None)
    )
    source = "gis_data_planning_kg" if kg is not None else None
    if kg is None:
        session_ref = str(
            getattr(state, "kg_session_ref", "")
            or getattr(state, "session_id", "")
            or ""
        )
        if session_ref:
            try:
                from app.modules.kg import require_session_kg

                kg = require_session_kg(session_ref)
                source = "kg_session_interface"
            except LookupError:
                kg = None
            except Exception as exc:  # KG is optional at the road-execution boundary.
                logger.warning("[road_execute] Could not access session PlanningKG: %s", exc)
    if kg is None:
        return None, None
    try:
        return RDFLibKGSpatialRetryAdapter(kg), source
    except (TypeError, ValueError) as exc:
        logger.warning("[road_execute] Ignoring incompatible PlanningKG: %s", exc)
        return None, None


def _write_bundle_layers(root: Path, gis_data: Mapping[str, Any]) -> Tuple[Path, ...]:
    bundle_keys = (
        ("current_parcels", ("parcel_geojson", "parcels_geojson", "current_parcel_geojson")),
        ("landuse_current_bundle", ("landuse_current_geojson", "current_landuse_geojson")),
        ("facilities_bundle", ("facility_geojson", "facilities_geojson", "current_facility_geojson")),
        ("road_bundle", ("road_geojson", "current_road_geojson")),
        ("planning_zones_bundle", ("planning_zone_geojson", "planning_zones_geojson")),
    )
    paths: List[Path] = []
    for layer_name, keys in bundle_keys:
        path = _write_optional_layer(root, layer_name, _gis_payload(gis_data, keys))
        if path is not None:
            paths.append(path)
    return tuple(paths)


def _layer_config(layer_type: str, data: Dict[str, Any], color: str, visible: bool = True) -> Dict[str, Any]:
    return {
        "layerType": layer_type,
        "data": data,
        "visible": visible,
        "color": color,
        "style": {
            "stroke": color,
            "fill": color,
            "radius": 6,
            "strokeWidth": 2,
            "opacity": 0.85,
        },
    }


def execute_road_planning_from_agent_state(state: Any) -> Dict[str, Any]:
    """Execute the road sub-task from typed PARSE/KG/Data state."""

    road_targets = _intent_road_targets(getattr(state, "intent", None))
    if not road_targets:
        return {
            "ran": False,
            "reason": "No PARSE road_targets were produced; road sub-task skipped.",
            "layout_layers": [],
        }

    gis_data = dict(getattr(state, "gis_data", None) or {})
    bundle = getattr(state, "gis_bundle", None)
    if bundle is not None and hasattr(bundle, "to_geojson_dict"):
        merged = bundle.to_geojson_dict()
        merged.update(gis_data)
        gis_data = merged

    output_root = (
        _project_root()
        / "output"
        / "gis-agent-road"
        / (str(getattr(state, "session_id", "") or getattr(state, "village_name", "") or "default"))
    )
    input_root = output_root / "inputs"

    road_payload = _gis_payload(gis_data, ("road_geojson", "current_road_geojson"))
    boundary_payload = _gis_payload(gis_data, ("boundary_geojson", "admin_area_geojson"))
    landuse_payload = _gis_payload(gis_data, ("landuse_current_geojson", "current_landuse_geojson"))
    annotation_payload = _gis_payload(gis_data, ("annotation_geojson", "current_annotation_geojson"))
    if road_payload is None or boundary_payload is None:
        return {
            "ran": False,
            "reason": "Road execution needs current road and boundary GeoJSON from the Data layer.",
            "road_target_count": len(road_targets),
            "layout_layers": [],
        }

    roads_path = _write_optional_layer(input_root, "current_roads", road_payload)
    boundary_path = _write_optional_layer(input_root, "boundary", boundary_payload)
    landuse_path = _write_optional_layer(input_root, "landuse_current", landuse_payload)
    annotation_path = _write_optional_layer(input_root, "annotation", annotation_payload)
    hazard_path = _write_optional_layer(
        input_root,
        "geological_hazard_points",
        _gis_payload(gis_data, ("geological_hazard_points_geojson", "hazard_points_geojson")),
    )
    manual_confirmation_path = None
    state_manual_path = getattr(state, "road_manual_confirmation_path", None)
    if state_manual_path:
        candidate_path = Path(str(state_manual_path))
        if candidate_path.exists():
            manual_confirmation_path = candidate_path
    if manual_confirmation_path is None:
        manual_confirmation_path = _write_optional_json_payload(
            input_root,
            "road_manual_confirmations",
            gis_data.get("road_manual_confirmations")
            or gis_data.get("road_manual_confirmations_geojson")
            or gis_data.get("manual_confirmations"),
        )
    kg_retry_response_path = _write_optional_json_payload(
        input_root,
        "road_kg_retry_response",
        gis_data.get("road_kg_retry_response")
        or gis_data.get("road_kg_retry_responses")
        or gis_data.get("kg_retry_response"),
    )
    kg_retry_adapter = gis_data.get("road_kg_retry_adapter") or getattr(
        state,
        "road_kg_retry_adapter",
        None,
    )
    kg_retry_adapter_source = "explicit" if kg_retry_adapter is not None else None
    if kg_retry_adapter is not None and not callable(kg_retry_adapter):
        logger.warning("[road_execute] Ignoring non-callable road_kg_retry_adapter")
        kg_retry_adapter = None
        kg_retry_adapter_source = None
    if kg_retry_adapter is None:
        kg_retry_adapter, kg_retry_adapter_source = _default_kg_retry_adapter(state, gis_data)
    if kg_retry_response_path is not None:
        manual_confirmation_path = None
    kg_retry_normalised_path = (
        output_root / "stage2_6" / "kg_retry_confirmations.normalized.json"
        if (kg_retry_response_path is not None or callable(kg_retry_adapter))
        else None
    )
    bundle_geometry_sources = _write_bundle_layers(input_root / "bundle", gis_data)
    stage2_dir = _road_targets_to_stage2(road_targets, output_root)

    stage1_result = build_road_network(
        roads_path,
        output_root / "stage1",
        NetworkBuildConfig(display_crs="EPSG:4326"),
    )
    point_sources = tuple(path for path in (annotation_path,) if path is not None)
    stage2_6_config = PlanningNodeBuildConfig(
        stage2_dir=stage2_dir,
        output_dir=output_root / "stage2_6",
        road_edges_path=stage1_result.edges_path,
        boundary_path=boundary_path,
        point_sources=point_sources,
        bundle_geometry_sources=bundle_geometry_sources,
        bound_spatial_entities_path=(
            Path(str(getattr(state, "bound_entities_artifact_path", "")))
            if str(getattr(state, "bound_entities_artifact_path", "")) and Path(str(getattr(state, "bound_entities_artifact_path", ""))).exists()
            else None
        ),
        manual_confirmation_path=manual_confirmation_path,
    )
    if callable(kg_retry_adapter):
        stage2_6_result = build_planning_nodes_with_kg_retry_adapter(
            stage2_6_config,
            kg_retry_adapter,
        )
    elif kg_retry_response_path is not None:
        stage2_6_result = build_planning_nodes_with_kg_retry_response(
            stage2_6_config,
            kg_retry_response_path,
        )
    else:
        stage2_6_result = build_planning_nodes(stage2_6_config)
    stage3_result = bind_road_spatial_requirements(
        SpatialBindingConfig(
            stage2_dir=stage2_dir,
            stage2_6_dir=stage2_6_result.output_dir,
            road_edges_path=stage1_result.edges_path,
            output_dir=output_root / "stage3",
            point_sources=point_sources,
        )
    )

    stage4_result = None
    stage3_gate = stage3_result.report.get("planning_gate") or {}
    if stage3_gate.get("automatic_route_generation_allowed") and landuse_path is not None:
        stage4_result = run_stage4_road_planning(
            RoadPlanningConfig(
                road_nodes_path=stage1_result.nodes_path,
                road_edges_path=stage1_result.edges_path,
                stage3_dir=stage3_result.output_dir,
                boundary_path=boundary_path,
                landuse_path=landuse_path,
                hazard_points_path=hazard_path,
                output_dir=output_root / "stage4",
            )
        )

    layers = [
        _layer_config("road_spatial_candidates", _read_json(stage2_6_result.spatial_candidates_path), "#a855f7", False),
        _layer_config("road_planning_entities", _read_json(stage2_6_result.located_entities_path), "#f59e0b", False),
        _layer_config("road_planning_nodes", _read_json(stage2_6_result.planning_nodes_path), "#2563eb", True),
    ]
    if stage4_result is not None:
        layers.append(
            _layer_config("planned_road_candidates", _read_json(stage4_result.candidates_path), "#ef4444", False)
        )

    return {
        "ran": True,
        "output_dir": str(output_root),
        "road_target_count": len(road_targets),
        "stage1_report": stage1_result.report,
        "stage2_6_report": stage2_6_result.report,
        "stage2_6_trace": _read_json(stage2_6_result.execute_trace_path),
        "stage2_6_iteration_records": _read_json(stage2_6_result.iteration_records_path),
        "stage2_6_quality_gates": _read_json(stage2_6_result.quality_gates_path),
        "stage2_6_human_confirmation_template": _read_json(
            stage2_6_result.human_confirmation_template_path
        ),
        "stage2_6_kg_retry_requests": _read_json(stage2_6_result.kg_retry_requests_path),
        "stage3_report": stage3_result.report,
        "stage4_report": stage4_result.report if stage4_result is not None else None,
        "automatic_route_generation_allowed": bool(stage3_gate.get("automatic_route_generation_allowed")),
        "blocked_reason": None if stage3_gate.get("automatic_route_generation_allowed") else stage3_gate.get("reason"),
        "artifacts": {
            "stage2": str(stage2_dir),
            "stage1": str(stage1_result.output_dir),
            "stage2_6": str(stage2_6_result.output_dir),
            "spatial_candidates": str(stage2_6_result.spatial_candidates_path),
            "spatial_quality_gates": str(stage2_6_result.quality_gates_path),
            "human_confirmation_template": str(stage2_6_result.human_confirmation_template_path),
            "iteration_records": str(stage2_6_result.iteration_records_path),
            "kg_retry_requests": str(stage2_6_result.kg_retry_requests_path),
            "spatial_preprocessing_trace": str(stage2_6_result.execute_trace_path),
            "manual_confirmation_path": str(
                kg_retry_normalised_path or manual_confirmation_path
            )
            if (kg_retry_normalised_path or manual_confirmation_path)
            else None,
            "kg_retry_loop_report": str(output_root / "stage2_6" / "kg_retry_loop_report.json")
            if (kg_retry_response_path is not None or callable(kg_retry_adapter))
            else None,
            "kg_retry_response_path": str(kg_retry_response_path) if kg_retry_response_path else None,
            "kg_retry_adapter_used": bool(callable(kg_retry_adapter)),
            "kg_retry_adapter_source": kg_retry_adapter_source,
            "stage3": str(stage3_result.output_dir),
            "stage4": str(stage4_result.output_dir) if stage4_result is not None else None,
            "bundle_geometry_sources": [str(path) for path in bundle_geometry_sources],
        },
        "layout_layers": layers,
    }


__all__ = ["execute_road_planning_from_agent_state"]
