"""Layer 4: PlannedState (规划成果, 版本化增量).

L4 entities mirror L3 intent virtual entities with precise geometry:
  ZoneTarget → PlannedParcel + PlannedZone
  FacilityTarget → PlannedFacility
  RoadTarget → PlannedRoad
  AxisTarget → PlannedAxis

Sparse write: only changed entities get L4 triples.
Unchanged entities have no L4 triples; query falls back to L1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from rdflib import Literal, RDF, URIRef
from rdflib.namespace import XSD

from app.utils.logger import get_logger
from ..ontology import PLN, EntityTypes, Relations

logger = get_logger(__name__)


# ── PlannedState entry types ──


@dataclass
class PlannedParcelEntry:
    """规划地块 — 对应 L3 ZoneTarget 的落实"""
    bsm: str
    planning_land_use: str = ""
    zone_type: str = ""
    area_ha: float = 0.0
    derived_from_bsms: List[str] = field(default_factory=list)
    derived_from_zone_target: str = ""


@dataclass
class PlannedZoneEntry:
    """规划分区面 — 线围成的面，对应 L3 ZoneTarget 的落实"""
    zone_type: str
    area_ha: float = 0.0
    name: str = ""
    derived_from_zone_target: str = ""


@dataclass
class PlannedFacilityEntry:
    """规划设施点 — 对应 L3 FacilityTarget 的落实"""
    name: str
    facility_type: str = ""
    lon: float = 0.0
    lat: float = 0.0
    service_radius: int = 0
    derived_from_target: str = ""


@dataclass
class PlannedRoadEntry:
    """规划道路线 — 对应 L3 RoadTarget 的落实"""
    name: str
    road_level: str = ""
    width_m: float = 0.0
    derived_from_target: str = ""


@dataclass
class PlannedAxisEntry:
    """规划发展轴线 — 对应 L3 AxisTarget 的落实"""
    name: str
    reference_feature: str = ""
    direction: str = ""
    derived_from_target: str = ""


@dataclass
class PlannedState:
    """规划成果状态 — L4 层的完整视图

    Morphologically aligned with VillageBundle:
      parcels → PlannedParcel (面)
      zones → PlannedZone (面)
      facilities → PlannedFacility (点)
      roads → PlannedRoad (线)
      axes → PlannedAxis (线)
    """
    version: str = "current"
    parcels: List[PlannedParcelEntry] = field(default_factory=list)
    zones: List[PlannedZoneEntry] = field(default_factory=list)
    facilities: List[PlannedFacilityEntry] = field(default_factory=list)
    roads: List[PlannedRoadEntry] = field(default_factory=list)
    axes: List[PlannedAxisEntry] = field(default_factory=list)
    source: str = ""


# ── L4 builder ──


def _apply_planned_state(self, planned_state: PlannedState) -> None:
    """Apply PlannedState to KG Layer 4.

    Sparse write: only entities with non-default values get L4 triples.
    Each entity tagged with pln:in_version for versioning.
    """
    if not isinstance(planned_state, PlannedState):
        return

    version = planned_state.version or "current"
    count = 0

    # ── PlannedParcel ──
    for p in planned_state.parcels:
        uri = PLN[f"planned_parcel_{p.bsm}_{version}"]
        self.g.add((uri, RDF.type, EntityTypes.PlannedParcel))
        self.g.add((uri, PLN.bsm, Literal(p.bsm)))
        self.g.add((uri, PLN.in_version, Literal(version)))
        if p.planning_land_use:
            self.g.add((uri, PLN.planning_land_use, Literal(p.planning_land_use)))
        if p.zone_type:
            self.g.add((uri, PLN.planning_zone_type, Literal(p.zone_type)))
        if p.area_ha:
            self.g.add((uri, PLN.planned_area_ha, Literal(p.area_ha, datatype=XSD.double)))
        for parent_bsm in p.derived_from_bsms:
            for s in self.g.subjects(PLN.bsm, Literal(parent_bsm)):
                if (s, RDF.type, EntityTypes.Parcel) in self.g:
                    self.g.add((uri, PLN.derived_from, s))
                    break
        count += 1

    # ── PlannedZone ──
    for z in planned_state.zones:
        uri = PLN[f"planned_zone_{z.zone_type}_{version}"]
        self.g.add((uri, RDF.type, EntityTypes.PlannedZone))
        self.g.add((uri, PLN.zone_type, Literal(z.zone_type)))
        self.g.add((uri, PLN.in_version, Literal(version)))
        if z.name:
            self.g.add((uri, PLN.name, Literal(z.name)))
        if z.area_ha:
            self.g.add((uri, PLN.area_target_ha, Literal(z.area_ha, datatype=XSD.double)))
        count += 1

    # ── PlannedFacility ──
    for f in planned_state.facilities:
        uri = PLN[f"planned_facility_{f.name}_{version}"]
        self.g.add((uri, RDF.type, EntityTypes.PlannedFacility))
        self.g.add((uri, PLN.name, Literal(f.name)))
        self.g.add((uri, PLN.in_version, Literal(version)))
        if f.facility_type:
            self.g.add((uri, PLN.facility_type, Literal(f.facility_type)))
        if f.lon and f.lat:
            self.g.add((uri, PLN.lon, Literal(f.lon, datatype=XSD.double)))
            self.g.add((uri, PLN.lat, Literal(f.lat, datatype=XSD.double)))
        if f.service_radius:
            self.g.add((uri, PLN.service_radius, Literal(f.service_radius, datatype=XSD.integer)))
        count += 1

    # ── PlannedRoad ──
    for r in planned_state.roads:
        uri = PLN[f"planned_road_{r.name}_{version}"]
        self.g.add((uri, RDF.type, EntityTypes.PlannedRoad))
        self.g.add((uri, PLN.name, Literal(r.name)))
        self.g.add((uri, PLN.in_version, Literal(version)))
        if r.road_level:
            self.g.add((uri, PLN.road_level, Literal(r.road_level)))
        if r.width_m:
            self.g.add((uri, PLN.buffer_width_m, Literal(r.width_m, datatype=XSD.double)))
        count += 1

    # ── PlannedAxis ──
    for a in planned_state.axes:
        uri = PLN[f"planned_axis_{a.name}_{version}"]
        self.g.add((uri, RDF.type, EntityTypes.PlannedAxis))
        self.g.add((uri, PLN.name, Literal(a.name)))
        self.g.add((uri, PLN.in_version, Literal(version)))
        if a.reference_feature:
            self.g.add((uri, PLN.reference_feature, Literal(a.reference_feature)))
        if a.direction:
            self.g.add((uri, PLN.direction, Literal(a.direction)))
        count += 1

    if count:
        logger.info("Layer 4: applied %d planned entities (version=%s)", count, version)


# ── Query methods: effective state (L1 + L4 merge) ──


def get_effective_land_use(self, bsm: str, version: str = "current") -> Optional[str]:
    """Get effective land use: L4 if changed, else L1 fallback."""
    l4 = self.query(
        f'PREFIX pln: <http://village-planning.org/ontology#> '
        f'SELECT ?lu WHERE {{ '
        f'?p a pln:PlannedParcel ; pln:bsm "{bsm}" ; '
        f'pln:planning_land_use ?lu ; pln:in_version "{version}" . }}')
    if l4:
        return l4[0].get("lu")
    l1 = self.query(
        f'PREFIX pln: <http://village-planning.org/ontology#> '
        f'SELECT ?dlbm WHERE {{ '
        f'?p a pln:Parcel ; pln:bsm "{bsm}" ; pln:dlbm ?dlbm . }}')
    return l1[0].get("dlbm") if l1 else None


def get_effective_area_ha(self, bsm: str, version: str = "current") -> Optional[float]:
    """Get effective area: L4 if changed, else L1 fallback."""
    l4 = self.query(
        f'PREFIX pln: <http://village-planning.org/ontology#> '
        f'SELECT ?area WHERE {{ '
        f'?p a pln:PlannedParcel ; pln:bsm "{bsm}" ; '
        f'pln:planned_area_ha ?area ; pln:in_version "{version}" . }}')
    if l4:
        try:
            return float(l4[0].get("area", 0))
        except (ValueError, TypeError):
            return None
    l1 = self.query(
        f'PREFIX pln: <http://village-planning.org/ontology#> '
        f'SELECT ?area WHERE {{ '
        f'?p a pln:Parcel ; pln:bsm "{bsm}" ; pln:area_ha ?area . }}')
    if l1:
        try:
            return float(l1[0].get("area", 0))
        except (ValueError, TypeError):
            return None
    return None


def get_plan_changes(self, version: str = "current") -> List[Dict[str, Any]]:
    """Get all planning changes (delta) for a version."""
    return self.query(
        f'PREFIX pln: <http://village-planning.org/ontology#> '
        f'SELECT ?p ?bsm ?lu ?area WHERE {{ '
        f'?p a pln:PlannedParcel ; pln:bsm ?bsm ; '
        f'pln:in_version "{version}" . '
        f'OPTIONAL {{ ?p pln:planning_land_use ?lu . }} '
        f'OPTIONAL {{ ?p pln:planned_area_ha ?area . }} }}')


def get_planned_parcels_in_zone(self, zone_type: str, version: str = "current") -> List[Dict[str, Any]]:
    return self.query(
        f"PREFIX pln: <http://village-planning.org/ontology#> "
        f"SELECT ?bsm ?land_use ?area WHERE {{ "
        f"?p a pln:PlannedParcel ; pln:bsm ?bsm ; pln:planning_land_use ?land_use ; "
        f'pln:planning_zone_type "{zone_type}" ; pln:in_version "{version}" . '
        f"OPTIONAL {{ ?p pln:planned_area_ha ?area . }} }}"
    )


def check_constraint_violations(self, version: str = "current") -> List[Dict[str, Any]]:
    violations = []
    for pp in self.query(f"PREFIX pln: <http://village-planning.org/ontology#> "
                         f"SELECT ?p ?bsm ?land_use WHERE {{ "
                         f"?p a pln:PlannedParcel ; pln:bsm ?bsm ; "
                         f"pln:planning_land_use ?land_use ; pln:in_version \"{version}\" . }}"):
        bsm = pp.get("bsm", "")
        for pz in self.query(f"PREFIX pln: <http://village-planning.org/ontology#> "
                              f"SELECT ?zone ?name ?rule WHERE {{ "
                              f"?s pln:bsm \"{bsm}\" . ?s pln:within_zone ?zone . "
                              f"?zone a pln:ThreeLine ; pln:name ?name . "
                              f"OPTIONAL {{ ?zone pln:restriction ?rule . }} }}"):
            violations.append({"bsm": bsm, "planned_land_use": pp.get("land_use", ""),
                               "protected_zone": pz.get("name", "?"), "rule": pz.get("rule", "禁止建设"),
                               "version": version})
    return violations


def compare_versions(self, version_a: str, version_b: str) -> Dict[str, Any]:
    """Compare two plan versions - returns changes between them."""
    a_map = {p["bsm"]: p for p in self.query(
        f"PREFIX pln: <http://village-planning.org/ontology#> "
        f"SELECT ?bsm ?land_use ?area WHERE {{ "
        f"?p a pln:PlannedParcel ; pln:in_version \"{version_a}\" ; "
        f"pln:bsm ?bsm . "
        f"OPTIONAL {{ ?p pln:planning_land_use ?land_use . }} "
        f"OPTIONAL {{ ?p pln:planned_area_ha ?area . }} }}") if p.get("bsm")}
    b_map = {p["bsm"]: p for p in self.query(
        f"PREFIX pln: <http://village-planning.org/ontology#> "
        f"SELECT ?bsm ?land_use ?area WHERE {{ "
        f"?p a pln:PlannedParcel ; pln:in_version \"{version_b}\" ; "
        f"pln:bsm ?bsm . "
        f"OPTIONAL {{ ?p pln:planning_land_use ?land_use . }} "
        f"OPTIONAL {{ ?p pln:planned_area_ha ?area . }} }}") if p.get("bsm")}
    changed = []
    for bsm, bp in b_map.items():
        if bsm in a_map:
            ap = a_map[bsm]
            if ap.get("land_use", "") != bp.get("land_use", ""):
                changed.append({"bsm": bsm, "from": ap.get("land_use", ""),
                                "to": bp.get("land_use", "")})
        else:
            changed.append({"bsm": bsm, "from": None, "to": bp.get("land_use", "")})
    a_keys = set(a_map.keys())
    b_keys = set(b_map.keys())
    return {"version_a": version_a, "version_b": version_b,
            "changed_parcels": changed,
            "added_parcels": list(b_keys - a_keys),
            "removed_parcels": list(a_keys - b_keys),
            "total_changes": len(changed) + len(b_keys - a_keys) + len(a_keys - b_keys)}