"""Diagnose spatial issues: empty areas, settlement out of bounds, adjacency quality."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.modules.data import DataCatalog
from app.modules.spatial_ops import build_spatial_index
from app.modules.spatial_ops.geometry import compute_parcel_relations
from shapely.geometry import shape, mapping
from shapely.validation import explain_validity

b = DataCatalog().load_village_bundle("金田村委会")
parcels = b.polygons.landuse_current
roads = b.lines.roads_current
anns = b.points.annotations_current
facils = b.points.facilities_current

# 1. Boundary vs parcel extent
boundary = getattr(b, "boundary", None)
if boundary:
    bgeom = shape(boundary.geometry)
    print("=== Boundary ===")
    print(f"  bounds: {bgeom.bounds}")
    print(f"  area: {bgeom.area:.6f} deg²")

# 2. Parcel extent
all_parcel_geoms = []
for p in parcels:
    g = getattr(p, "geometry", None)
    if g:
        try:
            s = shape(g)
            if not s.is_valid:
                s = s.buffer(0)
            if not s.is_empty:
                all_parcel_geoms.append(s)
        except:
            pass

from shapely.ops import unary_union
parcel_union = unary_union(all_parcel_geoms)
print(f"\n=== Parcel union ===")
print(f"  bounds: {parcel_union.bounds}")
print(f"  area: {parcel_union.area:.6f} deg²")
print(f"  boundary area: {bgeom.area:.6f} deg²")
print(f"  parcel coverage: {parcel_union.area / bgeom.area * 100:.1f}% of boundary")

# 3. Settlements vs boundary
village_anns = [a for a in anns if getattr(a, "category", "") == "村名"]
print(f"\n=== Settlements vs boundary ===")
for a in village_anns:
    pt = shape(a.geometry)
    inside = bgeom.contains(pt)
    print(f"  {a.text}: ({pt.x:.4f}, {pt.y:.4f}) inside_boundary={inside}")

# 4. Empty areas - grid analysis
print(f"\n=== Empty area check (grid) ===")
minx, miny, maxx, maxy = bgeom.bounds
grid_size = 5
cell_w = (maxx - minx) / grid_size
cell_h = (maxy - miny) / grid_size
empty_cells = 0
for i in range(grid_size):
    for j in range(grid_size):
        cell_minx = minx + i * cell_w
        cell_miny = miny + j * cell_h
        cell_maxx = cell_minx + cell_w
        cell_maxy = cell_miny + cell_h
        from shapely.geometry import box
        cell = box(cell_minx, cell_miny, cell_maxx, cell_maxy)
        overlap = parcel_union.intersection(cell).area / cell.area
        if overlap < 0.05:
            empty_cells += 1
            print(f"  Empty cell [{i},{j}]: coverage={overlap*100:.1f}% center=({(cell_minx+cell_maxx)/2:.4f}, {(cell_miny+cell_maxy)/2:.4f})")
print(f"  Total empty cells: {empty_cells}/{grid_size*grid_size}")

# 5. Adjacency quality
print(f"\n=== Adjacency quality ===")
relations = compute_parcel_relations(parcels, roads=roads)
print(f"  touches: {len(relations.touches)}")
print(f"  nearby: {len(relations.nearby)}")
print(f"  connected: {len(relations.connected)}")

# Check: how many touches have very short shared boundary
short_touches = 0
long_touches = 0
for t in relations.touches:
    if t.shared_boundary_length_m < 10:
        short_touches += 1
    else:
        long_touches += 1
print(f"  touches < 10m boundary: {short_touches} (likely false positives)")
print(f"  touches >= 10m boundary: {long_touches}")

# Sample some short touches
print(f"\n  Sample short touches (< 10m):")
count = 0
for t in relations.touches:
    if t.shared_boundary_length_m < 10:
        print(f"    {t.bsm_a[:12]}.. <-> {t.bsm_b[:12]}.. shared={t.shared_boundary_length_m:.2f}m")
        count += 1
        if count >= 5:
            break

# 6. Facilities
print(f"\n=== Facilities ===")
print(f"  facilities_current count: {len(facils)}")
for f in facils[:5]:
    g = getattr(f, "geometry", None)
    print(f"    name={getattr(f,'name','')} type={getattr(f,'facility_type','')} geom={g.get('type') if g else 'None'}")
