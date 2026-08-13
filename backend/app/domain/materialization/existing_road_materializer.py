"""Materialize verified interventions on authoritative current-road geometry.

This is deliberately not a route generator. Upgrade, widening, hardening, and
repair retain the selected current-road feature/Stage-1 segment geometry and
attach planning lineage. Missing identifiers remain diagnostics; no neighbour,
village-wide, or random road is substituted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform as shapely_transform

from app.contracts.domain.road_planning import ExistingRoadPlanningInput


@dataclass(frozen=True)
class ExistingRoadMaterializationResult:
    output_path: Path
    report_path: Path
    report: dict[str, Any]
    diagnostics: list[dict[str, Any]]


def _read_collection(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise ValueError(f"Road artifact is not a FeatureCollection: {path}")
    if not isinstance(payload.get("features") or [], list):
        raise ValueError(f"Road artifact has invalid features: {path}")
    return payload


def _collection_crs(payload: Mapping[str, Any], fallback: str) -> str:
    crs = payload.get("crs") or {}
    if isinstance(crs, Mapping):
        properties = crs.get("properties") or {}
        if isinstance(properties, Mapping):
            value = str(properties.get("name") or "").strip()
            if value:
                return value
    return fallback


def _feature_id(feature: Mapping[str, Any]) -> str:
    properties = feature.get("properties") or {}
    if not isinstance(properties, Mapping):
        properties = {}
    return str(
        properties.get("bsm")
        or properties.get("BSM")
        or properties.get("feature_id")
        or feature.get("id")
        or ""
    ).strip()


def _segment_id(feature: Mapping[str, Any]) -> str:
    properties = feature.get("properties") or {}
    if not isinstance(properties, Mapping):
        return ""
    return str(properties.get("edge_id") or "").strip()


def _geometry_in_crs(
    geometry: Mapping[str, Any],
    source_crs: str,
    display_crs: str,
) -> dict[str, Any]:
    value = shape(geometry)
    if source_crs != display_crs:
        transformer = Transformer.from_crs(source_crs, display_crs, always_xy=True)
        value = shapely_transform(transformer.transform, value)
    return mapping(value)


def _planned_properties(
    planning_input: ExistingRoadPlanningInput,
    *,
    source_feature_id: str = "",
    source_segment_id: str = "",
) -> dict[str, Any]:
    network = planning_input.routing_evidence.current_network
    return {
        "target_id": planning_input.target_id,
        "target_ids": [planning_input.target_id],
        "source_project_id": planning_input.source_project_id,
        "road_planning_kind": planning_input.planning_kind,
        "action": planning_input.action,
        "construction_action": planning_input.action,
        "road_level": planning_input.road_level,
        "planned_length_m": planning_input.length_m,
        "roadbed_width_m": planning_input.roadbed_width_m,
        "pavement_width_m": planning_input.pavement_width_m,
        "source_road_feature_id": source_feature_id or None,
        "source_road_segment_id": source_segment_id or None,
        "source_network_artifact_ref": network.artifact_ref if network else None,
        "source_network_checksum": network.checksum if network else None,
        "road_evidence_refs": planning_input.road_evidence_refs,
        "materialization_method": "authoritative_current_road_geometry",
        "geometry_changed": False,
        "is_construction_design": False,
    }


def _diagnostic(
    planning_input: ExistingRoadPlanningInput,
    code: str,
    message: str,
    identifier: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "error",
        "target_id": planning_input.target_id,
        "source_project_id": planning_input.source_project_id,
        "identifier": identifier,
        "message": message,
    }


def materialize_existing_road_interventions(
    planning_inputs: Sequence[ExistingRoadPlanningInput],
    *,
    road_edges_path: str | Path,
    current_roads_path: str | Path,
    output_path: str | Path,
    display_crs: str = "EPSG:4326",
) -> ExistingRoadMaterializationResult:
    """Write planned intervention lines for exactly the verified road ids."""

    edges_path = Path(road_edges_path).expanduser().resolve()
    roads_path = Path(current_roads_path).expanduser().resolve()
    destination = Path(output_path).expanduser().resolve()
    edge_payload = _read_collection(edges_path)
    road_payload = _read_collection(roads_path)
    edge_crs = _collection_crs(edge_payload, "EPSG:4527")
    road_crs = _collection_crs(road_payload, display_crs)
    edge_index = {
        identifier: feature
        for feature in edge_payload.get("features") or []
        if isinstance(feature, Mapping) and (identifier := _segment_id(feature))
    }
    road_index = {
        identifier: feature
        for feature in road_payload.get("features") or []
        if isinstance(feature, Mapping) and (identifier := _feature_id(feature))
    }

    features: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for planning_input in planning_inputs:
        # Segment ids are the more precise contract. Feature ids are used only
        # when no Stage-1 segment selection was supplied.
        if planning_input.existing_road_segment_ids:
            bindings = (
                ("segment", identifier)
                for identifier in planning_input.existing_road_segment_ids
            )
        else:
            bindings = (
                ("feature", identifier)
                for identifier in planning_input.existing_road_feature_ids
            )
        for binding_kind, identifier in bindings:
            source = edge_index.get(identifier) if binding_kind == "segment" else road_index.get(identifier)
            if source is None:
                code = (
                    "ROAD_EXISTING_SEGMENT_MATERIALIZATION_MISSING"
                    if binding_kind == "segment"
                    else "ROAD_EXISTING_FEATURE_MATERIALIZATION_MISSING"
                )
                diagnostics.append(
                    _diagnostic(
                        planning_input,
                        code,
                        f"Verified current-road {binding_kind} {identifier!r} was not found during materialization.",
                        identifier,
                    )
                )
                continue
            geometry = source.get("geometry")
            if not isinstance(geometry, Mapping):
                diagnostics.append(
                    _diagnostic(
                        planning_input,
                        "ROAD_EXISTING_GEOMETRY_MISSING",
                        f"Verified current-road {binding_kind} {identifier!r} has no geometry.",
                        identifier,
                    )
                )
                continue
            source_crs = edge_crs if binding_kind == "segment" else road_crs
            feature_index = len(features) + 1
            features.append(
                {
                    "type": "Feature",
                    "id": f"PR-EXISTING-{feature_index:05d}",
                    "geometry": _geometry_in_crs(geometry, source_crs, display_crs),
                    "properties": _planned_properties(
                        planning_input,
                        source_feature_id=identifier if binding_kind == "feature" else "",
                        source_segment_id=identifier if binding_kind == "segment" else "",
                    ),
                }
            )

    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "FeatureCollection",
        "name": "planned_existing_road_interventions",
        "crs": {"type": "name", "properties": {"name": display_crs}},
        "features": features,
    }
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    target_count = len(planning_inputs)
    materialized_targets = sorted(
        {
            str((feature.get("properties") or {}).get("target_id"))
            for feature in features
        }
    )
    report = {
        "schema_version": "road-existing-materialization-v1",
        "status": "pass" if not diagnostics else "partial",
        "input_target_count": target_count,
        "materialized_target_count": len(materialized_targets),
        "materialized_target_ids": materialized_targets,
        "materialized_feature_count": len(features),
        "diagnostic_count": len(diagnostics),
        "road_edges_path": str(edges_path),
        "current_roads_path": str(roads_path),
        "rule": "exact verified segment ids, otherwise exact verified feature ids; no fallback",
    }
    report_path = destination.with_name("existing_road_materialization_report.json")
    report_path.write_text(
        json.dumps(
            {**report, "diagnostics": diagnostics},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return ExistingRoadMaterializationResult(
        output_path=destination,
        report_path=report_path,
        report=report,
        diagnostics=diagnostics,
    )


__all__ = [
    "ExistingRoadMaterializationResult",
    "materialize_existing_road_interventions",
]
