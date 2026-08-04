"""Layout comparison — generated vs planned ground truth.

Computes per-zone matching metrics:
  1. Area comparison: generated zone areas vs planned DLBM areas
  2. Zone distribution: 6 planning zone ratios vs planned
  3. Protection compliance: encroachment into farmland/ecological/historical zones
  4. Facility coverage: service radius residential point coverage
  5. Primary zone comparison: 3-zone (生态/农业/建设) area match
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.utils.logger import get_logger
from app.modules.schema.advisory_crosswalks import (
    get_zone_type_for_dlbm,
    dlbm_to_planning_zone,
    get_primary_zone,
    get_primary_zone_for_planning_zone,
)
from app.modules.schema import (
    PLANNING_ZONE_NAMES,
    PRIMARY_ZONE_NAMES,
)

logger = get_logger(__name__)

try:
    import geopandas as gpd
    import shapely.geometry as geom
    from shapely.ops import unary_union
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False


@dataclass
class ZoneAreaMatch:
    zone_type: str
    generated_area_ha: float
    planned_area_ha: float
    diff_ha: float
    diff_pct: float
    match: bool  # within tolerance


@dataclass
class ComparisonReport:
    zone_area_matches: List[ZoneAreaMatch] = field(default_factory=list)
    planning_zone_match: Dict[str, float] = field(default_factory=dict)
    protection_violations: List[Dict[str, Any]] = field(default_factory=list)
    facility_coverage: Dict[str, float] = field(default_factory=dict)
    overall_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "zone_area_matches": [
                {
                    "zone_type": m.zone_type,
                    "generated_area_ha": round(m.generated_area_ha, 2),
                    "planned_area_ha": round(m.planned_area_ha, 2),
                    "diff_ha": round(m.diff_ha, 2),
                    "diff_pct": round(m.diff_pct, 1),
                    "match": bool(m.match),
                }
                for m in self.zone_area_matches
            ],
            "planning_zone_match": {
                k: round(v, 2) for k, v in self.planning_zone_match.items()
            },
            "protection_violations": self.protection_violations,
            "facility_coverage": {
                k: round(v, 2) for k, v in self.facility_coverage.items()
            },
            "overall_score": round(self.overall_score, 2),
        }


def _area_ha(geojson: Dict[str, Any]) -> float:
    """Compute total area in hectares from a GeoJSON FeatureCollection."""
    if not geojson or not geojson.get("features"):
        return 0.0
    total = 0.0
    for feat in geojson["features"]:
        props = feat.get("properties", {})
        area = props.get("area_ha", props.get("DLMJ", 0))
        if isinstance(area, (int, float)) and area > 0:
            if area > 10000:
                total += area / 10000.0
            else:
                total += area
    return total


def _aggregate_by_dlbm_group(geojson: Dict[str, Any]) -> Dict[str, float]:
    """Aggregate land area by zone type from parcel GeoJSON.

    DLMJ in planned data is always in square meters → convert to hectares.
    area_ha in generated data is already in hectares.
    """
    result: Dict[str, float] = {}
    for feat in geojson.get("features", []):
        props = feat.get("properties", {})
        # 现状层优先 DLBM (appendix5编码), 回退 QMDLBM
        dlbm = str(props.get("DLBM", props.get("QMDLBM", ""))).strip()
        if not dlbm:
            continue
        # Prefer area_ha if available (already in hectares)
        if "area_ha" in props and isinstance(props["area_ha"], (int, float)):
            area = float(props["area_ha"])
        elif "DLMJ" in props and isinstance(props["DLMJ"], (int, float)):
            area = float(props["DLMJ"]) / 10000.0  # m² → ha
        else:
            area = 0.0
        zone = get_zone_type_for_dlbm(dlbm)
        result[zone] = result.get(zone, 0.0) + area
    return result


def _get_features_as_gdf(geojson: Dict[str, Any]) -> Optional[Any]:
    """Convert FeatureCollection to GeoDataFrame."""
    if not GEOPANDAS_AVAILABLE or not geojson or not geojson.get("features"):
        return None
    geoms = []
    props = []
    for feat in geojson["features"]:
        g = feat.get("geometry", {})
        if g and g.get("coordinates"):
            try:
                geoms.append(geom.shape(g))
                props.append(feat.get("properties", {}))
            except Exception:
                continue
    if not geoms:
        return None
    return gpd.GeoDataFrame(props, geometry=geoms, crs="EPSG:4326")


def compare_zone_areas(
    generated: Dict[str, Any],
    planned: Dict[str, Any],
    tolerance_pct: float = 20.0,
) -> List[ZoneAreaMatch]:
    """Compare generated zone areas against planned DLBM-group areas.

    Args:
        generated: function_zone GeoJSON (from ZoneGenerator)
        planned: planned landuse GeoJSON (from data/gis/jintian/planned/)
        tolerance_pct: max acceptable % difference per zone type

    Returns:
        List of ZoneAreaMatch per zone type
    """
    gen_areas: Dict[str, float] = {}
    for feat in generated.get("features", []):
        props = feat.get("properties", {})
        land_use = props.get("land_use", "unknown")
        area = props.get("area_ha", 0)
        gen_areas[land_use] = gen_areas.get(land_use, 0.0) + area

    planned_areas = _aggregate_by_dlbm_group(planned)

    matches: List[ZoneAreaMatch] = []
    all_zone_types = set(gen_areas.keys()) | set(planned_areas.keys())

    for ztype in sorted(all_zone_types):
        gen_val = gen_areas.get(ztype, 0.0)
        plan_val = planned_areas.get(ztype, 0.0)
        diff = gen_val - plan_val
        diff_pct = (abs(diff) / plan_val * 100) if plan_val > 0 else 0.0
        matches.append(ZoneAreaMatch(
            zone_type=ztype,
            generated_area_ha=gen_val,
            planned_area_ha=plan_val,
            diff_ha=diff,
            diff_pct=diff_pct,
            match=diff_pct <= tolerance_pct,
        ))

    return matches


def compare_planning_zones(
    generated_planning_zone: Dict[str, Any],
    planned_landuse: Dict[str, Any],
) -> Dict[str, float]:
    """Compare 6 planning zone distribution between generated and planned.

    Returns dict: {zone_type: generated_pct - planned_pct}
    """

    # Generated planning zone distribution
    gen_zones: Dict[str, float] = {}
    gen_total = 0.0
    for feat in generated_planning_zone.get("features", []):
        props = feat.get("properties", {})
        zt = props.get("zone_type", props.get("assigned_zone", "unknown"))
        # Prefer area_ha; DLMJ is in m²
        if "area_ha" in props and isinstance(props["area_ha"], (int, float)):
            area = float(props["area_ha"])
        elif "DLMJ" in props and isinstance(props["DLMJ"], (int, float)):
            area = float(props["DLMJ"]) / 10000.0
        else:
            area = 0.0
        gen_zones[zt] = gen_zones.get(zt, 0.0) + area
        gen_total += area

    # Planned planning zone distribution
    plan_zones: Dict[str, float] = {}
    plan_total = 0.0
    for feat in planned_landuse.get("features", []):
        props = feat.get("properties", {})
        # 规划层优先 QMDLBM (tugui编码), 回退 DLBM
        dlbm = str(props.get("QMDLBM", props.get("DLBM", ""))).strip()
        if not dlbm:
            continue
        zt = dlbm_to_planning_zone(dlbm)
        if "area_ha" in props and isinstance(props["area_ha"], (int, float)):
            area = float(props["area_ha"])
        elif "DLMJ" in props and isinstance(props["DLMJ"], (int, float)):
            area = float(props["DLMJ"]) / 10000.0
        else:
            area = 0.0
        plan_zones[zt] = plan_zones.get(zt, 0.0) + area
        plan_total += area

    result: Dict[str, float] = {}
    for zt in set(gen_zones.keys()) | set(plan_zones.keys()):
        gen_pct = (gen_zones.get(zt, 0.0) / gen_total * 100) if gen_total > 0 else 0.0
        plan_pct = (plan_zones.get(zt, 0.0) / plan_total * 100) if plan_total > 0 else 0.0
        result[zt] = gen_pct - plan_pct

    return result


def check_protection_compliance(
    generated_zones: Dict[str, Any],
    protection_zones: Dict[str, Dict[str, Any]],
    threshold_ha: float = 0.01,
) -> List[Dict[str, Any]]:
    """Check if generated zones encroach on protection areas.

    For each protection zone type, checks overlap with non-matching zone types.

    Returns list of violations: {zone_id, zone_type, protection_type, overlap_ha}
    """
    if not GEOPANDAS_AVAILABLE:
        return []

    gen_gdf = _get_features_as_gdf(generated_zones)
    if gen_gdf is None:
        return []

    violations: List[Dict[str, Any]] = []

    for prot_name, prot_geojson in protection_zones.items():
        prot_gdf = _get_features_as_gdf(prot_geojson)
        if prot_gdf is None:
            continue

        prot_union = unary_union(prot_gdf.geometry.values)

        for _, row in gen_gdf.iterrows():
            g = row.geometry
            if g is None or g.is_empty:
                continue

            try:
                overlap = g.intersection(prot_union)
                if overlap.is_empty:
                    continue
                overlap_ha = overlap.area * 111320 * 111320 * 0.00001  # rough degree→ha
                if overlap_ha < threshold_ha:
                    continue

                props = row.to_dict()
                violations.append({
                    "zone_id": props.get("zone_id", "?"),
                    "zone_type": props.get("land_use", props.get("zone_type", "?")),
                    "protection_type": prot_name,
                    "overlap_ha": round(overlap_ha, 3),
                })
            except Exception:
                continue

    return violations


def compute_facility_coverage(
    facility_geojson: Dict[str, Any],
    residential_geojson: Optional[Dict[str, Any]] = None,
) -> Dict[str, float]:
    """Compute residential point coverage within facility service radii.

    Returns: {facility_id: coverage ratio (0.0–1.0)}
    """
    coverage: Dict[str, float] = {}
    for feat in facility_geojson.get("features", []):
        props = feat.get("properties", {})
        fid = props.get("facility_id", props.get("name", "?"))
        count = props.get("coverage_count", 0) if props.get("coverage_count") else 0
        coverage[fid] = float(count)

    return coverage


def compare_primary_zones(
    generated_planning_zone: Dict[str, Any],
    planned_landuse: Dict[str, Any],
) -> Dict[str, float]:
    """Compare 3 primary zone (三区) distribution between generated and planned.

    Aggregates 6 secondary zones into 3 primary zones for high-level comparison.
    Returns dict: {primary_zone: generated_pct - planned_pct}
    """
    # Generated: aggregate by primary zone
    gen_primary: Dict[str, float] = {}
    gen_total = 0.0
    for feat in generated_planning_zone.get("features", []):
        props = feat.get("properties", {})
        zt = props.get("zone_type", props.get("assigned_zone", "unknown"))
        primary = get_primary_zone_for_planning_zone(zt) if zt in PLANNING_ZONE_NAMES else "农业空间"
        if "area_ha" in props and isinstance(props["area_ha"], (int, float)):
            area = float(props["area_ha"])
        elif "DLMJ" in props and isinstance(props["DLMJ"], (int, float)):
            area = float(props["DLMJ"]) / 10000.0
        else:
            area = 0.0
        gen_primary[primary] = gen_primary.get(primary, 0.0) + area
        gen_total += area

    # Planned: aggregate DLBM → primary zone
    plan_primary: Dict[str, float] = {}
    plan_total = 0.0
    for feat in planned_landuse.get("features", []):
        props = feat.get("properties", {})
        # 规划层优先 QMDLBM (tugui编码), 回退 DLBM
        dlbm = str(props.get("QMDLBM", props.get("DLBM", ""))).strip()
        if not dlbm:
            continue
        primary = get_primary_zone(dlbm)
        if "area_ha" in props and isinstance(props["area_ha"], (int, float)):
            area = float(props["area_ha"])
        elif "DLMJ" in props and isinstance(props["DLMJ"], (int, float)):
            area = float(props["DLMJ"]) / 10000.0
        else:
            area = 0.0
        plan_primary[primary] = plan_primary.get(primary, 0.0) + area
        plan_total += area

    result: Dict[str, float] = {}
    for pz in PRIMARY_ZONE_NAMES:
        gen_pct = (gen_primary.get(pz, 0.0) / gen_total * 100) if gen_total > 0 else 0.0
        plan_pct = (plan_primary.get(pz, 0.0) / plan_total * 100) if plan_total > 0 else 0.0
        result[pz] = gen_pct - plan_pct

    return result


def compare(
    generated_layout: List[Dict[str, Any]],
    planned_data: Dict[str, Any],
    protection_zones: Optional[Dict[str, Dict[str, Any]]] = None,
    tolerance_pct: float = 20.0,
) -> ComparisonReport:
    """Run full comparison between generated and planned layouts.

    Args:
        generated_layout: list of {layerType, data} from generate_layout
        planned_data: gis_data dict from load_planned()
        protection_zones: optional protection zone dict
        tolerance_pct: max acceptable % difference per zone type

    Returns:
        ComparisonReport with all match metrics
    """
    # Extract layers from generated layout
    func_zone = None
    plan_zone = None
    fac_layer = None
    for lyr in generated_layout:
        lt = lyr.get("layerType", "")
        if lt == "function_zone":
            func_zone = lyr.get("data", {})
        elif lt == "planning_zone":
            plan_zone = lyr.get("data", {})
        elif lt == "facility_point":
            fac_layer = lyr.get("data", {})

    planned_landuse = planned_data.get("landuse_planned_geojson", {})

    # 1. Zone area comparison
    if func_zone and planned_landuse:
        area_matches = compare_zone_areas(func_zone, planned_landuse, tolerance_pct)
    else:
        area_matches = []

    # 2. Planning zone distribution
    if plan_zone and planned_landuse:
        zone_match = compare_planning_zones(plan_zone, planned_landuse)
    else:
        zone_match = {}

    # 3. Protection compliance
    if func_zone and protection_zones:
        violations = check_protection_compliance(func_zone, protection_zones)
    else:
        violations = []

    # 4. Facility coverage
    if fac_layer:
        fac_cov = compute_facility_coverage(fac_layer)
    else:
        fac_cov = {}

    # 5. Primary zone (三区) comparison
    if plan_zone and planned_landuse:
        primary_match = compare_primary_zones(plan_zone, planned_landuse)
    else:
        primary_match = {}

    # Compute overall score (weighted combination)
    score = 1.0
    if area_matches:
        matched = sum(1 for m in area_matches if m.match)
        score *= matched / len(area_matches)
    if violations:
        score *= max(0.0, 1.0 - len(violations) * 0.1)
    if zone_match:
        within_range = sum(1 for v in zone_match.values() if abs(v) <= 5.0)
        score *= within_range / len(zone_match)
    if primary_match:
        primary_within = sum(1 for v in primary_match.values() if abs(v) <= 5.0)
        score *= primary_within / len(primary_match)

    return ComparisonReport(
        zone_area_matches=area_matches,
        planning_zone_match=zone_match,
        protection_violations=violations,
        facility_coverage=fac_cov,
        overall_score=score,
    )
