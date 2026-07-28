"""Demonstrate parcel-level cognition from KG."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.data import DataCatalog
from app.modules.spatial_ops import build_constraint_index
from app.modules.spatial_ops.geometry import compute_parcel_relations
from app.modules.kg.builder import PlanningKG
from app.modules.kg.ontology import PLN, EntityTypes, Relations
from app.modules.kg.queries.semantic import (
    get_parcel_semantic_context, get_parcel_neighbors_semantic,
    get_parcel_detail_semantic, get_entity_semantics,
)
from rdflib import RDF, Literal

catalog = DataCatalog()
bundle = catalog.load_village_bundle("jintian")
relations = compute_parcel_relations(bundle.polygons.landuse_current, roads=bundle.lines.roads_current)
ci = build_constraint_index(bundle)
kg = PlanningKG("金田村委会")
kg.build_from_bundle(bundle=bundle, parcel_relations=relations, constraint_index=ci)

def show_parcel_cognition(kg, label, bsm):
    print(f"\n{'='*80}")
    print(f"  地块认知: {label}")
    print(f"  BSM: {bsm}")
    print(f"{'='*80}")

    # 1) Raw KG predicates
    pu = None
    for s in kg.g.subjects(RDF.type, EntityTypes.Parcel):
        for p, o in kg.g.predicate_objects(s):
            if str(p).endswith("bsm") and str(o) == bsm:
                pu = s
                break
        if pu:
            break
    if not pu:
        print("  ⚠️ 未找到该地块")
        return

    print("\n  ▸ 全部 KG 属性 (Literal):")
    for p, o in kg.g.predicate_objects(pu):
        pn = str(p).split("#")[-1]
        if isinstance(o, Literal):
            print(f"    {pn:30s} = {str(o)[:60]}")

    # 2) Spatial relations (non-literal)
    print("\n  ▸ 空间关系 (实体→实体):")
    for pred_uri, pred_label in [
        (Relations.touches, "touches(相邻)"),
        (Relations.nearby, "nearby(近邻)"),
        (Relations.connected_via_road, "connected_via_road(路网连通)"),
        (Relations.intersects, "intersects(交叉)"),
        (Relations.contains, "contains(包含)"),
        (Relations.located_in, "located_in(位于)"),
    ]:
        targets = list(kg.g.objects(pu, pred_uri))
        if targets:
            details = []
            for t in targets:
                tid = str(t).split("#")[-1][:25] if "#" in str(t) else str(t).split("/")[-1][:25]
                details.append(tid)
            print(f"    {pred_label:30s} → {', '.join(details[:8])}{'...' if len(details)>8 else ''}  ({len(details)}条)")

    # 3) Numerical properties of spatial relations
    print("\n  ▸ 空间关系量化数据:")
    for p_label, p_uri in [("shared_boundary_length", PLN.shared_boundary_length),
                            ("centroid_distance", PLN.centroid_distance)]:
        vals = list(kg.g.objects(pu, p_uri))
        if vals:
            fvals = [float(v) for v in vals if str(v).replace('.','',1).replace('-','',1).isdigit()]
            if fvals:
                print(f"    {p_label:25s}: min={min(fvals):.2f}  max={max(fvals):.2f}  avg={sum(fvals)/len(fvals):.2f}")

    # 4) Legal cognition
    print("\n  ▸ 法律约束认知:")
    for p_uri, p_label in [(PLN.legal_constraint, "legal_constraint"),
                            (PLN.allowed_operations, "allowed_operations")]:
        vals = list(kg.g.objects(pu, p_uri))
        if vals:
            print(f"    {p_label:25s}: {', '.join(str(v) for v in vals)}")

    # 5) Semantic query output
    print("\n  ▸ get_parcel_semantic_context():")
    try:
        ctx = get_parcel_semantic_context(kg, bsm)
        if ctx:
            for k, v in ctx.items():
                if isinstance(v, (int, float)):
                    print(f"    {k:25s} = {v}")
                else:
                    sv = json.dumps(v, ensure_ascii=False, default=str)
                    print(f"    {k:25s} = {sv[:120]}")
    except Exception as e:
        print(f"    ⚠️ {e}")

    # 6) Neighbors
    print("\n  ▸ get_parcel_neighbors_semantic():")
    try:
        nbrs = get_parcel_neighbors_semantic(kg, bsm)
        for n in nbrs[:6]:
            desc = n.get("description", "")
            rel = n.get("relation", "?")
            print(f"    [{rel:10s}] {desc[:80]}")
        if len(nbrs) > 6:
            print(f"    ... 还有 {len(nbrs)-6} 个")
    except Exception as e:
        print(f"    ⚠️ {e}")

# Pick diverse parcels
show_parcel_cognition(kg, "宅基地 (居住)", "441426211000055682")
show_parcel_cognition(kg, "耕地 (农业)", "441426211000049106")
show_parcel_cognition(kg, "水域", "441426211000049104")
