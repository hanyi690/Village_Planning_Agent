"""Materialize road corridors into authoritative parcel changes.

Road planning has two outputs with different geometrical meanings:

* a line feature consumed by ``PlannedRoad``; and
* polygonal land-use changes consumed by ``ParcelChangeSet``.

This module owns only the second output.  It never invents a road line and it
never expands a source BSM to an entire parcel: the caller must provide an
accepted, target-bound road line and a typed width.  All distance operations
are performed in a local metre-based CRS and returned in the source display
CRS.
"""

from __future__ import annotations

from typing import Any, Mapping

from shapely.geometry import shape
from shapely.ops import unary_union

from app.contracts.artifacts.classification_ref import (
    ClassificationRef,
    classification_code_names,
)
from app.contracts.execute.parcel_change_contracts import ParcelChange
from app.spatial.model.crs_engine import get_metric_crs, project_geometry


_ROAD_CLASSIFICATION_BY_LEVEL = {
    "公路": "1003",
    "国道": "1003",
    "省道": "1003",
    "县道": "1003",
    "乡道": "1003",
    "城镇村道路": "1004",
    "村庄道路": "1004",
    "村内道路": "1004",
    "村内交通": "1004",
    "village_road": "1006",
    "rural_road": "1006",
    "农村道路": "1006",
    "村道": "1006",
}


def _value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _crs(payload: Mapping[str, Any], default: str) -> str:
    value = payload.get("crs") or {}
    if isinstance(value, Mapping):
        properties = value.get("properties") or {}
        if isinstance(properties, Mapping):
            name = str(properties.get("name") or "").strip()
            if name:
                return name
    return default


def _feature_id(feature: Mapping[str, Any]) -> str:
    properties = feature.get("properties") or {}
    return str(
        properties.get("feature_id")
        or properties.get("source_feature_id")
        or feature.get("id")
        or ""
    ).strip()


def _target_matches(feature: Mapping[str, Any], target_id: str) -> bool:
    properties = feature.get("properties") or {}
    values = properties.get("target_ids")
    if not isinstance(values, list):
        values = [properties.get("target_id")]
    return target_id in {str(value).strip() for value in values if str(value).strip()}


def _road_features(layers: list[Mapping[str, Any]], target_id: str) -> list[Mapping[str, Any]]:
    features: list[Mapping[str, Any]] = []
    for layer in layers:
        layer_type = str(layer.get("layerType") or layer.get("layer_type") or "")
        if layer_type not in {"planned_road", "planned_road_candidates"}:
            continue
        data = layer.get("data") or layer.get("geojson") or layer
        for feature in data.get("features") or []:
            if not isinstance(feature, Mapping) or not _target_matches(feature, target_id):
                continue
            geometry = feature.get("geometry")
            if isinstance(geometry, Mapping) and str(geometry.get("type") or "") in {
                "LineString",
                "MultiLineString",
            }:
                features.append(feature)
    return features


def _road_code(target: Any, features: list[Mapping[str, Any]]) -> tuple[str, str]:
    levels = [str(_value(target, "road_level", "") or "").strip()]
    for feature in features:
        properties = feature.get("properties") or {}
        levels.append(str(
            properties.get("road_level")
            or properties.get("road_class")
            or ""
        ).strip())
    for level in levels:
        code = _ROAD_CLASSIFICATION_BY_LEVEL.get(level)
        if code:
            names = classification_code_names("gbt21010") or {}
            if code in names:
                return code, names[code]
    return "", ""


def _road_width_m(target: Any, features: list[Mapping[str, Any]]) -> float:
    for value in (
        _value(target, "roadbed_width_m"),
        _value(target, "width_m"),
        *[
            (feature.get("properties") or {}).get(key)
            for feature in features
            for key in ("roadbed_width_m", "planned_width_m", "width_m")
        ],
    ):
        try:
            width = float(value or 0)
        except (TypeError, ValueError):
            continue
        if width > 0:
            return width
    return 0.0


def _parcel_geometry(feature: Mapping[str, Any]):
    geometry = feature.get("geometry")
    if not isinstance(geometry, Mapping) or not geometry.get("type"):
        return None
    try:
        value = shape(geometry)
    except Exception:
        return None
    if value.is_empty or value.geom_type not in {"Polygon", "MultiPolygon"}:
        return None
    return value if value.is_valid else value.buffer(0)


def _parcel_classification(feature: Mapping[str, Any]) -> ClassificationRef | None:
    properties = feature.get("properties") or {}
    system = str(properties.get("DLBM_SYSTEM") or properties.get("dlbm_system") or "gbt21010")
    code = str(properties.get("DLBM") or properties.get("dlbm") or "").strip()
    names = classification_code_names(system)
    if not code or names is None or code not in names:
        return None
    return ClassificationRef(
        system=system,
        code=code,
        canonical_name=names[code],
        source="preserve",
        evidence_refs=[f"bundle:current-landuse:{str(properties.get('BSM') or properties.get('bsm') or '')}"],
    )


