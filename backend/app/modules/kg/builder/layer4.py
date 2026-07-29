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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rdflib import Literal, RDF, URIRef
from rdflib.namespace import XSD

from app.utils.logger import get_logger
from ..ontology import PLN, EntityTypes, Relations, EntityIdPolicy

logger = get_logger(__name__)


# ── PlannedState entry types ──


@dataclass
class PlannedParcelEntry:
    """规划地块 — 对应 L3 ZoneTarget 的落实

    geometry: WKT geometry string (e.g. "POLYGON((...))") or empty.
    When non-empty, stored as pln:geometry WKT literal in KG.
    When empty, EXECUTE must fall back to BSM → SpatialInaex lookup.
    """
    bsm: str
    planning_land_use: str = ""
    zone_type: str = ""
    area_ha: float = 0.0
    geometry: str = ""                               # WKT geometry string
    derived_from_bsms: List[str] = field(default_factory=list)
    derived_from_zone_target: str = ""


@dataclass
class PlannedZoneEntry:
    """规划分区面 — 线围成的面，对应 L3 ZoneTarget 的落实"""
    zone_type: str
    area_ha: float = 0.0
    name: str = ""
    geometry: str = ""                               # WKT polygon geometry string
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


def ingest_planned_state_from_geojson(data_dir: str | Path) -> PlannedState:
    """Read planned/ GeoJSON files (landuse, road, construction_zone) into PlannedState.

    These are planning outputs (L4), not L1 reference layers:
      - planned/landuse.geojson  → PlannedParcelEntry (GHYTBM = appendix5 planning code)
      - planned/road.geojson     → PlannedRoadEntry (sparse: LnType + geometry)
      - planned/construction_zone.geojson → PlannedZoneEntry (LX = zone type)

    Reads GeoJSON directly (avoids ingest_feature whitelist mismatch).
    Uses shapely for geometry → WKT conversion.
    """
    from json import load as json_load

    def _geojson_to_wkt(geom: dict) -> str:
        if not geom or "type" not in geom:
            return ""
        gtype = geom["type"]
        coords = geom.get("coordinates", [])

        def _pt(c):
            return f"{c[0]} {c[1]}"

        def _line(c):
            return ", ".join(_pt(p) for p in c)

        def _poly(c):
            return "(" + ", ".join(
                "(" + ", ".join(_pt(p) for p in ring) + ")"
                for ring in c
            ) + ")"

        if gtype == "Point":
            return f"POINT ({_pt(coords)})"
        elif gtype == "MultiPoint":
            return "MULTIPOINT (" + ", ".join(_pt(p) for p in coords) + ")"
        elif gtype == "LineString":
            return f"LINESTRING ({_line(coords)})"
        elif gtype == "MultiLineString":
            return "MULTILINESTRING (" + ", ".join(
                "(" + _line(part) + ")" for part in coords
            ) + ")"
        elif gtype == "Polygon":
            return f"POLYGON {_poly(coords)}"
        elif gtype == "MultiPolygon":
            return "MULTIPOLYGON (" + ", ".join(
                _poly(part) for part in coords
            ) + ")"
        return ""

    data_dir = Path(data_dir)
    state = PlannedState(source="planned_geojson")

    # ── planned/landuse.geojson → PlannedParcelEntry ──
    landuse_path = data_dir / "planned" / "landuse.geojson"
    if landuse_path.exists():
        with open(landuse_path, encoding="utf-8") as f:
            data = json_load(f)
        seen_bsms: set[str] = set()
        for i, feat in enumerate(data.get("features", [])):
            props = feat.get("properties", {})
            geom = feat.get("geometry")
            wkt_str = _geojson_to_wkt(geom) if geom else ""
            bsm = str(props.get("BSM") or "").strip()
            if not bsm or bsm in seen_bsms:
                bsm = f"planned_parcel_{i}"
            seen_bsms.add(bsm)
            land_use = str(props.get("GHYTBM") or props.get("GHFLBM") or "").strip()
            dlmj = float(props.get("DLMJ") or 0)
            state.parcels.append(PlannedParcelEntry(
                bsm=bsm,
                planning_land_use=land_use,
                zone_type="planned",
                area_ha=dlmj / 10000.0 if dlmj else 0.0,
                geometry=wkt_str,
            ))
        logger.info("L4 ingest: %d PlannedParcel from %s", len(state.parcels), landuse_path.name)

    # ── planned/road.geojson → PlannedRoadEntry ──
    road_path = data_dir / "planned" / "road.geojson"
    if road_path.exists():
        with open(road_path, encoding="utf-8") as f:
            data = json_load(f)
        for i, feat in enumerate(data.get("features", [])):
            props = feat.get("properties", {})
            ln_type = str(props.get("LnType") or "").strip()
            state.roads.append(PlannedRoadEntry(
                name=f"规划道路_{i}",
                road_level=ln_type or "unknown",
                width_m=0.0,
            ))
        logger.info("L4 ingest: %d PlannedRoad from %s", len(state.roads), road_path.name)

    # ── planned/construction_zone.geojson → PlannedZoneEntry ──
    cz_path = data_dir / "planned" / "construction_zone.geojson"
    if cz_path.exists():
        with open(cz_path, encoding="utf-8") as f:
            data = json_load(f)
        for i, feat in enumerate(data.get("features", [])):
            props = feat.get("properties", {})
            geom = feat.get("geometry")
            wkt_str = _geojson_to_wkt(geom) if geom else ""
            bsm = str(props.get("BSM") or "").strip() or f"planned_zone_{i}"
            zone_type = str(props.get("LX") or "有条件建设区").strip()
            mj = float(props.get("MJ") or 0)
            name = str(props.get("XZQHM") or "建设区").strip()
            state.zones.append(PlannedZoneEntry(
                zone_type=zone_type,
                area_ha=mj / 10000.0 if mj else 0.0,
                name=name,
                geometry=wkt_str,
            ))
        logger.info("L4 ingest: %d PlannedZone from %s", len(state.zones), cz_path.name)

    return state


