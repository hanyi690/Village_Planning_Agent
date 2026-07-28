"""Debug why parcel 441426211000049106 has no spatial relations."""
import sys, json, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.data import DataCatalog
from app.modules.spatial_ops.geometry import compute_parcel_relations
from app.modules.kg.builder import PlanningKG
from app.modules.kg.ontology import EntityTypes, Relations, PLN
from rdflib import RDF

catalog = DataCatalog()
bundle = catalog.load_village_bundle("jintian")

lu = bundle.polygons.landuse_current
target_bsm = "441426211000049106"
target_id = f"parcel_{target_bsm}"

# 1) Verify the parcel exists in input data
print(f"=== 验证目标地块存在于输入数据 ===")
found_idx = None
for i, p in enumerate(lu):
    if getattr(p, 'bsm', '') == target_bsm:
        found_idx = i
        print(f"  Found at index {i}: area={getattr(p, 'area_ha', '?')}ha")
        break
if found_idx is None:
    print(f"  ⚠️ 目标地块不在 landuse_current 中!")
else:
    p = lu[found_idx]
    print(f"  dir: {[a for a in dir(p) if not a.startswith('_')]}")

# 2) Compute relations and check
print(f"\n=== 计算空间关系 ===")
roads = bundle.lines.roads_current
print(f"  地块数: {len(lu)}")
print(f"  道路数: {len(roads)}")
relations = compute_parcel_relations(lu, roads=roads)

print(f"\n  touches: {len(relations.touches)} 对")
print(f"  nearby:  {len(relations.nearby)} 对")
print(f"  connected: {len(relations.connected)} 对")

# Search target in touches/nearby
in_touches = [pair for pair in relations.touches if target_id in pair]
in_nearby = [pair for pair in relations.nearby if target_id in pair]
print(f"\n  touches 含 {target_id}: {len(in_touches)}")
print(f"  nearby  含 {target_id}: {len(in_nearby)}")

# 3) Show first few touches to understand the format
print(f"\n=== touches 格式示例 (前5对) ===")
for a, b in relations.touches[:5]:
    print(f"  {a[:60]} <-> {b[:60]}")

# Show touches near the target
print(f"\n=== 目标地块附近的 touches 搜索 ===")
for i, (a, b) in enumerate(relations.touches):
    if target_bsm in a or target_bsm in b:
        print(f"  FOUND touch: {a[:60]} <-> {b[:60]}")
if not in_touches:
    print(f"  完全未找到! 现在检查目标周围的 touches...")
    # Find parcels close to target
    target_lon = getattr(lu[found_idx], 'lon', None) if found_idx is not None else None
    target_lat = getattr(lu[found_idx], 'lat', None) if found_idx is not None else None
    if target_lon is None:
        # Check if it's in geometry
        geom = getattr(lu[found_idx], 'geometry', None) if found_idx is not None else None
        print(f"  目标属性: lon={target_lon}, lat={target_lat}, has_geom={geom is not None}")
        if geom:
            target_lon, target_lat = geom.centroid.x, geom.centroid.y
            print(f"  从 geometry 取 centroid: {target_lon}, {target_lat}")

# 4) Build KG and investigate further
print(f"\n=== 构建 KG ===")
kg = PlanningKG("test")
kg.build_from_bundle(bundle=bundle, parcel_relations=relations)

target_uri = None
for s in kg.g.subjects(RDF.type, EntityTypes.Parcel):
    bsm = None
    for p, o in kg.g.predicate_objects(s):
        if str(p).endswith("bsm"):
            bsm = str(o)
            break
    if bsm == target_bsm:
        target_uri = s
        break

if not target_uri:
    print("⚠️ 目标 URI 未在 KG 中找到!")
    # Check first parcel
    s = next(kg.g.subjects(RDF.type, EntityTypes.Parcel))
    print(f"  First parcel URI: {s}")
    for p, o in kg.g.predicate_objects(s):
        if str(p).endswith("bsm"):
            print(f"  First parcel BSM: {o}")
            break
    sys.exit(1)

print(f"\n  目标 URI: {target_uri}")
# Get all spatial relations
for pred_uri, pred_name in [(Relations.touches, "touches"),
                              (Relations.nearby, "nearby"),
                              (Relations.connected_via_road, "connected")]:
    targets = list(kg.g.objects(target_uri, pred_uri))
    print(f"  KG.{pred_name}: {len(targets)} 条")
    if targets:
        for t in targets[:3]:
            tid = str(t).split("#")[-1]
            print(f"    {tid}")

# Check if the parcel has any relations AT ALL
print(f"\n=== 目标地块在 KG 中的全部非 Literal 谓词 ===")
for p, o in kg.g.predicate_objects(target_uri):
    if not isinstance(o, (str, int, float, type(None))) and hasattr(o, 'startswith'):
        pn = str(p).split("#")[-1]
        on = str(o).split("#")[-1] if "#" in str(o) else str(o)
        print(f"  {pn:30s} → {on[:50]}")
    elif not hasattr(o, 'startswith') and not isinstance(o, (int, float)):
        pn = str(p).split("#")[-1]
        print(f"  {pn:30s} → {type(o).__name__}: {str(o)[:50]}")

# 5) Check geometry - is it really isolated?
print(f"\n=== 几何体检查 ===")
# Find the parcel's geometry
p = lu[found_idx]
geom = getattr(p, 'geometry', None)
print(f"  有 geometry: {geom is not None}")
if geom:
    print(f"  geom type: {geom.geom_type}")
    print(f"  area: {geom.area}")
    bounds = geom.bounds
    print(f"  bounds: {bounds}")

    # Find all parcels within the same bounding box
    minx, miny, maxx, maxy = bounds
    nearby_polys = []
    for i, op in enumerate(lu):
        if i == found_idx:
            continue
        ogeom = getattr(op, 'geometry', None)
        if ogeom is None:
            continue
        obounds = ogeom.bounds
        # Check if bounding boxes overlap (within 500m buffer)
        if (obounds[0] < maxx + 0.005 and obounds[2] > minx - 0.005 and
            obounds[1] < maxy + 0.005 and obounds[3] > miny - 0.005):
            nbrs = getattr(op, 'bsm', '') or ''
            nlu = getattr(op, 'dlmc', '') or ''
            nearby_polys.append((i, nbrs, nlu))
            if len(nearby_polys) >= 10:
                break

    print(f"\n  半径 ~500m 内的其他地块: {len(nearby_polys)}")
    for idx, nbsm, nlu in nearby_polys:
        if nbsm:
            nid = f"parcel_{nbsm}"
            intouch = nid in [b for a,b in relations.touches] or nid in [a for a,b in relations.touches]
            print(f"    {nbsm:30s} {nlu:10s}  in touches? {intouch}")
