"""Build the authoritative complete spatial view at the delivery boundary."""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from app.modules.schema.contracts.spatial_delivery_contracts import (
    DeliverySpatialSnapshot,
    SpatialLayerRef,
)

from app.infrastructure.gis.spatial_data_port import LocalSpatialDataPort, SpatialDataPort


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _as_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, Mapping):
        return dict(item)
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    return {}


def _normalize_feature_collection(
    payload: Mapping[str, Any],
    *,
    drop_zero_origin_points: bool = False,
) -> dict[str, Any]:
    """Normalize GeoJSON once at the data-to-delivery boundary.

    The renderer must receive valid geometry and must never turn missing
    coordinates into a visual point.  Invalid source polygons are repaired
    with Shapely's deterministic ``make_valid``; an unrecoverable feature
    fails the snapshot build instead of producing a misleading artifact.
    """
    normalized = copy.deepcopy(dict(payload))
    features: list[dict[str, Any]] = []
    for feature in payload.get("features") or []:
        item = copy.deepcopy(dict(feature))
        geometry = item.get("geometry")
        if geometry is None:
            features.append(item)
            continue
        try:
            from shapely.geometry import mapping, shape
            from shapely.validation import make_valid

            parsed = shape(geometry)
            if (
                drop_zero_origin_points
                and parsed.geom_type == "Point"
                and tuple(parsed.coords)[0] == (0.0, 0.0)
            ):
                continue
            if parsed.is_empty:
                raise ValueError("empty geometry")
            if not parsed.is_valid:
                parsed = make_valid(parsed)
            if parsed is None or parsed.is_empty or not parsed.is_valid:
                raise ValueError("geometry remains invalid after make_valid")
            item["geometry"] = mapping(parsed)
        except Exception as exc:
            raise ValueError("delivery input contains unrecoverable geometry") from exc
        features.append(item)
    normalized["features"] = features
    return normalized


def _feature_bsm(feature: Mapping[str, Any]) -> str:
    properties = feature.get("properties") or {}
    for key, value in properties.items():
        if str(key).lower() == "bsm":
            return "" if value is None else str(value)
    return ""


def _source_bsms(change: Any) -> list[str]:
    action = str(_value(change, "action", "modify") or "modify").lower()
    source = _value(change, "derived_from_bsms", None)
    if source is None:
        source = _value(change, "source_bsms", None)
    if not source and action not in {"create", "add"}:
        source = [_value(change, "bsm", "")]
    if isinstance(source, str):
        source = [source]
    return list(dict.fromkeys(str(value) for value in source if str(value)))


def _geometry_from_change(change: Any) -> Any:
    geometry = _value(change, "after_geometry", None)
    if isinstance(geometry, Mapping):
        return copy.deepcopy(dict(geometry))
    geometry_wkt = str(_value(change, "after_geometry_wkt", "") or "")
    if not geometry_wkt:
        return None
    try:
        from shapely import wkt as shapely_wkt
        from shapely.geometry import mapping

        parsed = shapely_wkt.loads(geometry_wkt)
        if parsed.is_empty:
            return None
        return mapping(parsed)
    except Exception as exc:
        raise ValueError("planned change contains invalid after_geometry_wkt") from exc


def _classification_properties(change: Any) -> dict[str, Any]:
    classification = _value(change, "after_classification", None)
    values = _as_dict(classification)
    if not values:
        return {}
    result = {}
    for key in ("system", "code", "canonical_name", "name"):
        if values.get(key) not in (None, ""):
            result[f"planning_{key}"] = values[key]
    return result


def _change_status(action: str) -> str:
    return {
        "modify": "modified",
        "reclassify": "modified",
        "split": "split",
        "merge": "merged",
        "create": "created",
        "remove": "removed",
    }.get(action, "modified")


def _changed_feature(change: Any, base: Mapping[str, Any] | None) -> dict[str, Any] | None:
    action = str(_value(change, "action", "modify") or "modify").lower()
    if action in {"remove", "delete"}:
        return None
    feature = copy.deepcopy(dict(base)) if base is not None else {
        "type": "Feature",
        "properties": {},
        "geometry": None,
    }
    properties = dict(feature.get("properties") or {})
    bsm = str(_value(change, "bsm", "") or "")
    if bsm:
        properties["BSM"] = bsm
    source_bsms = _source_bsms(change)
    if source_bsms:
        properties["source_bsms"] = source_bsms
    properties["change_status"] = _change_status(action)
    properties["provenance"] = "delivery_spatial_snapshot"
    properties.update(_classification_properties(change))
    feature["properties"] = properties
    geometry = _geometry_from_change(change)
    if geometry is not None:
        feature["geometry"] = geometry
    return feature


