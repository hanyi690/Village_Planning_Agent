"""Check if parcels cover the entire village boundary."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.modules.data import DataCatalog
from shapely.geometry import shape, box
from shapely.ops import unary_union

b = DataCatalog().load_village_bundle("金田村委会")
parcels = b.polygons.landuse_current
boundary = shape(b.boundary.geometry)

print("=== Boundary ===")
print(f"  bounds: {boundary.bounds}")
print(f"  area: {boundary.area:.8f} deg² ({boundary.area * 111000 * 111000 * 0.92:.0f} m²)")

# Fix and union all parcels
geoms = []
for p in parcels:
    g = getattr(p, "geometry", None)
    if g:
        try:
            s = shape(g)
            if not s.is_valid:
                s = s.buffer(0)
            if not s.is_empty:
                geoms.append(s)
        except:
            pass

union = unary_union(geoms)
print(f"\n=== Parcel union ===")
print(f"  area: {union.area:.8f} deg²")
print(f"  coverage of boundary: {union.area / boundary.area * 100:.1f}%")

# Difference: what's in boundary but not in parcels
diff = boundary.difference(union)
print(f"\n=== Uncovered area (boundary - parcels) ===")
print(f"  area: {diff.area:.8f} deg² ({diff.area / boundary.area * 100:.1f}% of boundary)")
print(f"  bounds: {diff.bounds}")

# Check if diff is large or just slivers
if diff.area / boundary.area > 0.05:
    print("  >> More than 5% uncovered - significant gaps")

# Grid analysis: which cells have gaps
minx, miny, maxx, maxy = boundary.bounds
grid_n = 10
cell_w = (maxx - minx) / grid_n
cell_h = (maxy - miny) / grid_n

print(f"\n=== {grid_n}x{grid_n} grid coverage ===")
for i in range(grid_n):
    row = []
    for j in range(grid_n):
        cell = box(
            minx + j * cell_w, miny + i * cell_h,
            minx + (j+1) * cell_w, miny + (i+1) * cell_h,
        )
        in_boundary = boundary.intersection(cell).area
        if in_boundary < 0.0001:
            row.append("  ")  # outside boundary
            continue
        in_parcels = union.intersection(cell).area
        pct = in_parcels / in_boundary * 100 if in_boundary > 0 else 0
        if pct > 80:
            row.append("██")
        elif pct > 40:
            row.append("▓▓")
        elif pct > 10:
            row.append("░░")
        elif pct > 0:
            row.append("··")
        else:
            row.append("  ")
    print(f"  {' '.join(row)}")

# Check: are there parcels that extend beyond boundary?
outside = union.difference(boundary)
print(f"\n=== Parcels outside boundary ===")
print(f"  area: {outside.area:.8f} deg² ({outside.area / boundary.area * 100:.1f}%)")

# Check planned landuse - does it have more coverage?
planned = b.polygons.landuse_planned
print(f"\n=== Planned landuse ===")
print(f"  count: {len(planned)}")
if planned:
    planned_geoms = []
    for p in planned:
        g = getattr(p, "geometry", None)
        if g:
            try:
                s = shape(g)
                if not s.is_valid:
                    s = s.buffer(0)
                if not s.is_empty:
                    planned_geoms.append(s)
            except:
                pass
    if planned_geoms:
        planned_union = unary_union(planned_geoms)
        print(f"  area: {planned_union.area:.8f} deg²")
        print(f"  coverage of boundary: {planned_union.area / boundary.area * 100:.1f}%")
