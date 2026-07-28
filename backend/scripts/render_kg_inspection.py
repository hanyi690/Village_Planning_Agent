"""Render KG for human inspection in 3 formats + stats JSON.

Unified, simpler replacement for render_kg_layers.py (763 lines) and
visualize_kg_v481.py. Builds the KG from local jintian GeoJSON files
using the same direct-file approach as the golden snapshot test
(DataCatalog.load_village_bundle is currently broken for jintian due
to a Tianditu WMS source returning non-GeoJSON data).

Usage:
    python scripts/render_kg_inspection.py [--village jintian] [--output-dir output/kg_inspection]

Outputs (in --output-dir):
    - kg_full.ttl          (RDF Turtle - full triple dump for reading raw triples)
    - kg_layers.html       (Leaflet map - spatial visualization of parcels colored by DLBM)
    - kg_graph.svg         (Graphviz - entity relationship graph showing KG structure)
    - kg_stats.json        (statistics: triple count, entity breakdown, parcel count)

Run from the backend/ directory:
    cd backend
    python scripts/render_kg_inspection.py --output-dir output/kg_inspection
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Path bootstrap (script lives in backend/scripts/) ──────────────
# scripts/render_kg_inspection.py -> parents[1] = backend/
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Project root must be cwd for relative data paths (data/gis/jintian/...).
# The golden snapshot test does os.chdir(_PROJECT_ROOT) for the same reason.
_PROJECT_ROOT = _BACKEND_DIR.parent
os.chdir(_PROJECT_ROOT)

from rdflib import RDF, Literal, Namespace, URIRef

from app.modules.data.ingest import ingest_current_landuse, ingest_feature
from app.modules.kg.builder import PlanningKG
from app.modules.kg.ontology import EntityTypes, Relations, GEO, PLN
from app.modules.schema.types.canonical import VillageBundle
from app.modules.spatial_ops import build_constraint_index
from app.modules.spatial_ops.geometry import compute_parcel_relations

# ── Constants ──────────────────────────────────────────────────────

PLN_NS = "http://village-planning.org/ontology#"
GEO_NS = "http://www.opengis.net/ont/geosparql#"

_JINTIAN_DATA = _PROJECT_ROOT / "data" / "gis" / "jintian"

# DLBM code prefix -> (color, Chinese label) for the Leaflet legend.
# Based on the appendix5 village planning land use classification.
# 01xx = 耕地, 02xx = 园地, 03xx = 林地, 04xx = 草地,
# 11xx = 水域, 12xx = 自然保留地,
# 21xx = 村庄建设用地, 22xx = 区域基础设施.
DLBM_CATEGORY_COLORS: Dict[str, Tuple[str, str]] = {
    "01": ("#95d5b2", "耕地"),     # agriculture - light green
    "02": ("#b7e4c7", "园地"),     # orchard - pale green
    "03": ("#2d6a4f", "林地"),     # forest - dark green
    "04": ("#d8f3dc", "草地"),     # grass - mint
    "11": ("#4ea8de", "水域"),     # water - blue
    "12": ("#ced4da", "自然保留地"),  # natural reserve - light gray
    "21": ("#ffd166", "村庄建设用地"),  # village construction - yellow
    "22": ("#6c757d", "区域基础设施"),  # regional infrastructure - gray
}
DEFAULT_DLBM_COLOR = "#e9ecef"
DEFAULT_DLBM_LABEL = "其他"


def _dlbm_color_and_label(dlbm: str) -> Tuple[str, str]:
    """Resolve (color, label) from a DLBM code by 2-char prefix."""
    if dlbm and len(dlbm) >= 2:
        prefix = dlbm[:2]
        if prefix in DLBM_CATEGORY_COLORS:
            return DLBM_CATEGORY_COLORS[prefix]
    return DEFAULT_DLBM_COLOR, DEFAULT_DLBM_LABEL


# ── Step 1: Build KG from local files (mirrors golden snapshot test) ──

def build_kg(village_name: str = "jintian") -> Tuple[PlanningKG, VillageBundle]:
    """Build KG from checked-in jintian GeoJSON files.

    Mirrors the golden_kg fixture in tests/integration/test_golden_kg_snapshot.py.
    Uses direct ingest_* calls instead of DataCatalog because the catalog's
    urban_dev_boundary WMS source is currently broken (returns non-GeoJSON).
    L1+L2 only (no L3 intent, no L4 planned state) - matches the golden baseline.
    """
    bundle = VillageBundle(village_name=village_name)

    # Layer 1: current landuse parcels
    parcels, _ = ingest_current_landuse(str(_JINTIAN_DATA / "current" / "landuse.geojson"))
    for p in parcels:
        bundle.add(p)

    # Layer 1: current roads
    roads, _ = ingest_feature(
        str(_JINTIAN_DATA / "current" / "road.geojson"), "current_road"
    )
    for r in roads:
        bundle.add(r)

    # Layer 1: current annotations (facility candidates)
    anns, _ = ingest_feature(
        str(_JINTIAN_DATA / "current" / "annotation.geojson"), "current_annotation"
    )
    for a in anns:
        bundle.add(a)

    # Constraint reference polygons (planned/ folder)
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
        raise RuntimeError("No parcels loaded from jintian GeoJSON - data missing?")

    # Spatial relations + constraint index (same as golden fixture)
    parcel_relations = compute_parcel_relations(
        bundle.polygons.get("landuse_current"),
        roads=bundle.lines.get("roads_current"),
    )
    constraint_index = build_constraint_index(bundle)

    kg = PlanningKG(village_name=village_name)
    kg.build_from_bundle(
        bundle=bundle,
        parcel_relations=parcel_relations,
        constraint_index=constraint_index,
    )
    return kg, bundle


# ── Step 2: Stats JSON ─────────────────────────────────────────────

def _short_uri(uri: Any) -> str:
    s = str(uri)
    if s.startswith(PLN_NS):
        return "pln:" + s[len(PLN_NS):]
    if s.startswith(GEO_NS):
        return "geo:" + s[len(GEO_NS):]
    return s


def build_stats(kg: PlanningKG, village_name: str) -> Dict[str, Any]:
    """Compute KG statistics: triple count, entity breakdown, relation breakdown."""
    # Entity breakdown: count subjects by rdf:type
    entity_counts: Counter = Counter()
    for s, _, o in kg.g.triples((None, RDF.type, None)):
        # Skip RDF typing of rdf:Property / owl:Class style ontology terms;
        # only count instances of our entity types (URIs under pln: or geo:).
        short = _short_uri(o)
        if short.startswith(("pln:", "geo:")):
            entity_counts[short] += 1

    # Relation breakdown: count triples by predicate (only spatial/semantic
    # relations, not rdf:type / data properties).
    relation_predicates = {
        _short_uri(r): r for r in Relations.all()
    }
    relation_counts: Counter = Counter()
    for pred_short, pred_uri in relation_predicates.items():
        relation_counts[pred_short] = len(list(kg.g.triples((None, pred_uri, None))))

    parcel_count = len(list(kg.g.subjects(RDF.type, EntityTypes.Parcel)))

    return {
        "village_name": village_name,
        "triple_count": kg.get_triple_count(),
        "parcel_count": parcel_count,
        "entity_breakdown": dict(entity_counts.most_common()),
        "relation_breakdown": dict(relation_counts.most_common()),
    }


def write_stats(stats: Dict[str, Any], output_dir: Path) -> Path:
    path = output_dir / "kg_stats.json"
    path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ── Step 3: Turtle dump ────────────────────────────────────────────

def write_turtle(kg: PlanningKG, output_dir: Path) -> Path:
    path = output_dir / "kg_full.ttl"
    turtle_str = kg.to_turtle()
    if isinstance(turtle_str, bytes):  # rdflib < 6 compat
        turtle_str = turtle_str.decode("utf-8")
    path.write_text(turtle_str, encoding="utf-8")
    return path


# ── Step 4: Leaflet HTML map ───────────────────────────────────────

def _fix_geom(geom: Optional[dict]) -> Optional[dict]:
    """Fix invalid geometry with buffer(0); return clean GeoJSON or None."""
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


def _collect_parcel_features(kg: PlanningKG, bundle: VillageBundle) -> List[dict]:
    """Build GeoJSON Feature list for parcels: geometry from bundle, DLBM from KG.

    The KG stores BSM but geometry lives in the bundle. We join them:
      1. Build (bsm, seq) -> geometry lookup from bundle.landuse_current
      2. Query KG for each parcel's BSM, seq, DLBM, area, zone_type
      3. Emit a Feature per (bsm, seq) with both geometry and KG attributes
    """
    # (bsm, seq) -> geometry, matching the render_kg_layers.py approach
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

    # Query KG for parcel attributes (BSM + seq + DLBM + area + zone_type)
    sparql = f"""
    PREFIX pln: <{PLN_NS}>
    SELECT ?bsm ?seq ?dlbm ?area ?zone WHERE {{
      ?p a pln:Parcel ;
         pln:bsm ?bsm .
      OPTIONAL {{ ?p pln:seq ?seq . }}
      OPTIONAL {{ ?p pln:dlbm ?dlbm . }}
      OPTIONAL {{ ?p pln:area_sqm ?area . }}
      OPTIONAL {{ ?p pln:current_zone_type ?zone . }}
    }}
    """
    rows = kg.query(sparql)

    features: List[dict] = []
    for row in rows:
        bsm = row.get("bsm", "")
        try:
            seq = int(row.get("seq") or 0)
        except (ValueError, TypeError):
            seq = 0
        dlbm = row.get("dlbm", "") or ""
        zone = row.get("zone", "") or ""
        try:
            area_sqm = float(row.get("area") or 0)
        except (ValueError, TypeError):
            area_sqm = 0.0

        geom = geom_lookup.get((bsm, seq))
        if not geom:
            continue
        geom = _fix_geom(geom)
        if not geom:
            continue

        color, label = _dlbm_color_and_label(dlbm)
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "bsm": bsm,
                "dlbm": dlbm,
                "dlbm_label": label,
                "area_sqm": round(area_sqm, 1),
                "zone_type": zone,
                "color": color,
            },
        })
    return features


def write_leaflet_html(kg: PlanningKG, bundle: VillageBundle, output_dir: Path) -> Path:
    """Write a self-contained Leaflet HTML map colored by DLBM category."""
    parcel_features = _collect_parcel_features(kg, bundle)
    data_json = json.dumps(
        {"type": "FeatureCollection", "features": parcel_features},
        ensure_ascii=False,
    )

    # Build legend HTML from the categories that actually appear
    used_prefixes: Counter = Counter()
    for f in parcel_features:
        dlbm = f["properties"]["dlbm"]
        prefix = dlbm[:2] if len(dlbm) >= 2 else ""
        used_prefixes[prefix] += 1
    legend_items = []
    for prefix, _count in sorted(used_prefixes.items()):
        color, label = DLBM_CATEGORY_COLORS.get(prefix, (DEFAULT_DLBM_COLOR, DEFAULT_DLBM_LABEL))
        legend_items.append(
            f'<span class="lg"><i style="background:{color}"></i>{label} ({prefix}xx)</span>'
        )
    legend_html = "".join(legend_items)

    triple_count = kg.get_triple_count()
    parcel_count = len(parcel_features)

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KG Inspection - 金田村地块图层 (DLBM 着色)</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: "Microsoft YaHei", sans-serif; background:#1a1a2e; color:#eee; }}
  #map {{ width:100vw; height:80vh; min-height:500px; }}
  #bar {{ padding:8px 16px; background:#16213e; display:flex; flex-wrap:wrap; gap:16px; align-items:center; font-size:13px; }}
  #bar .stat {{ color:#ffd380; font-weight:bold; }}
  #legend {{ background:#0f3460; padding:6px 16px; display:flex; flex-wrap:wrap; gap:10px; font-size:12px; }}
  #legend .lg {{ display:inline-flex; align-items:center; gap:4px; }}
  #legend .lg i {{ width:14px; height:14px; border-radius:3px; display:inline-block; border:1px solid rgba(255,255,255,0.3); }}
  h2 {{ font-size:15px; color:#ffd380; }}
</style>
</head>
<body>
<div id="bar">
  <h2>KG 地块图层</h2>
  <div>三元组: <span class="stat">{triple_count}</span></div>
  <div>地块: <span class="stat">{parcel_count}</span></div>
  <div>坐标系: <span class="stat">WGS-84</span></div>
</div>
<div id="legend">{legend_html}</div>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
var DATA = {data_json};
var map = L.map('map', {{ preferCanvas: true }}).setView([24.819, 116.0415], 14);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  maxZoom: 19, opacity: 0.15, attribution: '&copy; OSM'
}}).addTo(map);
var parcels = L.geoJSON(DATA, {{
  style: function(f) {{
    return {{
      color: '#fff', weight: 0.5,
      fillColor: f.properties.color || '#ccc', fillOpacity: 0.6
    }};
  }},
  onEachFeature: function(f, layer) {{
    var p = f.properties;
    layer.bindPopup(
      '<b>BSM:</b> ' + p.bsm + '<br>' +
      '<b>DLBM:</b> ' + (p.dlbm || '?') + ' (' + p.dlbm_label + ')<br>' +
      '<b>面积:</b> ' + p.area_sqm + ' m²<br>' +
      '<b>分区:</b> ' + (p.zone_type || '?')
    );
  }}
}}).addTo(map);
try {{
  var b = parcels.getBounds();
  if (b.isValid()) map.fitBounds(b, {{ padding: [30, 30] }});
}} catch(e) {{}}
</script>
</body>
</html>
"""
    path = output_dir / "kg_layers.html"
    path.write_text(html, encoding="utf-8")
    return path