def _bounds(features: list[dict[str, Any]]) -> tuple[float, float, float, float] | None:
    try:
        from shapely.geometry import shape

        geometries = [shape(feature["geometry"]) for feature in features if feature.get("geometry")]
        geometries = [geometry for geometry in geometries if not geometry.is_empty]
        if not geometries:
            return None
        minx = min(geometry.bounds[0] for geometry in geometries)
        miny = min(geometry.bounds[1] for geometry in geometries)
        maxx = max(geometry.bounds[2] for geometry in geometries)
        maxy = max(geometry.bounds[3] for geometry in geometries)
        return minx, miny, maxx, maxy
    except Exception:
        return None


def _layer_ref_for_output(
    source_ref: SpatialLayerRef,
    features: list[dict[str, Any]],
    output_path: Path,
    output_artifact_ref: str | None,
    planned_landuse_ref: SpatialLayerRef | None,
) -> SpatialLayerRef:
    properties = [feature.get("properties") or {} for feature in features]
    fields = sorted({str(key) for item in properties for key in item})
    payload = {"type": "FeatureCollection", "features": features}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(raw)
    checksum = hashlib.sha256(raw).hexdigest()
    base = planned_landuse_ref or source_ref
    return base.model_copy(
        update={
            "artifact_ref": output_artifact_ref or base.artifact_ref + ":planned",
            "path": str(output_path),
            "layer_name": "complete_planned_landuse",
            "driver": "GeoJSON",
            "bbox": _bounds(features),
            "fields": fields,
            "feature_count": len(features),
            "checksum": checksum,
        }
    )


def _unique_refs(refs: Iterable[SpatialLayerRef]) -> list[SpatialLayerRef]:
    result: dict[str, SpatialLayerRef] = {}
    for ref in refs:
        result.setdefault(ref.artifact_ref, ref)
    return list(result.values())


def _geojson_change(feature: Mapping[str, Any]) -> dict[str, Any]:
    properties = dict(feature.get("properties") or {})
    status = str(properties.get("change_status") or "modified").lower()
    action = {
        "preserved": "preserve",
        "unchanged": "preserve",
        "created": "create",
        "split": "split",
        "merged": "merge",
    }.get(status, "modify")
    source_bsms = properties.get("source_bsms") or properties.get("source_bsm")
    if isinstance(source_bsms, str):
        source_bsms = [source_bsms]
    if not source_bsms and action != "create" and properties.get("BSM"):
        source_bsms = [str(properties["BSM"])]
    return {
        "bsm": str(properties.get("BSM") or properties.get("bsm") or ""),
        "action": action,
        "derived_from_bsms": list(source_bsms or []),
        "after_geometry": copy.deepcopy(feature.get("geometry")),
    }


def _write_source_layer(
    output_dir: Path,
    key: str,
    payload: Mapping[str, Any],
    *,
    drop_zero_origin_points: bool = False,
) -> SpatialLayerRef:
    payload = _normalize_feature_collection(
        payload,
        drop_zero_origin_points=drop_zero_origin_points,
    )
    source_path = output_dir / "sources" / f"{key}.geojson"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    source_path.write_bytes(raw)
    features = list(payload.get("features") or [])
    fields = sorted({str(field) for feature in features for field in (feature.get("properties") or {})})

    return SpatialLayerRef(
        artifact_ref=f"delivery-source:{key}",
        path=str(source_path),
        layer_name=key,
        driver="GeoJSON",
        fields=fields,
        feature_count=len(features),
        bbox=_bounds(features),
        checksum=hashlib.sha256(raw).hexdigest(),
    )


def canonical_gis_data_from_workspace(workspace: Any) -> dict[str, Any]:
    """Materialize the canonical GIS input at the data-layer boundary.

    Agents pass the typed workspace; they must not manufacture or repair GIS layers.
    A missing current land-use layer is an input-quality error, not a reason
    to reinterpret an EXECUTE result as the current state.
    """
    if workspace is None or not hasattr(workspace, "to_delivery_inputs"):
        raise ValueError("delivery requires a SpatialWorkspace")
    gis_data = workspace.to_delivery_inputs()
    if not isinstance(gis_data, dict):
        raise ValueError("SpatialWorkspace did not produce a GIS mapping")
    current = gis_data.get("landuse_current_geojson")
    if not isinstance(current, Mapping) or not current.get("features"):
        raise ValueError("delivery bundle lacks landuse_current_geojson")
    return gis_data


