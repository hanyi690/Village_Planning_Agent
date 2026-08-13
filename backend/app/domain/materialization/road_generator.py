"""Road execution adapter for the GIS EXECUTE Agent.

Migrated from agent/gis/execute/road/generator.py per docs/architecture/agent-graph.md §5.

This module bridges the agent-layer ``RoadTarget`` intent contract to the
deterministic road-planning services.  The agent does not draw road geometry
directly; it prepares structured spatial inputs, runs Stage 2.6/3 gates, and
only invokes Stage 4 when the inputs are confirmed enough for automatic routing.
"""

from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import unquote, urlparse

from app.contracts.domain.road_planning import (
    ExistingRoadPlanningInput,
    NewCorridorPlanningInput,
    RoadArtifactEvidence,
    RoadRoutingEvidence,
)
from app.domain.materialization.existing_road_materializer import (
    materialize_existing_road_interventions,
)

from app.spatial.network import (
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
from app.infrastructure.logging import get_logger
from app.spatial.network.road_candidate_preparation import (
    build_road_evidence_catalog,
    new_corridor_inputs_to_stage2_targets,
    prepare_road_candidates,
)
from app.spatial.network.terrain_grid_preparation import (
    TerrainGridPreparationError,
    prepare_terrain_friction_grid,
)


logger = get_logger(__name__)


def _project_root() -> Path:
    """Resolve the repository root; parents[6] over-shoots to the drive root."""
    try:
        from app.core.settings import PROJECT_ROOT

        if PROJECT_ROOT:
            return PROJECT_ROOT
    except Exception:
        pass
    return Path(__file__).resolve().parents[4]


def _road_output_root() -> Path:
    """Road planning artifacts live under the session run tmp root (isolated)."""
    try:
        from app.infrastructure.paths import run_tmp_root

        return run_tmp_root() / "road"
    except Exception:
        return _project_root() / "output" / "gis-agent-road"


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

    def add_demand(
        name: str,
        geometry: Optional[Dict[str, Any]],
        project_id: str,
        role: str,
        evidence: str,
        endpoint_evidence: Optional[Mapping[str, Any]] = None,
    ) -> str:
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
                        **(
                            {
                                "endpoint_entity_ref": endpoint_evidence.get("entity_ref"),
                                "source_artifact_ref": endpoint_evidence.get("source_artifact_ref"),
                                "source_feature_id": endpoint_evidence.get("source_feature_id"),
                                "evidence_refs": endpoint_evidence.get("evidence_refs") or [],
                            }
                            if endpoint_evidence
                            else {}
                        ),
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
            or f"RP-TARGET-{index:04d}"
        )
        typed_contract = target.get("typed_contract_version") == "road-planning-input-v1"
        connects = [str(item) for item in target.get("connects") or [] if str(item or "").strip()]
        path_bsms = [str(item) for item in target.get("path_bsms") or [] if str(item or "").strip()]
        candidate_bsms = [str(item) for item in target.get("candidate_bsms") or [] if str(item or "").strip()]
        candidate_bbox = target.get("candidate_bbox") or target.get("bbox")
        start_endpoint = target.get("start_endpoint") if typed_contract else None
        end_endpoint = target.get("end_endpoint") if typed_contract else None
        if typed_contract:
            if not isinstance(start_endpoint, Mapping) or not isinstance(end_endpoint, Mapping):
                raise ValueError("typed new-corridor input requires endpoint evidence")
            start_name = str(
                start_endpoint.get("entity_ref")
                or start_endpoint.get("source_feature_id")
                or ""
            ).strip()
            end_name = str(
                end_endpoint.get("entity_ref")
                or end_endpoint.get("source_feature_id")
                or ""
            ).strip()
            if not start_name or not end_name:
                raise ValueError("typed new-corridor endpoint is missing an auditable id")
        else:
            start_name = connects[0] if connects else f"{project_id}-start"
            end_name = connects[1] if len(connects) > 1 else f"{project_id}-end"
        start_geometry = _point_geometry(target.get("start_anchor"))
        end_geometry = _point_geometry(target.get("end_anchor"))
        evidence = _semantic_text(target)
        action = str(target.get("action") or "").strip() or _infer_action(evidence)
        if typed_contract and not (start_geometry and end_geometry):
            raise ValueError("typed new-corridor input requires two resolved coordinates")
        start_demand_id = add_demand(
            start_name,
            start_geometry,
            project_id,
            "start",
            evidence,
            start_endpoint if isinstance(start_endpoint, Mapping) else None,
        )
        end_demand_id = add_demand(
            end_name,
            end_geometry,
            project_id,
            "end",
            evidence,
            end_endpoint if isinstance(end_endpoint, Mapping) else None,
        )
        projects.append(
            {
                "project_id": project_id,
                "target_id": target.get("target_id") or project_id,
                "typed_contract_version": target.get("typed_contract_version"),
                "road_planning_kind": target.get("road_planning_kind"),
                "name": evidence or f"{start_name}-{end_name}",
                "action": action,
                "road_class": target.get("road_level") or "village_road",
                "recommended_road_class": target.get("road_level") or "village_road",
                "recommended_width_m": float(
                    target.get("pavement_width_m")
                    or target.get("roadbed_width_m")
                    or target.get("width_m")
                    or 0
                ) or None,
                "planned_length_m": target.get("length_m"),
                "start_place": start_name,
                "end_place": end_name,
                "start_demand_id": start_demand_id,
                "end_demand_id": end_demand_id,
                "start_geometry": start_geometry,
                "end_geometry": end_geometry,
                "start_endpoint_evidence": start_endpoint,
                "end_endpoint_evidence": end_endpoint,
                "routing_evidence": target.get("routing_evidence") if typed_contract else None,
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
    stage2_schema_version = (
        "road-planning-input-v1"
        if road_targets
        and all(
            target.get("typed_contract_version") == "road-planning-input-v1"
            for target in road_targets
        )
        else "agent-parse-adapter-v1"
    )
    _write_json(
        stage2_dir / "road_projects.json",
        {
            "type": "RoadProjectCollection",
            "schema_version": stage2_schema_version,
            "projects": projects,
        },
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
                from app.infrastructure.kg import require_session_kg

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


def _partition_stage4_candidates(
    payload: Mapping[str, Any],
    target_ids: set[str],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Separate L3 target candidates from global network-repair diagnostics."""

    target_features: List[Dict[str, Any]] = []
    rejected_target_features: List[Dict[str, Any]] = []
    network_features: List[Dict[str, Any]] = []
    for feature in payload.get("features") or []:
        if not isinstance(feature, Mapping):
            continue
        properties = feature.get("properties") or {}
        feature_targets: set[str] = set()
        if isinstance(properties, Mapping):
            raw_targets = properties.get("target_ids")
            if isinstance(raw_targets, (list, tuple, set)):
                feature_targets.update(str(value) for value in raw_targets if str(value))
            target_id = str(properties.get("target_id") or "")
            if target_id:
                feature_targets.add(target_id)
        if feature_targets & target_ids:
            destination = (
                rejected_target_features
                if str(properties.get("screening_status") or "")
                == "rejected_hard_constraint"
                else target_features
            )
        else:
            destination = network_features
        destination.append(dict(feature))

    def collection(features: List[Dict[str, Any]], name: str) -> Dict[str, Any]:
        result = dict(payload)
        result["name"] = name
        result["features"] = features
        return result

    return (
        collection(target_features, "target_bound_road_candidates"),
        collection(rejected_target_features, "rejected_target_road_candidates"),
        collection(network_features, "network_improvement_diagnostics"),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _workspace_dem_evidence(workspace: Any) -> Tuple[Optional[Path], Optional[RoadArtifactEvidence]]:
    """Return only a real DEM exposed by the typed workspace."""

    rasters = getattr(workspace, "rasters", None)
    dem = getattr(rasters, "dem", None)
    raw_path = dem.get("path") if isinstance(dem, Mapping) else getattr(dem, "path", "")
    if not str(raw_path or "").strip():
        return None, None
    path = Path(str(raw_path)).expanduser().resolve()
    if not path.is_file():
        logger.warning("[road_execute] Workspace DEM does not exist: %s", path)
        return None, None
    try:
        import rasterio

        with rasterio.open(path) as dataset:
            if dataset.count < 1 or dataset.crs is None or dataset.width < 2 or dataset.height < 2:
                raise ValueError("DEM has no usable band, CRS, or grid")
    except Exception as exc:
        logger.warning("[road_execute] Workspace DEM is not a usable raster: %s", exc)
        return None, None
    return path, RoadArtifactEvidence(
        role="dem",
        artifact_ref=path.as_uri(),
        checksum=_sha256_file(path),
    )


def _artifact_local_path(evidence: RoadArtifactEvidence) -> Optional[Path]:
    value = evidence.artifact_ref.strip()
    parsed = urlparse(value)
    if parsed.scheme == "file":
        raw_path = unquote(parsed.path)
        if parsed.netloc:
            raw_path = f"//{parsed.netloc}{raw_path}"
        if re.fullmatch(r"/[A-Za-z]:/.*", raw_path):
            raw_path = raw_path[1:]
        path = Path(raw_path)
    elif not parsed.scheme:
        path = Path(value)
    else:
        return None
    return path.expanduser().resolve()


def _verified_terrain_grid_path(
    planning_inputs: Sequence[NewCorridorPlanningInput],
) -> Optional[Path]:
    """Resolve a real Stage-4 NPZ cost grid from typed artifact evidence.

    A raw GeoTIFF DEM is valid evidence but is not the combined terrain/friction
    grid consumed by ``terrain_router``. It is therefore never passed through
    this boundary unless the artifact itself has the required NPZ arrays.
    """

    import numpy as np

    required = {
        "elevation_m",
        "slope_deg",
        "land_cost",
        "inside_boundary",
        "x_min",
        "y_max",
        "cell_size_m",
        "metric_crs",
    }
    verified: set[Path] = set()
    for planning_input in planning_inputs:
        routing = planning_input.routing_evidence
        for evidence in (routing.land_friction, routing.dem):
            if evidence is None:
                continue
            path = _artifact_local_path(evidence)
            if path is None or not path.is_file():
                continue
            if _sha256_file(path) != evidence.checksum:
                logger.warning(
                    "[road_execute] Terrain-grid checksum mismatch: %s",
                    path,
                )
                continue
            try:
                with np.load(path, allow_pickle=False) as payload:
                    if not required.issubset(payload.files):
                        continue
                    elevation = payload["elevation_m"]
                    if elevation.ndim != 2 or min(elevation.shape) < 2:
                        continue
                    if any(payload[name].shape != elevation.shape for name in (
                        "slope_deg",
                        "land_cost",
                        "inside_boundary",
                    )):
                        continue
            except Exception:
                continue
            verified.add(path)
    if len(verified) == 1:
        return next(iter(verified))
    if len(verified) > 1:
        logger.warning(
            "[road_execute] Multiple incompatible terrain grids supplied; "
            "Stage 4 will not guess one: %s",
            sorted(str(path) for path in verified),
        )
    return None


def _typed_unresolved_items(batch: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for result in batch.results:
        if result.status != "unresolved":
            continue
        diagnostics = [item.model_dump(mode="json") for item in result.diagnostics]
        items.append(
            {
                "type": "RoadUnresolved",
                "code": "road_unresolved",
                "target_id": result.target_id,
                "planning_kind": result.planning_kind,
                "diagnostic_codes": [item["code"] for item in diagnostics],
                "diagnostics": diagnostics,
                "message": "Road planning input did not satisfy the evidence-complete contract.",
            }
        )
    return items


def _planning_input_evidence_refs(
    planning_input: NewCorridorPlanningInput,
) -> List[str]:
    refs: set[str] = set()
    for endpoint in (planning_input.start_endpoint, planning_input.end_endpoint):
        refs.update(endpoint.evidence_refs)
        refs.add(endpoint.source_artifact_ref)
    routing = planning_input.routing_evidence
    for evidence in (
        routing.current_network,
        routing.dem,
        routing.land_friction,
        routing.hazard,
        routing.spatial_constraints,
    ):
        if evidence is not None:
            refs.add(evidence.artifact_ref)
    return sorted(ref for ref in refs if ref)


def execute_road_planning_from_agent_state(state: Any) -> Dict[str, Any]:
    """Execute the road sub-task from the typed execution plan and workspace."""

    from app.domain.materialization.nodes.worker_common import _execution_intent_from_plan

    road_targets = _intent_road_targets(_execution_intent_from_plan(state))
    if not road_targets:
        return {
            "ran": False,
            "reason": "No road targets were produced by the execution plan; road sub-task skipped.",
            "layout_layers": [],
        }

    bundle = getattr(state, "spatial_workspace", None)
    if bundle is not None:
        from app.infrastructure.export.delivery_snapshot import canonical_gis_data_from_workspace

        gis_data = canonical_gis_data_from_workspace(bundle)
    else:
        raise ValueError("EXECUTE road worker requires spatial_workspace")

    output_root = (
        _road_output_root()
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
    assert roads_path is not None
    assert boundary_path is not None
    stage1_result = build_road_network(
        roads_path,
        output_root / "stage1",
        NetworkBuildConfig(display_crs="EPSG:4326"),
    )
    dem_path, dem_evidence = _workspace_dem_evidence(bundle)
    routing_evidence = RoadRoutingEvidence(dem=dem_evidence)
    catalog = build_road_evidence_catalog(
        road_edges_path=stage1_result.edges_path,
        current_roads_path=roads_path,
        routing_evidence=routing_evidence,
    )
    preparation = prepare_road_candidates(road_targets, catalog)
    preliminary_new_inputs = [
        item
        for item in preparation.ready_inputs
        if isinstance(item, NewCorridorPlanningInput)
    ]
    terrain_preparation_result = None
    if preliminary_new_inputs and dem_path is not None and landuse_path is not None:
        try:
            terrain_preparation_result = prepare_terrain_friction_grid(
                dem_path=dem_path,
                boundary_path=boundary_path,
                landuse_path=landuse_path,
                output_dir=output_root / "terrain",
            )
            routing_evidence = RoadRoutingEvidence(
                dem=dem_evidence,
                land_friction=terrain_preparation_result.evidence,
            )
            catalog = build_road_evidence_catalog(
                road_edges_path=stage1_result.edges_path,
                current_roads_path=roads_path,
                routing_evidence=routing_evidence,
            )
            preparation = prepare_road_candidates(road_targets, catalog)
        except (TerrainGridPreparationError, OSError, ValueError) as exc:
            logger.warning(
                "[road_execute] Terrain/friction grid preparation unavailable: %s",
                exc,
            )
    preparation_path = output_root / "road_candidate_preparation.json"
    _write_json(preparation_path, preparation.model_dump(mode="json"))
    unresolved_items = _typed_unresolved_items(preparation)
    existing_inputs = [
        item
        for item in preparation.ready_inputs
        if isinstance(item, ExistingRoadPlanningInput)
    ]
    new_inputs = [
        item
        for item in preparation.ready_inputs
        if isinstance(item, NewCorridorPlanningInput)
    ]
    terrain_grid_path = _verified_terrain_grid_path(new_inputs)

    existing_result = None
    layers: List[Dict[str, Any]] = []
    if existing_inputs:
        existing_result = materialize_existing_road_interventions(
            existing_inputs,
            road_edges_path=stage1_result.edges_path,
            current_roads_path=roads_path,
            output_path=output_root / "existing" / "planned_existing_roads.geojson",
        )
        for item in existing_result.diagnostics:
            unresolved_items.append(
                {
                    "type": "RoadUnresolved",
                    "code": "road_unresolved",
                    "target_id": item.get("target_id"),
                    "planning_kind": "existing_road_intervention",
                    "diagnostic_codes": [item.get("code")],
                    "diagnostics": [item],
                    "message": item.get("message"),
                }
            )
        existing_payload = _read_json(existing_result.output_path)
        if existing_payload.get("features"):
            layers.append(
                _layer_config("planned_road", existing_payload, "#dc2626", True)
            )

    stage2_dir = None
    stage2_6_result = None
    stage3_result = None
    stage4_result = None
    stage3_gate: Mapping[str, Any] = {}
    point_sources = tuple(path for path in (annotation_path,) if path is not None)
    if new_inputs:
        stage2_targets = new_corridor_inputs_to_stage2_targets(new_inputs)
        stage2_dir = _road_targets_to_stage2(stage2_targets, output_root)
        stage2_6_config = PlanningNodeBuildConfig(
            stage2_dir=stage2_dir,
            output_dir=output_root / "stage2_6",
            road_edges_path=stage1_result.edges_path,
            boundary_path=boundary_path,
            point_sources=point_sources,
            bundle_geometry_sources=bundle_geometry_sources,
            bound_spatial_entities_path=(
                Path(str(getattr(state, "bound_entities_artifact_path", "")))
                if str(getattr(state, "bound_entities_artifact_path", ""))
                and Path(str(getattr(state, "bound_entities_artifact_path", ""))).exists()
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
                    dem_grid_path=terrain_grid_path,
                    output_dir=output_root / "stage4",
                )
            )

        layers.extend(
            [
                _layer_config(
                    "road_spatial_candidates",
                    _read_json(stage2_6_result.spatial_candidates_path),
                    "#a855f7",
                    False,
                ),
                _layer_config(
                    "road_planning_entities",
                    _read_json(stage2_6_result.located_entities_path),
                    "#f59e0b",
                    False,
                ),
                _layer_config(
                    "road_planning_nodes",
                    _read_json(stage2_6_result.planning_nodes_path),
                    "#2563eb",
                    True,
                ),
            ]
        )
        if stage4_result is not None:
            candidate_payload = _read_json(stage4_result.candidates_path)
            target_payload, rejected_target_payload, network_payload = _partition_stage4_candidates(
                candidate_payload,
                {planning_input.target_id for planning_input in new_inputs},
            )
            if target_payload.get("features"):
                layers.append(
                    _layer_config(
                        "planned_road_candidates",
                        target_payload,
                        "#ef4444",
                        False,
                    )
                )
            if network_payload.get("features"):
                layers.append(
                    _layer_config(
                        "road_network_improvement_candidates",
                        network_payload,
                        "#64748b",
                        False,
                    )
                )
            if rejected_target_payload.get("features"):
                layers.append(
                    _layer_config(
                        "road_rejected_target_candidates",
                        rejected_target_payload,
                        "#991b1b",
                        False,
                    )
                )
            produced_target_ids = {
                str(target_id)
                for feature in target_payload.get("features") or []
                for properties in [feature.get("properties") or {}]
                for target_id in (
                    properties.get("target_ids")
                    if isinstance(properties.get("target_ids"), list)
                    else [properties.get("target_id")]
                )
                if str(target_id or "")
            }
            for planning_input in new_inputs:
                if planning_input.target_id in produced_target_ids:
                    continue
                rejected = [
                    feature
                    for feature in rejected_target_payload.get("features") or []
                    if str((feature.get("properties") or {}).get("target_id") or "")
                    == planning_input.target_id
                ]
                diagnostic_code = (
                    "ROAD_ALL_CANDIDATES_REJECTED"
                    if rejected
                    else "ROAD_CANDIDATE_NOT_GENERATED"
                )
                unresolved_items.append(
                    {
                        "type": "RoadUnresolved",
                        "code": "road_unresolved",
                        "target_id": planning_input.target_id,
                        "planning_kind": planning_input.planning_kind,
                        "diagnostic_codes": [diagnostic_code],
                        "evidence_refs": _planning_input_evidence_refs(planning_input),
                        "diagnostics": [
                            {
                                "candidate_id": (feature.get("properties") or {}).get("candidate_id"),
                                "screening_status": (feature.get("properties") or {}).get("screening_status"),
                                "hard_violations": (feature.get("properties") or {}).get("hard_violations") or [],
                            }
                            for feature in rejected
                        ],
                        "message": (
                            "All target-bound Stage 4 candidates were rejected by hard constraints."
                            if rejected
                            else "Stage 4 produced no candidate for this typed new corridor."
                        ),
                    }
                )
        else:
            for planning_input in new_inputs:
                unresolved_items.append(
                    {
                        "type": "RoadUnresolved",
                        "code": "road_unresolved",
                        "target_id": planning_input.target_id,
                        "planning_kind": planning_input.planning_kind,
                        "diagnostic_codes": ["ROAD_STAGE3_GATE_BLOCKED"],
                        "evidence_refs": _planning_input_evidence_refs(planning_input),
                        "diagnostics": [],
                        "message": str(
                            stage3_gate.get("reason")
                            or "Stage 3 did not authorize automatic corridor generation."
                        ),
                    }
                )

    return {
        "ran": True,
        "reason": (
            None
            if layers
            else "No road target passed the evidence-complete road planning contract."
        ),
        "output_dir": str(output_root),
        "road_target_count": len(road_targets),
        "ready_existing_target_count": len(existing_inputs),
        "ready_new_corridor_target_count": len(new_inputs),
        "unresolved_target_count": len(unresolved_items),
        "unresolved_items": unresolved_items,
        "road_candidate_preparation": preparation.model_dump(mode="json"),
        "existing_road_materialization_report": (
            existing_result.report if existing_result is not None else None
        ),
        "stage1_report": stage1_result.report,
        "stage2_6_report": stage2_6_result.report if stage2_6_result else None,
        "stage2_6_trace": (
            _read_json(stage2_6_result.execute_trace_path) if stage2_6_result else None
        ),
        "stage2_6_iteration_records": (
            _read_json(stage2_6_result.iteration_records_path)
            if stage2_6_result
            else None
        ),
        "stage2_6_quality_gates": (
            _read_json(stage2_6_result.quality_gates_path) if stage2_6_result else None
        ),
        "stage2_6_human_confirmation_template": (
            _read_json(stage2_6_result.human_confirmation_template_path)
            if stage2_6_result
            else None
        ),
        "stage2_6_kg_retry_requests": (
            _read_json(stage2_6_result.kg_retry_requests_path)
            if stage2_6_result
            else None
        ),
        "stage3_report": stage3_result.report if stage3_result else None,
        "stage4_report": stage4_result.report if stage4_result is not None else None,
        "automatic_route_generation_allowed": (
            bool(stage3_gate.get("automatic_route_generation_allowed"))
            if new_inputs
            else None
        ),
        "blocked_reason": (
            None
            if not new_inputs or stage3_gate.get("automatic_route_generation_allowed")
            else stage3_gate.get("reason")
        ),
        "routing_evidence": catalog.routing_evidence.model_dump(mode="json"),
        "terrain_grid_preparation_report": (
            terrain_preparation_result.report
            if terrain_preparation_result is not None
            else None
        ),
        "artifacts": {
            "road_candidate_preparation": str(preparation_path),
            "stage1": str(stage1_result.output_dir),
            "existing_road": (
                str(existing_result.output_path) if existing_result is not None else None
            ),
            "existing_road_materialization_report": (
                str(existing_result.report_path) if existing_result is not None else None
            ),
            "stage2": str(stage2_dir) if stage2_dir else None,
            "stage2_6": str(stage2_6_result.output_dir) if stage2_6_result else None,
            "spatial_candidates": (
                str(stage2_6_result.spatial_candidates_path) if stage2_6_result else None
            ),
            "spatial_quality_gates": (
                str(stage2_6_result.quality_gates_path) if stage2_6_result else None
            ),
            "human_confirmation_template": (
                str(stage2_6_result.human_confirmation_template_path)
                if stage2_6_result
                else None
            ),
            "iteration_records": (
                str(stage2_6_result.iteration_records_path) if stage2_6_result else None
            ),
            "kg_retry_requests": (
                str(stage2_6_result.kg_retry_requests_path) if stage2_6_result else None
            ),
            "spatial_preprocessing_trace": (
                str(stage2_6_result.execute_trace_path) if stage2_6_result else None
            ),
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
            "stage3": str(stage3_result.output_dir) if stage3_result else None,
            "stage4": str(stage4_result.output_dir) if stage4_result is not None else None,
            "dem": str(dem_path) if dem_path else None,
            "terrain_routing_grid": (
                str(terrain_grid_path) if terrain_grid_path else None
            ),
            "terrain_grid_preparation_report": (
                str(terrain_preparation_result.report_path)
                if terrain_preparation_result is not None
                else None
            ),
            "bundle_geometry_sources": [str(path) for path in bundle_geometry_sources],
        },
        "layout_layers": layers,
    }


__all__ = ["execute_road_planning_from_agent_state"]
