"""Check which parcels are missing and DLBM color mapping issues."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.modules.data import DataCatalog
from shapely.geometry import shape, mapping
from collections import Counter

b = DataCatalog().load_village_bundle("金田村委会")
parcels = b.polygons.landuse_current

# 1. DLBM distribution
dlbm_counter = Counter()
for p in parcels:
    dlbm_counter[p.dlbm] += 1
print("=== DLBM distribution ===")
for code, count in dlbm_counter.most_common():
    print(f"  {code}: {count}")

# 2. Check which parcels fail _fix_and_serialize_geom
from scripts.render_kg_layers import _fix_and_serialize_geom
failed = []
ok = 0
for p in parcels:
    geom = getattr(p, "geometry", None)
    if not geom:
        failed.append((p.bsm, p.dlbm, "no geometry"))
        continue
    fixed = _fix_and_serialize_geom(geom)
    if fixed is None:
        failed.append((p.bsm, p.dlbm, "fix returned None"))
    else:
        ok += 1
print(f"\n=== Geometry fix check ===")
print(f"  OK: {ok}/{len(parcels)}")
print(f"  Failed: {len(failed)}")
for bsm, dlbm, reason in failed:
    print(f"    BSM={bsm} DLBM={dlbm} reason={reason}")

# 3. Check DLBM color mapping
DLBM_COLORS = {
    "1100": "#95d5b2",  # 耕地
    "1200": "#b7e4c7",  # 园地
    "1340": "#52b788",  # 商品林
    "1400": "#d8f3dc",  # 草地
    "1510": "#d8f3dc",  # 设施农用地
    "2121": "#ffd166",  # 宅基地
    "2122": "#ffa45c",  # 公共服务
    "2123": "#f4845f",  # 基础设施
    "2124": "#e85d75",  # 经营性
    "2125": "#a8dadc",  # 景观绿化
    "2126": "#adb5bd",  # 村内交通
    "2270": "#457b9d",  # 水利设施
    "3100": "#4ea8de",  # 水域
}
print("\n=== DLBM -> color mapping ===")
for code, count in dlbm_counter.most_common():
    color = DLBM_COLORS.get(code, "#e9ecef (DEFAULT)")
    print(f"  {code} ({count} parcels) -> {color}")

# 4. Check what 3100 (水域) parcels look like
print("\n=== 3100 (水域) parcels ===")
water_parcel = None
for p in parcels:
    if p.dlbm == "3100":
        g = shape(p.geometry)
        if not g.is_valid:
            g = g.buffer(0)
        print(f"  BSM={p.bsm} area={g.area:.8f} deg² ({g.area*111000*111000*0.92:.0f} m²)")
        if g.area > 0.0001:
            water_parcel = p
            print(f"    >> LARGE water parcel! bounds={g.bounds}")

# 5. Check the DLBM_TO_DLMC names
from app.modules.schema.encodings.code_sets import DLBM_TO_DLMC
print("\n=== DLBM names ===")
for code in sorted(dlbm_counter.keys()):
    name = DLBM_TO_DLMC.get(code, "UNKNOWN")
    print(f"  {code} -> {name}")