def build_delivery_spatial_snapshot_from_gis_data(
    gis_data: Mapping[str, Any],
    *,
    planned_geojson: Mapping[str, Any] | None = None,
    planned_changes: Iterable[Any] = (),
    output_dir: str | Path,
    output_artifact_ref: str = "delivery-spatial-snapshot",
    provenance: Mapping[str, Any] | None = None,
) -> DeliverySpatialSnapshot:
    """Create a delivery snapshot from in-memory bundle layers.

    This adapter is intended for DELIVER only.  It writes immutable source
    layer copies and the complete planned layer under the session run folder;
    callers persist only the typed snapshot reference in workflow state.
    """
    root = Path(output_dir)
    source_refs: dict[str, SpatialLayerRef] = {}
    planned_overlay_names = {
        "planned_project_geojson",
        "planned_project_point_geojson",
        "planned_facility_geojson",
        "planned_road_geojson",
        "planned_axis_geojson",
        "planned_zone_geojson",
        "planned_restoration_geojson",
        "planned_protection_geojson",
    }
    for key, payload in (gis_data or {}).items():
        if not str(key).endswith("_geojson") or not isinstance(payload, Mapping):
            continue
        if payload.get("type") != "FeatureCollection":
            continue
        source_refs[str(key)] = _write_source_layer(
            root,
            str(key),
            payload,
            drop_zero_origin_points=str(key) in planned_overlay_names,
        )
    current_ref = source_refs.get("landuse_current_geojson")
    if current_ref is None:
        raise ValueError("delivery snapshot requires landuse_current_geojson")

    changes = list(planned_changes)
    if not changes and planned_geojson and planned_geojson.get("features"):
        changes = [_geojson_change(feature) for feature in planned_geojson["features"]]
    constraint_names = {
        "ecological_redline_geojson",
        "farmland_protection_geojson",
        "historical_protection_geojson",
        "construction_zone_geojson",
        "hazard_points_geojson",
    }
    planned_overlay_names = {
        "planned_project_geojson",
        "planned_project_point_geojson",
        "planned_facility_geojson",
        "planned_road_geojson",
        "planned_axis_geojson",
        "planned_zone_geojson",
        "planned_restoration_geojson",
        "planned_protection_geojson",
    }
    planned_overlays = {
        key: ref for key, ref in source_refs.items() if key in planned_overlay_names
    }
    current_sources = {
        key: ref for key, ref in source_refs.items() if key not in planned_overlay_names
    }
    constraints = {
        key: ref for key, ref in source_refs.items() if key in constraint_names
    }
    return build_delivery_spatial_snapshot(
        current_ref,
        changes,
        output_path=root / "planned" / "complete_planned_landuse.geojson",
        output_artifact_ref=output_artifact_ref,
        current_layers=current_sources,
        planned_overlay_layers=planned_overlays,
        constraint_layers=constraints,
        provenance={"source": "gis_data_delivery_boundary", **dict(provenance or {})},
    )


def load_complete_planned_geojson(snapshot: DeliverySpatialSnapshot) -> dict[str, Any]:
    """Load the complete planned layer referenced by a local snapshot."""
    ref = snapshot.complete_planned_landuse
    if ref is None:
        raise ValueError("delivery snapshot has no complete_planned_landuse reference")
    payload = json.loads(Path(ref.path).read_text(encoding="utf-8"))
    if payload.get("type") != "FeatureCollection":
        raise ValueError("complete planned artifact is not a FeatureCollection")
    return payload


def load_snapshot_gis_data(snapshot: DeliverySpatialSnapshot) -> dict[str, Any]:
    """Load all source layers referenced by a delivery snapshot."""
    data: dict[str, Any] = {}
    refs = [*snapshot.current_layers.values(), *snapshot.constraint_layers.values()]
    for ref in _unique_refs(refs):
        payload = json.loads(Path(ref.path).read_text(encoding="utf-8"))
        if payload.get("type") == "FeatureCollection":
            data[ref.layer_name] = payload
    return data


def load_snapshot_planned_overlays(snapshot: DeliverySpatialSnapshot) -> dict[str, Any]:
    """Load only planned overlay layers from the authoritative snapshot."""
    data: dict[str, Any] = {}
    for key, ref in snapshot.planned_overlay_layers.items():
        payload = json.loads(Path(ref.path).read_text(encoding="utf-8"))
        if payload.get("type") == "FeatureCollection":
            data[key] = payload
    return data


