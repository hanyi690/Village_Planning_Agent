"""Render KG for human inspection: deck.gl 3D geospatial visualization.

Builds the KG from local jintian GeoJSON files (L1+L4), then outputs:
  - kg_inspection.html   (self-contained: deck.gl 3D + MapLibre GL + 高德底图)
  - kg_full.ttl          (RDF Turtle dump)
  - kg_stats.json        (statistics)

Usage:
    cd backend
    python scripts/render_kg_inspection.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
_PROJECT_ROOT = _BACKEND_DIR.parent
os.chdir(_PROJECT_ROOT)

from rdflib import RDF, Literal, URIRef

from app.modules.data.ingest import ingest_current_landuse, ingest_feature
from app.modules.kg.builder import PlanningKG
from app.modules.kg.builder.layer4 import ingest_planned_state_from_geojson
from app.modules.kg.ontology import EntityTypes, Relations, GEO, PLN
from app.modules.schema.types.canonical import VillageBundle
from app.modules.spatial_ops import build_constraint_index
from app.modules.spatial_ops.geometry import compute_parcel_relations

# ── Constants ──

PLN_NS = "http://village-planning.org/ontology#"
GEO_NS = "http://www.opengis.net/ont/geosparql#"

_JINTIAN_DATA = _PROJECT_ROOT / "data" / "gis" / "jintian"

# Full appendix5 DLBM → (color, label, zone_type) mapping
DLBM_MAP: Dict[str, Tuple[str, str, str]] = {
    "1100": ("#b5d3a8", "耕地", "农业用地"),
    "1200": ("#d4e8c2", "园地", "农业用地"),
    "1340": ("#5a8f5a", "商品林", "林业用地"),
    "1350": ("#2d6a4f", "生态林", "生态绿地"),
    "1400": ("#d8f3dc", "草地", "生态绿地"),
    "1510": ("#c9b99a", "设施农用地", "农业用地"),
    "2121": ("#ffd166", "宅基地", "居住用地"),
    "2122": ("#f4a261", "公共服务设施用地", "公共服务用地"),
    "2124": ("#e76f51", "经营性建设用地", "产业用地"),
    "2125": ("#a8dadc", "景观与绿化用地", "公共服务用地"),
    "2126": ("#adb5bd", "村内交通用地", "交通用地"),
    "2200": ("#6c757d", "对外交通用地", "交通用地"),
    "2270": ("#7eb8d4", "水利设施用地", "农业用地"),
    "3100": ("#4ea8de", "水域", "水域"),
    "3200": ("#ced4da", "自然保留地", "农业用地"),
}

DEFAULT_DLBM_COLOR = "#e9ecef"
DEFAULT_DLBM_LABEL = "其他"

# Constraint zone colors (used for protection polygons)
ZONE_COLORS: Dict[str, str] = {
    "farmland_protection": "#e74c3c",
    "ecological_protection": "#27ae60",
    "historical_protection": "#8e44ad",
    "cultivated_land_target": "#e67e22",
    "urban_dev_boundary": "#c0392b",
    "village_dev_boundary": "#d35400",
    "nature_reserve": "#1abc9c",
}

DEFAULT_ZONE_COLOR = "#95a5a6"


def _dlbm_color(dlbm: str) -> str:
    if dlbm in DLBM_MAP:
        return DLBM_MAP[dlbm][0]
    return DEFAULT_DLBM_COLOR

def _dlbm_label(dlbm: str) -> str:
    if dlbm in DLBM_MAP:
        return DLBM_MAP[dlbm][1]
    return DEFAULT_DLBM_LABEL

def _dlbm_zone_type(dlbm: str) -> str:
    if dlbm in DLBM_MAP:
        return DLBM_MAP[dlbm][2]
    return ""


# ── Helpers for deck.gl data conversion ──

def _hex_to_rgba(hex_color: str, alpha: int = 255) -> list:
    h = hex_color.lstrip("#")
    return [int(h[i:i+2], 16) for i in (0, 2, 4)] + [alpha]


def _geojson_to_deck_polygons(geom: dict) -> list:
    if not geom or "type" not in geom:
        return []
    if geom["type"] == "Polygon":
        return [[[list(c) for c in ring] for ring in geom["coordinates"]]]
    elif geom["type"] == "MultiPolygon":
        result = []
        for polygon in geom["coordinates"]:
            rings = [[list(c) for c in ring] for ring in polygon]
            if rings:
                result.append(rings)
        return result
    return []


def _collect_parcel_centroids(bundle: VillageBundle) -> dict:
    from shapely.geometry import shape
    centroids = {}
    # Parcels
    for p in bundle.polygons.get("landuse_current") or []:
        bsm = str(getattr(p, "bsm", "")).strip()
        geom = getattr(p, "geometry", None)
        if not bsm or not isinstance(geom, dict):
            continue
        try:
            s = shape(geom)
            c = s.centroid
            if not c.is_empty:
                centroids[bsm] = (c.x, c.y)
        except Exception:
            pass
    # Roads (line centroids)
    for r in bundle.lines.get("roads_current") or []:
        bsm = str(getattr(r, "bsm", "")).strip()
        geom = getattr(r, "geometry", None)
        if not bsm or not isinstance(geom, dict):
            continue
        try:
            s = shape(geom)
            c = s.centroid
            if not c.is_empty:
                centroids[bsm] = (c.x, c.y)
        except Exception:
            pass
    # Protection zones (polygon centroids)
    for zt in ("farmland_protection", "ecological_redline", "historical_protection"):
        for z in bundle.polygons.get(zt) or []:
            bsm = str(getattr(z, "bsm", "")).strip()
            geom = getattr(z, "geometry", None)
            if not bsm or not isinstance(geom, dict):
                continue
            try:
                s = shape(geom)
                c = s.centroid
                if not c.is_empty:
                    centroids[bsm] = (c.x, c.y)
            except Exception:
                pass
    return centroids


def _compute_center(bundle: VillageBundle) -> tuple:
    from shapely.geometry import shape
    lngs, lats = [], []
    for p in bundle.polygons.get("landuse_current") or []:
        geom = getattr(p, "geometry", None)
        if not isinstance(geom, dict):
            continue
        try:
            s = shape(geom)
            if s.is_empty:
                continue
            bounds = s.bounds
            lngs.extend([bounds[0], bounds[2]])
            lats.extend([bounds[1], bounds[3]])
        except Exception:
            pass
    if lngs and lats:
        return (min(lngs) + max(lngs)) / 2, (min(lats) + max(lats)) / 2
    return (116.0415, 24.819)


# ── Step 1: Build KG ──

def build_kg(village_name: str = "jintian") -> Tuple[PlanningKG, VillageBundle]:
    bundle = VillageBundle(village_name=village_name)

    # L1: current landuse
    parcels, _ = ingest_current_landuse(str(_JINTIAN_DATA / "current" / "landuse.geojson"))
    for p in parcels:
        bundle.add(p)

    # L1: current roads
    roads, _ = ingest_feature(str(_JINTIAN_DATA / "current" / "road.geojson"), "current_road")
    for r in roads:
        bundle.add(r)

    # L1: current annotations
    anns, _ = ingest_feature(str(_JINTIAN_DATA / "current" / "annotation.geojson"), "current_annotation")
    for a in anns:
        bundle.add(a)

    # L1: admin boundary
    boundary, _ = ingest_feature(str(_JINTIAN_DATA / "current" / "boundary.geojson"), "admin_area")
    for b in boundary:
        bundle.add(b)

    # L1: admin boundary line
    try:
        abl, _ = ingest_feature(str(_JINTIAN_DATA / "current" / "admin_boundary_line.geojson"), "admin_boundary_line")
        for a in abl:
            bundle.add(a)
    except Exception:
        pass

    # L1: constraint reference polygons
    for feature_type, filename in [
        ("farmland_protection", "farmland_protection.geojson"),
        ("ecological_redline", "ecological_protection.geojson"),
        ("historical_protection", "historical_protection.geojson"),
    ]:
        path = _JINTIAN_DATA / "planned" / filename
        if path.exists():
            feats, _ = ingest_feature(str(path), feature_type)
            for f in feats:
                bundle.add(f)

    if bundle.parcel_count == 0:
        raise RuntimeError("No parcels loaded")

    # Spatial relations
    parcel_relations = compute_parcel_relations(
        bundle.polygons.get("landuse_current"),
        roads=bundle.lines.get("roads_current"),
    )
    constraint_index = build_constraint_index(bundle)

    # L4: planned state from GeoJSON
    planned_state = ingest_planned_state_from_geojson(_JINTIAN_DATA)

    # Assign BSMs to planned parcels using bundle's counter (same village sequence)
    for p in planned_state.parcels:
        bundle._assign_bsm(p)

    # Inject planned geometry into bundle (replaces KG pln:geometry)
    from shapely import wkt as shapely_wkt
    from shapely.geometry import mapping

    planned_parcel_features = []
    for p in planned_state.parcels:
        if p.geometry:
            try:
                s = shapely_wkt.loads(p.geometry)
                geom = mapping(s)
                planned_parcel_features.append({"bsm": p.bsm, "geometry": geom})
            except Exception:
                continue
    bundle.polygons.set("planned_parcels", planned_parcel_features)

    planned_zone_features = []
    zone_seq: dict[str, int] = {}
    for z in planned_state.zones:
        zone_id = z.zone_type or z.name or ""
        seq = zone_seq.get(zone_id, 0)
        zone_seq[zone_id] = seq + 1
        if z.geometry:
            try:
                s = shapely_wkt.loads(z.geometry)
                geom = mapping(s)
                planned_zone_features.append({"zone_type": z.zone_type, "name": z.name, "seq": seq, "geometry": geom})
            except Exception:
                continue
    bundle.polygons.set("planned_zones", planned_zone_features)

    kg = PlanningKG(village_name=village_name)
    kg.build_from_bundle(
        bundle=bundle,
        parcel_relations=parcel_relations,
        constraint_index=constraint_index,
        planned_state=planned_state,
    )
    return kg, bundle


# ── Step 2: Stats JSON ──

def _short_uri(uri: Any) -> str:
    s = str(uri)
    if s.startswith(PLN_NS):
        return "pln:" + s[len(PLN_NS):]
    if s.startswith(GEO_NS):
        return "geo:" + s[len(GEO_NS):]
    return s

def build_stats(kg: PlanningKG, village_name: str) -> Dict[str, Any]:
    entity_counts: Counter = Counter()
    for s, _, o in kg.g.triples((None, RDF.type, None)):
        short = _short_uri(o)
        if short.startswith(("pln:", "geo:")):
            entity_counts[short] += 1

    relation_predicates = {_short_uri(r): r for r in Relations.all()}
    relation_counts: Counter = Counter()
    for pred_short, pred_uri in relation_predicates.items():
        relation_counts[pred_short] = len(list(kg.g.triples((None, pred_uri, None))))

    return {
        "village_name": village_name,
        "triple_count": kg.get_triple_count(),
        "parcel_count": len(list(kg.g.subjects(RDF.type, EntityTypes.Parcel))),
        "entity_breakdown": dict(entity_counts.most_common()),
        "relation_breakdown": dict(relation_counts.most_common()),
    }

def write_stats(stats: Dict[str, Any], output_dir: Path) -> Path:
    path = output_dir / "kg_stats.json"
    path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ── Step 3: Turtle dump ──

def write_turtle(kg: PlanningKG, output_dir: Path) -> Path:
    path = output_dir / "kg_full.ttl"
    turtle_str = kg.to_turtle()
    if isinstance(turtle_str, bytes):
        turtle_str = turtle_str.decode("utf-8")
    path.write_text(turtle_str, encoding="utf-8")
    return path


# ── Step 4: Query functions for deck.gl data ──

def _fix_geom(geom: Optional[dict]) -> Optional[dict]:
    if not geom or not isinstance(geom, dict):
        return None
    try:
        from shapely.geometry import shape, mapping
        s = shape(geom)
        if s.is_empty:
            return None
        if not s.is_valid:
            s = s.buffer(0)
            if s.is_empty:
                return None
        return mapping(s)
    except Exception:
        return None


def _query_parcels(kg: PlanningKG, bundle: VillageBundle) -> List[dict]:
    geom_lookup: Dict[Tuple[str, int], dict] = {}
    seq_counter: Dict[str, int] = {}
    for p in bundle.polygons.get("landuse_current") or []:
        bsm = str(getattr(p, "bsm", "")).strip()
        geom = getattr(p, "geometry", None)
        if not bsm or not isinstance(geom, dict):
            continue
        seq = seq_counter.get(bsm, 0)
        seq_counter[bsm] = seq + 1
        geom_lookup[(bsm, seq)] = geom

    sparql = f"""
    PREFIX pln: <{PLN_NS}>
    SELECT ?bsm ?seq ?dlbm ?area ?zone ?semLabel ?taxParent ?legalConstraint ?primZone ?planZone ?decidedBy ?decConf ?decEvid WHERE {{
      ?p a pln:Parcel ; pln:bsm ?bsm .
      OPTIONAL {{ ?p pln:seq ?seq . }}
      OPTIONAL {{ ?p pln:dlbm ?dlbm . }}
      OPTIONAL {{ ?p pln:area_sqm ?area . }}
      OPTIONAL {{ ?p pln:current_zone_type ?zone . }}
      OPTIONAL {{ ?p pln:has_semantic_label ?semLabel . }}
      OPTIONAL {{ ?p pln:taxonomic_parent ?taxParent . }}
      OPTIONAL {{ ?p pln:legal_constraint ?legalConstraint . }}
      OPTIONAL {{ ?p pln:primary_zone ?primZone . }}
      OPTIONAL {{ ?p pln:planning_zone ?planZone . }}
      OPTIONAL {{ ?p pln:decided_by ?decidedBy . }}
      OPTIONAL {{ ?p pln:decision_confidence ?decConf . }}
      OPTIONAL {{ ?p pln:decision_evidence ?decEvid . }}
    }}
    """
    rows = kg.query(sparql)
    items = []
    for row in rows:
        bsm = row.get("bsm", "")
        seq = int(row.get("seq") or 0) if row.get("seq") else 0
        dlbm = row.get("dlbm", "") or ""
        geom = geom_lookup.get((bsm, seq))
        if not geom:
            continue
        geom = _fix_geom(geom)
        if not geom:
            continue
        contours = _geojson_to_deck_polygons(geom)
        if not contours:
            continue
        color_hex = _dlbm_color(dlbm)
        color = _hex_to_rgba(color_hex)
        tooltip_parts = []
        tooltip_parts.append(f'<b>BSM:</b> {bsm}')
        tooltip_parts.append(f'<b>DLBM:</b> {dlbm} ({_dlbm_label(dlbm)})')
        tooltip_parts.append(f'<b>面积:</b> {round(float(row.get("area") or 0), 1)} m²')
        tooltip_parts.append(f'<b>分区:</b> {row.get("zone", "") or _dlbm_zone_type(dlbm)}')
        if row.get("semLabel"):
            tooltip_parts.append(f'<b>语义标签:</b> {row["semLabel"]}')
        if row.get("taxParent"):
            tooltip_parts.append(f'<b>分类归属:</b> {row["taxParent"]}')
        if row.get("legalConstraint"):
            tooltip_parts.append(f'<b>约束:</b> {row["legalConstraint"]}')
        if row.get("primZone") or row.get("planZone"):
            tooltip_parts.append(f'<b>三区:</b> {row.get("primZone","?")} → {row.get("planZone","?")}')
        if row.get("decidedBy"):
            tooltip_parts.append(f'<b>决策:</b> {row["decidedBy"]} ({row.get("decConf","?")})')
        for contour in contours:
            items.append({
                "contour": contour,
                "color": color,
                "tooltip": "<br>".join(tooltip_parts),
                "bsm": bsm,
                "dlbm": dlbm,
                "dlbm_label": _dlbm_label(dlbm),
                "area_sqm": round(float(row.get("area") or 0), 1),
                "zone_type": row.get("zone", "") or _dlbm_zone_type(dlbm),
            })
    return items


def _query_zones(kg: PlanningKG, bundle: VillageBundle) -> List[dict]:
    from shapely.geometry import mapping
    items = []

    # Build geometry lookup from bundle: {gtype: {bsm: feature_dict}}
    # Map KG gtype -> bundle polygon key (differ for ecological due to naming)
    _GTYPE_TO_BUNDLE = {
        "farmland_protection": "farmland_protection",
        "ecological_protection": "ecological_redline",
        "historical_protection": "historical_protection",
    }
    bundle_geom: Dict[str, Dict[str, dict]] = {}
    for gtype_key, bundle_key in _GTYPE_TO_BUNDLE.items():
        feats = bundle.polygons.get(bundle_key) or []
        lookup: Dict[str, dict] = {}
        for f in feats:
            geom = getattr(f, "geometry", None)
            if not geom or not isinstance(geom, dict):
                continue
            bsm = str(getattr(f, "bsm", "")).strip()
            if bsm:
                contours = _geojson_to_deck_polygons(geom)
                if contours:
                    lookup[bsm] = {"contour": contours, "geometry": geom}
        bundle_geom[gtype_key] = lookup

    for s in kg.g.subjects(RDF.type, EntityTypes.Zone):
        props = {}
        bsm = ""
        for p, o in kg.g.predicate_objects(s):
            ps = _short_uri(p)
            if ps == "pln:current_zone_type":
                props["zone_type"] = str(o)
            elif ps == "pln:has_semantic_label":
                props["label"] = str(o)
            elif ps == "pln:gis_type_ref":
                props["gtype"] = str(o)
            elif ps == "pln:legal_constraint":
                props["constraint"] = str(o)
            elif ps == "pln:bsm":
                bsm = str(o)
        gtype = props.get("gtype", "")
        # Look up geometry from bundle
        contours = None
        if gtype in bundle_geom and bsm in bundle_geom[gtype]:
            contours = bundle_geom[gtype][bsm]["contour"]
        if not contours:
            continue
        zt = props.get("zone_type", "")
        label = props.get("label", "") or zt
        color_hex = ZONE_COLORS.get(gtype, DEFAULT_ZONE_COLOR)
        color = _hex_to_rgba(color_hex)
        tooltip_parts = []
        tooltip_parts.append(f'<b>类型:</b> {zt}')
        tooltip_parts.append(f'<b>标签:</b> {label}')
        if props.get("constraint"):
            tooltip_parts.append(f'<b>约束:</b> {props["constraint"]}')
        for contour in contours:
            items.append({
                "contour": contour,
                "color": color,
                "tooltip": "<br>".join(tooltip_parts),
                "zone_type": zt,
                "label": label,
                "gtype": gtype,
            })
    return items


def _query_roads(kg: PlanningKG, bundle: VillageBundle) -> List[dict]:
    from shapely.geometry import shape
    # Build geometry lookup from bundle: {bsm: geojson_geom}
    geom_lookup = {}
    for r in bundle.lines.get("roads_current") or []:
        bsm = str(getattr(r, "bsm", "")).strip()
        geom = getattr(r, "geometry", None)
        if bsm and isinstance(geom, dict):
            geom_lookup[bsm] = geom

    items = []
    for s in kg.g.subjects(RDF.type, EntityTypes.Road):
        name = ""
        label = ""
        bsm = ""
        for p, o in kg.g.predicate_objects(s):
            ps = _short_uri(p)
            if ps == "pln:name":
                name = str(o)
            elif ps == "pln:has_semantic_label":
                label = str(o)
            elif ps == "pln:bsm":
                bsm = str(o)
        geom = geom_lookup.get(bsm)
        if not geom:
            continue
        if geom.get("type") == "MultiLineString":
            path = [[c[0], c[1]] for c in geom["coordinates"][0]]
        elif geom.get("type") == "LineString":
            path = [[c[0], c[1]] for c in geom["coordinates"]]
        else:
            continue
        items.append({
            "path": path,
            "color": [243, 156, 18, 200],
            "width": 2,
            "tooltip": f'<b>道路:</b> {name or label or ""}',
            "name": name or label or "",
        })
    return items


def _query_facilities(kg: PlanningKG) -> List[dict]:
    items = []
    for s in kg.g.subjects(RDF.type, EntityTypes.Facility):
        name = ""
        ftype = ""
        lat = None
        lon = None
        for p, o in kg.g.predicate_objects(s):
            ps = _short_uri(p)
            if ps == "pln:name":
                name = str(o)
            elif ps == "pln:facility_type":
                ftype = str(o)
            elif ps == "pln:lat":
                try: lat = float(o)
                except: pass
            elif ps == "pln:lon":
                try: lon = float(o)
                except: pass
        if lat is not None and lon is not None:
            items.append({
                "position": [lon, lat],
                "radius": 40,
                "color": [231, 76, 60, 255],
                "tooltip": f'<b>设施:</b> {name or ""}<br><b>类型:</b> {ftype or ""}',
                "name": name or "",
                "ftype": ftype or "",
            })
    return items


def _query_residential_clusters(kg: PlanningKG) -> List[dict]:
    items = []
    for s in kg.g.subjects(RDF.type, EntityTypes.ResidentialCluster):
        name = ""
        lat = None
        lon = None
        for p, o in kg.g.predicate_objects(s):
            ps = _short_uri(p)
            if ps in ("pln:name", "pln:has_semantic_label"):
                name = str(o)
            elif ps == "pln:lat":
                try: lat = float(o)
                except: pass
            elif ps == "pln:lon":
                try: lon = float(o)
                except: pass
        if lat is not None and lon is not None:
            items.append({
                "position": [lon, lat],
                "height": 50,
                "color": [233, 30, 99, 200],
                "tooltip": f'<b>居民点:</b> {name or ""}',
                "name": name or "",
            })
    return items


def _query_planned_parcels(kg: PlanningKG, bundle: VillageBundle) -> List[dict]:
    geom_lookup: Dict[str, dict] = {}
    for p in bundle.polygons.get("planned_parcels") or []:
        if isinstance(p, dict):
            bsm = str(p.get("bsm", "")).strip()
            geom = p.get("geometry")
        else:
            bsm = str(getattr(p, "bsm", "")).strip()
            geom = getattr(p, "geometry", None)
        if bsm and isinstance(geom, dict):
            geom_lookup[bsm] = geom

    items = []
    for s in kg.g.subjects(RDF.type, EntityTypes.PlannedParcel):
        bsm = ""
        lu = ""
        area = 0.0
        for p, o in kg.g.predicate_objects(s):
            ps = _short_uri(p)
            if ps == "pln:bsm":
                bsm = str(o)
            elif ps == "pln:planning_land_use":
                lu = str(o)
            elif ps == "pln:planned_area_ha":
                try:
                    area = float(o)
                except (ValueError, TypeError):
                    pass
        if not bsm or bsm not in geom_lookup:
            continue
        geom = _fix_geom(geom_lookup[bsm])
        if not geom:
            continue
        contours = _geojson_to_deck_polygons(geom)
        if not contours:
            continue
        color_hex = _dlbm_color(lu) if lu else "#9b59b6"
        color = _hex_to_rgba(color_hex)
        label = _dlbm_label(lu) if lu else "规划"
        tooltip_parts = []
        tooltip_parts.append(f'<b>规划地块 BSM:</b> {bsm}')
        tooltip_parts.append(f'<b>规划用地:</b> {lu} ({label})')
        if area:
            tooltip_parts.append(f'<b>面积:</b> {round(area, 2)} ha')
        for contour in contours:
            items.append({
                "contour": contour,
                "color": color,
                "tooltip": "<br>".join(tooltip_parts),
                "bsm": bsm,
                "planning_land_use": lu,
                "label": label,
                "area_ha": round(area, 2),
            })
    return items


def _query_planned_zones(kg: PlanningKG, bundle: VillageBundle) -> List[dict]:
    geom_lookup: Dict[Tuple[str, str, int], dict] = {}
    for z in bundle.polygons.get("planned_zones") or []:
        if isinstance(z, dict):
            zt = str(z.get("zone_type", "")).strip()
            name = str(z.get("name", "")).strip()
            seq = int(z.get("seq", 0))
            geom = z.get("geometry")
        else:
            zt = str(getattr(z, "zone_type", "")).strip()
            name = str(getattr(z, "name", "")).strip()
            seq = int(getattr(z, "seq", 0))
            geom = getattr(z, "geometry", None)
        if zt and isinstance(geom, dict):
            geom_lookup[(zt, name, seq)] = geom

    items = []
    for s in kg.g.subjects(RDF.type, EntityTypes.PlannedZone):
        zt = ""
        name = ""
        area = 0.0
        seq = 0
        for p, o in kg.g.predicate_objects(s):
            ps = _short_uri(p)
            if ps == "pln:zone_type":
                zt = str(o)
            elif ps == "pln:name":
                name = str(o)
            elif ps == "pln:area_target_ha":
                try:
                    area = float(o)
                except (ValueError, TypeError):
                    pass
            elif ps == "pln:seq":
                try:
                    seq = int(o)
                except (ValueError, TypeError):
                    pass
        key = (zt, name, seq)
        if key not in geom_lookup:
            continue
        geom = _fix_geom(geom_lookup[key])
        if not geom:
            continue
        contours = _geojson_to_deck_polygons(geom)
        if not contours:
            continue
        color = [142, 68, 173, 200]
        tooltip_parts = []
        tooltip_parts.append(f'<b>规划分区:</b> {zt}')
        tooltip_parts.append(f'<b>名称:</b> {name}')
        if area:
            tooltip_parts.append(f'<b>面积:</b> {round(area, 2)} ha')
        for contour in contours:
            items.append({
                "contour": contour,
                "color": color,
                "tooltip": "<br>".join(tooltip_parts),
                "zone_type": zt,
                "name": name,
                "area_ha": round(area, 2),
            })
    return items


def _query_boundary(bundle: VillageBundle) -> List[dict]:
    items = []
    for p in bundle.polygons.get("admin_areas") or []:
        geom = getattr(p, "geometry", None)
        if not geom or not isinstance(geom, dict):
            continue
        contours = _geojson_to_deck_polygons(geom)
        if not contours:
            continue
        for contour in contours:
            items.append({
                "contour": contour,
                "color": [255, 255, 255, 255],
            })
    return items


def _collect_l2_relations(kg: PlanningKG, parcel_centroids: dict) -> List[dict]:
    items = []
    for s, p, o in kg.g.triples((None, Relations.sfTouches, None)):
        s_bsm = None
        o_bsm = None
        for p1, o1 in kg.g.predicate_objects(s):
            if _short_uri(p1) == "pln:bsm":
                s_bsm = str(o1)
                break
        for p2, o2 in kg.g.predicate_objects(o):
            if _short_uri(p2) == "pln:bsm":
                o_bsm = str(o2)
                break
        if s_bsm and o_bsm and s_bsm in parcel_centroids and o_bsm in parcel_centroids:
            ca, cb = parcel_centroids[s_bsm], parcel_centroids[o_bsm]
            items.append({
                "source": [ca[0], ca[1], 200],
                "target": [cb[0], cb[1], 200],
                "color": [46, 204, 113, 180],
                "type": "sfTouches",
                "width": 1.5,
            })

    for s, p, o in kg.g.triples((None, Relations.connected_via_road, None)):
        s_bsm = None
        o_bsm = None
        for p1, o1 in kg.g.predicate_objects(s):
            if _short_uri(p1) == "pln:bsm":
                s_bsm = str(o1)
                break
        for p2, o2 in kg.g.predicate_objects(o):
            if _short_uri(p2) == "pln:bsm":
                o_bsm = str(o2)
                break
        if s_bsm and o_bsm and s_bsm in parcel_centroids and o_bsm in parcel_centroids:
            ca, cb = parcel_centroids[s_bsm], parcel_centroids[o_bsm]
            items.append({
                "source": [ca[0], ca[1], 200],
                "target": [cb[0], cb[1], 200],
                "color": [52, 152, 219, 180],
                "type": "connected_via_road",
                "width": 1.5,
            })

    # nearby — sample 100 max
    nearby_count = 0
    for s, p, o in kg.g.triples((None, Relations.nearby, None)):
        if nearby_count >= 100:
            break
        s_bsm = None
        o_bsm = None
        for p1, o1 in kg.g.predicate_objects(s):
            if _short_uri(p1) == "pln:bsm":
                s_bsm = str(o1)
                break
        for p2, o2 in kg.g.predicate_objects(o):
            if _short_uri(p2) == "pln:bsm":
                o_bsm = str(o2)
                break
        if s_bsm and o_bsm and s_bsm in parcel_centroids and o_bsm in parcel_centroids:
            ca, cb = parcel_centroids[s_bsm], parcel_centroids[o_bsm]
            items.append({
                "source": [ca[0], ca[1], 200],
                "target": [cb[0], cb[1], 200],
                "color": [155, 89, 182, 120],
                "type": "nearby",
                "width": 0.8,
            })
            nearby_count += 1

    # sfWithin
    for s, p, o in kg.g.triples((None, Relations.sfWithin, None)):
        s_bsm = None
        o_bsm = None
        for p1, o1 in kg.g.predicate_objects(s):
            if _short_uri(p1) == "pln:bsm":
                s_bsm = str(o1)
                break
        for p2, o2 in kg.g.predicate_objects(o):
            if _short_uri(p2) == "pln:bsm":
                o_bsm = str(o2)
                break
        if s_bsm and o_bsm and s_bsm in parcel_centroids and o_bsm in parcel_centroids:
            ca, cb = parcel_centroids[s_bsm], parcel_centroids[o_bsm]
            items.append({
                "source": [ca[0], ca[1], 200],
                "target": [cb[0], cb[1], 200],
                "color": [231, 76, 60, 150],
                "type": "sfWithin",
                "width": 1.5,
            })

    # sfIntersects
    for s, p, o in kg.g.triples((None, Relations.sfIntersects, None)):
        s_bsm = None
        o_bsm = None
        for p1, o1 in kg.g.predicate_objects(s):
            if _short_uri(p1) == "pln:bsm":
                s_bsm = str(o1)
                break
        for p2, o2 in kg.g.predicate_objects(o):
            if _short_uri(p2) == "pln:bsm":
                o_bsm = str(o2)
                break
        if s_bsm and o_bsm and s_bsm in parcel_centroids and o_bsm in parcel_centroids:
            ca, cb = parcel_centroids[s_bsm], parcel_centroids[o_bsm]
            items.append({
                "source": [ca[0], ca[1], 200],
                "target": [cb[0], cb[1], 200],
                "color": [241, 196, 15, 150],
                "type": "sfIntersects",
                "width": 1.5,
            })

    return items


# ── Step 5: HTML generation (deck.gl 3D) ──

def _make_dlbm_legend_html() -> str:
    items = []
    for code, (color, label, _) in sorted(DLBM_MAP.items()):
        items.append(
            f'<span class="lg"><i style="background:{color}"></i>{code} {label}</span>'
        )
    return "".join(items)

def _make_zone_legend_html() -> str:
    items = []
    for gtype, color in sorted(ZONE_COLORS.items()):
        label = gtype.replace("_", " ")
        items.append(
            f'<span class="lg"><i style="background:{color}"></i>{label}</span>'
        )
    items.append(f'<span class="lg"><i style="background:{DEFAULT_ZONE_COLOR}"></i>other</span>')
    return "".join(items)


def _make_entity_tree_html(stats: Dict[str, Any]) -> str:
    parts = []
    layers = {
        "L1 现状实体": [],
        "L4 规划成果": [],
        "其他": [],
    }
    for short, cnt in stats.get("entity_breakdown", {}).items():
        if short.startswith("geo:"):
            continue
        if short.startswith("pln:Planned"):
            layers["L4 规划成果"].append((short, cnt))
        elif short.startswith("pln:"):
            layers["L1 现状实体"].append((short, cnt))
        else:
            layers["其他"].append((short, cnt))

    for layer_name, items in layers.items():
        if not items:
            continue
        parts.append(f'<div class="layer-group"><b>{layer_name}</b></div>')
        for short, cnt in items:
            label = short.split(":")[-1]
            cls = "type-entity"
            parts.append(
                f'<div class="{cls}" data-type="{short}">{label} <span class="cnt">{cnt}</span></div>'
            )

    return "\n".join(parts)

def _make_relation_list_html(stats: Dict[str, Any]) -> str:
    parts = []
    parts.append('<div class="section-title">空间关系</div>')
    for short, cnt in stats.get("relation_breakdown", {}).items():
        if cnt == 0:
            continue
        label = short.split(":")[-1]
        parts.append(
            f'<div class="rel-item" data-rel="{short}">{label} <span class="cnt">{cnt}</span></div>'
        )
    return "\n".join(parts)


def write_html(kg: PlanningKG, bundle: VillageBundle, stats: Dict[str, Any], output_dir: Path) -> Path:
    """Write self-contained kg_inspection.html (deck.gl 3D + MapLibre GL + 高德底图)."""

    # Collect all layer data
    parcel_data = _query_parcels(kg, bundle)
    zone_data = _query_zones(kg, bundle)
    road_data = _query_roads(kg, bundle)
    facility_data = _query_facilities(kg)
    cluster_data = _query_residential_clusters(kg)
    planned_parcel_data = _query_planned_parcels(kg, bundle)
    planned_zone_data = _query_planned_zones(kg, bundle)
    boundary_data = _query_boundary(bundle)

    # L2 spatial relations
    parcel_centroids = _collect_parcel_centroids(bundle)
    l2_relations = _collect_l2_relations(kg, parcel_centroids)

    # Compute center
    center_lng, center_lat = _compute_center(bundle)

    # Legend HTML
    dlbm_legend = _make_dlbm_legend_html()
    zone_legend = _make_zone_legend_html()
    entity_tree_html = _make_entity_tree_html(stats)
    relation_list_html = _make_relation_list_html(stats)

    # Serialize all data
    data_json = json.dumps({
        "parcels": parcel_data,
        "zones": zone_data,
        "roads": road_data,
        "facilities": facility_data,
        "clusters": cluster_data,
        "planned_parcels": planned_parcel_data,
        "planned_zones": planned_zone_data,
        "l2_relations": l2_relations,
        "boundary": boundary_data,
    }, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KG Inspection 3D - 金田村 ({stats['triple_count']} triples)</title>
<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@4.1.0/dist/maplibre-gl.css">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:"Microsoft YaHei",sans-serif; background:#1a1a2e; color:#eee; overflow:hidden; height:100vh; }}
#topbar {{ padding:6px 16px; background:#16213e; display:flex; flex-wrap:wrap; gap:12px; align-items:center; font-size:13px; z-index:10; position:relative; }}
#topbar .stat {{ color:#ffd380; font-weight:bold; }}
#topbar .layer-toggle {{ cursor:pointer; padding:2px 8px; border-radius:4px; font-size:12px; border:1px solid transparent; user-select:none; }}
#topbar .layer-toggle.active {{ background:#0f3460; border-color:#4ea8de; }}
#main {{ display:flex; height:calc(100vh - 36px); }}
#sidebar {{ width:200px; min-width:200px; background:#0f3460; overflow-y:auto; padding:8px; font-size:12px; z-index:10; position:relative; }}
#sidebar .section-title {{ color:#ffd380; font-weight:bold; margin:8px 0 4px; font-size:13px; }}
#sidebar .layer-group {{ margin:6px 0 2px; color:#4ea8de; font-size:12px; }}
#sidebar .type-entity,.sidebar .rel-item {{ cursor:pointer; padding:2px 6px; border-radius:3px; }}
#sidebar .type-entity:hover,.sidebar .rel-item:hover {{ background:#1a1a4e; }}
#sidebar .cnt {{ color:#888; float:right; }}
#map {{ flex:1; min-width:0; }}
#legend {{ background:#0f3460; padding:3px 12px; display:flex; flex-wrap:wrap; gap:6px; font-size:11px; overflow-x:auto; z-index:10; position:relative; }}
#legend .lg {{ display:inline-flex; align-items:center; gap:3px; white-space:nowrap; }}
#legend .lg i {{ width:12px; height:12px; border-radius:2px; display:inline-block; border:1px solid rgba(255,255,255,0.3); }}
.deck-tooltip {{ font-size:12px; line-height:1.5; max-width:320px; pointer-events:none; background:rgba(22,33,62,0.92); color:#eee; padding:8px 12px; border-radius:6px; border:1px solid #4ea8de; }}
</style>
</head>
<body>
<div id="topbar">
  <b style="color:#ffd380;font-size:14px;">KG 3D 金田村</b>
  <span class="layer-toggle active" data-layer="basemap">底图</span>
  <div>三元组: <span class="stat">{stats['triple_count']}</span></div>
  <div>实体类型: <span class="stat">{len(stats['entity_breakdown'])}</span></div>
  <div>地块: <span class="stat">{stats['parcel_count']}</span></div>
  <span class="layer-toggle active" data-layer="parcels">地块</span>
  <span class="layer-toggle" data-layer="planned_parcels">规划地块</span>
  <span class="layer-toggle" data-layer="planned_zones">规划分区</span>
  <span class="layer-toggle active" data-layer="roads">道路</span>
  <span class="layer-toggle" data-layer="rel_sfTouches">相邻({stats['relation_breakdown'].get('geo:sfTouches', 0)})</span>
  <span class="layer-toggle" data-layer="rel_connected_via_road">道路连接({stats['relation_breakdown'].get('pln:connected_via_road', 0)})</span>
  <span class="layer-toggle" data-layer="rel_nearby">邻近(100)</span>
  <span class="layer-toggle" data-layer="rel_sfWithin">包含({stats['relation_breakdown'].get('geo:sfWithin', 0)})</span>
  <span class="layer-toggle" data-layer="rel_sfIntersects">相交({stats['relation_breakdown'].get('geo:sfIntersects', 0)})</span>
  <span class="layer-toggle" data-layer="facilities">设施</span>
  <span class="layer-toggle" data-layer="clusters">居民点</span>
  <span class="layer-toggle" data-layer="zones_farmland">农田保护(88)</span>
  <span class="layer-toggle active" data-layer="zones_ecological">生态红线(5)</span>
  <span class="layer-toggle active" data-layer="zones_historical">历史保护(3)</span>
  <span class="layer-toggle" data-layer="boundary">村界</span>
</div>
<div id="main">
  <div id="sidebar">
    <div class="section-title">实体浏览器</div>
    {entity_tree_html}
    <hr style="border-color:#333;margin:8px 0;">
    {relation_list_html}
  </div>
  <div id="map"></div>
</div>
<div id="legend">
  <span style="color:#ffd380;font-weight:bold;margin-right:4px;">DLBM:</span>
  {dlbm_legend}
  <span style="color:#ffd380;font-weight:bold;margin:0 4px;">|</span>
  <span style="color:#ffd380;font-weight:bold;margin-right:4px;">约束:</span>
  {zone_legend}
</div>

<script src="https://unpkg.com/maplibre-gl@4.1.0/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/deck.gl@9.3.7/dist.min.js"></script>
<script>
var DATA = {data_json};
var CENTER = [{center_lng}, {center_lat}];

var GAODE_STYLE = {{
  version: 8,
  sources: {{
    'gaode': {{
      type: 'raster',
      tiles: [
        'https://webrd01.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=7&x={{x}}&y={{y}}&z={{z}}',
        'https://webrd02.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=7&x={{x}}&y={{y}}&z={{z}}',
        'https://webrd03.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=7&x={{x}}&y={{y}}&z={{z}}',
        'https://webrd04.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=7&x={{x}}&y={{y}}&z={{z}}'
      ],
      tileSize: 256,
      attribution: '高德地图'
    }}
  }},
  layers: [{{
    id: 'gaode-layer',
    type: 'raster',
    source: 'gaode',
    minzoom: 0,
    maxzoom: 18
  }}]
}};



var allLayers = [];
var layerVisibility = {{}};

// 1. 现状地块 (PolygonLayer, flat, z=0) — default ON
var parcelLayer = new deck.PolygonLayer({{
  id: 'parcels',
  data: DATA.parcels,
  extruded: false,
  wireframe: false,
  filled: true,
  stroked: true,
  getPolygon: function(d) {{ return d.contour; }},
  getFillColor: function(d) {{ return d.color; }},
  getLineColor: [255, 255, 255, 80],
  getLineWidth: 1,
  lineWidthMinPixels: 0.5,
  pickable: true,
  autoHighlight: true,
  highlightColor: [255, 255, 255, 100],
  material: {{ambient: 1, diffuse: 0, shininess: 0}},
  onClick: function(info) {{}},
  visible: true,
}});
allLayers.push(parcelLayer);
layerVisibility.parcels = true;

// 2a. 农田保护 (PolygonLayer, flat, dashed) — default OFF (88 polygons would obscure parcels)
var farmlandLayer = new deck.PolygonLayer({{
  id: 'zones_farmland',
  data: DATA.zones.filter(function(d) {{ return d.gtype === 'farmland_protection'; }}),
  extruded: false,
  wireframe: false,
  filled: true,
  stroked: true,
  getPolygon: function(d) {{ return d.contour; }},
  getFillColor: function(d) {{ var c = d.color; return [c[0], c[1], c[2], 180]; }},
  getLineColor: function(d) {{ return d.color; }},
  getLineWidth: 2,
  lineWidthMinPixels: 1,
  getLineDashArray: [4, 3],
  dashJustified: true,
  pickable: false,
  autoHighlight: false,
  material: {{ambient: 1, diffuse: 0, shininess: 0}},
  visible: false,
}});
allLayers.push(farmlandLayer);
layerVisibility.zones_farmland = false;

// 2b. 生态红线 (PolygonLayer, flat, dashed) — default ON
var ecologicalLayer = new deck.PolygonLayer({{
  id: 'zones_ecological',
  data: DATA.zones.filter(function(d) {{ return d.gtype === 'ecological_protection'; }}),
  extruded: false,
  wireframe: false,
  filled: true,
  stroked: true,
  getPolygon: function(d) {{ return d.contour; }},
  getFillColor: function(d) {{ var c = d.color; return [c[0], c[1], c[2], 180]; }},
  getLineColor: function(d) {{ return d.color; }},
  getLineWidth: 2,
  lineWidthMinPixels: 1,
  getLineDashArray: [4, 3],
  dashJustified: true,
  pickable: false,
  autoHighlight: false,
  material: {{ambient: 1, diffuse: 0, shininess: 0}},
  visible: true,
}});
allLayers.push(ecologicalLayer);
layerVisibility.zones_ecological = true;

// 2c. 历史保护 (PolygonLayer, flat, dashed) — default ON
var historicalLayer = new deck.PolygonLayer({{
  id: 'zones_historical',
  data: DATA.zones.filter(function(d) {{ return d.gtype === 'historical_protection'; }}),
  extruded: false,
  wireframe: false,
  filled: true,
  stroked: true,
  getPolygon: function(d) {{ return d.contour; }},
  getFillColor: function(d) {{ var c = d.color; return [c[0], c[1], c[2], 180]; }},
  getLineColor: function(d) {{ return d.color; }},
  getLineWidth: 2,
  lineWidthMinPixels: 1,
  getLineDashArray: [4, 3],
  dashJustified: true,
  pickable: false,
  autoHighlight: false,
  material: {{ambient: 1, diffuse: 0, shininess: 0}},
  visible: true,
}});
allLayers.push(historicalLayer);
layerVisibility.zones_historical = true;

// 3. 道路 (PathLayer) — default ON
var roadLayer = new deck.PathLayer({{
  id: 'roads',
  data: DATA.roads,
  getPath: function(d) {{ return d.path; }},
  getColor: function(d) {{ return d.color; }},
  getWidth: 3,
  widthMinPixels: 1.5,
  widthMaxPixels: 8,
  pickable: true,
  autoHighlight: true,
  highlightColor: [255, 255, 255, 150],
  visible: true,
}});
allLayers.push(roadLayer);
layerVisibility.roads = true;

// 4. 规划地块 (PolygonLayer, extruded 50m, alpha 120) — default OFF
var plannedParcelLayer = new deck.PolygonLayer({{
  id: 'planned_parcels',
  data: DATA.planned_parcels,
  extruded: true,
  wireframe: false,
  elevationScale: 1,
  getElevation: 50,
  filled: true,
  stroked: true,
  getPolygon: function(d) {{ return d.contour; }},
  getFillColor: function(d) {{ var c = d.color; return [c[0], c[1], c[2], 120]; }},
  getLineColor: [255, 255, 255, 120],
  getLineWidth: 1,
  lineWidthMinPixels: 0.5,
  getLineDashArray: [6, 4],
  dashJustified: true,
  pickable: true,
  autoHighlight: true,
  highlightColor: [255, 255, 255, 100],
  material: {{ambient: 0.6, diffuse: 0.4, shininess: 0}},
  visible: false,
}});
allLayers.push(plannedParcelLayer);
layerVisibility.planned_parcels = false;

// 5. 规划分区 (PolygonLayer, extruded 100m, alpha 120) — default OFF
var zoneLayer = new deck.PolygonLayer({{
  id: 'planned_zones',
  data: DATA.planned_zones,
  extruded: true,
  wireframe: false,
  elevationScale: 1,
  getElevation: 100,
  filled: true,
  stroked: true,
  getPolygon: function(d) {{ return d.contour; }},
  getFillColor: function(d) {{ var c = d.color; return [c[0], c[1], c[2], 120]; }},
  getLineColor: [200, 200, 200, 80],
  getLineWidth: 1,
  lineWidthMinPixels: 0.5,
  pickable: true,
  autoHighlight: true,
  highlightColor: [255, 255, 255, 100],
  material: {{ambient: 0.6, diffuse: 0.4, shininess: 0}},
  visible: false,
}});
allLayers.push(zoneLayer);
layerVisibility.planned_zones = false;

// 6. 设施点 (ScatterplotLayer) — default OFF
var facilityLayer = new deck.ScatterplotLayer({{
  id: 'facilities',
  data: DATA.facilities,
  getPosition: function(d) {{ return d.position; }},
  getRadius: function(d) {{ return d.radius; }},
  getFillColor: function(d) {{ return d.color; }},
  radiusMinPixels: 3,
  radiusMaxPixels: 20,
  pickable: true,
  autoHighlight: true,
  highlightColor: [255, 255, 255, 200],
  visible: false,
}});
allLayers.push(facilityLayer);
layerVisibility.facilities = false;

// 7. 居民点 (ColumnLayer) — default OFF
var clusterLayer = new deck.ColumnLayer({{
  id: 'clusters',
  data: DATA.clusters,
  getPosition: function(d) {{ return d.position; }},
  getElevation: function(d) {{ return d.height; }},
  getFillColor: function(d) {{ return d.color; }},
  getLineColor: [233, 30, 99, 255],
  getLineWidth: 1,
  radius: 30,
  elevationScale: 1,
  pickable: true,
  autoHighlight: true,
  highlightColor: [255, 255, 255, 200],
  visible: false,
}});
allLayers.push(clusterLayer);
layerVisibility.clusters = false;

// 8a. 相邻 (LineLayer, z=200) — default OFF
var relSfTouchesLayer = new deck.LineLayer({{
  id: 'rel_sfTouches',
  data: DATA.l2_relations.filter(function(d) {{ return d.type === 'sfTouches'; }}),
  getSourcePosition: function(d) {{ return d.source; }},
  getTargetPosition: function(d) {{ return d.target; }},
  getColor: [46, 204, 113, 180],
  getWidth: 1.5,
  widthMinPixels: 0.5,
  widthMaxPixels: 3,
  pickable: false,
  visible: false,
}});
allLayers.push(relSfTouchesLayer);
layerVisibility.rel_sfTouches = false;

// 8b. 道路连接 (LineLayer, z=200) — default OFF
var relConnectedRoadLayer = new deck.LineLayer({{
  id: 'rel_connected_via_road',
  data: DATA.l2_relations.filter(function(d) {{ return d.type === 'connected_via_road'; }}),
  getSourcePosition: function(d) {{ return d.source; }},
  getTargetPosition: function(d) {{ return d.target; }},
  getColor: [52, 152, 219, 180],
  getWidth: 1.5,
  widthMinPixels: 0.5,
  widthMaxPixels: 3,
  pickable: false,
  visible: false,
}});
allLayers.push(relConnectedRoadLayer);
layerVisibility.rel_connected_via_road = false;

// 8c. 邻近 (LineLayer, z=200) — default OFF
var relNearbyLayer = new deck.LineLayer({{
  id: 'rel_nearby',
  data: DATA.l2_relations.filter(function(d) {{ return d.type === 'nearby'; }}),
  getSourcePosition: function(d) {{ return d.source; }},
  getTargetPosition: function(d) {{ return d.target; }},
  getColor: [155, 89, 182, 120],
  getWidth: 0.8,
  widthMinPixels: 0.5,
  widthMaxPixels: 3,
  pickable: false,
  visible: false,
}});
allLayers.push(relNearbyLayer);
layerVisibility.rel_nearby = false;

// 8d. 包含 (LineLayer, z=200) — default OFF
var relSfWithinLayer = new deck.LineLayer({{
  id: 'rel_sfWithin',
  data: DATA.l2_relations.filter(function(d) {{ return d.type === 'sfWithin'; }}),
  getSourcePosition: function(d) {{ return d.source; }},
  getTargetPosition: function(d) {{ return d.target; }},
  getColor: [231, 76, 60, 150],
  getWidth: 1.5,
  widthMinPixels: 0.5,
  widthMaxPixels: 3,
  pickable: false,
  visible: false,
}});
allLayers.push(relSfWithinLayer);
layerVisibility.rel_sfWithin = false;

// 8e. 相交 (LineLayer, z=200) — default OFF
var relSfIntersectsLayer = new deck.LineLayer({{
  id: 'rel_sfIntersects',
  data: DATA.l2_relations.filter(function(d) {{ return d.type === 'sfIntersects'; }}),
  getSourcePosition: function(d) {{ return d.source; }},
  getTargetPosition: function(d) {{ return d.target; }},
  getColor: [241, 196, 15, 150],
  getWidth: 1.5,
  widthMinPixels: 0.5,
  widthMaxPixels: 3,
  pickable: false,
  visible: false,
}});
allLayers.push(relSfIntersectsLayer);
layerVisibility.rel_sfIntersects = false;

// 9. 村界 (PolygonLayer, white outline, no fill) — default OFF
var boundaryLayer = new deck.PolygonLayer({{
  id: 'boundary',
  data: DATA.boundary,
  extruded: false,
  wireframe: false,
  filled: false,
  stroked: true,
  getPolygon: function(d) {{ return d.contour; }},
  getLineColor: [255, 255, 255, 255],
  getLineWidth: 3,
  lineWidthMinPixels: 2,
  pickable: false,
  material: {{ambient: 1, diffuse: 0, shininess: 0}},
  visible: false,
}});
allLayers.push(boundaryLayer);
layerVisibility.boundary = false;

// Lighting
var ambientLight = new deck.AmbientLight({{
  color: [255, 255, 255],
  intensity: 0.5
}});
var directionalLight = new deck.DirectionalLight({{
  color: [255, 255, 255],
  intensity: 1.0,
  direction: [-1, -1, -1]
}});
var lightingEffect = new deck.LightingEffect({{ambientLight, directionalLight}});

// Helper: return all layers with visible prop set (never remove layers from array)
function getVisibleLayers() {{
  return allLayers.map(function(l) {{
    var vis = layerVisibility[l.id] !== undefined ? layerVisibility[l.id] : true;
    return l.clone({{ visible: vis }});
  }});
}}

// deck.gl overlay
var deckOverlay = new deck.DeckGL({{
  container: 'map',
  mapStyle: GAODE_STYLE,
  effects: [lightingEffect],
  layers: getVisibleLayers(),
  getTooltip: function(info) {{
    if (!info || !info.object) return null;
    var d = info.object;
    if (d.tooltip) {{
      return {{ html: d.tooltip, className: 'deck-tooltip' }};
    }}
    return null;
  }},
  initialViewState: {{
    longitude: CENTER[0],
    latitude: CENTER[1],
    zoom: 14,
    pitch: 45,
    bearing: 0
  }},
  controller: true,
  useDevicePixels: false
}});

// Layer toggles
document.querySelectorAll('.layer-toggle').forEach(function(el) {{
  el.addEventListener('click', function() {{
    var layerName = this.dataset.layer;

    // Special case: basemap toggle (MapLibre, not deck.gl)
    if (layerName === 'basemap') {{
      var visible = !layerVisibility['basemap'];
      layerVisibility['basemap'] = visible;
      var internalMap = deckOverlay.getMap();
      if (internalMap) {{
        internalMap.setLayoutProperty('gaode-layer', 'visibility', visible ? 'visible' : 'none');
      }}
      if (visible) {{ this.classList.add('active'); }} else {{ this.classList.remove('active'); }}
      return;
    }}

    var visible = !layerVisibility[layerName];
    layerVisibility[layerName] = visible;
    if (visible) {{
      this.classList.add('active');
    }} else {{
      this.classList.remove('active');
    }}
    deckOverlay.setProps({{
      layers: getVisibleLayers()
    }});
  }});
}});

// Sidebar entity click -> zoom to layer
document.querySelectorAll('.type-entity').forEach(function(el) {{
  el.addEventListener('click', function() {{
    var type = this.dataset.type;
    var short = type.split(':').pop();
    if (short === 'Zone') {{
      // Zone entity maps to 3 separate layers — toggle all OFF ones ON
      ['zones_farmland', 'zones_ecological', 'zones_historical'].forEach(function(zn) {{
        var tg = document.querySelector('.layer-toggle[data-layer="' + zn + '"]');
        if (tg && !layerVisibility[zn]) tg.click();
      }});
      var m = deckOverlay.getMap(); if (m) m.flyTo({{ center: CENTER, zoom: 14, pitch: 45 }});
      return;
    }}
    var layerName = null;
    if (short === 'Parcel') layerName = 'parcels';
    else if (short === 'Road') layerName = 'roads';
    else if (short === 'Facility') layerName = 'facilities';
    else if (short === 'ResidentialCluster') layerName = 'clusters';
    else if (short === 'PlannedParcel') layerName = 'planned_parcels';
    else if (short === 'PlannedZone') layerName = 'planned_zones';
    if (layerName) {{
      var toggle = document.querySelector('.layer-toggle[data-layer="' + layerName + '"]');
      if (toggle && !layerVisibility[layerName]) {{
        toggle.click();
      }}
      var m = deckOverlay.getMap(); if (m) m.flyTo({{ center: CENTER, zoom: 14, pitch: 45 }});
    }}
  }});
}});

// Resize handler
window.addEventListener('resize', function() {{
  deckOverlay.setProps({{}});
}});
</script>
</body>
</html>
"""
    path = output_dir / "kg_inspection.html"
    path.write_text(html, encoding="utf-8")
    return path