# ── Step 5: Graphviz SVG (high-level structure diagram) ────────────

def write_graph_svg(kg: PlanningKG, output_dir: Path) -> Optional[Path]:
    """Render a high-level KG structure diagram (entity types + relation types).

    Returns the output Path on success, or None if the `dot` executable is
    unavailable (the graphviz Python package shells out to Graphviz's dot).
    """
    try:
        import graphviz
    except ImportError:
        print("  [skip] graphviz Python package not installed - skipping SVG")
        return None

    def _count_type(t: URIRef) -> int:
        return len(list(kg.g.triples((None, RDF.type, t))))

    dot = graphviz.Digraph("KG_Inspection", format="svg")
    dot.attr(rankdir="TB", bgcolor="white", fontname="SimHei",
             label=f"金田村 KG 结构 ({kg.get_triple_count()} triples, L1+L2)",
             labelloc="t", fontsize="18")
    dot.attr("node", fontname="SimHei", fontsize="10")
    dot.attr("edge", fontname="SimHei", fontsize="9")

    # ── L1 entity nodes (grouped in a cluster) ──
    with dot.subgraph(name="cluster_l1") as c:
        c.attr(label="Layer 1: 现状空间实体", style="rounded,filled",
               fillcolor="#E8F5E9", color="#4CAF50", fontsize="12")
        l1_nodes = []
        for name, uri in [
            ("Village", EntityTypes.Village),
            ("Parcel", EntityTypes.Parcel),
            ("Road", EntityTypes.Road),
            ("Facility", EntityTypes.Facility),
            ("WaterBody", EntityTypes.WaterBody),
            ("ResidentialCluster", EntityTypes.ResidentialCluster),
            ("Zone", EntityTypes.Zone),
            ("ControlLine", EntityTypes.ControlLine),
            ("GisLayerSet", EntityTypes.GisLayerSet),
        ]:
            cnt = _count_type(uri)
            if cnt == 0:
                continue
            node_id = "l1_" + name.lower()
            c.node(node_id, f"{name}\\n{cnt} 个", shape="box",
                   style="filled", fillcolor="#A5D6A7")
            l1_nodes.append((name, node_id))

    # ── L2 relation nodes (grouped in a cluster) ──
    with dot.subgraph(name="cluster_l2") as c:
        c.attr(label="Layer 2: 空间关系", style="rounded,filled",
               fillcolor="#FFF3E0", color="#FF9800", fontsize="12")
        rel_defs = [
            ("sfTouches", Relations.sfTouches, "拓扑邻接"),
            ("nearby", Relations.nearby, "近邻"),
            ("connected_via_road", Relations.connected_via_road, "路网连通"),
            ("sfWithin", Relations.sfWithin, "包含于"),
            ("sfIntersects", Relations.sfIntersects, "交叉"),
            ("sfContains", Relations.sfContains, "包含"),
            ("serves", Relations.serves, "服务"),
            ("derived_from", Relations.derived_from, "派生自"),
        ]
        rel_node_ids = []
        for short, uri, cn in rel_defs:
            cnt = len(list(kg.g.triples((None, uri, None))))
            if cnt == 0:
                continue
            node_id = "l2_" + short
            c.node(node_id, f"{short}\\n({cn})\\n{cnt} 条", shape="ellipse",
                   style="filled", fillcolor="#FFE0B2")
            rel_node_ids.append((short, node_id))

    # ── Cross-layer edges: parcels are the hub of most relations ──
    parcel_id = "l1_parcel"
    has_parcel = any(n == "Parcel" for n, _ in l1_nodes)
    if has_parcel:
        for short, node_id in rel_node_ids:
            if short in ("sfTouches", "nearby", "connected_via_road",
                         "sfWithin", "sfIntersects", "sfContains"):
                dot.edge(parcel_id, node_id, label=short, style="dotted",
                         color="#FF9800", fontsize="8")
        # Village contains parcels
        if any(n == "Village" for n, _ in l1_nodes):
            dot.edge("l1_village", parcel_id, label="contains", color="#4CAF50")
        # Facility serves
        if any(n == "Facility" for n, _ in l1_nodes) and any(s == "serves" for s, _ in rel_node_ids):
            dot.edge("l1_facility", "l2_serves", label="serves", style="dotted",
                     color="#FF9800", fontsize="8")

    # Check dot availability first to avoid leaving a stray source file
    # behind when render() raises ExecutableNotFound mid-flight.
    dot_available = False
    try:
        from graphviz.backend.execute import check_executable
        check_executable("dot")
        dot_available = True
    except Exception:
        dot_available = False

    out = output_dir / "kg_graph"
    if dot_available:
        try:
            dot.render(str(out), cleanup=True)
        except Exception as e:
            print(f"  [skip] Graphviz render failed ({type(e).__name__}) - skipping SVG")
            gv_path = output_dir / "kg_graph.gv"
            gv_path.write_text(dot.source, encoding="utf-8")
            print(f"  [note] Wrote Graphviz source to {gv_path} (render with: dot -Tsvg {gv_path.name})")
            return None
        return output_dir / "kg_graph.svg"
    else:
        print("  [skip] Graphviz dot executable not on PATH - skipping SVG")
        gv_path = output_dir / "kg_graph.gv"
        gv_path.write_text(dot.source, encoding="utf-8")
        print(f"  [note] Wrote Graphviz source to {gv_path} (render with: dot -Tsvg {gv_path.name})")
        return None