def build_delivery_spatial_snapshot(
    current_landuse_ref: SpatialLayerRef,
    planned_changes: Iterable[Any] = (),
    *,
    data_port: SpatialDataPort | None = None,
    output_path: str | Path | None = None,
    output_artifact_ref: str | None = None,
    planned_landuse_ref: SpatialLayerRef | None = None,
    current_layers: Mapping[str, SpatialLayerRef] | None = None,
    planned_overlay_layers: Mapping[str, SpatialLayerRef] | None = None,
    constraint_layers: Mapping[str, SpatialLayerRef] | None = None,
    classification_audit: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
    delivery_status: str | None = None,
    statutory_complete: bool = False,
) -> DeliverySpatialSnapshot:
    """Materialize a complete planned land-use layer and return its snapshot.

    The source layer is read in full only here, at the delivery boundary.  All
    earlier stages can use ``SpatialLayerRef`` and bounded ``FeatureBatch``
    objects without carrying the complete source GeoJSON or WKT through state.
    """
    port = data_port or LocalSpatialDataPort()
    current = port.materialize(current_landuse_ref)
    if not current.complete:
        raise ValueError("delivery snapshot requires a complete current land-use batch")

    base_features = [copy.deepcopy(feature) for feature in current.features]
    by_bsm = {_feature_bsm(feature): feature for feature in base_features if _feature_bsm(feature)}
    changes = list(planned_changes)
    touched_bsms: set[str] = set()
    features_by_source: dict[str, list[dict[str, Any]]] = {}
    created_features: list[dict[str, Any]] = []
    counts = {"preserved": 0, "modified": 0, "split": 0, "merged": 0, "created": 0, "removed": 0}

    for change in changes:
        action = str(_value(change, "action", "modify") or "modify").lower()
        source_bsms = _source_bsms(change)
        known_sources = [bsm for bsm in source_bsms if bsm in by_bsm]
        if action == "preserve":
            continue
        touched_bsms.update(known_sources)
        base = by_bsm.get(known_sources[0]) if known_sources else None
        changed = _changed_feature(change, base)
        if action in {"remove", "delete"}:
            counts["removed"] += len(known_sources) or 1
            continue
        counts[_change_status(action)] = counts.get(_change_status(action), 0) + 1
        if known_sources:
            features_by_source.setdefault(known_sources[0], []).append(changed)  # type: ignore[arg-type]
        elif changed is not None:
            created_features.append(changed)

    output_features: list[dict[str, Any]] = []
    for feature in base_features:
        bsm = _feature_bsm(feature)
        replacements = features_by_source.get(bsm)
        if replacements:
            output_features.extend(replacements)
            continue
        if bsm in touched_bsms:
            continue
        preserved = copy.deepcopy(feature)
        properties = dict(preserved.get("properties") or {})
        properties["change_status"] = "preserved"
        if bsm:
            properties["source_bsms"] = [bsm]
        properties["provenance"] = "delivery_spatial_snapshot"
        preserved["properties"] = properties
        output_features.append(preserved)
        counts["preserved"] += 1
    output_features.extend(created_features)
    counts["source_feature_count"] = len(base_features)
    counts["source_bsm_covered"] = len(touched_bsms)
    counts["planned_feature_count"] = len(output_features)

    if output_path is None and planned_landuse_ref is None:
        raise ValueError("output_path or planned_landuse_ref is required for delivery materialization")
    target_path = Path(output_path or planned_landuse_ref.path)  # type: ignore[union-attr]
    complete_ref = _layer_ref_for_output(
        current_landuse_ref,
        output_features,
        target_path,
        output_artifact_ref,
        planned_landuse_ref,
    )
    all_current = dict(current_layers or {"current_landuse": current_landuse_ref})
    overlays = dict(planned_overlay_layers or {})
    constraints = dict(constraint_layers or {})
    source_refs = _unique_refs([*all_current.values(), *overlays.values(), *constraints.values()])
    summary = dict(counts)
    summary["preserved"] = counts["preserved"]
    unresolved_change = any(
        _source_bsms(change) and not any(bsm in by_bsm for bsm in _source_bsms(change))
        for change in changes
    )
    has_material_change = any(
        str(_value(change, "action", "modify") or "modify").lower()
        not in {"preserve", "unchanged"}
        for change in changes
    )
    status = (
        delivery_status or "complete"
        if has_material_change and not unresolved_change
        else "partial"
    )
    snapshot = DeliverySpatialSnapshot(
        current_layers=all_current,
        complete_planned_landuse=complete_ref,
        planned_overlay_layers=overlays,
        constraint_layers=constraints,
        change_summary=summary,
        source_layer_refs=source_refs,
        classification_audit=dict(classification_audit or {}),
        parent_digests={
            key: str(ref.checksum or ref.artifact_ref)
            for key, ref in {
                **all_current,
                **overlays,
                **constraints,
            }.items()
        },
        provenance={"builder": "build_delivery_spatial_snapshot", **dict(provenance or {})},
        delivery_status=status,  # type: ignore[arg-type]
        statutory_complete=statutory_complete,
    )
    snapshot_checksum = hashlib.sha256(
        json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return snapshot.model_copy(update={"checksum": snapshot_checksum})


build_delivery_snapshot = build_delivery_spatial_snapshot


__all__ = [
    "build_delivery_spatial_snapshot",
    "build_delivery_snapshot",
    "build_delivery_spatial_snapshot_from_gis_data",
    "canonical_gis_data_from_workspace",
    "load_complete_planned_geojson",
    "load_snapshot_gis_data",
    "load_snapshot_planned_overlays",
]
