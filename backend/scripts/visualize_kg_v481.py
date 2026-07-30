"""KG v4.8.1 visualization: render all entity layers + relations.

Produces:
  1. Console summary of all entity types with counts
  2. Graphviz architecture diagram (4-layer structure with actual v4.8.1 entities)
  3. Graphviz sample subgraph (key entities + cross-type relations)
  4. Matplotlib entity distribution + relation statistics chart
  5. DLBM distribution pie chart

Usage:
  cd F:/project/Village_Planning_Agent
  python backend/scripts/visualize_kg_v481.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from collections import Counter, defaultdict

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND.parent)

OUTPUT_DIR = BACKEND.parent / "docs" / "gis" / "kg_visualization"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Ontology helpers ──

PLN_NS = "http://village-planning.org/ontology#"
from rdflib import RDF, Namespace, URIRef
PLN = Namespace(PLN_NS)

def _short_uri(u):
    s = str(u)
    if s.startswith(PLN_NS):
        return "pln:" + s[len(PLN_NS):]
    return s

def count_type(kg, t):
    return len(list(kg.g.triples((None, RDF.type, t))))

# ── Known RDF type URIs for v4.8.1 entities ──

L1_ENTITIES = {
    "AdministrativeVillage": PLN.AdministrativeVillage,
    "Parcel": PLN.Parcel,
    "Road": PLN.Road,
    "WaterBody": PLN.WaterBody,
    "Facility": PLN.Facility,
    "ResidentialCluster": PLN.ResidentialCluster,
    "Zone": PLN.Zone,
    "ControlLine": PLN.ControlLine,
    "PlaceRef": PLN.PlaceRef,
    "GisLayerSet": PLN.GisLayerSet,
}

L3_ENTITIES = {
    "ZoneTarget": PLN.ZoneTarget,
    "FacilityTarget": PLN.FacilityTarget,
    "AxisTarget": PLN.AxisTarget,
    "RoadTarget": PLN.RoadTarget,
}

L4_ENTITIES = {
    "PlannedParcel": PLN.PlannedParcel,
    "PlannedZone": PLN.PlannedZone,
    "PlannedFacility": PLN.PlannedFacility,
    "PlannedRoad": PLN.PlannedRoad,
    "PlannedAxis": PLN.PlannedAxis,
}

# ── Step 1: Build KG ──

def build_kg():
    """Build KG from real jintian data (v4.8.1 API)."""
    from app.modules.data import DataCatalog
    from app.modules.spatial_ops.geometry import compute_parcel_relations
    from app.modules.spatial_ops.bridge import build_constraint_index
    from app.modules.kg.builder import PlanningKG
    from app.modules.schema.contracts.parse_contracts import (
        SpatialPlanningIntent, ZoneTarget,
    )

    catalog = DataCatalog()
    bundle = catalog.load_village_bundle("jintian")
    relations = compute_parcel_relations(
        bundle.polygons.landuse_current,
        roads=bundle.lines.roads_current,
    )
    constraint_index = build_constraint_index(bundle)

    kg = PlanningKG("jintian")
    kg.build_from_bundle(
        bundle=bundle,
        parcel_relations=relations,
        constraint_index=constraint_index,
    )

    # Build L3 with a sample intent to show L3 entities
    all_bsms = []
    for s, _, o in kg.g.triples((None, PLN.bsm, None)):
        if (s, RDF.type, PLN.Parcel) in kg.g:
            all_bsms.append(str(o))
        if len(all_bsms) >= 3:
            break

    intent = SpatialPlanningIntent(
        village_name="jintian",
        zone_targets=[
            ZoneTarget(land_use="2121", area_ratio=0.15,
                       candidate_bsms=all_bsms[:2]),
        ],
    )
    kg.build_intent_layer(intent)

    # Build L4 with a sample planned state
    from app.modules.kg.builder.layer4 import (
        PlannedState, PlannedParcelEntry,
    )
    planned = PlannedState(version="v1")
    if all_bsms:
        planned.parcels.append(
            PlannedParcelEntry(
                bsm=all_bsms[0],
                planning_land_use="2121",
                area_ha=0.15,
                derived_from_bsms=[all_bsms[0]],
            )
        )
    kg.apply_planned_state(planned)

    return kg, bundle


# ── Step 2: Console summary ──

def print_entity_summary(kg):
    print("\n" + "=" * 70)
    print("  KG v4.8.1 实体图层完整统计")
    print("=" * 70)
    print(f"  Total triples: {len(kg.g)}")

    print("\n  ── L1 现状实体 ──")
    l1_total = 0
    for name, uri in L1_ENTITIES.items():
        c = count_type(kg, uri)
        if c > 0:
            print(f"    {name:25s} {c:>6d}")
            l1_total += c
    print(f"    {'─'*32}")
    print(f"    {'L1 Total':25s} {l1_total:>6d}")

    print("\n  ── L3 意图虚拟实体 ──")
    l3_total = 0
    for name, uri in L3_ENTITIES.items():
        c = count_type(kg, uri)
        if c > 0:
            print(f"    {name:25s} {c:>6d}")
            l3_total += c
    if l3_total == 0:
        print("    (none injected)")
    else:
        print(f"    {'L3 Total':25s} {l3_total:>6d}")

    print("\n  ── L4 规划成果 ──")
    l4_total = 0
    for name, uri in L4_ENTITIES.items():
        c = count_type(kg, uri)
        if c > 0:
            print(f"    {name:25s} {c:>6d}")
            l4_total += c
    if l4_total == 0:
        print("    (none injected)")
    else:
        print(f"    {'L4 Total':25s} {l4_total:>6d}")

    # Relations
    print("\n  ── 空间关系 ──")
    touches_cnt = len(list(kg.g.triples((None, PLN.touches, None)))) // 2
    nearby_cnt = len(list(kg.g.triples((None, PLN.nearby, None))))
    connected_cnt = len(list(kg.g.triples((None, PLN.connected_via_road, None))))
    located_in_cnt = len(list(kg.g.triples((None, PLN.located_in, None))))
    intersects_cnt = len(list(kg.g.triples((None, PLN.intersects, None))))
    contains_cnt = len(list(kg.g.triples((None, PLN.contains, None))))
    spatial_total = touches_cnt + nearby_cnt + connected_cnt + located_in_cnt + intersects_cnt + contains_cnt
    print(f"    touches              {touches_cnt:>6d} pairs (拓扑邻接)")
    print(f"    nearby               {nearby_cnt:>6d} edges (近邻)")
    print(f"    connected_via_road   {connected_cnt:>6d} edges (路网连通)")
    print(f"    located_in           {located_in_cnt:>6d} edges (包含)")
    print(f"    intersects           {intersects_cnt:>6d} edges (交叉)")
    print(f"    contains             {contains_cnt:>6d} edges (包围)")
    print(f"    {'─'*42}")
    print(f"    Spatial Total        {spatial_total:>6d}")

    print("\n  ── 三维度谓词覆盖 ──")
    # Check how many entities have v4.8 three-dimension predicates
    layer_type_cnt = len(list(kg.g.triples((None, PLN.gis_type_ref, None))))
    geometry_kind_cnt = len(list(kg.g.triples((None, PLN.geometry_kind, None))))
    semantic_group_cnt = len(list(kg.g.triples((None, PLN.semantic_group, None))))
    has_label_cnt = len(list(kg.g.triples((None, PLN.has_semantic_label, None))))
    print(f"    layer_type          {layer_type_cnt:>6d}")
    print(f"    geometry_kind       {geometry_kind_cnt:>6d}")
    print(f"    semantic_group      {semantic_group_cnt:>6d}")
    print(f"    has_semantic_label  {has_label_cnt:>6d}")

    print("\n  ── LayerGroup 虚拟实体 ──")
    for lg in kg.g.subjects(RDF.type, PLN.GisLayerSet):
        group_name = ""
        count = 0
        for p, o in kg.g.predicate_objects(lg):
            if p == PLN.semantic_group:
                group_name = str(o)
            elif p == PLN.entity_count:
                try: count = int(o)
                except: pass
        print(f"    LayerGroup_{group_name:25s} {count:>6d} entities")

    print("=" * 70)


# ── Step 3: Graphviz architecture diagram ──

def render_architecture_diagram(kg):
    import graphviz

    dot = graphviz.Digraph("KG_Architecture_v481", format="svg")
    dot.attr(rankdir="TB", bgcolor="white", fontname="SimHei",
             label=f"金田村 KG v4.8.1 四层架构 ({len(kg.g)} triples)",
             labelloc="t", fontsize="20")
    dot.attr("node", fontname="SimHei", fontsize="10")
    dot.attr("edge", fontname="SimHei", fontsize="9")

    # ── Layer 1: 现状实体 ──
    with dot.subgraph(name="cluster_l1") as c:
        c.attr(label="Layer 1: 现状空间实体 (持久, 数据更新时重建)", style="rounded,filled",
               fillcolor="#E8F5E9", color="#4CAF50", fontsize="13")

        # Village
        v_cnt = count_type(kg, PLN.AdministrativeVillage)
        c.node("village", f"AdministrativeVillage\n{v_cnt} 个", shape="box",
               style="filled", fillcolor="#C8E6C9")

        # Core entities
        p_cnt = count_type(kg, PLN.Parcel)
        c.node("parcels", f"Parcel (地块)\n{p_cnt} 个", shape="box",
               style="filled", fillcolor="#A5D6A7")

        r_cnt = count_type(kg, PLN.Road)
        c.node("roads", f"Road (道路)\n{r_cnt} 个", shape="box",
               style="filled", fillcolor="#A5D6A7")

        f_cnt = count_type(kg, PLN.Facility)
        c.node("facilities", f"Facility (设施)\n{f_cnt} 个", shape="box",
               style="filled", fillcolor="#A5D6A7")

        w_cnt = count_type(kg, PLN.WaterBody)
        c.node("water", f"WaterBody (水域)\n{w_cnt} 个", shape="box",
               style="filled", fillcolor="#A5D6A7")

        s_cnt = count_type(kg, PLN.ResidentialCluster)
        c.node("settlements", f"ResidentialCluster\n(居民点) {s_cnt} 个", shape="box",
               style="filled", fillcolor="#A5D6A7")

        z_cnt = count_type(kg, PLN.Zone)
        c.node("zones", f"Zone (分区)\n{z_cnt} 个", shape="box",
               style="filled", fillcolor="#A5D6A7")

        cl_cnt = count_type(kg, PLN.ControlLine)
        c.node("ctrllines", f"ControlLine (控制线)\n{cl_cnt} 个", shape="box",
               style="filled", fillcolor="#A5D6A7")

        pl_cnt = count_type(kg, PLN.PlaceRef)
        c.node("placeref", f"PlaceRef (村名)\n{pl_cnt} 个", shape="box",
               style="filled", fillcolor="#A5D6A7")

    # ── Layer 1b: 三维度 + LayerGroup ──
    with dot.subgraph(name="cluster_l1b") as c:
        c.attr(label="v4.8 三维度谓词 + LayerGroup 虚拟实体", style="rounded,filled",
               fillcolor="#F1F8E9", color="#689F38", fontsize="11")
        lg_cnt = count_type(kg, PLN.GisLayerSet)
        c.node("layergroups", f"LayerGroup (图层组)\n{lg_cnt} 个虚拟实体", shape="ellipse",
               style="filled", fillcolor="#DCEDC8")
        lt_cnt = len(list(kg.g.triples((None, PLN.gis_type_ref, None))))
        c.node("dims", f"三维度谓词\nlayer_type/geometry_kind/\nsemantic_group/has_semantic_label\n{lt_cnt} 个实体标注",
               shape="ellipse", style="filled", fillcolor="#DCEDC8")

    # ── Layer 2: 空间关系 ──
    with dot.subgraph(name="cluster_l2") as c:
        c.attr(label="Layer 2: 空间关系 (spatial_ops 预计算)", style="rounded,filled",
               fillcolor="#FFF3E0", color="#FF9800", fontsize="11")
        touches_cnt = len(list(kg.g.triples((None, PLN.touches, None)))) // 2
        nearby_cnt = len(list(kg.g.triples((None, PLN.nearby, None))))
        connected_cnt = len(list(kg.g.triples((None, PLN.connected_via_road, None))))
        c.node("l1_touches", f"pln:touches (拓扑邻接)\n{touches_cnt} pairs",
               shape="ellipse", style="filled", fillcolor="#FFE0B2")
        c.node("l2_nearby", f"pln:nearby (近邻 ≤200m)\n{nearby_cnt} edges",
               shape="ellipse", style="filled", fillcolor="#FFE0B2")
        c.node("l3_connected", f"pln:connected_via_road (路网连通)\n{connected_cnt} edges",
               shape="ellipse", style="filled", fillcolor="#FFE0B2")
        li_cnt = len(list(kg.g.triples((None, PLN.located_in, None))))
        it_cnt = len(list(kg.g.triples((None, PLN.intersects, None))))
        cc_cnt = len(list(kg.g.triples((None, PLN.contains, None))))
        c.node("cross", f"pln:located_in/intersects/contains\n(交叉类型, v4.8.1)\n{li_cnt+it_cnt+cc_cnt} edges",
               shape="ellipse", style="filled", fillcolor="#FFE0B2")

    # ── Layer 3: 意图 ──
    with dot.subgraph(name="cluster_l3") as c:
        c.attr(label="Layer 3: PARSE 意图虚拟实体 (会话易失)", style="rounded,filled",
               fillcolor="#F3E5F5", color="#9C27B0", fontsize="13")
        zt_cnt = count_type(kg, PLN.ZoneTarget)
        ft_cnt = count_type(kg, PLN.FacilityTarget)
        at_cnt = count_type(kg, PLN.AxisTarget)
        rt_cnt = count_type(kg, PLN.RoadTarget)
        c.node("l3_nodes", f"ZoneTarget({zt_cnt}) / FacilityTarget({ft_cnt})\nAxisTarget({at_cnt}) / RoadTarget({rt_cnt})",
               shape="box", style="dashed", fillcolor="#E1BEE7")

    # ── Layer 4: 规划成果 ──
    with dot.subgraph(name="cluster_l4") as c:
        c.attr(label="Layer 4: 规划成果 (版本化增量)", style="rounded,filled",
               fillcolor="#FFEBEE", color="#F44336", fontsize="13")
        pp_cnt = count_type(kg, PLN.PlannedParcel)
        pz_cnt = count_type(kg, PLN.PlannedZone)
        pf_cnt = count_type(kg, PLN.PlannedFacility)
        c.node("l4_nodes", f"PlannedParcel({pp_cnt}) / PlannedZone({pz_cnt})\nPlannedFacility({pf_cnt}) / PlannedRoad / PlannedAxis",
               shape="box", style="filled", fillcolor="#FFCDD2")

    # Cross-layer edges
    dot.edge("village", "parcels", label="pln:located_in")
    dot.edge("parcels", "l1_touches", label="pln:touches", style="dotted")
    dot.edge("parcels", "l2_nearby", label="pln:nearby", style="dotted")
    dot.edge("parcels", "l3_connected", label="pln:connected_via_road", style="dotted")
    dot.edge("parcels", "cross", label="pln:intersects", style="dotted", color="#FF9800")
    dot.edge("parcels", "dims", label="v4.8 三维度", style="dashed", color="#689F38")
    dot.edge("dims", "layergroups", label="聚合到", style="dashed", color="#689F38")
    dot.edge("parcels", "l3_nodes", label="candidate_bsm", style="dashed", color="#9C27B0")
    dot.edge("l3_nodes", "l4_nodes", label="derived_from_target", style="dashed", color="#F44336")
    dot.edge("l4_nodes", "parcels", label="derived_from (sparse)", style="dashed", color="#F44336", dir="back")

    out = OUTPUT_DIR / "kg_architecture"
    dot.render(str(out), cleanup=True)
    print(f"\n  Architecture diagram: {out}.svg")


# ── Step 4: Sample subgraph ──

def render_sample_subgraph(kg):
    import graphviz

    dot = graphviz.Digraph("KG_Sample_v481", format="svg")
    dot.attr(rankdir="LR", bgcolor="white", fontname="SimHei",
             label="金田村 KG v4.8.1 样本子图 (实体 + 关系)",
             labelloc="t", fontsize="14")
    dot.attr("node", fontname="SimHei", fontsize="9")
    dot.attr("edge", fontname="SimHei", fontsize="8")

    # Village
    dot.node("village", "pln:village\n金田村", shape="box",
             style="filled,bold", fillcolor="#C8E6C9", width="2")

    # Sample parcels (5)
    parcels = list(kg.g.subjects(RDF.type, PLN.Parcel))[:5]
    parcel_nodes = {}
    for i, pu in enumerate(parcels):
        bsm = ""
        dlbm = ""
        area = ""
        label = ""
        for p, o in kg.g.predicate_objects(pu):
            if p == PLN.bsm: bsm = str(o)[:12]
            elif p == PLN.dlbm: dlbm = str(o)
            elif p == PLN.area_ha:
                try: area = f"{float(o):.2f}ha"
                except: pass
            elif p == PLN.has_semantic_label: label = str(o)
        pid = f"parcel_{i}"
        parcel_nodes[str(pu)] = pid
        bsm_short = bsm + ".." if len(str(bsm)) > 12 else bsm
        disp = f"Parcel\n{bsm_short}\nDLBM={dlbm}\n{area}\n{label}" if label else f"Parcel\n{bsm_short}\nDLBM={dlbm}\n{area}"
        dot.node(pid, disp, shape="box", style="filled", fillcolor="#A5D6A7")
        dot.edge("village", pid, label="located_in", fontsize="7", color="#4CAF50")

    # Touches between sample parcels
    for s1, _, o1 in kg.g.triples((None, PLN.touches, None)):
        su = str(s1)
        ou = str(o1)
        if su in parcel_nodes and ou in parcel_nodes:
            dot.edge(parcel_nodes[su], parcel_nodes[ou], label="touches",
                     style="dashed", color="#FF9800", fontsize="7")

    # Sample roads
    roads = list(kg.g.subjects(RDF.type, PLN.Road))[:3]
    for i, ru in enumerate(roads):
        name = ""
        for p, o in kg.g.predicate_objects(ru):
            if p == PLN.name: name = str(o)
        rid = f"road_{i}"
        dot.node(rid, f"Road\n{name}", shape="box", style="filled",
                 fillcolor="#81D4FA")
        dot.edge("village", rid, label="connects", fontsize="7", color="#0288D1")

    # Sample facilities
    facs = list(kg.g.subjects(RDF.type, PLN.Facility))[:3]
    for i, fu in enumerate(facs):
        name = ""
        ftype = ""
        for p, o in kg.g.predicate_objects(fu):
            if p == PLN.name: name = str(o)
            elif p == PLN.facility_type: ftype = str(o)
        fid = f"fac_{i}"
        dot.node(fid, f"Facility\n{name}\n({ftype})", shape="box",
                 style="filled", fillcolor="#FFCC80")
        dot.edge("village", fid, label="has_facility", fontsize="7")

    # L3 ZoneTarget
    for zt in kg.g.subjects(RDF.type, PLN.ZoneTarget):
        zid = "zone_target"
        target_id = ""
        land_use = ""
        for p, o in kg.g.predicate_objects(zt):
            if p == PLN.target_id: target_id = str(o)
            elif p == PLN.land_use_code: land_use = str(o)
        dot.node(zid, f"ZoneTarget\n{target_id}\nland_use={land_use}",
                 shape="box", style="dashed", fillcolor="#E1BEE7", color="#9C27B0")
        dot.edge("village", zid, label="has_zone", style="dashed",
                 color="#9C27B0", fontsize="7")
        # Show candidate_bsm links
        for _, _, bsm_ref in kg.g.triples((zt, PLN.candidate_bsm, None)):
            bsm_str = _short_uri(bsm_ref)
            for pu_str, pid in parcel_nodes.items():
                for _, _, o in kg.g.triples((URIRef(pu_str), PLN.bsm, None)):
                    if str(o) in bsm_str:
                        dot.edge(zid, pid, label="candidate_bsm", style="dotted",
                                 color="#9C27B0", fontsize="6")

    # L4 PlannedParcel
    for pp in kg.g.subjects(RDF.type, PLN.PlannedParcel):
        pid4 = "planned"
        bsm4 = ""
        lu = ""
        for p, o in kg.g.predicate_objects(pp):
            if p == PLN.bsm: bsm4 = str(o)[:12]
            elif p == PLN.planning_land_use: lu = str(o)
        dot.node(pid4, f"PlannedParcel\n{bsm4}..\n→{lu}",
                 shape="box", style="filled", fillcolor="#FFCDD2", color="#F44336")
        dot.edge("village", pid4, label="in_version=v1", style="dashed",
                 color="#F44336", fontsize="7")
        # derived_from link
        for _, _, parent in kg.g.triples((pp, PLN.derived_from, None)):
            ps = str(parent)
            if ps in parcel_nodes:
                dot.edge(pid4, parcel_nodes[ps], label="derived_from",
                         style="dashed", color="#F44336", fontsize="7", dir="back")

    # LayerGroup
    lgs = list(kg.g.subjects(RDF.type, PLN.GisLayerSet))
    for i, lg in enumerate(lgs[:4]):
        gname = ""
        gcnt = 0
        for p, o in kg.g.predicate_objects(lg):
            if p == PLN.semantic_group: gname = str(o)
            elif p == PLN.entity_count:
                try: gcnt = int(o)
                except: pass
        gid = f"lg_{i}"
        dot.node(gid, f"LayerGroup\n{gname}\n{gcnt} entities",
                 shape="ellipse", style="filled", fillcolor="#DCEDC8",
                 color="#689F38")
        # Link to a sample member
        for _, _, member in kg.g.triples((lg, PLN.contains_entity, None)):
            ms = str(member)
            if ms in parcel_nodes:
                dot.edge(gid, parcel_nodes[ms], label="contains_entity",
                         style="dotted", color="#689F38", fontsize="6")
                break

    # Legend
    with dot.subgraph(name="cluster_legend") as c:
        c.attr(label="图例", style="rounded,filled", fillcolor="#FAFAFA",
               color="#9E9E9E", fontsize="10")
        c.node("leg_l1", "L1 现状", shape="box", style="filled",
               fillcolor="#A5D6A7", fontsize="8")
        c.node("leg_l3", "L3 意图", shape="box", style="dashed",
               fillcolor="#E1BEE7", fontsize="8")
        c.node("leg_l4", "L4 规划", shape="box", style="filled",
               fillcolor="#FFCDD2", fontsize="8")
        c.node("leg_lg", "LayerGroup", shape="ellipse", style="filled",
               fillcolor="#DCEDC8", fontsize="8")
        c.edge("leg_l1", "leg_l3", style="invis")
        c.edge("leg_l3", "leg_l4", style="invis")
        c.edge("leg_l4", "leg_lg", style="invis")

    out = OUTPUT_DIR / "kg_sample_subgraph"
    dot.render(str(out), cleanup=True)
    print(f"  Sample subgraph: {out}.svg")


# ── Step 5: Statistics chart ──

def render_statistics(kg):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm

    for f in fm.fontManager.ttflist:
        if f.name in ("SimHei", "Microsoft YaHei", "SimSun", "KaiTi", "FangSong"):
            plt.rcParams["font.sans-serif"] = [f.name, "SimHei", "DejaVu Sans"]
            break
    plt.rcParams["axes.unicode_minus"] = False

    # Entity distribution
    entity_data = {}
    for name, uri in {**L1_ENTITIES, **L3_ENTITIES, **L4_ENTITIES}.items():
        c = count_type(kg, uri)
        if c > 0:
            entity_data[name] = c

    # Relation distribution
    rel_data = {
        "touches": len(list(kg.g.triples((None, PLN.touches, None)))) // 2,
        "nearby": len(list(kg.g.triples((None, PLN.nearby, None)))),
        "connected\n_via_road": len(list(kg.g.triples((None, PLN.connected_via_road, None)))),
        "located_in": len(list(kg.g.triples((None, PLN.located_in, None)))),
        "intersects": len(list(kg.g.triples((None, PLN.intersects, None)))),
        "contains": len(list(kg.g.triples((None, PLN.contains, None)))),
    }

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 5.5))

    colors_ent = ["#4CAF50", "#66BB6A", "#81C784", "#A5D6A7", "#C8E6C9",
                  "#FF9800", "#FFA726", "#FFB74D", "#FFCC80", "#FFE0B2",
                  "#9C27B0", "#AB47BC", "#BA68C8", "#CE93D8",
                  "#F44336", "#EF5350", "#E57373", "#EF9A9A"]
    names = list(entity_data.keys())
    values = list(entity_data.values())
    bars = ax1.barh(names, values, color=colors_ent[:len(names)])
    ax1.set_title("KG v4.8.1 实体分布 (金田村)", fontsize=13, fontweight="bold")
    ax1.set_xlabel("数量")
    for bar, val in zip(bars, values):
        ax1.text(bar.get_width() + 5, bar.get_y() + bar.get_height()/2,
                 str(val), ha="left", va="center", fontsize=9)

    rel_names = list(rel_data.keys())
    rel_values = list(rel_data.values())
    rel_colors = ["#FF9800", "#F57C00", "#E65100", "#9E9E9E", "#757575", "#616161"]
    bars2 = ax2.bar(rel_names, rel_values, color=rel_colors[:len(rel_names)])
    ax2.set_title("KG v4.8.1 空间关系分布", fontsize=13, fontweight="bold")
    ax2.set_ylabel("三元组数量")
    for bar, val in zip(bars2, rel_values):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 15,
                 str(val), ha="center", va="bottom", fontsize=9)
    ax2.tick_params(axis="x", labelsize=8)

    plt.tight_layout()
    out = OUTPUT_DIR / "kg_statistics.png"
    plt.savefig(str(out), dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Statistics chart: {out}")


# ── Step 6: DLBM distribution ──

def render_dlbm_distribution(kg):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm

    for f in fm.fontManager.ttflist:
        if "SimHei" in f.name or "Microsoft YaHei" in f.name:
            plt.rcParams["font.sans-serif"] = [f.name, "SimHei"]
            break
    plt.rcParams["axes.unicode_minus"] = False

    from collections import Counter
    dlbm_count = Counter()
    for s, _, o in kg.g.triples((None, PLN.dlbm, None)):
        if (s, RDF.type, PLN.Parcel) in kg.g:
            dlbm_count[str(o)] += 1

    top = dlbm_count.most_common(10)
    labels = [d[0] for d in top]
    sizes = [d[1] for d in top]
    other = sum(dlbm_count.values()) - sum(sizes)
    if other > 0:
        labels.append("其他")
        sizes.append(other)

    # DLBM -> 中文名
    try:
        from app.modules.schema.encodings.code_sets import DLBM_TO_DLMC
        labels_cn = []
        for lbl in labels:
            if lbl in DLBM_TO_DLMC:
                labels_cn.append(f"{DLBM_TO_DLMC[lbl]}({lbl})")
            else:
                labels_cn.append(lbl)
    except Exception:
        labels_cn = labels

    fig, ax = plt.subplots(figsize=(9, 8))
    colors = plt.cm.Set3(range(len(labels_cn)))
    wedges, texts, autotexts = ax.pie(sizes, labels=labels_cn, autopct="%1.1f%%",
                                       colors=colors, startangle=90)
    ax.set_title("金田村 地块 DLBM 分布 (Top 10)", fontsize=14, fontweight="bold")

    out = OUTPUT_DIR / "kg_dlbm_distribution.png"
    plt.savefig(str(out), dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  DLBM distribution: {out}")


# ── Main ──

def main():
    print("=" * 60)
    print("  KG v4.8.1 Visualization Generator (jintian)")
    print("=" * 60)

    print("\n[1/5] Building KG from jintian data...")
    kg, bundle = build_kg()
    print(f"  KG built: {len(kg.g)} triples, {kg.get_parcel_count()} parcels")

    print("\n[2/5] Entity layer summary...")
    print_entity_summary(kg)

    print("\n[3/5] Rendering architecture diagram...")
    render_architecture_diagram(kg)

    print("\n[4/5] Rendering sample subgraph...")
    render_sample_subgraph(kg)

    print("\n[5/5] Rendering statistics...")
    render_statistics(kg)
    render_dlbm_distribution(kg)

    print(f"\n  All outputs in: {OUTPUT_DIR}")
    print("  Files generated:")
    for f in sorted(OUTPUT_DIR.iterdir()):
        if f.suffix in (".svg", ".png"):
            print(f"    {f.name} ({f.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
