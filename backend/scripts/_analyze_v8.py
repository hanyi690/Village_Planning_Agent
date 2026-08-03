import json

with open('scripts/_tencent_map_probe_jintian.json', 'r', encoding='utf-8') as f:
    t = json.load(f)

with open('scripts/_baidu_probe_jintian.json', 'r', encoding='utf-8') as f:
    b = json.load(f)

# 本村中心
JINTIAN_CENTER = (116.0408, 24.8169)  # 从本地 annotation 取的中心
DISTANCE_THRESHOLD_KM = 5.0  # 5km 内认为可能属于本村


def haversine_km(lon1, lat1, lon2, lat2):
    from math import radians, sin, cos, atan2, sqrt
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))


def analyze_source(label, results, names):
    print(f"\n=== {label} ===")
    in_count = 0
    out_count = 0
    for name in names:
        r = results.get(name, {})
        if not r or "first" not in r:
            print(f"  {name}: NO DATA")
            continue
        first = r.get("first") or {}
        # 腾讯 location 是 {lat, lng}
        # 百度 location 是 {lat, lng}
        loc = first.get("location") or {}
        lat = loc.get("lat")
        lng = loc.get("lng")
        if lat is None or lng is None:
            print(f"  {name}: NO LOC (first={first})")
            continue
        dist = haversine_km(JINTIAN_CENTER[0], JINTIAN_CENTER[1], lng, lat)
        status = "IN" if dist <= DISTANCE_THRESHOLD_KM else "OUT"
        if status == "IN":
            in_count += 1
        else:
            out_count += 1
        poi_name = first.get("title") or first.get("name") or ""
        print(f"  {name}: ({lat:.4f},{lng:.4f}) dist={dist:.1f}km [{status}] POI='{poi_name}'")
    print(f"  本村内命中: {in_count}/{len(names)}")


# 腾讯 T6 - 12 自然村
JINTIAN_NATURAL = ["田坑", "黄竹", "园寨", "社前", "分水", "清明",
                     "塘笃", "长塘", "炉池", "肩丰", "营仔", "新山"]
analyze_source("腾讯 T6 - 自然村", t.get("t6_natural_village", {}), JINTIAN_NATURAL)

# 百度 B1 - 12 自然村
analyze_source("百度 B1 v3 region - 自然村", b.get("b1_v3_region_natural", {}), JINTIAN_NATURAL)

# 百度 B11 - v2 search 12 自然村
analyze_source("百度 B11 v2 search - 自然村", b.get("b11_v2_search_natural", {}), JINTIAN_NATURAL)

# 腾讯 T7 - 邻村
JINTIAN_NEIGHBORS = ["八社村", "上举村", "符坑村", "文贵村"]
analyze_source("腾讯 T7 - 邻村", t.get("t7_neighbors", {}), JINTIAN_NEIGHBORS)

# 百度 B2 - 邻村
analyze_source("百度 B2 - 邻村", b.get("b2_v3_region_neighbors", {}), JINTIAN_NEIGHBORS)