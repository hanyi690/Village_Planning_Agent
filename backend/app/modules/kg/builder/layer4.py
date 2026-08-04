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

from pathlib import Path

from rdflib import Literal, RDF, URIRef
from rdflib.namespace import XSD

from app.utils.logger import get_logger
from ..ontology import PLN, EntityTypes, EntityIdPolicy
from app.modules.schema.contracts.planned_state_contracts import (
    PlannedAxis,
    PlannedFacility,
    PlannedParcel,
    PlannedRoad,
    PlannedState,
    PlannedZone,
)

logger = get_logger(__name__)


def ingest_planned_state_from_geojson(data_dir: str | Path) -> PlannedState:
    """Read planned/ GeoJSON files (landuse, road, construction_zone) into PlannedState.

    These are planning outputs (L4), not L1 reference layers:
      - planned/landuse.geojson  → PlannedParcel (GHYTBM = appendix5 planning code)
      - planned/road.geojson     → PlannedRoad (sparse: LnType + geometry)
      - planned/construction_zone.geojson → PlannedZone (LX = zone type)

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

    # ── planned/landuse.geojson → PlannedParcel ──
    landuse_path = data_dir / "planned" / "landuse.geojson"
    if landuse_path.exists():
        with open(landuse_path, encoding="utf-8") as f:
            data = json_load(f)
        for i, feat in enumerate(data.get("features", [])):
            props = feat.get("properties", {})
            geom = feat.get("geometry")
            wkt_str = _geojson_to_wkt(geom) if geom else ""
            bsm = str(props.get("BSM") or "").strip()
            land_use = str(props.get("GHYTBM") or props.get("GHFLBM") or "").strip()
            dlmj = float(props.get("DLMJ") or 0)
            state.parcels.append(PlannedParcel(
                bsm=bsm,
                planning_land_use=land_use,
                zone_type="planned",
                area_ha=dlmj / 10000.0 if dlmj else 0.0,
                geometry=wkt_str,
            ))
        logger.info("L4 ingest: %d PlannedParcel from %s", len(state.parcels), landuse_path.name)

    # ── planned/road.geojson → PlannedRoad ──
    road_path = data_dir / "planned" / "road.geojson"
    if road_path.exists():
        with open(road_path, encoding="utf-8") as f:
            data = json_load(f)
        for i, feat in enumerate(data.get("features", [])):
            props = feat.get("properties", {})
            ln_type = str(props.get("LnType") or "").strip()
            state.roads.append(PlannedRoad(
                name=f"规划道路_{i}",
                road_level=ln_type or "unknown",
                width_m=0.0,
            ))
        logger.info("L4 ingest: %d PlannedRoad from %s", len(state.roads), road_path.name)

    # ── planned/construction_zone.geojson → PlannedZone ──
    cz_path = data_dir / "planned" / "construction_zone.geojson"
    if cz_path.exists():
        with open(cz_path, encoding="utf-8") as f:
            data = json_load(f)
        for i, feat in enumerate(data.get("features", [])):
            props = feat.get("properties", {})
            geom = feat.get("geometry")
            wkt_str = _geojson_to_wkt(geom) if geom else ""
            zone_type = str(props.get("LX") or "有条件建设区").strip()
            mj = float(props.get("MJ") or 0)
            name = str(props.get("XZQHM") or "建设区").strip()
            state.zones.append(PlannedZone(
                zone_type=zone_type,
                area_ha=mj / 10000.0 if mj else 0.0,
                name=name,
                geometry=wkt_str,
            ))
        logger.info("L4 ingest: %d PlannedZone from %s", len(state.zones), cz_path.name)

    return state


# ── L4 builder ──


def apply_planned_state(kg, planned_state: PlannedState) -> None:
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
        kg.g.add((uri, RDF.type, EntityTypes.PlannedParcel))
        EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
        kg.g.add((uri, PLN.in_version, Literal(version)))
        if p.planning_land_use:
            kg.g.add((uri, PLN.planning_land_use, Literal(p.planning_land_use)))
        if p.zone_type:
            kg.g.add((uri, PLN.planning_zone_type, Literal(p.zone_type)))
        if p.area_ha:
            kg.g.add((uri, PLN.planned_area_ha, Literal(p.area_ha, datatype=XSD.double)))
        for parent_bsm in p.derived_from_bsms:
            for s in kg.g.subjects(PLN.bsm, Literal(parent_bsm)):
                if (s, RDF.type, EntityTypes.Parcel) in kg.g:
                    kg.g.add((uri, PLN.derived_from, s))
                    break
        if p.derived_from_zone_target:
            kg.g.add((uri, PLN.derived_from_target, URIRef(p.derived_from_zone_target)))
        if p.source_spec:
            kg.g.add((uri, PLN.source_spec, Literal(p.source_spec)))
        if p.decided_by:
            kg.g.add((uri, PLN.decided_by, Literal(p.decided_by)))
        if p.operation:
            kg.g.add((uri, PLN.operation, Literal(p.operation)))
        if p.area_change_ha:
            kg.g.add((uri, PLN.area_change_ha, Literal(p.area_change_ha, datatype=XSD.double)))
        count += 1

    # ── PlannedZone (with zone_seq dedup) ──
    zone_seq: dict[str, int] = {}
    for z in planned_state.zones:
        zone_id = z.zone_type or z.name or f"idx{count}"
        seq = zone_seq.get(zone_id, 0)
        zone_seq[zone_id] = seq + 1
        uri = EntityIdPolicy.uri_with_seq("planned_zone", zone_id, seq, version)
        kg.g.add((uri, RDF.type, EntityTypes.PlannedZone))
        kg.g.add((uri, PLN.zone_type, Literal(z.zone_type)))
        kg.g.add((uri, PLN.seq, Literal(seq, datatype=XSD.integer)))
        kg.g.add((uri, PLN.in_version, Literal(version)))
        if z.name:
            kg.g.add((uri, PLN.name, Literal(z.name)))
        if z.area_ha:
            kg.g.add((uri, PLN.area_target_ha, Literal(z.area_ha, datatype=XSD.double)))
        if z.derived_from_zone_target:
            kg.g.add((uri, PLN.derived_from_target, URIRef(z.derived_from_zone_target)))
        count += 1

    # ── PlannedFacility ──
    for f in planned_state.facilities:
        fac_id = f.name or f.facility_type or f"idx{count}"
        uri = EntityIdPolicy.uri("planned_facility", fac_id, version)
        kg.g.add((uri, RDF.type, EntityTypes.PlannedFacility))
        kg.g.add((uri, PLN.name, Literal(f.name)))
        kg.g.add((uri, PLN.in_version, Literal(version)))
        if f.facility_type:
            kg.g.add((uri, PLN.facility_type, Literal(f.facility_type)))
        if f.lon and f.lat:
            kg.g.add((uri, PLN.lon, Literal(f.lon, datatype=XSD.double)))
            kg.g.add((uri, PLN.lat, Literal(f.lat, datatype=XSD.double)))
        if f.service_radius:
            kg.g.add((uri, PLN.service_radius, Literal(f.service_radius, datatype=XSD.integer)))
        if f.derived_from_target:
            kg.g.add((uri, PLN.derived_from_target, URIRef(f.derived_from_target)))
        count += 1

    # ── PlannedRoad ──
    for r in planned_state.roads:
        road_id = r.name or f"idx{count}"
        uri = EntityIdPolicy.uri("planned_road", road_id, version)
        kg.g.add((uri, RDF.type, EntityTypes.PlannedRoad))
        kg.g.add((uri, PLN.name, Literal(r.name)))
        kg.g.add((uri, PLN.in_version, Literal(version)))
        if r.road_level:
            kg.g.add((uri, PLN.road_level, Literal(r.road_level)))
        if r.width_m:
            kg.g.add((uri, PLN.buffer_width_m, Literal(r.width_m, datatype=XSD.double)))
        if r.derived_from_target:
            kg.g.add((uri, PLN.derived_from_target, URIRef(r.derived_from_target)))
        count += 1

    # ── PlannedAxis ──
    for a in planned_state.axes:
        axis_id = a.name or a.reference_feature or f"idx{count}"
        uri = EntityIdPolicy.uri("planned_axis", axis_id, version)
        kg.g.add((uri, RDF.type, EntityTypes.PlannedAxis))
        kg.g.add((uri, PLN.name, Literal(a.name)))
        kg.g.add((uri, PLN.in_version, Literal(version)))
        if a.reference_feature:
            kg.g.add((uri, PLN.reference_feature, Literal(a.reference_feature)))
        if a.direction:
            kg.g.add((uri, PLN.direction, Literal(a.direction)))
        if a.derived_from_target:
            kg.g.add((uri, PLN.derived_from_target, URIRef(a.derived_from_target)))
        count += 1

    if count:
        logger.info("Layer 4: applied %d planned entities (version=%s)", count, version)