# ── Main ──

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render KG for human inspection (deck.gl 3D HTML + Turtle + stats).",
    )
    parser.add_argument("--village", default="jintian",
                        help="Village name (default: jintian).")
    parser.add_argument("--output-dir", default="output/kg_inspection",
                        help="Output directory (default: output/kg_inspection).")
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = _PROJECT_ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  KG Inspection Renderer (v3 — deck.gl 3D)")
    print("=" * 60)
    print(f"  Village:    {args.village}")
    print(f"  Output dir: {output_dir}")
    print(f"  Data dir:   {_JINTIAN_DATA}")

    print("\n[1/4] Building KG from local GeoJSON files (L1 + L4)...")
    kg, bundle = build_kg(village_name=args.village)
    print(f"  KG built: {kg.get_triple_count()} triples, {kg.get_parcel_count()} parcels")

    print("\n[2/4] Writing kg_full.ttl (Turtle dump)...")
    ttl_path = write_turtle(kg, output_dir)
    print(f"  {ttl_path.name}: {ttl_path.stat().st_size:,} bytes")

    print("\n[3/4] Writing kg_stats.json (statistics)...")
    stats = build_stats(kg, args.village)
    stats_path = write_stats(stats, output_dir)
    print(f"  {stats_path.name}: {stats_path.stat().st_size:,} bytes")
    print(f"  Triple count: {stats['triple_count']}")
    print(f"  Parcel count: {stats['parcel_count']}")
    print(f"  Entity types: {len(stats['entity_breakdown'])}")
    print(f"  Entity breakdown:")
    for short, cnt in sorted(stats["entity_breakdown"].items(), key=lambda x: -x[1]):
        print(f"    {short:35s} {cnt}")
    print(f"  Relation breakdown:")
    for short, cnt in sorted(stats["relation_breakdown"].items(), key=lambda x: -x[1]):
        if cnt:
            print(f"    {short:35s} {cnt}")

    print("\n[4/4] Writing kg_inspection.html (deck.gl 3D visualization)...")
    html_path = write_html(kg, bundle, stats, output_dir)
    print(f"  {html_path.name}: {html_path.stat().st_size:,} bytes")

    print("\n" + "=" * 60)
    print("  Done. Outputs:")
    for f in sorted(output_dir.iterdir()):
        if f.is_file():
            print(f"    {f.name:20s} {f.stat().st_size:>12,} bytes")
    print("=" * 60)
    if kg.get_parcel_count() > 660:
        print(f"\n  NOTE: {kg.get_parcel_count() - 660} additional entities found beyond parcels!")
    return 0


if __name__ == "__main__":
    sys.exit(main())