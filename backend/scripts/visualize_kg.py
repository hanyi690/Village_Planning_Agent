"""Generate KG visualization from real jintian data.

Produces:
  1. KG architecture diagram (four-layer structure with actual counts)
  2. KG sample subgraph (key entities + relations, readable)
  3. KG statistics summary (as SVG/PNG)

Usage:
  cd F:/project/Village_Planning_Agent
  export PATH="$PATH:/c/Program Files/Graphviz/bin"
  python backend/scripts/visualize_kg.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from collections import Counter, defaultdict

# Ensure backend on path
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND.parent)

OUTPUT_DIR = BACKEND.parent / "docs" / "gis" / "kg_visualization"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def build_kg():
    """Build KG from real jintian data."""
    from app.modules.data import DataCatalog
    from app.modules.spatial_ops import compute_context_blocks
    from app.modules.spatial_ops.geometry import compute_parcel_relations
    from app.modules.kg.builder import PlanningKG
    from app.modules.schema.contracts.context_contracts import (
        PlanBlock, ParcelChange, FacilityChange, RoadChange,
    )

    catalog = DataCatalog()
    bundle = catalog.load_village_bundle("jintian")
    blocks = compute_context_blocks(bundle, max_token_budget=5000)
    relations = compute_parcel_relations(
        bundle.polygons.landuse_current,
        roads=bundle.lines.roads_current,
    )

    kg = PlanningKG("jintian")
    from app.modules.spatial_ops import build_constraint_index
    constraint_index = build_constraint_index(bundle)
    kg.build_from_bundle(bundle=bundle, parcel_relations=relations,
                         constraint_index=constraint_index)

    # Apply a sample PlanBlock (on a clone, to show L4 delta)
    from rdflib import Namespace
    PLN = Namespace("http://village-planning.org/ontology#")
    sample_bsms = []
    for s, _, o in kg.g.triples((None, PLN.bsm, None)):
        if (s, None, PLN.Parcel) in kg.g:
            sample_bsms.append(str(o))
        if len(sample_bsms) >= 2:
            break

    plan = PlanBlock(version="v1",
        parcel_changes=[
            ParcelChange(bsm=sample_bsms[0] if sample_bsms else "DEMO_001",
                         action="reclassify", new_planning_land_use="2121",
                         new_area_ha=0.15,
                         derived_from_bsms=[sample_bsms[0] if sample_bsms else "DEMO_001"]),
            ParcelChange(bsm="DEMO_SPLIT_1", action="split",
                         new_planning_land_use="2121", new_area_ha=0.3,
                         derived_from_bsms=[sample_bsms[1] if len(sample_bsms) > 1 else "DEMO_002"]),
            ParcelChange(bsm="DEMO_SPLIT_2", action="split",
                         new_planning_land_use="0101", new_area_ha=0.7,
                         derived_from_bsms=[sample_bsms[1] if len(sample_bsms) > 1 else "DEMO_002"]),
        ],
        facility_changes=[
            FacilityChange(name="规划展销中心", action="new", facility_type="商业",
                           area_sqm=400, center=(113.5, 23.5)),
        ],
        road_changes=[
            RoadChange(name="规划主干道", action="new", road_level="主干道", width_m=12),
        ],
    )
    kg._apply_plan_block(plan)

    return kg, bundle, blocks, relations


def render_architecture_diagram(kg):
    """Render four-layer architecture diagram with actual counts."""
    import graphviz

    dot = graphviz.Digraph("KG_Architecture", format="svg")
    dot.attr(rankdir="TB", bgcolor="white", fontname="SimHei",
             label="Jintian KG 四层架构 (21,077 triples)", labelloc="t", fontsize="20")
    dot.attr("node", fontname="SimHei", fontsize="11")
    dot.attr("edge", fontname="SimHei", fontsize="9")

    from rdflib import RDF, Namespace
    PLN = Namespace("http://village-planning.org/ontology#")

    def count_type(t):
        return len(list(kg.g.triples((None, RDF.type, t))))

    # Layer 1
    with dot.subgraph(name="cluster_l1") as c:
        c.attr(label="Layer 1: 现状 (持久)", style="rounded,filled",
               fillcolor="#E8F5E9", color="#4CAF50", fontsize="13")
        c.node("village", f"AdministrativeVillage\n(count: {count_type(PLN.AdministrativeVillage)})",
               shape="box", style="filled", fillcolor="#C8E6C9")
        c.node("parcels", f"Parcel (地块)\n(count: {count_type(PLN.Parcel)})",
               shape="box", style="filled", fillcolor="#A5D6A7")
        c.node("roads", f"Road (道路)\n(count: {count_type(PLN.Road)})",
               shape="box", style="filled", fillcolor="#A5D6A7")
        c.node("facilities", f"Facility (设施)\n(count: {count_type(PLN.Facility)})",
               shape="box", style="filled", fillcolor="#A5D6A7")
        c.node("settlements", f"NaturalSettlement\n(count: {count_type(PLN.NaturalSettlement)})",
               shape="box", style="filled", fillcolor="#A5D6A7")
        c.node("water", f"WaterBody (水域)\n(count: {count_type(PLN.WaterBody)})",
               shape="box", style="filled", fillcolor="#A5D6A7")
        c.node("vne", f"LandUseCategory (VNE)\n(count: {count_type(PLN.LandUseCategory)})",
               shape="box", style="filled", fillcolor="#A5D6A7")

    # Layer 1 relations
    with dot.subgraph(name="cluster_l1r") as c:
        c.attr(label="L1 三层空间关系 (spatial_ops 预计算)", style="rounded,filled",
               fillcolor="#FFF3E0", color="#FF9800", fontsize="11")
        touches_count = len(list(kg.g.triples((None, PLN.touches, None))))
        nearby_count = len(list(kg.g.triples((None, PLN.nearby, None))))
        connected_count = len(list(kg.g.triples((None, PLN.connected_via_road, None))))
        c.node("l1_touches", f"pln:touches (L1 拓扑)\n{touches_count} pairs",
               shape="ellipse", style="filled", fillcolor="#FFE0B2")
        c.node("l2_nearby", f"pln:nearby (L2 近邻)\n{nearby_count} pairs",
               shape="ellipse", style="filled", fillcolor="#FFE0B2")
        c.node("l3_connected", f"pln:connected_via_road (L3 路网)\n{connected_count} pairs",
               shape="ellipse", style="filled", fillcolor="#FFE0B2")

    # Layer 2
    with dot.subgraph(name="cluster_l2") as c:
        c.attr(label="Layer 2: 约束规则 (项目级)", style="rounded,filled",
               fillcolor="#E3F2FD", color="#2196F3", fontsize="13")
        c.node("constraints", f"Constraint (约束)\n(count: {count_type(PLN.Constraint)})",
               shape="diamond", style="filled", fillcolor="#BBDEFB")
        c.node("threezone", f"ThreeZone (三区)\n(count: {count_type(PLN.ThreeZone)})",
               shape="diamond", style="filled", fillcolor="#BBDEFB")
        c.node("threeline", f"ThreeLine (三线)\n(count: {count_type(PLN.ThreeLine)})",
               shape="diamond", style="filled", fillcolor="#BBDEFB")
        c.node("zones", f"Zone (分区)\n(count: {count_type(PLN.Zone)})",
               shape="diamond", style="filled", fillcolor="#BBDEFB")

    # Layer 3
    with dot.subgraph(name="cluster_l3") as c:
        c.attr(label="Layer 3: PARSE 意图 (会话级易失)", style="rounded,filled",
               fillcolor="#F3E5F5", color="#9C27B0", fontsize="13")
        c.node("intent", "PlanIntent\n(本次未注入)", shape="box", style="filled,dashed",
               fillcolor="#E1BEE7", color="#9C27B0")

    # Layer 4
    with dot.subgraph(name="cluster_l4") as c:
        c.attr(label="Layer 4: PlanBlock 增量变更集 (版本化)", style="rounded,filled",
               fillcolor="#FFEBEE", color="#F44336", fontsize="13")
        pp_count = count_type(PLN.PlannedParcel)
        c.node("planblock", f"PlanBlock v1\n({pp_count} parcel_changes)",
               shape="box", style="filled", fillcolor="#FFCDD2")
        c.node("split", "split: DEMO_SPLIT_1/2\n(新 bsm, derived_from)",
               shape="box", style="filled", fillcolor="#FFCDD2")
        c.node("reclassify", "reclassify: sample_bsm\n(同 bsm, 改地类)",
               shape="box", style="filled", fillcolor="#FFCDD2")

    # Cross-layer edges
    dot.edge("village", "parcels", label="contains")
    dot.edge("village", "constraints", label="has_constraint")
    dot.edge("village", "planblock", label="has_plan_version", style="dashed", color="#F44336")
    dot.edge("parcels", "l1_touches", label="touches", style="dotted")
    dot.edge("parcels", "l2_nearby", label="nearby", style="dotted")
    dot.edge("parcels", "l3_connected", label="connected", style="dotted")
    dot.edge("parcels", "constraints", label="constrained_by", style="dashed")
    dot.edge("planblock", "parcels", label="derived_from\n(sparse)", style="dashed", color="#F44336")
    dot.edge("split", "parcels", label="derived_from", style="dashed", color="#F44336")

    out = OUTPUT_DIR / "kg_architecture"
    dot.render(str(out), cleanup=True)
    print(f"  Architecture diagram: {out}.svg")


def render_sample_subgraph(kg):
    """Render a readable sample subgraph: village + constraints + sample parcels + L4 delta."""
    import graphviz
    from rdflib import RDF, Namespace, Literal, URIRef
    PLN = Namespace("http://village-planning.org/ontology#")

    dot = graphviz.Digraph("KG_Sample", format="svg")
    dot.attr(rankdir="LR", bgcolor="white", fontname="SimHei",
             label="Jintian KG 样本子图 (village + constraints + parcels + L4 delta)",
             labelloc="t", fontsize="16")
    dot.attr("node", fontname="SimHei", fontsize="10")
    dot.attr("edge", fontname="SimHei", fontsize="8")

    # Village node
    dot.node("village", "pln:village\nAdministrativeVillage\nname=jintian",
             shape="box", style="filled,bold", fillcolor="#C8E6C9", width="2")

    # Constraints
    for c in kg.get_constraints():
        cid = c.get("id", "?")
        val = c.get("value", "?")
        field = c.get("field", "?")
        op = c.get("op", "?")
        dot.node(f"const_{cid}", f"pln:Constraint\n{cid}\n{field} {op} {val}",
                 shape="diamond", style="filled", fillcolor="#BBDEFB")
        dot.edge("village", f"const_{cid}", label="has_constraint")

    # ThreeLine entities
    tl_query = kg.query(
        "PREFIX pln: <http://village-planning.org/ontology#> "
        "SELECT ?l ?name ?code WHERE { ?l a pln:ThreeLine ; pln:name ?name ; pln:code ?code . }")
    for tl in tl_query[:4]:
        name = tl.get("name", "?")
        code = tl.get("code", "?")
        node_id = f"tl_{code}"
        dot.node(node_id, f"pln:ThreeLine\n{name}\n(code={code})",
                 shape="diamond", style="filled", fillcolor="#BBDEFB")
        dot.edge("village", node_id, label="has_zone")

    # Sample parcels (5 real ones)
    parcels = kg.query(
        "PREFIX pln: <http://village-planning.org/ontology#> "
        "SELECT ?p ?bsm ?dlbm ?area ?zt WHERE { "
        "?p a pln:Parcel ; pln:bsm ?bsm ; pln:dlbm ?dlbm ; "
        "pln:area_ha ?area ; pln:zone_type ?zt . } LIMIT 5")
    for i, p in enumerate(parcels):
        pid = f"parcel_{i}"
        bsm = p["bsm"][:12] + "..."
        dlbm = p["dlbm"]
        area = float(p["area"])
        zt = p["zt"]
        dot.node(pid, f"pln:Parcel\nBSM={bsm}\nDLBM={dlbm}\narea={area:.3f}ha\nzone={zt}",
                 shape="box", style="filled", fillcolor="#A5D6A7")
        dot.edge("village", pid, label="contains")

    # Show touches between sample parcels (if any)
    sample_uris = [p["p"] for p in parcels]
    for i, uri_a in enumerate(sample_uris):
        for j, uri_b in enumerate(sample_uris):
            if i < j:
                if (URIRef(uri_a), PLN.touches, URIRef(uri_b)) in kg.g:
                    dot.edge(f"parcel_{i}", f"parcel_{j}", label="touches", color="#FF9800", style="dashed")
                if (URIRef(uri_a), PLN.nearby, URIRef(uri_b)) in kg.g:
                    dot.edge(f"parcel_{i}", f"parcel_{j}", label="nearby", color="#2196F3", style="dotted")

    # L4 PlanBlock delta
    pp = kg.query(
        "PREFIX pln: <http://village-planning.org/ontology#> "
        "SELECT ?p ?bsm ?action ?lu WHERE { "
        '?p a pln:PlannedParcel ; pln:bsm ?bsm ; pln:change_action ?action ; '
        'pln:in_version "v1" . OPTIONAL { ?p pln:planning_land_use ?lu . } }')
    for i, p in enumerate(pp):
        pid = f"planned_{i}"
        bsm = p["bsm"][:15] + "..." if len(p["bsm"]) > 15 else p["bsm"]
        action = p["action"]
        lu = p.get("lu", "")
        dot.node(pid, f"pln:PlannedParcel\nBSM={bsm}\naction={action}\nlu={lu}",
                 shape="box", style="filled", fillcolor="#FFCDD2", color="#F44336")
        dot.edge("village", pid, label="has_plan_v1", style="dashed", color="#F44336")
        # Check derived_from
        p_uri = URIRef(p["p"])
        for _, _, parent in kg.g.triples((p_uri, PLN.derived_from, None)):
            for parent_idx, sp in enumerate(parcels):
                if sp["p"] == str(parent):
                    dot.edge(pid, f"parcel_{parent_idx}", label="derived_from",
                             color="#F44336", style="dashed")

    # Legend
    with dot.subgraph(name="cluster_legend") as c:
        c.attr(label="图例", style="rounded,filled", fillcolor="#FAFAFA",
               color="#9E9E9E", fontsize="11")
        c.node("leg_l1", "Layer 1 (现状)", shape="box", style="filled", fillcolor="#A5D6A7", fontsize="9")
        c.node("leg_l2", "Layer 2 (约束)", shape="diamond", style="filled", fillcolor="#BBDEFB", fontsize="9")
        c.node("leg_l4", "Layer 4 (增量)", shape="box", style="filled", fillcolor="#FFCDD2", fontsize="9")
        c.node("leg_rel", "L1-L3 关系", shape="ellipse", style="filled", fillcolor="#FFE0B2", fontsize="9")
        c.edge("leg_l1", "leg_l2", style="invis")
        c.edge("leg_l2", "leg_l4", style="invis")
        c.edge("leg_l4", "leg_rel", style="invis")

    out = OUTPUT_DIR / "kg_sample_subgraph"
    dot.render(str(out), cleanup=True)
    print(f"  Sample subgraph: {out}.svg")


def render_relation_heatmap(kg, bundle):
    """Render L1/L2/L3 relation statistics as a bar chart."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm

    # Find a Chinese font
    zh_font = None
    for f in fm.fontManager.ttflist:
        if f.name in ("SimHei", "Microsoft YaHei", "SimSun", "KaiTi", "FangSong"):
            zh_font = f.name
            break
    if zh_font:
        plt.rcParams["font.sans-serif"] = [zh_font, "SimHei", "Microsoft YaHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    from rdflib import Namespace
    PLN = Namespace("http://village-planning.org/ontology#")

    # Count relations
    touches = len(list(kg.g.triples((None, PLN.touches, None))))
    nearby = len(list(kg.g.triples((None, PLN.nearby, None))))
    connected = len(list(kg.g.triples((None, PLN.connected_via_road, None))))
    located_in = len(list(kg.g.triples((None, PLN.located_in, None))))

    # Entity distribution
    from rdflib import RDF
    entity_counts = {
        "Parcel\n(地块)": len(list(kg.g.triples((None, RDF.type, PLN.Parcel)))),
        "Road\n(道路)": len(list(kg.g.triples((None, RDF.type, PLN.Road)))),
        "Facility\n(设施)": len(list(kg.g.triples((None, RDF.type, PLN.Facility)))),
        "WaterBody\n(水域)": len(list(kg.g.triples((None, RDF.type, PLN.WaterBody)))),
        "Settlement\n(村落)": len(list(kg.g.triples((None, RDF.type, PLN.NaturalSettlement)))),
        "Zone\n(分区)": len(list(kg.g.triples((None, RDF.type, PLN.Zone)))),
        "LandUseCat\n(VNE)": len(list(kg.g.triples((None, RDF.type, PLN.LandUseCategory)))),
        "Constraint\n(约束)": len(list(kg.g.triples((None, RDF.type, PLN.Constraint)))),
        "ThreeLine\n(三线)": len(list(kg.g.triples((None, RDF.type, PLN.ThreeLine)))),
    }

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # Left: entity distribution
    names = list(entity_counts.keys())
    values = list(entity_counts.values())
    colors = ["#4CAF50", "#2196F3", "#FF9800", "#00BCD4", "#9C27B0",
              "#795548", "#607D8B", "#F44336", "#3F51B5"]
    bars = ax1.bar(names, values, color=colors)
    ax1.set_title("KG 实体分布 (jintian)", fontsize=14, fontweight="bold")
    ax1.set_ylabel("数量")
    for bar, val in zip(bars, values):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 5,
                 str(val), ha="center", va="bottom", fontsize=9)
    ax1.tick_params(axis="x", labelsize=8)

    # Right: relation distribution
    rel_names = ["touches\n(L1 拓扑)", "nearby\n(L2 近邻)", "connected\n(L3 路网)", "located_in"]
    rel_values = [touches, nearby, connected, located_in]
    rel_colors = ["#FF9800", "#2196F3", "#4CAF50", "#9E9E9E"]
    bars2 = ax2.bar(rel_names, rel_values, color=rel_colors)
    ax2.set_title("KG 空间关系分布 (三层)", fontsize=14, fontweight="bold")
    ax2.set_ylabel("三元组数量")
    for bar, val in zip(bars2, rel_values):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 20,
                 str(val), ha="center", va="bottom", fontsize=9)

    plt.tight_layout()
    out = OUTPUT_DIR / "kg_statistics.png"
    plt.savefig(str(out), dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Statistics chart: {out}")


def render_dlbm_distribution(kg):
    """Render DLBM (land use code) distribution as a pie chart."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    zh_font = None
    import matplotlib.font_manager as fm
    for f in fm.fontManager.ttflist:
        if "SimHei" in f.name or "Microsoft YaHei" in f.name:
            zh_font = f.name
            break
    if zh_font:
        plt.rcParams["font.sans-serif"] = [zh_font]
    plt.rcParams["axes.unicode_minus"] = False

    from rdflib import Namespace
    PLN = Namespace("http://village-planning.org/ontology#")

    # Count parcels by DLBM
    dlbm_counts = Counter()
    for s, _, o in kg.g.triples((None, PLN.dlbm, None)):
        if (s, None, PLN.Parcel) in kg.g:
            dlbm_counts[str(o)] += 1

    # Top 10 DLBMs
    top = dlbm_counts.most_common(10)
    labels = [d[0] for d in top]
    sizes = [d[1] for d in top]
    other = sum(dlbm_counts.values()) - sum(sizes)
    if other > 0:
        labels.append("其他")
        sizes.append(other)

    fig, ax = plt.subplots(figsize=(8, 8))
    colors = plt.cm.Set3(range(len(labels)))
    wedges, texts, autotexts = ax.pie(sizes, labels=labels, autopct="%1.1f%%",
                                       colors=colors, startangle=90)
    ax.set_title("Jintian 地块 DLBM 分布 (Top 10)", fontsize=14, fontweight="bold")

    out = OUTPUT_DIR / "kg_dlbm_distribution.png"
    plt.savefig(str(out), dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  DLBM distribution: {out}")


def main():
    print("=" * 60)
    print("  KG Visualization Generator (jintian real data)")
    print("=" * 60)

    print("\n[1/5] Building KG from jintian data...")
    kg, bundle, blocks, relations = build_kg()
    print(f"  KG built: {kg.get_triple_count()} triples, {kg.get_parcel_count()} parcels")

    print("\n[2/5] Rendering architecture diagram...")
    render_architecture_diagram(kg)

    print("\n[3/5] Rendering sample subgraph...")
    render_sample_subgraph(kg)

    print("\n[4/5] Rendering statistics chart...")
    render_relation_heatmap(kg, bundle)

    print("\n[5/5] Rendering DLBM distribution...")
    render_dlbm_distribution(kg)

    print(f"\nAll outputs in: {OUTPUT_DIR}")
    print("\nFiles generated:")
    for f in sorted(OUTPUT_DIR.iterdir()):
        print(f"  {f.name} ({f.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
