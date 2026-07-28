"""Render KG for human inspection: multi-layer map + KG browser + D3.js force graph.

Builds the KG from local jintian GeoJSON files (L1+L4), then outputs:
  - kg_inspection.html   (single-page: Leaflet map + KG browser + D3.js force graph)
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


# ── Step 4: SPARQL queries for all entity types ──

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
    """Query parcels with full semantic enrichment."""
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
    features = []
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
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "layer": "parcels",
                "bsm": bsm,
                "dlbm": dlbm,
                "dlbm_label": _dlbm_label(dlbm),
                "area_sqm": round(float(row.get("area") or 0), 1),
                "zone_type": row.get("zone", "") or _dlbm_zone_type(dlbm),
                "color": _dlbm_color(dlbm),
                "semantic_label": row.get("semLabel", "") or "",
                "taxonomic_parent": row.get("taxParent", "") or "",
                "legal_constraint": row.get("legalConstraint", "") or "",
                "primary_zone": row.get("primZone", "") or "",
                "planning_zone": row.get("planZone", "") or "",
                "decided_by": row.get("decidedBy", "") or "",
                "decision_confidence": row.get("decConf", "") or "",
                "decision_evidence": row.get("decEvid", "") or "",
            },
        })
    return features

def _query_zones(kg: PlanningKG) -> List[dict]:
    from shapely import wkt as shapely_wkt
    from shapely.geometry import mapping
    features = []
    for s in kg.g.subjects(RDF.type, EntityTypes.Zone):
        props = {"layer": "zones"}
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
        geom_wkt = None
        for g in kg.g.objects(s, GEO.hasGeometry):
            for wkt_val in kg.g.objects(g, GEO.asWKT):
                geom_wkt = str(wkt_val)
        if not geom_wkt:
            continue
        try:
            s_geom = shapely_wkt.loads(geom_wkt)
            geom = mapping(s_geom)
        except Exception:
            continue
        gtype = props.get("gtype", "")
        zt = props.get("zone_type", "")
        label = props.get("label", "") or zt
        color = ZONE_COLORS.get(gtype, DEFAULT_ZONE_COLOR)
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "layer": "zones",
                "zone_type": zt,
                "label": label,
                "gtype": gtype,
                "constraint": props.get("constraint", ""),
                "color": color,
            },
        })
    return features

def _query_roads(kg: PlanningKG) -> List[dict]:
    from rdflib import RDF as RDFLIB
    from shapely import wkt as shapely_wkt
    from shapely.geometry import mapping
    features = []
    for s in kg.g.subjects(RDF.type, EntityTypes.Road):
        name = ""
        label = ""
        for _, o in kg.g.predicate_objects(s):
            if str(kg.g.compute_qname(_)) == "pln:name":
                name = str(o)
            elif _ == PLN.has_semantic_label:
                label = str(o)
        geom_wkt = None
        for g in kg.g.objects(s, GEO.hasGeometry):
            for wkt_val in kg.g.objects(g, GEO.asWKT):
                geom_wkt = str(wkt_val)
        if not geom_wkt:
            continue
        try:
            s_geom = shapely_wkt.loads(geom_wkt)
            geom = mapping(s_geom)
        except Exception:
            continue
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "layer": "roads",
                "name": name or label or "",
                "color": "#f39c12",
            },
        })
    return features

def _query_facilities(kg: PlanningKG) -> List[dict]:
    from shapely import wkt as shapely_wkt
    from shapely.geometry import mapping
    features = []
    for s in kg.g.subjects(RDF.type, EntityTypes.Facility):
        name = ""
        ftype = ""
        for p, o in kg.g.predicate_objects(s):
            ps = _short_uri(p)
            if ps == "pln:name":
                name = str(o)
            elif ps == "pln:facility_type":
                ftype = str(o)
        geom_wkt = None
        for g in kg.g.objects(s, GEO.hasGeometry):
            for wkt_val in kg.g.objects(g, GEO.asWKT):
                geom_wkt = str(wkt_val)
        if not geom_wkt:
            continue
        try:
            s_geom = shapely_wkt.loads(geom_wkt)
            geom = mapping(s_geom)
        except Exception:
            continue
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "layer": "facilities",
                "name": name or "",
                "ftype": ftype or "",
                "color": "#e74c3c",
            },
        })
    return features

def _query_residential_clusters(kg: PlanningKG) -> List[dict]:
    from shapely import wkt as shapely_wkt
    from shapely.geometry import mapping
    features = []
    for s in kg.g.subjects(RDF.type, EntityTypes.ResidentialCluster):
        name = ""
        for p, o in kg.g.predicate_objects(s):
            ps = _short_uri(p)
            if ps in ("pln:name", "pln:has_semantic_label"):
                name = str(o)
        geom_wkt = None
        for g in kg.g.objects(s, GEO.hasGeometry):
            for wkt_val in kg.g.objects(g, GEO.asWKT):
                geom_wkt = str(wkt_val)
        if not geom_wkt:
            continue
        try:
            s_geom = shapely_wkt.loads(geom_wkt)
            geom = mapping(s_geom)
        except Exception:
            continue
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "layer": "clusters",
                "name": name or "",
                "color": "#e91e63",
                "weight": 3,
            },
        })
    return features

def _query_planned_parcels(kg: PlanningKG) -> List[dict]:
    from shapely import wkt as shapely_wkt
    from shapely.geometry import mapping
    features = []
    for s in kg.g.subjects(RDF.type, EntityTypes.PlannedParcel):
        bsm = ""
        lu = ""
        area = 0.0
        geom_wkt = ""
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
            elif ps == "pln:geometry":
                geom_wkt = str(o)
        if not geom_wkt:
            continue
        try:
            s_geom = shapely_wkt.loads(geom_wkt)
            geom = mapping(s_geom)
        except Exception:
            continue
        color = _dlbm_color(lu) if lu else "#9b59b6"
        label = _dlbm_label(lu) if lu else "规划"
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "layer": "planned_parcels",
                "bsm": bsm,
                "planning_land_use": lu,
                "label": label,
                "area_ha": round(area, 2),
                "color": color,
                "dashArray": "6,4",
            },
        })
    return features

def _query_planned_zones(kg: PlanningKG) -> List[dict]:
    from shapely import wkt as shapely_wkt
    from shapely.geometry import mapping
    features = []
    for s in kg.g.subjects(RDF.type, EntityTypes.PlannedZone):
        zt = ""
        name = ""
        area = 0.0
        geom_wkt = ""
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
            elif ps == "pln:geometry":
                geom_wkt = str(o)
        if not geom_wkt:
            continue
        try:
            s_geom = shapely_wkt.loads(geom_wkt)
            geom = mapping(s_geom)
        except Exception:
            continue
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "layer": "planned_zones",
                "zone_type": zt,
                "name": name,
                "area_ha": round(area, 2),
                "color": "#8e44ad",
                "dashArray": "4,4",
            },
        })
    return features


# ── Step 5: D3.js force graph data ──

def _build_force_graph_data(kg: PlanningKG) -> Dict[str, Any]:
    """Build node-link data for D3.js force-directed graph using direct rdflib iteration."""
    entity_counts: Counter = Counter()
    for s, _, o in kg.g.triples((None, RDF.type, None)):
        short = _short_uri(o)
        if short.startswith(("pln:", "geo:")):
            entity_counts[short] += 1

    LAYER_COLORS = {
        "pln:": "#4CAF50",
        "geo:": "#FF9800",
    }
    LAYER_NAMES = {
        "pln:AdministrativeVillage": "L1 AdministrativeVillage",
        "pln:Parcel": "L1 Parcel",
        "pln:Road": "L1 Road",
        "pln:Facility": "L1 Facility",
        "pln:WaterBody": "L1 WaterBody",
        "pln:ResidentialCluster": "L1 ResidentialCluster",
        "pln:Zone": "L1 Zone",
        "pln:ControlLine": "L1 ControlLine",
        "pln:GisLayerSet": "L1 GisLayerSet",
        "pln:PlaceRef": "L1 PlaceRef",
        "pln:RasterDataset": "L1 RasterDataset",
        "pln:PlannedParcel": "L4 PlannedParcel",
        "pln:PlannedZone": "L4 PlannedZone",
        "pln:PlannedFacility": "L4 PlannedFacility",
        "pln:PlannedRoad": "L4 PlannedRoad",
        "pln:PlannedAxis": "L4 PlannedAxis",
        "geo:Geometry": "Geometry",
    }

    nodes = []
    for short, cnt in entity_counts.most_common():
        if short == "geo:Geometry":
            continue
        prefix = short.split(":")[0] + ":"
        nodes.append({
            "id": short,
            "label": LAYER_NAMES.get(short, short),
            "count": cnt,
            "layer": "L1" if short.startswith("pln:") else "L2",
            "color": LAYER_COLORS.get(prefix, "#999"),
            "radius": max(8, min(40, cnt ** 0.5)),
        })

    # Build subject->type and object->type caches for fast lookup
    type_cache: Dict[str, str] = {}
    for s, _, o in kg.g.triples((None, RDF.type, None)):
        s_short = _short_uri(s)
        o_short = _short_uri(o)
        if o_short.startswith(("pln:", "geo:")) and o_short != "geo:Geometry":
            type_cache[s_short] = o_short

    rel_preds = {}
    for r in Relations.all():
        rs = _short_uri(r)
        rel_preds[rs] = r

    # Count cross-type relations by iterating triples
    rel_type_counts: Dict[Tuple[str, str, str], int] = {}
    for s, p, o in kg.g:
        ps = _short_uri(p)
        if ps not in rel_preds:
            continue
        ss = _short_uri(s)
        os_ = _short_uri(o)
        st = type_cache.get(ss, "")
        ot = type_cache.get(os_, "")
        if not st or not ot or st == ot:
            continue
        if st == "geo:Geometry" or ot == "geo:Geometry":
            continue
        key = (st, ot, ps)
        rel_type_counts[key] = rel_type_counts.get(key, 0) + 1

    links = []
    for (st, ot, ps), cnt in sorted(rel_type_counts.items(), key=lambda x: -x[1])[:20]:
        links.append({
            "source": st,
            "target": ot,
            "type": ps.split(":")[-1] if ":" in ps else ps,
            "count": cnt,
        })

    return {"nodes": nodes, "links": links}


# ── Step 6: HTML generation ──

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
    """Build HTML for the entity type tree sidebar."""
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

def _make_popup_html(props: Dict[str, str]) -> str:
    """Build a rich popup HTML from feature properties."""
    lines = []
    layer = props.get("layer", "")
    if layer == "parcels":
        lines.append(f'<b>BSM:</b> {props.get("bsm","?")}')
        lines.append(f'<b>DLBM:</b> {props.get("dlbm","?")} ({props.get("dlbm_label","?")})')
        lines.append(f'<b>面积:</b> {props.get("area_sqm","?")} m²')
        lines.append(f'<b>分区:</b> {props.get("zone_type","?")}')
        if props.get("semantic_label"):
            lines.append(f'<b>语义标签:</b> {props["semantic_label"]}')
        if props.get("taxonomic_parent"):
            lines.append(f'<b>分类归属:</b> {props["taxonomic_parent"]}')
        if props.get("legal_constraint"):
            lines.append(f'<b>约束:</b> {props["legal_constraint"]}')
        if props.get("primary_zone") or props.get("planning_zone"):
            lines.append(f'<b>三区:</b> {props.get("primary_zone","?")} → {props.get("planning_zone","?")}')
        if props.get("decided_by"):
            lines.append(f'<b>决策:</b> {props["decided_by"]} ({props.get("decision_confidence","?")})')
    elif layer == "zones":
        lines.append(f'<b>类型:</b> {props.get("zone_type","?")}')
        lines.append(f'<b>标签:</b> {props.get("label","?")}')
        if props.get("constraint"):
            lines.append(f'<b>约束:</b> {props["constraint"]}')
    elif layer == "roads":
        lines.append(f'<b>道路:</b> {props.get("name","?")}')
    elif layer == "facilities":
        lines.append(f'<b>设施:</b> {props.get("name","?")}')
        if props.get("ftype"):
            lines.append(f'<b>类型:</b> {props["ftype"]}')
    elif layer == "clusters":
        lines.append(f'<b>居民点:</b> {props.get("name","?")}')
    elif layer == "planned_parcels":
        lines.append(f'<b>规划地块 BSM:</b> {props.get("bsm","?")}')
        lines.append(f'<b>规划用地:</b> {props.get("planning_land_use","?")} ({props.get("label","?")})')
        lines.append(f'<b>面积:</b> {props.get("area_ha","?")} ha')
    elif layer == "planned_zones":
        lines.append(f'<b>规划分区:</b> {props.get("zone_type","?")}')
        lines.append(f'<b>名称:</b> {props.get("name","?")}')
        if props.get("area_ha"):
            lines.append(f'<b>面积:</b> {props["area_ha"]} ha')
    else:
        for k, v in props.items():
            if k not in ("layer", "color", "dashArray", "weight", "marker"):
                lines.append(f'<b>{k}:</b> {v}')
    return "<br>".join(lines)


def write_html(kg: PlanningKG, bundle: VillageBundle, stats: Dict[str, Any], output_dir: Path) -> Path:
    """Write self-contained kg_inspection.html (Leaflet + D3.js + KG browser)."""

    # Collect all layer features
    parcel_features = _query_parcels(kg, bundle)
    zone_features = _query_zones(kg)
    road_features = _query_roads(kg)
    facility_features = _query_facilities(kg)
    cluster_features = _query_residential_clusters(kg)
    planned_parcel_features = _query_planned_parcels(kg)
    planned_zone_features = _query_planned_zones(kg)

    force_data = _build_force_graph_data(kg)
    entity_tree_html = _make_entity_tree_html(stats)
    relation_list_html = _make_relation_list_html(stats)
    dlbm_legend = _make_dlbm_legend_html()
    zone_legend = _make_zone_legend_html()

    data_json = json.dumps({
        "parcels": {"type": "FeatureCollection", "features": parcel_features},
        "zones": {"type": "FeatureCollection", "features": zone_features},
        "roads": {"type": "FeatureCollection", "features": road_features},
        "facilities": {"type": "FeatureCollection", "features": facility_features},
        "clusters": {"type": "FeatureCollection", "features": cluster_features},
        "planned_parcels": {"type": "FeatureCollection", "features": planned_parcel_features},
        "planned_zones": {"type": "FeatureCollection", "features": planned_zone_features},
    }, ensure_ascii=False)
    force_json = json.dumps(force_data, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KG Inspection - 金田村 ({stats['triple_count']} triples)</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:"Microsoft YaHei",sans-serif; background:#1a1a2e; color:#eee; overflow:hidden; height:100vh; }}
#topbar {{ padding:6px 16px; background:#16213e; display:flex; flex-wrap:wrap; gap:12px; align-items:center; font-size:13px; }}
#topbar .stat {{ color:#ffd380; font-weight:bold; }}
#topbar .layer-toggle {{ cursor:pointer; padding:2px 8px; border-radius:4px; font-size:12px; }}
#topbar .layer-toggle.active {{ background:#0f3460; }}
#main {{ display:flex; height:calc(100vh - 36px); }}
#sidebar {{ width:200px; min-width:200px; background:#0f3460; overflow-y:auto; padding:8px; font-size:12px; }}
#sidebar .section-title {{ color:#ffd380; font-weight:bold; margin:8px 0 4px; font-size:13px; }}
#sidebar .layer-group {{ margin:6px 0 2px; color:#4ea8de; font-size:12px; }}
#sidebar .type-entity,.sidebar .rel-item {{ cursor:pointer; padding:2px 6px; border-radius:3px; }}
#sidebar .type-entity:hover,.sidebar .rel-item:hover {{ background:#1a1a4e; }}
#sidebar .cnt {{ color:#888; float:right; }}
#map {{ flex:1; min-width:0; }}
#force-panel {{ width:280px; min-width:280px; background:#16213e; overflow:hidden; display:flex; flex-direction:column; }}
#force-panel .title {{ padding:4px 8px; background:#0f3460; font-size:12px; color:#ffd380; text-align:center; }}
#force-graph {{ flex:1; }}
#legend {{ background:#0f3460; padding:3px 12px; display:flex; flex-wrap:wrap; gap:6px; font-size:11px; overflow-x:auto; }}
#legend .lg {{ display:inline-flex; align-items:center; gap:3px; white-space:nowrap; }}
#legend .lg i {{ width:12px; height:12px; border-radius:2px; display:inline-block; border:1px solid rgba(255,255,255,0.3); }}
.leaflet-popup-content {{ font-size:12px; line-height:1.5; max-height:300px; overflow-y:auto; }}
.leaflet-container {{ background:#1a1a2e; }}
</style>
</head>
<body>
<div id="topbar">
  <b style="color:#ffd380;font-size:14px;">KG 金田村</b>
  <div>三元组: <span class="stat">{stats['triple_count']}</span></div>
  <div>实体类型: <span class="stat">{len(stats['entity_breakdown'])}</span></div>
  <div>地块: <span class="stat">{stats['parcel_count']}</span></div>
  <span class="layer-toggle active" data-layer="parcels">地块</span>
  <span class="layer-toggle active" data-layer="zones">约束</span>
  <span class="layer-toggle active" data-layer="roads">道路</span>
  <span class="layer-toggle active" data-layer="facilities">设施</span>
  <span class="layer-toggle active" data-layer="clusters">居民点</span>
  <span class="layer-toggle active" data-layer="planned_parcels">规划地块</span>
  <span class="layer-toggle active" data-layer="planned_zones">规划分区</span>
</div>
<div id="main">
  <div id="sidebar">
    <div class="section-title">实体浏览器</div>
    {entity_tree_html}
    <hr style="border-color:#333;margin:8px 0;">
    {relation_list_html}
  </div>
  <div id="map"></div>
  <div id="force-panel">
    <div class="title">KG 关系图 (D3.js 力导向)</div>
    <div id="force-graph"></div>
  </div>
</div>
<div id="legend">
  <span style="color:#ffd380;font-weight:bold;margin-right:4px;">DLBM:</span>
  {dlbm_legend}
  <span style="color:#ffd380;font-weight:bold;margin:0 4px;">|</span>
  <span style="color:#ffd380;font-weight:bold;margin-right:4px;">约束:</span>
  {zone_legend}
</div>

<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
var DATA = {data_json};
var FORCE = {force_json};
var LAYER_GROUPS = {{}};
var map = L.map('map', {{ preferCanvas: true, zoomControl: true }}).setView([24.819, 116.0415], 14);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  maxZoom: 19, opacity: 0.12, attribution: '&copy; OSM'
}}).addTo(map);

// Parcels
LAYER_GROUPS.parcels = L.geoJSON(DATA.parcels, {{
  style: function(f) {{
    return {{ color: '#fff', weight: 0.5, fillColor: f.properties.color || '#ccc', fillOpacity: 0.6 }};
  }},
  onEachFeature: function(f, layer) {{
    layer.bindPopup(`<div>${{makePopup(f.properties)}}</div>`);
  }}
}}).addTo(map);

// Zones (constraint polygons)
LAYER_GROUPS.zones = L.geoJSON(DATA.zones, {{
  style: function(f) {{
    return {{ color: f.properties.color || '#95a5a6', weight: 1.5, fillColor: f.properties.color || '#95a5a6', fillOpacity: 0.2, dashArray: '4,3' }};
  }},
  onEachFeature: function(f, layer) {{
    layer.bindPopup(`<div>${{makePopup(f.properties)}}</div>`);
  }}
}}).addTo(map);

// Roads
LAYER_GROUPS.roads = L.geoJSON(DATA.roads, {{
  style: function(f) {{
    return {{ color: '#f39c12', weight: 2, opacity: 0.7 }};
  }},
  onEachFeature: function(f, layer) {{
    layer.bindPopup(`<div>${{makePopup(f.properties)}}</div>`);
  }}
}}).addTo(map);

// Facilities
LAYER_GROUPS.facilities = L.geoJSON(DATA.facilities, {{
  pointToLayer: function(f, latlng) {{
    return L.circleMarker(latlng, {{ radius: 6, color: '#e74c3c', fillColor: '#e74c3c', fillOpacity: 0.8, weight: 1 }});
  }},
  onEachFeature: function(f, layer) {{
    layer.bindPopup(`<div>${{makePopup(f.properties)}}</div>`);
  }}
}}).addTo(map);

// Residential clusters
LAYER_GROUPS.clusters = L.geoJSON(DATA.clusters, {{
  style: function(f) {{
    return {{ color: '#e91e63', weight: 3, fill: false, dashArray: '8,4' }};
  }},
  onEachFeature: function(f, layer) {{
    layer.bindPopup(`<div>${{makePopup(f.properties)}}</div>`);
  }}
}}).addTo(map);

// Planned parcels
LAYER_GROUPS.planned_parcels = L.geoJSON(DATA.planned_parcels, {{
  style: function(f) {{
    return {{ color: '#fff', weight: 0.5, fillColor: f.properties.color || '#9b59b6', fillOpacity: 0.5, dashArray: f.properties.dashArray || '6,4' }};
  }},
  onEachFeature: function(f, layer) {{
    layer.bindPopup(`<div>${{makePopup(f.properties)}}</div>`);
  }}
}}).addTo(map);

// Planned zones
LAYER_GROUPS.planned_zones = L.geoJSON(DATA.planned_zones, {{
  style: function(f) {{
    return {{ color: '#8e44ad', weight: 2, fillColor: '#8e44ad', fillOpacity: 0.15, dashArray: '4,4' }};
  }},
  onEachFeature: function(f, layer) {{
    layer.bindPopup(`<div>${{makePopup(f.properties)}}</div>`);
  }}
}}).addTo(map);

function makePopup(p) {{
  var lines = [];
  var layer = p.layer || '';
  if (layer === 'parcels') {{
    lines.push('<b>BSM:</b> ' + (p.bsm||'?'));
    lines.push('<b>DLBM:</b> ' + (p.dlbm||'?') + ' (' + (p.dlbm_label||'?') + ')');
    lines.push('<b>面积:</b> ' + (p.area_sqm||'?') + ' m²');
    lines.push('<b>分区:</b> ' + (p.zone_type||'?'));
    if (p.semantic_label) lines.push('<b>语义标签:</b> ' + p.semantic_label);
    if (p.taxonomic_parent) lines.push('<b>分类归属:</b> ' + p.taxonomic_parent);
    if (p.legal_constraint) lines.push('<b>约束:</b> ' + p.legal_constraint);
    if (p.primary_zone || p.planning_zone) lines.push('<b>三区:</b> ' + (p.primary_zone||'?') + ' → ' + (p.planning_zone||'?'));
    if (p.decided_by) lines.push('<b>决策:</b> ' + p.decided_by + ' (' + (p.decision_confidence||'?') + ')');
  }} else if (layer === 'zones') {{
    lines.push('<b>类型:</b> ' + (p.zone_type||'?'));
    lines.push('<b>标签:</b> ' + (p.label||'?'));
    if (p.constraint) lines.push('<b>约束:</b> ' + p.constraint);
  }} else if (layer === 'roads') {{
    lines.push('<b>道路:</b> ' + (p.name||'?'));
  }} else if (layer === 'facilities') {{
    lines.push('<b>设施:</b> ' + (p.name||'?'));
    if (p.ftype) lines.push('<b>类型:</b> ' + p.ftype);
  }} else if (layer === 'clusters') {{
    lines.push('<b>居民点:</b> ' + (p.name||'?'));
  }} else if (layer === 'planned_parcels') {{
    lines.push('<b>规划地块 BSM:</b> ' + (p.bsm||'?'));
    lines.push('<b>规划用地:</b> ' + (p.planning_land_use||'?') + ' (' + (p.label||'?') + ')');
    if (p.area_ha) lines.push('<b>面积:</b> ' + p.area_ha + ' ha');
  }} else if (layer === 'planned_zones') {{
    lines.push('<b>规划分区:</b> ' + (p.zone_type||'?'));
    lines.push('<b>名称:</b> ' + (p.name||'?'));
    if (p.area_ha) lines.push('<b>面积:</b> ' + p.area_ha + ' ha');
  }}
  return lines.join('<br>');
}}

// Fit bounds
try {{
  var allBounds = L.latLngBounds([]);
  Object.values(LAYER_GROUPS).forEach(function(g) {{
    try {{ var b = g.getBounds(); if (b.isValid()) allBounds.extend(b); }} catch(e) {{}}
  }});
  if (allBounds.isValid()) map.fitBounds(allBounds, {{ padding: [30, 30] }});
}} catch(e) {{}}

// Layer toggles
document.querySelectorAll('.layer-toggle').forEach(function(el) {{
  el.addEventListener('click', function() {{
    var layer = this.dataset.layer;
    var g = LAYER_GROUPS[layer];
    if (!g) return;
    if (map.hasLayer(g)) {{
      map.removeLayer(g);
      this.classList.remove('active');
    }} else {{
      g.addTo(map);
      this.classList.add('active');
    }}
  }});
}});

// Sidebar entity click -> zoom to type
document.querySelectorAll('.type-entity').forEach(function(el) {{
  el.addEventListener('click', function() {{
    var type = this.dataset.type;
    // Find features of this type in the map
    var short = type.split(':').pop();
    var layerName = null;
    if (short === 'Parcel') layerName = 'parcels';
    else if (short === 'Zone') layerName = 'zones';
    else if (short === 'Road') layerName = 'roads';
    else if (short === 'Facility') layerName = 'facilities';
    else if (short === 'ResidentialCluster') layerName = 'clusters';
    else if (short === 'PlannedParcel') layerName = 'planned_parcels';
    else if (short === 'PlannedZone') layerName = 'planned_zones';
    if (layerName && LAYER_GROUPS[layerName]) {{
      try {{
        var b = LAYER_GROUPS[layerName].getBounds();
        if (b.isValid()) map.fitBounds(b, {{ padding: [30, 30] }});
      }} catch(e) {{}}
    }}
  }});
}});

// ── D3.js Force Graph ──
var svg = d3.select('#force-graph')
  .append('svg')
  .attr('width', '100%')
  .attr('height', '100%');

var width = 280, height = 500;
var g = svg.append('g');

var zoom = d3.zoom()
  .scaleExtent([0.1, 4])
  .on('zoom', function(event) {{ g.attr('transform', event.transform); }});
svg.call(zoom);

var nodeData = FORCE.nodes.map(function(d) {{
  return Object.assign({{}}, d, {{ radius: Math.max(6, Math.min(35, Math.sqrt(d.count) * 1.2)) }});
}});

var linkData = FORCE.links.map(function(d) {{
  return Object.assign({{}}, d);
}});

var simulation = d3.forceSimulation(nodeData)
  .force('link', d3.forceLink(linkData).id(function(d) {{ return d.id; }}).distance(80))
  .force('charge', d3.forceManyBody().strength(-200))
  .force('center', d3.forceCenter(width / 2, height / 2))
  .force('collision', d3.forceCollide().radius(function(d) {{ return d.radius + 4; }}));

var link = g.append('g')
  .selectAll('line')
  .data(linkData)
  .join('line')
  .attr('stroke', '#555')
  .attr('stroke-width', function(d) {{ return Math.max(1, Math.min(5, Math.sqrt(d.count) * 0.3)) }})
  .attr('stroke-opacity', 0.5);

var node = g.append('g')
  .selectAll('circle')
  .data(nodeData)
  .join('circle')
  .attr('r', function(d) {{ return d.radius; }})
  .attr('fill', function(d) {{ return d.color; }})
  .attr('stroke', '#fff')
  .attr('stroke-width', 1)
  .attr('opacity', 0.85)
  .call(d3.drag()
    .on('start', function(event, d) {{ if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }})
    .on('drag', function(event, d) {{ d.fx = event.x; d.fy = event.y; }})
    .on('end', function(event, d) {{ if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }})
  );

var label = g.append('g')
  .selectAll('text')
  .data(nodeData)
  .join('text')
  .text(function(d) {{ return d.label.split(' ').pop() + ' [' + d.count + ']'; }})
  .attr('font-size', 9)
  .attr('dx', function(d) {{ return d.radius + 3; }})
  .attr('dy', 3)
  .attr('fill', '#ccc');

node.append('title')
  .text(function(d) {{ return d.label + '\\n' + d.count + ' 个实体'; }});

link.append('title')
  .text(function(d) {{ return d.type + ': ' + d.count + ' 条关系'; }});

simulation.on('tick', function() {{
  link
    .attr('x1', function(d) {{ return d.source.x; }})
    .attr('y1', function(d) {{ return d.source.y; }})
    .attr('x2', function(d) {{ return d.target.x; }})
    .attr('y2', function(d) {{ return d.target.y; }});
  node
    .attr('cx', function(d) {{ return d.x; }})
    .attr('cy', function(d) {{ return d.y; }});
  label
    .attr('x', function(d) {{ return d.x; }})
    .attr('y', function(d) {{ return d.y; }});
}});

// Resize observer
var ro = new ResizeObserver(function() {{
  width = document.getElementById('force-panel').clientWidth;
  height = document.getElementById('force-panel').clientHeight - 24;
  svg.attr('width', width).attr('height', height);
  simulation.force('center', d3.forceCenter(width / 2, height / 2));
  simulation.alpha(0.3).restart();
}});
ro.observe(document.getElementById('force-panel'));
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
        description="Render KG for human inspection (HTML + Turtle + stats).",
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
    print("  KG Inspection Renderer (v2 — multi-layer + D3.js)")
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

    print("\n[4/4] Writing kg_inspection.html (multi-layer map + D3.js force graph)...")
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