# ── L4 builder ──


def _apply_planned_state(self, planned_state: PlannedState) -> None:
    """Apply PlannedState to KG Layer 4.

    Sparse write: only entities with non-default values get L4 triples.
    Each entity tagged with pln:in_version for versioning.
    L4->L3 links written via pln:derived_from_target when source field set.
    """
    if not isinstance(planned_state, PlannedState):
        return

    version = planned_state.version or "current"
    count = 0

    # ── PlannedParcel (with bsm_seq dedup) ──
    bsm_seq_pp: dict[str, int] = {}
    for p in planned_state.parcels:
        bsm = p.bsm
        seq = bsm_seq_pp.get(bsm, 0)
        bsm_seq_pp[bsm] = seq + 1
        uri = EntityIdPolicy.uri_with_seq("planned_parcel", bsm, seq, version)
        self.g.add((uri, RDF.type, EntityTypes.PlannedParcel))
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, PLN.in_version, Literal(version)))
        if p.planning_land_use:
            self.g.add((uri, PLN.planning_land_use, Literal(p.planning_land_use)))
        if p.zone_type:
            self.g.add((uri, PLN.planning_zone_type, Literal(p.zone_type)))
        if p.area_ha:
            self.g.add((uri, PLN.planned_area_ha, Literal(p.area_ha, datatype=XSD.double)))
        if p.geometry:
            self.g.add((uri, PLN.geometry, Literal(p.geometry, datatype=XSD.string)))
        for parent_bsm in p.derived_from_bsms:
            for s in self.g.subjects(PLN.bsm, Literal(parent_bsm)):
                if (s, RDF.type, EntityTypes.Parcel) in self.g:
                    self.g.add((uri, PLN.derived_from, s))
                    break
        if p.derived_from_zone_target:
            self.g.add((uri, PLN.derived_from_target, URIRef(p.derived_from_zone_target)))
        count += 1

    # ── PlannedZone (with zone_seq dedup) ──
    zone_seq: dict[str, int] = {}
    for z in planned_state.zones:
        zone_id = z.zone_type or z.name or f"idx{count}"
        seq = zone_seq.get(zone_id, 0)
        zone_seq[zone_id] = seq + 1
        uri = EntityIdPolicy.uri_with_seq("planned_zone", zone_id, seq, version)
        self.g.add((uri, RDF.type, EntityTypes.PlannedZone))
        self.g.add((uri, PLN.zone_type, Literal(z.zone_type)))
        self.g.add((uri, PLN.in_version, Literal(version)))
        if z.name:
            self.g.add((uri, PLN.name, Literal(z.name)))
        if z.area_ha:
            self.g.add((uri, PLN.area_target_ha, Literal(z.area_ha, datatype=XSD.double)))
        if z.geometry:
            self.g.add((uri, PLN.geometry, Literal(z.geometry, datatype=XSD.string)))
        if z.derived_from_zone_target:
            self.g.add((uri, PLN.derived_from_target, URIRef(z.derived_from_zone_target)))
        count += 1

    # ── PlannedFacility ──
    for f in planned_state.facilities:
        fac_id = f.name or f.facility_type or f"idx{count}"
        uri = EntityIdPolicy.uri("planned_facility", fac_id, version)
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
        if f.derived_from_target:
            self.g.add((uri, PLN.derived_from_target, URIRef(f.derived_from_target)))
        count += 1

    # ── PlannedRoad ──
    for r in planned_state.roads:
        road_id = r.name or f"idx{count}"
        uri = EntityIdPolicy.uri("planned_road", road_id, version)
        self.g.add((uri, RDF.type, EntityTypes.PlannedRoad))
        self.g.add((uri, PLN.name, Literal(r.name)))
        self.g.add((uri, PLN.in_version, Literal(version)))
        if r.road_level:
            self.g.add((uri, PLN.road_level, Literal(r.road_level)))
        if r.width_m:
            self.g.add((uri, PLN.buffer_width_m, Literal(r.width_m, datatype=XSD.double)))
        if r.derived_from_target:
            self.g.add((uri, PLN.derived_from_target, URIRef(r.derived_from_target)))
        count += 1

    # ── PlannedAxis ──
    for a in planned_state.axes:
        axis_id = a.name or a.reference_feature or f"idx{count}"
        uri = EntityIdPolicy.uri("planned_axis", axis_id, version)
        self.g.add((uri, RDF.type, EntityTypes.PlannedAxis))
        self.g.add((uri, PLN.name, Literal(a.name)))
        self.g.add((uri, PLN.in_version, Literal(version)))
        if a.reference_feature:
            self.g.add((uri, PLN.reference_feature, Literal(a.reference_feature)))
        if a.direction:
            self.g.add((uri, PLN.direction, Literal(a.direction)))
        if a.derived_from_target:
            self.g.add((uri, PLN.derived_from_target, URIRef(a.derived_from_target)))
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
    """Check planned parcels against constraint polygons via spatial_ops bridge.

    Uses self._constraint_index (ConstraintIndex) if available.
    Returns list of violation dicts with bsm, planned_land_use, protected_zone, rule.
    """
    violations = []
    if self._constraint_index is None:
        logger.debug("check_constraint_violations: no constraint_index injected")
        return violations

    for pp in self.query(f"PREFIX pln: <http://village-planning.org/ontology#> "
                         f"SELECT ?p ?bsm ?land_use WHERE {{ "
                         f"?p a pln:PlannedParcel ; pln:bsm ?bsm ; "
                         f"pln:planning_land_use ?land_use ; pln:in_version \"{version}\" . }}"):
        bsm = pp.get("bsm", "")
        overlaps = self._constraint_index.parcel_in_constraint(bsm)
        for ov in overlaps:
            violations.append({
                "bsm": bsm,
                "planned_land_use": pp.get("land_use", ""),
                "protected_zone": ov.constraint_type,
                "rule": ov.rule,
                "overlap_area_sqm": ov.overlap_area_sqm,
                "overlap_pct": ov.overlap_pct,
                "version": version,
            })
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