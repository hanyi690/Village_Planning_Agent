import json, re
with open("F:/project/Village_Planning_Agent/output/kg_visualization/kg_layers.html", "r", encoding="utf-8") as f:
    html = f.read()
m = re.search(r"var DATA = (.+?);", html, re.DOTALL)
if m:
    data = json.loads(m.group(1))
    parcels = data["parcels"]["features"]
    from collections import Counter
    dlbm_count = Counter()
    for f in parcels:
        dlbm = f["properties"].get("dlbm", "?")
        dlbm_count[dlbm] += 1
    print("=== Rendered DLBM distribution ===")
    for dlbm, cnt in dlbm_count.most_common():
        print(f"  {dlbm:6s}: {cnt:4d} features")
    print(f"  Total: {len(parcels)} features")
    water = [f for f in parcels if f["properties"].get("dlbm") == "3100"]
    print(f"\n3100 (water): {len(water)} features")
    for w in water[:5]:
        geom = w["geometry"]
        gtype = geom["type"]
        coords = geom.get("coordinates", [[]])
        if gtype == "Polygon":
            ring0 = coords[0][0] if coords[0] else "?"
        elif gtype == "MultiPolygon":
            ring0 = coords[0][0][0] if coords[0] and coords[0][0] else "?"
        else:
            ring0 = "?"
        print(f"    BSM={w['properties']['bsm']} type={gtype} first_coord={ring0}")
else:
    print("DATA not found in HTML")