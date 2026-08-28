"""Generate planning sub-geometries from source-backed parcel footprints.

The bundle parcel geometry remains the authoritative source extent.  This
module creates a transient planning footprint for SELECT; it never changes a
parcel BSM and never writes geometry back to the KG.  All area calculations
and subdivision operations happen in a metric CRS, while the returned WKT is
converted back to the source CRS used by the bundle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from shapely import wkt
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from app.spatial.model.crs_engine import get_metric_crs, project_geometry
from app.spatial.model.subdivision import split_for_footprint

_HA_M2 = 10_000.0
_DEFAULT_SOURCE_CRS = "EPSG:4326"


@dataclass(frozen=True)
class PlanningSubgeometryResult:
    """Auditable result of one source parcel footprint derivation."""

    geometry_wkt: str
    source_area_ha: float
    planning_area_ha: float
    coverage_ratio: float | None
    source_crs: str
    metric_crs: str
    operation: str
    diagnostics: tuple[str, ...] = ()
    # ``eligible_area_ha`` is measured after allowed/avoid clipping but before
    # a requested planning footprint is carved out.  Keeping both areas lets
    # callers distinguish a fully prohibited parcel from a partially usable
    # one instead of treating every hard failure as all-or-nothing.
    eligible_area_ha: float = 0.0
    excluded_area_ha: float = 0.0
    availability_status: str = "unknown"
    remainder_geometry_wkts: tuple[str, ...] = ()
    # Eligible geometry before a requested planning footprint is carved out.
    # Keeping this parent extent is necessary when multiple targets share one
    # source parcel: each target must be cut from the same usable extent, not
    # from an already-sized footprint returned for another target.
    eligible_geometry_wkt: str = ""

    @property
    def feasible(self) -> bool:
        return (
            self.availability_status != "fully_unavailable"
            and bool(self.geometry_wkt)
            and "planning_area_insufficient" not in self.diagnostics
            and "subdivision_failed" not in self.diagnostics
        )


def _availability_status(source_area_ha: float, eligible_area_ha: float) -> str:
    if source_area_ha <= 0.0:
        return "unknown"
    ratio = max(0.0, min(1.0, eligible_area_ha / source_area_ha))
    if ratio <= 1e-9:
        return "fully_unavailable"
    if ratio < 1.0 - 1e-6:
        return "partially_available"
    return "fully_available"


def _parse_geometry(value: str | BaseGeometry | None) -> BaseGeometry | None:
    if value is None:
        return None
    try:
        geometry = wkt.loads(value) if isinstance(value, str) else value
    except Exception:
        return None
    if geometry is None or geometry.is_empty:
        return None
    if not geometry.is_valid:
        try:
            geometry = geometry.buffer(0)
        except Exception:
            return None
    if geometry.is_empty or not geometry.is_valid:
        return None
    if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        return None
    return geometry


def _polygonal(geometry: BaseGeometry | None) -> BaseGeometry | None:
    if geometry is None or geometry.is_empty:
        return None
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return geometry
    try:
        merged = unary_union(geometry)
    except Exception:
        return None
    return (
        merged
        if merged.geom_type in {"Polygon", "MultiPolygon"} and not merged.is_empty
        else None
    )


def _metric_crs(source_crs: str, geometry: BaseGeometry) -> str:
    """Select a local metric CRS without imposing one on source WKT."""
    normalized = str(source_crs or _DEFAULT_SOURCE_CRS).strip() or _DEFAULT_SOURCE_CRS
    try:
        from pyproj import CRS

        if not CRS.from_user_input(normalized).is_geographic:
            return normalized
    except Exception:
        # A non-empty projected CRS can still be passed through when pyproj
        # cannot inspect it.  The transformation below will fail closed.
        if normalized != _DEFAULT_SOURCE_CRS:
            return normalized
    return get_metric_crs(float(geometry.representative_point().x))


def _project(
    geometry: BaseGeometry,
    source_crs: str,
    metric_crs: str,
) -> BaseGeometry:
    normalized = str(source_crs or _DEFAULT_SOURCE_CRS).strip() or _DEFAULT_SOURCE_CRS
    if normalized == metric_crs:
        return geometry
    return project_geometry(geometry, normalized, metric_crs)


def _transform_back(
    geometry: BaseGeometry,
    source_crs: str,
    metric_crs: str,
) -> BaseGeometry:
    normalized = str(source_crs or _DEFAULT_SOURCE_CRS).strip() or _DEFAULT_SOURCE_CRS
    if normalized == metric_crs:
        return geometry
    return project_geometry(geometry, metric_crs, normalized)


def _largest_polygon(geometry: BaseGeometry) -> BaseGeometry | None:
    if geometry.geom_type == "Polygon":
        return geometry
    parts = [part for part in geometry.geoms if not part.is_empty and part.area > 0]
    if not parts:
        return None
    return max(parts, key=lambda part: (float(part.area), part.wkb_hex))


def _apply_allowed_and_avoid(
    source: BaseGeometry,
    *,
    allowed_geometry: BaseGeometry | None,
    avoid_geometries: Iterable[BaseGeometry],
    setback_m: float,
) -> tuple[BaseGeometry | None, list[str]]:
    diagnostics: list[str] = []
    available = source
    if allowed_geometry is not None:
        available = available.intersection(allowed_geometry)
        diagnostics.append("intersected_allowed_geometry")
    avoid = [item for item in avoid_geometries if item is not None and not item.is_empty]
    if avoid:
        available = available.difference(unary_union(avoid))
        diagnostics.append("subtracted_avoid_geometry")
    if setback_m > 0:
        buffered = available.buffer(-float(setback_m))
        if not buffered.is_empty:
            available = buffered
            diagnostics.append("applied_setback")
        else:
            diagnostics.append("setback_empty")
            return None, diagnostics
    available = _polygonal(available)
    if available is None or available.is_empty:
        return None, diagnostics + ["available_geometry_empty"]
    return available, diagnostics


def derive_planning_subgeometry(
    source_geometry_wkt: str,
    *,
    source_crs: str = _DEFAULT_SOURCE_CRS,
    target_area_ha: float | None = None,
    allowed_geometry_wkt: str = "",
    avoid_geometry_wkts: Iterable[str] = (),
    setback_m: float = 0.0,
    tolerance_pct: float = 5.0,
) -> PlanningSubgeometryResult | None:
    """Derive a source-backed planning footprint.

    ``target_area_ha`` is a planning demand, not a new parcel identity.  A
    value of ``None`` or a non-positive value keeps the available source
    extent.  If the requested area cannot be produced after allowed/avoid
    clipping, the result is returned with a diagnostic and ``feasible=False``
    so SELECT can defer it instead of silently materializing a full parcel.
    """
    source_raw = _parse_geometry(source_geometry_wkt)
    if source_raw is None:
        return None
    normalized_source_crs = (
        str(source_crs or _DEFAULT_SOURCE_CRS).strip() or _DEFAULT_SOURCE_CRS
    )
    try:
        metric_crs = _metric_crs(normalized_source_crs, source_raw)
        source_metric = _project(source_raw, normalized_source_crs, metric_crs)
        allowed_raw = _parse_geometry(allowed_geometry_wkt) if allowed_geometry_wkt else None
        allowed_metric = (
            _project(allowed_raw, normalized_source_crs, metric_crs)
            if allowed_raw is not None
            else None
        )
        avoid_metric = [
            _project(parsed, normalized_source_crs, metric_crs)
            for raw in avoid_geometry_wkts
            if (parsed := _parse_geometry(raw)) is not None
        ]
    except Exception:
        return None

    source_area_ha = max(float(source_metric.area) / _HA_M2, 0.0)
    available, diagnostics = _apply_allowed_and_avoid(
        source_metric,
        allowed_geometry=allowed_metric,
        avoid_geometries=avoid_metric,
        setback_m=max(float(setback_m or 0.0), 0.0),
    )
    if available is None:
        return PlanningSubgeometryResult(
            geometry_wkt="",
            eligible_geometry_wkt="",
            source_area_ha=source_area_ha,
            planning_area_ha=0.0,
            coverage_ratio=0.0 if source_area_ha else None,
            source_crs=normalized_source_crs,
            metric_crs=metric_crs,
            operation="planning_clip_failed",
            diagnostics=tuple(diagnostics),
            eligible_area_ha=0.0,
            excluded_area_ha=source_area_ha,
            availability_status="fully_unavailable",
        )

    available_area_ha = max(float(available.area) / _HA_M2, 0.0)
    availability_status = _availability_status(source_area_ha, available_area_ha)
    excluded_area_ha = max(source_area_ha - available_area_ha, 0.0)
    requested = float(target_area_ha or 0.0)
    footprint = available
    operation = "bundle_extent"
    remainders: list[BaseGeometry] = []
    if requested > 0.0:
        if available_area_ha + 1e-9 < requested:
            diagnostics.append("planning_area_insufficient")
        elif (
            abs(available_area_ha - requested) / max(requested, 1e-9)
            > max(float(tolerance_pct), 0.0) / 100.0
        ):
            polygon = _largest_polygon(available)
            if polygon is None or polygon.area / _HA_M2 + 1e-9 < requested:
                diagnostics.append("planning_area_insufficient")
            else:
                try:
                    footprint, remainders = split_for_footprint(
                        polygon,
                        requested,
                        tolerance_pct=max(float(tolerance_pct), 0.0),
                        exact_search=source_raw.geom_type == "Polygon",
                    )
                    operation = "obb_subdivide"
                except (ValueError, TypeError, RuntimeError):
                    diagnostics.append("subdivision_failed")
        else:
            operation = "bundle_extent_within_tolerance"
    if footprint is None or footprint.is_empty:
        diagnostics.append("subdivision_failed")
        return PlanningSubgeometryResult(
            geometry_wkt="",
            eligible_geometry_wkt=_transform_back(available, normalized_source_crs, metric_crs).wkt,
            source_area_ha=source_area_ha,
            planning_area_ha=0.0,
            coverage_ratio=0.0 if source_area_ha else None,
            source_crs=normalized_source_crs,
            metric_crs=metric_crs,
            operation="planning_clip_failed",
            diagnostics=tuple(dict.fromkeys(diagnostics)),
            eligible_area_ha=available_area_ha,
            excluded_area_ha=excluded_area_ha,
            availability_status=availability_status,
        )
    footprint = _polygonal(footprint)
    if footprint is None:
        diagnostics.append("subdivision_failed")
        return PlanningSubgeometryResult(
            geometry_wkt="",
            eligible_geometry_wkt=_transform_back(available, normalized_source_crs, metric_crs).wkt,
            source_area_ha=source_area_ha,
            planning_area_ha=0.0,
            coverage_ratio=0.0 if source_area_ha else None,
            source_crs=normalized_source_crs,
            metric_crs=metric_crs,
            operation="planning_clip_failed",
            diagnostics=tuple(dict.fromkeys(diagnostics)),
            eligible_area_ha=available_area_ha,
            excluded_area_ha=excluded_area_ha,
            availability_status=availability_status,
        )
    planning_area_ha = max(float(footprint.area) / _HA_M2, 0.0)
    # Exact area alone is not enough for an executable planning footprint.
    # A very thin sliver can be produced when an irregular/multipart parcel
    # is cut along an OBB axis; reject that shape while preserving it for
    # diagnostics and remainder lineage.
    if footprint.geom_type == "Polygon" and footprint.length > 0.0:
        compactness = (4.0 * 3.141592653589793 * float(footprint.area)) / (
            float(footprint.length) ** 2
        )
        if compactness < 0.03:
            diagnostics.append("subdivision_sliver")
            diagnostics.append("subdivision_failed")
    if requested > 0.0 and (
        abs(planning_area_ha - requested) / max(requested, 1e-9)
        > max(float(tolerance_pct), 0.0) / 100.0
    ):
        # A split operation is only executable when it actually satisfies the
        # requested area tolerance.  OBB is a deterministic heuristic, not a
        # proof that an irregular source polygon can yield the target size.
        # Keep the source-backed geometry for diagnostics, but fail closed so
        # SELECT cannot approve a materially undersized footprint.
        diagnostics.append("planning_area_insufficient")
    output = _transform_back(footprint, normalized_source_crs, metric_crs)
    eligible_output = _transform_back(available, normalized_source_crs, metric_crs)
    return PlanningSubgeometryResult(
        geometry_wkt=output.wkt,
        eligible_geometry_wkt=eligible_output.wkt,
        source_area_ha=source_area_ha,
        planning_area_ha=planning_area_ha,
        coverage_ratio=(planning_area_ha / source_area_ha) if source_area_ha else None,
        source_crs=normalized_source_crs,
        metric_crs=metric_crs,
        operation=operation,
        diagnostics=tuple(dict.fromkeys(diagnostics)),
        eligible_area_ha=available_area_ha,
        excluded_area_ha=excluded_area_ha,
        availability_status=availability_status,
        remainder_geometry_wkts=tuple(
            _transform_back(item, normalized_source_crs, metric_crs).wkt
            for item in remainders
            if item is not None and not item.is_empty
        ),
    )


__all__ = ["PlanningSubgeometryResult", "derive_planning_subgeometry"]
