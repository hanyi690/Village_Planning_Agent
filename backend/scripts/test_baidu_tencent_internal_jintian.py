"""百度 + 腾讯 内部归属详细探测 — 金田村场景

目标:
  - 详化百度 4 邻村 + 12 自然村的 address/district 字段
  - 详化腾讯 12 自然村 实际本村内坐标
  - 验证防误连逻辑 (point_in_polygon vs address 字段)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.settings import BAIDU_API_KEY, TECENT_MAP_API_KEY
from app.utils.logger import get_logger

logger = get_logger(__name__)

JINTIAN_NATURAL = [
    "田坑", "黄竹", "园寨", "社前", "分水", "清明",
    "塘笃", "长塘", "炉池", "肩丰", "营仔", "新山",
]
JINTIAN_NEIGHBORS = ["八社村", "上举村", "符坑村", "文贵村"]

# 金田村中心 (本地 annotation 已知)
JINTIAN_CENTER = (116.0408, 24.8169)
DISTANCE_THRESHOLD_KM = 5.0


def haversine_km(lon1, lat1, lon2, lat2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def baidu_search_region(query: str, region: str) -> Dict[str, Any]:
    """百度 place/v3/region"""
    if not BAIDU_API_KEY:
        return {"error": "BAIDU_API_KEY 未配置"}
    try:
        resp = requests.get(
            "https://api.map.baidu.com/place/v3/region",
            params={
                "ak": BAIDU_API_KEY,
                "query": query, "region": region,
                "region_limit": "true",
                "coord_type": 1,  # WGS84
                "page_size": 5,
            },
            timeout=10,
        )
    except Exception as e:
        return {"error": str(e)}
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}"}
    data = resp.json()
    if data.get("status") != 0:
        return {"error": data.get("message", "unknown")}
    return {
        "results": data.get("results", []),
        "total": data.get("total", 0),
    }


def baidu_parse_pois(results: List[Dict]) -> List[Dict[str, Any]]:
    """百度 results → 标准化 POI 列表"""
    pois = []
    for r in results:
        loc = r.get("location", {})
        lat = loc.get("lat")
        lng = loc.get("lng")
        if lat is None or lng is None:
            continue
        pois.append({
            "id": r.get("uid", ""),
            "name": r.get("name", ""),
            "lon": float(lng), "lat": float(lat),
            "address": r.get("address", ""),
            "province": r.get("province", ""),
            "city": r.get("city", ""),
            "area": r.get("area", ""),
            "telephone": r.get("telephone", ""),
        })
    return pois


def tencent_search_region(keyword: str, region: str) -> Dict[str, Any]:
    """腾讯 place/v1/search region search"""
    if not TECENT_MAP_API_KEY:
        return {"error": "TECENT_MAP_API_KEY 未配置"}
    boundary = f"region({region},0)"
    try:
        resp = requests.get(
            "https://apis.map.qq.com/ws/place/v1/search",
            params={
                "keyword": keyword, "boundary": boundary,
                "page_size": 5, "page_index": 1,
                "key": TECENT_MAP_API_KEY,
                "coord_type": "wgs84",
            },
            timeout=10,
        )
    except Exception as e:
        return {"error": str(e)}
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}"}
    data = resp.json()
    if data.get("status") != 0:
        return {"error": data.get("message", "unknown")}
    return {
        "results": data.get("data", []),
        "count": data.get("count", 0),
    }


def tencent_parse_pois(results: List[Dict]) -> List[Dict[str, Any]]:
    pois = []
    for r in results:
        loc = r.get("location", {})
        lat = loc.get("lat")
        lng = loc.get("lng")
        if lat is None or lng is None:
            continue
        ad = r.get("ad_info", {})
        pois.append({
            "id": r.get("id", ""),
            "name": r.get("title", ""),
            "lon": float(lng), "lat": float(lat),
            "address": r.get("address", ""),
            "category": r.get("category", ""),
            "type": r.get("type", 0),
            "adcode": ad.get("adcode", ""),
            "province": ad.get("province", ""),
            "city": ad.get("city", ""),
            "district": ad.get("district", ""),
            "distance": r.get("_distance", 0),
        })
    return pois


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    print("=" * 70)
    print(f"百度+腾讯 内部归属详细探测")
    print(f"金田村中心: {JINTIAN_CENTER}, 距离阈值 {DISTANCE_THRESHOLD_KM}km")
    print("=" * 70)

    results: Dict[str, Any] = {
        "baidu_natural_village": {},
        "baidu_neighbor_village": {},
        "tencent_natural_village": {},
        "tencent_neighbor_village": {},
    }

    # ===== 百度: 12 自然村 =====
    print("\n=== 百度 place/v3/region 12 自然村 ===")
    for name in JINTIAN_NATURAL:
        r = baidu_search_region(name, "梅州市平远县")
        pois = baidu_parse_pois(r.get("results", []))
        in_count = 0
        for p in pois:
            dist = haversine_km(JINTIAN_CENTER[0], JINTIAN_CENTER[1],
                                 p["lon"], p["lat"])
            if dist <= DISTANCE_THRESHOLD_KM:
                in_count += 1
        results["baidu_natural_village"][name] = {
            "count": len(pois),
            "in_village": in_count,
            "first_3": pois[:3],
        }
        first = pois[0] if pois else None
        if first:
            dist = haversine_km(JINTIAN_CENTER[0], JINTIAN_CENTER[1],
                                 first["lon"], first["lat"])
            status = "IN" if dist <= DISTANCE_THRESHOLD_KM else "OUT"
            print(f"  {name}: count={len(pois)}, in={in_count}, "
                  f"first='{first['name']}' [{status}] "
                  f"addr='{first['address'][:50]}'")
        else:
            print(f"  {name}: 0 hits")
        time.sleep(0.1)

    # ===== 百度: 4 邻村 =====
    print("\n=== 百度 place/v3/region 4 邻村 ===")
    for name in JINTIAN_NEIGHBORS:
        r = baidu_search_region(name, "梅州市平远县")
        pois = baidu_parse_pois(r.get("results", []))
        in_count = 0
        for p in pois:
            dist = haversine_km(JINTIAN_CENTER[0], JINTIAN_CENTER[1],
                                 p["lon"], p["lat"])
            if dist <= DISTANCE_THRESHOLD_KM:
                in_count += 1
        results["baidu_neighbor_village"][name] = {
            "count": len(pois),
            "in_village": in_count,
            "first_3": pois[:3],
        }
        first = pois[0] if pois else None
        if first:
            dist = haversine_km(JINTIAN_CENTER[0], JINTIAN_CENTER[1],
                                 first["lon"], first["lat"])
            status = "IN" if dist <= DISTANCE_THRESHOLD_KM else "OUT"
            print(f"  {name}: count={len(pois)}, in={in_count}, "
                  f"first='{first['name']}' [{status}] "
                  f"addr='{first['address'][:60]}' area='{first['area']}'")
        time.sleep(0.1)

    # ===== 腾讯: 12 自然村 =====
    print("\n=== 腾讯 place/v1/search 12 自然村 ===")
    for name in JINTIAN_NATURAL:
        r = tencent_search_region(name, "441426")
        pois = tencent_parse_pois(r.get("results", []))
        in_count = 0
        for p in pois:
            dist = haversine_km(JINTIAN_CENTER[0], JINTIAN_CENTER[1],
                                 p["lon"], p["lat"])
            if dist <= DISTANCE_THRESHOLD_KM:
                in_count += 1
        results["tencent_natural_village"][name] = {
            "count": len(pois),
            "in_village": in_count,
            "first_3": pois[:3],
        }
        first = pois[0] if pois else None
        if first:
            dist = haversine_km(JINTIAN_CENTER[0], JINTIAN_CENTER[1],
                                 first["lon"], first["lat"])
            status = "IN" if dist <= DISTANCE_THRESHOLD_KM else "OUT"
            print(f"  {name}: count={len(pois)}, in={in_count}, "
                  f"first='{first['name']}' [{status}] "
                  f"district='{first['district']}'")
        else:
            print(f"  {name}: 0 hits")
        time.sleep(0.1)

    # ===== 腾讯: 4 邻村 =====
    print("\n=== 腾讯 place/v1/search 4 邻村 ===")
    for name in JINTIAN_NEIGHBORS:
        r = tencent_search_region(name, "441426")
        pois = tencent_parse_pois(r.get("results", []))
        in_count = 0
        for p in pois:
            dist = haversine_km(JINTIAN_CENTER[0], JINTIAN_CENTER[1],
                                 p["lon"], p["lat"])
            if dist <= DISTANCE_THRESHOLD_KM:
                in_count += 1
        results["tencent_neighbor_village"][name] = {
            "count": len(pois),
            "in_village": in_count,
            "first_3": pois[:3],
        }
        first = pois[0] if pois else None
        if first:
            dist = haversine_km(JINTIAN_CENTER[0], JINTIAN_CENTER[1],
                                 first["lon"], first["lat"])
            status = "IN" if dist <= DISTANCE_THRESHOLD_KM else "OUT"
            print(f"  {name}: count={len(pois)}, in={in_count}, "
                  f"first='{first['name']}' [{status}] "
                  f"district='{first['district']}'")
        time.sleep(0.1)

    # 摘要
    print("\n" + "=" * 70)
    print("摘要 — IN_VILLAGE 命中数")
    print("=" * 70)
    for src in ("baidu", "tencent"):
        for ttype in ("natural_village", "neighbor_village"):
            data = results[f"{src}_{ttype}"]
            in_count = sum(1 for n, r in data.items() if r.get("in_village", 0) > 0)
            total = len(data)
            label = f"{src}_{ttype}"
            print(f"  {label:<32}: {in_count}/{total} 本村内")

    out_path = args.output or str(
        Path(__file__).parent / "_baidu_tencent_internal.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n[output] {out_path}")


if __name__ == "__main__":
    main()