def materialize_road_parcel_changes(
    *,
    target: Any,
    layers: list[Mapping[str, Any]],
    landuse_payload: Mapping[str, Any],
    target_id: str,
    display_crs: str = "EPSG:4326",
    evidence_refs: list[str] | None = None,
    feature_bsms: list[str] | None = None,
    source_feature_ids: list[str] | None = None,
    l1_snapshot_ref: str = "",
    bundle_snapshot_digest: str = "",
) -> tuple[list[ParcelChange], list[dict[str, Any]]]:
    """Return transport-land parcel changes and blocking diagnostics.

    The corridor is the union of target-bound accepted line features buffered
    by half the typed roadbed width.  Each intersected source parcel is split
    into a transport polygon and an optional preserved remainder.  Missing
    typed road semantics, source classification, or geometry is reported and
    produces no partial change.
    """

    diagnostics: list[dict[str, Any]] = []
    road_features = _road_features(layers, target_id)
    if not road_features:
        return [], [{
            "code": "road_parcel_line_missing",
            "target_id": target_id,
            "message": "Road parcel materialization requires a target-bound planned road line.",
        }]
    road_code, road_name = _road_code(target, road_features)
    if not road_code:
        return [], [{
            "code": "road_transport_classification_missing",
            "target_id": target_id,
            "message": "Road level is not mapped to an explicit GB/T 21010 transport-land code.",
        }]
    width_m = _road_width_m(target, road_features)
    if width_m <= 0:
        return [], [{
            "code": "road_width_missing",
            "target_id": target_id,
            "message": "Road parcel materialization requires a positive typed roadbed width.",
        }]

    source_crs = _crs(landuse_payload, display_crs)
    landuse_features = [
        feature
        for feature in landuse_payload.get("features") or []
        if isinstance(feature, Mapping)
    ]
    lines = []
    for feature in road_features:
        try:
            line = shape(feature["geometry"])
        except Exception:
            continue
        if not line.is_empty and line.is_valid:
            lines.append(line)
    if not lines:
        return [], [{
            "code": "road_parcel_line_invalid",
            "target_id": target_id,
            "message": "Target-bound planned road geometry is empty or invalid.",
        }]

    display_line = unary_union(lines)
    metric_crs = get_metric_crs(float(display_line.representative_point().x)) if source_crs == display_crs else source_crs
    metric_line = project_geometry(display_line, source_crs, metric_crs)
    corridor_metric = metric_line.buffer(width_m / 2.0, cap_style=2, join_style=2)
    refs = list(dict.fromkeys([
        *list(evidence_refs or []),
        *[f"road-feature:{_feature_id(feature)}" for feature in road_features if _feature_id(feature)],
    ]))
    if not refs:
        return [], [{
            "code": "road_transport_classification_evidence_missing",
            "target_id": target_id,
            "message": "Transport-land materialization requires source evidence refs.",
        }]
    after = ClassificationRef(
        system="gbt21010",
        code=road_code,
        canonical_name=road_name,
        source="derived",
        evidence_refs=refs,
        decision_ref=target_id,
    )
    changes: list[ParcelChange] = []
    for feature in landuse_features:
        properties = feature.get("properties") or {}
        bsm = str(properties.get("BSM") or properties.get("bsm") or "").strip()
        parcel = _parcel_geometry(feature)
        if not bsm or parcel is None:
            continue
        parcel_source = _parcel_classification(feature)
        if parcel_source is None:
            diagnostics.append({
                "code": "road_source_classification_missing",
                "target_id": target_id,
                "bsm": bsm,
                "message": "Intersected source parcel has no valid current DLBM classification.",
            })
            continue
        parcel_metric = project_geometry(parcel, source_crs, metric_crs)
        occupied_metric = parcel_metric.intersection(corridor_metric)
        if occupied_metric.is_empty or occupied_metric.area <= 0:
            continue
        remainder_metric = parcel_metric.difference(corridor_metric)
        occupied = project_geometry(occupied_metric, metric_crs, source_crs)
        remainder = project_geometry(remainder_metric, metric_crs, source_crs)
        source_wkt = parcel.wkt
        road_bsm = f"{bsm}:road:{target_id}"
        common = {
            "derived_from_bsms": [bsm],
            "project_ref": target_id,
            "intervention_id": target_id,
            "feature_bsms": list(feature_bsms or []),
            "source_feature_ids": list(source_feature_ids or []),
            "evidence_refs": refs,
            "l1_snapshot_ref": l1_snapshot_ref,
            "bundle_snapshot_digest": bundle_snapshot_digest,
        }
        changes.append(ParcelChange(
            bsm=road_bsm,
            action="preserve" if parcel_source.code == road_code else "split",
            before_classification=parcel_source,
            after_classification=after,
            before_geometry_wkt=source_wkt,
            after_geometry_wkt=occupied.wkt,
            new_area_ha=float(occupied_metric.area / 10000.0),
            **common,
        ))
        if not remainder.is_empty and remainder.area > 0:
            changes.append(ParcelChange(
                bsm=f"{bsm}:remainder:{target_id}",
                action="preserve",
                before_classification=parcel_source,
                after_classification=parcel_source,
                before_geometry_wkt=source_wkt,
                after_geometry_wkt=remainder.wkt,
                new_area_ha=float(remainder_metric.area / 10000.0),
                **common,
            ))

    if not changes:
        diagnostics.append({
            "code": "road_corridor_no_parcel_overlap",
            "target_id": target_id,
            "message": "The accepted road corridor does not intersect any current land-use parcel.",
        })
    return changes, diagnostics


__all__ = ["materialize_road_parcel_changes"]
