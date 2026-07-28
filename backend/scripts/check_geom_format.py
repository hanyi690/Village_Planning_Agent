"""Investigate geometry format inconsistency."""
import sys; sys.path.insert(0, 'backend')
from app.modules.data import DataCatalog

catalog = DataCatalog()
bundle = catalog.load_village_bundle('jintian')
lu = bundle.polygons.landuse_current

target_bsm = "441426211000049106"

# Check geometry types across a sample
print("=== 检查几何体格式分布 ===")
dict_geom = 0
shapely_geom = 0
other_geom = 0
for i, p in enumerate(lu):
    g = getattr(p, 'geometry', None) or (p.get('geometry') if isinstance(p, dict) else None)
    if isinstance(g, dict):
        dict_geom += 1
    elif g is not None:
        shapely_geom += 1
    else:
        other_geom += 1
print(f"  GeoJSON dict: {dict_geom}")
print(f"  Shapely/other: {shapely_geom}")
print(f"  None/missing: {other_geom}")

# Show some examples
print("\n=== 格式示例 ===")
for i, p in enumerate(lu[:5]):
    g = getattr(p, 'geometry', None) or (p.get('geometry') if isinstance(p, dict) else None)
    bsm = getattr(p, 'bsm', '')
    print(f"  {bsm}: geom_type={type(g).__name__}, val={str(g)[:80]}")

# Check target
for i, p in enumerate(lu):
    bsm = getattr(p, 'bsm', '')
    if bsm == target_bsm:
        g = getattr(p, 'geometry', None)
        print(f"\n=== 目标地块 {target_bsm} ===")
        print(f"  geometry type: {type(g).__name__}")
        if isinstance(g, dict):
            print(f"  GeoJSON keys: {list(g.keys())}")
            print(f"  GeoJSON type: {g.get('type')}")
            # Check if it has coordinates
            coords = g.get('coordinates', 'N/A')
            if isinstance(coords, list):
                print(f"  coordinates length: {len(coords)}")
                if coords and isinstance(coords[0], list):
                    print(f"  first coord: {coords[0][:2]}")
        break

# Check if touch-capable parcels have a different geometry format
print("\n=== 有 touches 的地块 vs 无 touches 的地块 ===")
# Find a parcel index that has touches (parcel at index 0 is a different water parcel)
p0 = lu[0]
g0 = getattr(p0, 'geometry', None)
print(f"  Parcel[0] ({getattr(p0,'bsm','')}): geometry type={type(g0).__name__}")
if isinstance(g0, dict):
    print(f"    dict keys: {list(g0.keys())}")

# This might be the issue - the compute_parcel_relations function
# Compare with a parcel that definitely has touches
from app.modules.spatial_ops.geometry import compute_parcel_relations
relations = compute_parcel_relations(lu, roads=bundle.lines.roads_current)

touches = list(relations.touches)
if touches:
    # Find a parcel with touches
    touch_bsms = set()
    for t in touches[:50]:
        touch_bsms.add(t.bsm_a)
        touch_bsms.add(t.bsm_b)
    
    # Check geometry of a touch-capable parcel
    for t_bsm in list(touch_bsms)[:3]:
        for p in lu:
            if getattr(p, 'bsm', '') == t_bsm:
                g = getattr(p, 'geometry', None)
                print(f"\n  Touch-capable {t_bsm}: geom type={type(g).__name__}")
                if isinstance(g, dict):
                    print(f"    dict keys: {list(g.keys())}")
                else:
                    print(f"    geom type: {g.geom_type if hasattr(g, 'geom_type') else 'N/A'}")
                break
