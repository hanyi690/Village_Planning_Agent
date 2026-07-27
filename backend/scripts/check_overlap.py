"""Check for overlapping parcels."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.modules.data import DataCatalog
from shapely.geometry import shape
from shapely.ops import unary_union
from collections import defaultdict

b = DataCatalog().load_village_bundle("金田村委会")
parcels = b.polygons.landuse_current

# Build valid geometries
geoms = []
for p in parcels:
    g = getattr(p, "geometry", None)
    if not g:
        continue
    try:
        s = shape(g)
        if not s.is_valid:
            s = s.buffer(0)
        if not s.is_empty:
            geoms.append((p.bsm, p.dlbm, s))
    except:
        pass

print(f"Total valid parcels: {len(geoms)}")

# Check: union area vs sum of individual areas
sum_area = sum(g.area for _, _, g in geoms)
union = unary_union([g for _, _, g in geoms])
print(f"Sum of individual areas: {sum_area:.10f} deg²")
print(f"Union area:              {union.area:.10f} deg²")
print(f"Overlap ratio:           {(sum_area - union.area) / sum_area * 100:.2f}%")

# Find actual overlapping pairs (sample - checking all pairs is O(n²))
print(f"\n=== Finding overlapping pairs (checking first 200 parcels) ===")
overlap_pairs = []
check_n = min(200, len(geoms))
for i in range(check_n):
    bsm_i, dlbm_i, g_i = geoms[i]
    for j in range(i + 1, check_n):
        bsm_j, dlbm_j, g_j = geoms[j]
        if g_i.intersects(g_j):
            intersection = g_i.intersection(g_j)
            if not intersection.is_empty and intersection.area > 1e-12:
                overlap_area = intersection.area * 111000 * 111000 * 0.92
                if overlap_area > 100:  # > 100 m²
                    overlap_pairs.append((bsm_i, dlbm_j, dlbm_i, dlbm_j, overlap_area))

print(f"Overlapping pairs (>100m²) in first {check_n}: {len(overlap_pairs)}")
for bsm_a, bsm_b, dlbm_a, dlbm_b, area in overlap_pairs[:15]:
    print(f"  {bsm_a[:16]}.. ({dlbm_a}) <-> {bsm_b[:16]}.. ({dlbm_b}) overlap={area:.0f} m²")

# Check if overlaps are same-DLBM (likely duplicate geometry) or cross-DLBM
same_dlbm = sum(1 for _, _, da, db, _ in overlap_pairs if da == db)
cross_dlbm = len(overlap_pairs) - same_dlbm
print(f"\n  Same DLBM overlaps: {same_dlbm} (possible duplicates)")
print(f"  Cross DLBM overlaps: {cross_dlbm} (boundary conflicts)")

# Check for exact duplicate BSMs
bsm_counts = defaultdict(int)
for p in parcels:
    bsm_counts[p.bsm] += 1
dups = {bsm: cnt for bsm, cnt in bsm_counts.items() if cnt > 1}
print(f"\n=== Duplicate BSMs ===")
print(f"  Total unique BSMs: {len(bsm_counts)}")
print(f"  Duplicate BSMs: {len(dups)}")
for bsm, cnt in sorted(dups.items(), key=lambda x: -x[1])[:10]:
    print(f"    {bsm}: {cnt} parcels")
