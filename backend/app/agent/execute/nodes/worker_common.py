"""Shared helpers for the EXECUTE worker nodes (parcel adaptation, task routing)."""

from __future__ import annotations

from typing import Any, Dict, List

from app.agent.execute.execute_state import ExecuteAgentState


def _intent_list(intent: Any, key: str) -> List[Any]:
    """Read a list field off a typed intent or a legacy intent dict."""
    if intent is None:
        return []
    if isinstance(intent, dict):
        value = intent.get(key)
    else:
        value = getattr(intent, key, None)
    return list(value or [])


def _worker_result_get(result: Any, key: str, default: Any = None) -> Any:
    if isinstance(result, dict):
        return result.get(key, default)
    return getattr(result, key, default)


def _worker_type(result: Any) -> str:
    return str(_worker_result_get(result, "worker_type", "") or "")


def _task_enabled(state: ExecuteAgentState, task: str) -> bool:
    """A task runs when no explicit routing was set, or when it is routed.

    Legacy nodes treated an empty ``tasks_to_run`` as "run everything"; the
    graph always populates ``tasks_to_run`` via ``_route_tasks_node``.
    """
    return not state.tasks_to_run or task in state.tasks_to_run


def _build_landuse_geojson(state: ExecuteAgentState) -> dict:
    """Resolve the current land-use GeoJSON from gis_bundle or gis_data."""
    gis_data = state.gis_data or {}
    gis_bundle = getattr(state, "gis_bundle", None)
    if gis_bundle is not None and hasattr(gis_bundle, "polygons") and (
        gis_bundle.polygons.get("landuse_current")
        or gis_bundle.polygons.get("landuse_planned")
    ):
        landuse = gis_bundle.to_geojson_dict().get("landuse_current_geojson")
    else:
        landuse = gis_data.get("landuse_current_geojson")
    return landuse or {}


def _build_parcel_by_bsm(state: ExecuteAgentState) -> Dict[str, Any]:
    """Map bsm -> parcel (Land Design Worker shape) from the current land use."""
    landuse = _build_landuse_geojson(state)
    return {
        str((feature.get("properties") or {}).get("BSM")
            or (feature.get("properties") or {}).get("bsm") or ""): _parcel_from_feature(feature)
        for feature in (landuse.get("features") or [])
    }


def _resolve_parcel_by_bsm(state: ExecuteAgentState) -> Dict[str, Any]:
    """Prepared parcel index, falling back to a fresh build when empty.

    Direct node/worker invocation in tests skips ``prepare_inputs``; this keeps
    the workers functional by deriving the index from gis_data on demand.
    """
    return dict(state.parcel_by_bsm or {}) or _build_parcel_by_bsm(state)


def _parcel_from_feature(feature: dict) -> Any:
    """Adapt a landuse GeoJSON feature into the Land Design Worker parcel shape.

    The worker reads .bsm/.geometry/.dlbm/.area_sqm from each parcel entry.

    Invalid source geometry (e.g. self-intersecting cadastral polygons) is
    repaired at load time via buffer(0)/make_valid so downstream WKT output
    never carries an invalid geometry. GeometryCollection results are reduced
    to their areal parts (mirrors app/utils/geo_utils.py convention).
    """
    from types import SimpleNamespace

    from shapely.geometry import mapping, shape
    from shapely.ops import unary_union
    from shapely.validation import make_valid

    props = feature.get("properties") or {}
    raw_geom = feature.get("geometry")
    if raw_geom and isinstance(raw_geom, dict) and raw_geom.get("type"):
        try:
            g = shape(raw_geom)
            if not g.is_valid:
                try:
                    g = g.buffer(0)
                except Exception:
                    g = make_valid(g)
                if g.geom_type == "GeometryCollection":
                    areal = [p for p in g.geoms if p.area > 0]
                    g = unary_union(areal) if len(areal) > 1 else areal[0]
                raw_geom = mapping(g)
        except Exception:
            pass
    return SimpleNamespace(
        bsm=str(props.get("BSM") or props.get("bsm") or ""),
        geometry=raw_geom,
        dlbm=str(props.get("DLBM") or props.get("dlbm") or ""),
        area_sqm=float(props.get("area_sqm") or props.get("area") or 0),
        area_ha=float(props.get("area_ha") or 0),
    )


def _parcel_geometry(parcel: Any) -> dict:
    geometry = parcel.get("geometry") if isinstance(parcel, dict) else getattr(parcel, "geometry", None)
    return geometry if isinstance(geometry, dict) else {}


def _footprint_geometry(change: Any, fallback_geometry: dict) -> dict:
    """Polygon footprint for a planned feature.

    Prefer the change's after geometry (WKT -> GeoJSON); fall back to the
    source parcel geometry when the WKT is empty or invalid.
    """
    from shapely import wkt
    from shapely.geometry import mapping as geometry_mapping

    after_wkt = getattr(change, "after_geometry_wkt", "") or ""
    if after_wkt:
        try:
            geom = wkt.loads(after_wkt)
            if not geom.is_empty:
                return geometry_mapping(geom)
        except Exception:
            pass
    return fallback_geometry or {}
