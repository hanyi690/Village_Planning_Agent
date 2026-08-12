"""Build the canonical village-scale custom planning-zone layer.

The existing vocabulary generator selects suitable parcel candidates for one
theme at a time.  This module turns those candidates into a single mutually
exclusive, coverage-complete planning layer after deterministic vocabulary-driven allocation.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from shapely.geometry import shape


PENDING_ZONE_NAME = "待确认分区"
PENDING_ZONE_CODE = "pending"


def _bsm(feature: Dict[str, Any], index: int) -> str:
    props = feature.get("properties") or {}
    return str(props.get("BSM") or props.get("bsm") or f"parcel-{index}")


def _area_ha(feature: Dict[str, Any]) -> float:
    props = feature.get("properties") or {}
    value = props.get("area_ha")
    if value not in (None, ""):
        return float(value)
    return float(props.get("area_sqm") or props.get("DLMJ") or 0) / 10000.0


def build_custom_zone_allocation_inputs(
    landuse_geojson: Dict[str, Any],
    generated_zones: Iterable[Dict[str, Any]],
) -> Tuple[Dict[str, float], Dict[str, List[str]], Dict[str, Dict[str, Any]]]:
    """Translate CustomZoningGenerator output into deterministic allocation inputs.

    Every parcel is eligible for exactly one explicit fallback zone when it is
    not selected by any evidence-backed custom target.  This avoids silently
    assigning an ungrounded parcel to a thematic zone just to satisfy coverage.
    """
    all_bsms = [_bsm(feature, index) for index, feature in enumerate(landuse_geojson.get("features") or [])]
    claimed: set[str] = set()
    targets: Dict[str, float] = {}
    candidates: Dict[str, List[str]] = {}
    metadata: Dict[str, Dict[str, Any]] = {}
    for index, zone in enumerate(generated_zones):
        name = str(zone.get("pln:category_name_zh") or zone.get("name") or "").strip()
        if not name:
            continue
        bsms = [str(value) for value in zone.get("pln:target_bsms") or [] if str(value)]
        if not bsms:
            continue
        claimed.update(bsms)
        target = float(zone.get("pln:area_target_ha") or 0)
        if target <= 0:
            target = sum(
                _area_ha(feature)
                for feature_index, feature in enumerate(landuse_geojson.get("features") or [])
                if _bsm(feature, feature_index) in set(bsms)
            )
        targets[name] = target
        candidates[name] = bsms
        metadata[name] = {
            "zone_id": f"CZ-{index + 1:02d}",
            "category_code": zone.get("pln:category_code") or name,
            "color": zone.get("pln:color") or "#64748b",
            "target_area_ha": target,
            "target_bsms": bsms,
            "decided_by": zone.get("pln:decided_by") or "rule",
            "confidence": zone.get("pln:confidence") or 0.0,
            "vocabulary_name": zone.get("pln:vocabulary_name") or "",
        }
    pending = [bsm for bsm in all_bsms if bsm not in claimed]
    targets[PENDING_ZONE_NAME] = sum(
            _area_ha(feature)
            for index, feature in enumerate(landuse_geojson.get("features") or [])
            if _bsm(feature, index) in set(pending)
    )
    candidates[PENDING_ZONE_NAME] = pending
    metadata[PENDING_ZONE_NAME] = {
        "zone_id": "CZ-PENDING",
        "category_code": PENDING_ZONE_CODE,
        "color": "#94a3b8",
        "target_area_ha": targets[PENDING_ZONE_NAME],
        "target_bsms": pending,
        "decided_by": "coverage_repair",
        "confidence": 0.0,
        "vocabulary_name": "",
    }
    return targets, candidates, metadata


def validate_custom_planning_zone_layer(geojson: Dict[str, Any]) -> Dict[str, Any]:
    """Check overlap and continuity of the canonical custom-zone result."""
    features = list(geojson.get("features") or [])
    overlaps = 0.0
    for index, feature in enumerate(features):
        geometry = feature.get("geometry")
        if not geometry:
            continue
        left = shape(geometry)
        for other in features[index + 1:]:
            other_geometry = other.get("geometry")
            if other_geometry:
                overlaps += left.intersection(shape(other_geometry)).area
    pending = next(
        (feature for feature in features if (feature.get("properties") or {}).get("zone_name") == PENDING_ZONE_NAME),
        None,
    )
    return {
        "feature_count": len(features),
        "overlap_area_native": overlaps,
        "pending_area_ha": (pending or {}).get("properties", {}).get("area_ha", 0.0),
        "pending_parcel_count": (pending or {}).get("properties", {}).get("parcel_count", 0),
        "passed": overlaps <= 1e-12,
    }