# ── Main ───────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render KG for human inspection (Turtle + Leaflet HTML + Graphviz SVG + stats JSON).",
    )
    parser.add_argument("--village", default="jintian",
                        help="Village name (default: jintian). Must match data/gis/<name>.")
    parser.add_argument("--output-dir", default="output/kg_inspection",
                        help="Output directory (default: output/kg_inspection).")
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    # Resolve relative to project root (cwd was set to _PROJECT_ROOT at import).
    if not output_dir.is_absolute():
        output_dir = _PROJECT_ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  KG Inspection Renderer")
    print("=" * 60)
    print(f"  Village:    {args.village}")
    print(f"  Output dir: {output_dir}")
    print(f"  Data dir:   {_JINTIAN_DATA}")

    print("\n[1/4] Building KG from local GeoJSON files...")
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
    print(f"  Relation types: {len(stats['relation_breakdown'])}")

    print("\n[4a/4] Writing kg_layers.html (Leaflet map)...")
    html_path = write_leaflet_html(kg, bundle, output_dir)
    print(f"  {html_path.name}: {html_path.stat().st_size:,} bytes")

    print("\n[4b/4] Writing kg_graph.svg (Graphviz structure diagram)...")
    svg_path = write_graph_svg(kg, output_dir)
    if svg_path and svg_path.exists():
        print(f"  {svg_path.name}: {svg_path.stat().st_size:,} bytes")
    else:
        print("  SVG not generated (see notes above).")

    print("\n" + "=" * 60)
    print("  Done. Outputs:")
    for f in sorted(output_dir.iterdir()):
        if f.is_file():
            print(f"    {f.name:20s} {f.stat().st_size:>12,} bytes")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
