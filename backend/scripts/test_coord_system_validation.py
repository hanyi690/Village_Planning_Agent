"""坐标系统一性验证 — 选已知 WGS84 点, 跨 5 provider 查同一位置

目的: 验证各 provider 实际返回坐标与真值偏差
  - AMap: 文档说 v3/place/text 已 GCJ02→WGS84, 验证
  - 百度: coord_type=1 → WGS84, 验证
  - 腾讯: coord_type=wgs84 → WGS84, 验证
  - 天地图: CGCS2000 ≈ WGS84, 验证
  - OSM: WGS84, 验证

真值点: 已知位置 → 跨 provider 查 → 计算 haversine 偏差
  偏差 < 50m → WGS84 正确
  偏差 > 100m → GCJ02/BD09 (需在 pipeline 转换)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.settings import (
    AMAP_API_KEY, BAIDU_API_KEY, TECENT_MAP_API_KEY, TIANDITU_API_KEY,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """两点间球面距离 (米)."""
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def verdict(distance_m: float) -> str:
    if distance_m < 50:
        return "✓ WGS84"
    elif distance_m < 200:
        return "⚠ drift (likely WGS84 with minor offset)"
    else:
        return "✗ NOT_WGS84 (likely GCJ02/BD09)"


# ==================== Test Points ====================

TEST_POINTS: List[Dict[str, Any]] = [
    {
        # 本地 annotation 已知 — 村委会类 (高德/百度最容易收录)
        "name": "金田村委会",
        "true_lon": 116.0408,
        "true_lat": 24.8169,
        "address": "广东省梅州市平远县泗水镇金田村委会",
        "category": "village_committee",
    },
    {
        # 自然村 (腾讯命中)
        "name": "泗水镇",
        "true_lon": 116.0244,
        "true_lat": 24.7527,
        "address": "广东省梅州市平远县泗水镇",
        "category": "township",
    },
    {
        # 邻村 (本地已知)
        "name": "八社村",
        "true_lon": 116.0473,
        "true_lat": 24.8504,
        "address": "广东省梅州市平远县泗水镇八社村",
        "category": "neighbor_village",
    },
]


def test_amap(name: str, address: str) -> List[Dict[str, Any]]:
    """AMap geocode — 默认返回 GCJ02? 实际是?"""
    if not AMAP_API_KEY:
        return [{"provider": "amap", "error": "AMAP_API_KEY 未配置"}]

    url = "https://restapi.amap.com/v3/geocode/geo"
    try:
        resp = requests.get(url, params={
            "key": AMAP_API_KEY, "address": address, "city": "梅州市",
        }, timeout=10)
    except Exception as e:
        return [{"provider": "amap", "error": str(e)}]
    if resp.status_code != 200:
        return [{"provider": "amap", "error": f"HTTP {resp.status_code}"}]
    data = resp.json()
    if data.get("status") != "1":
        return [{"provider": "amap", "error": data.get("info", "unknown")}]
    geocodes = data.get("geocodes", [])
    if not geocodes:
        return [{"provider": "amap", "geocodes": 0}]
    # AMap 内部已 gcj02_to_wgs84, 所以 location 是 WGS84
    return [{
        "provider": "amap",
        "name": geocodes[0].get("formatted_address", ""),
        "lon": float(geocodes[0]["location"].split(",")[0]),
        "lat": float(geocodes[0]["location"].split(",")[1]),
        "level": geocodes[0].get("level", ""),
    }]


def test_baidu(name: str, address: str) -> List[Dict[str, Any]]:
    """百度 geocoding — coord_type=1 应为 WGS84."""
    if not BAIDU_API_KEY:
        return [{"provider": "baidu", "error": "BAIDU_API_KEY 未配置"}]

    url = "https://api.map.baidu.com/geocoding/v3/"
    try:
        resp = requests.get(url, params={
            "ak": BAIDU_API_KEY, "address": address,
            "city": "梅州市", "output": "json",
            "coord_type": 1,   # 强制 WGS84
        }, timeout=10)
    except Exception as e:
        return [{"provider": "baidu", "error": str(e)}]
    if resp.status_code != 200:
        return [{"provider": "baidu", "error": f"HTTP {resp.status_code}"}]
    data = resp.json()
    if data.get("status") != 0:
        return [{"provider": "baidu", "error": data.get("message", "unknown")}]
    result = data.get("result", {})
    if not result.get("location"):
        return [{"provider": "baidu", "geocodes": 0}]
    return [{
        "provider": "baidu",
        "name": result.get("formatted_address", "") or result.get("precise", ""),
        "lon": float(result["location"]["lng"]),
        "lat": float(result["location"]["lat"]),
        "level": result.get("level", ""),
        "confidence": result.get("confidence", ""),
    }]


def test_tencent(name: str, address: str) -> List[Dict[str, Any]]:
    """腾讯 geocoder — coord_type=wgs84 应为 WGS84."""
    if not TECENT_MAP_API_KEY:
        return [{"provider": "tencent", "error": "TECENT_MAP_API_KEY 未配置"}]

    # 改用 place/v1/search (与探测一致)
    url = "https://apis.map.qq.com/ws/place/v1/search"
    boundary = f"region(梅州市平远县,0)"
    try:
        resp = requests.get(url, params={
            "key": TECENT_MAP_API_KEY,
            "keyword": name,
            "boundary": boundary,
            "page_size": 1,
            "coord_type": "wgs84",  # 强制 WGS84
        }, timeout=10)
    except Exception as e:
        return [{"provider": "tencent", "error": str(e)}]
    if resp.status_code != 200:
        return [{"provider": "tencent", "error": f"HTTP {resp.status_code}",
                "raw": resp.text[:200]}]
    data = resp.json()
    if data.get("status") != 0:
        return [{"provider": "tencent", "error": data.get("message", "unknown")}]
    results = data.get("data", [])
    if not results:
        return [{"provider": "tencent", "geocodes": 0}]
    r = results[0]
    loc = r.get("location", {})
    return [{
        "provider": "tencent",
        "name": r.get("title", ""),
        "lon": float(loc.get("lng", 0)),
        "lat": float(loc.get("lat", 0)),
        "address": r.get("address", ""),
    }]


def test_tianditu(name: str, address: str) -> List[Dict[str, Any]]:
    """天地图 geocoder — CGCS2000 ≈ WGS84."""
    if not TIANDITU_API_KEY:
        return [{"provider": "tianditu", "error": "TIANDITU_API_KEY 未配置"}]

    # 天地图 v2 search 接口 (queryType=12)
    url = "https://api.tianditu.gov.cn/v2/search"
    try:
        resp = requests.get(url, params={
            "postStr": json.dumps({
                "keyWord": name, "queryType": 12,
                "start": 0, "count": 1,
                "specify": "156441426",  # 平远县 adcode
            }, ensure_ascii=False),
            "type": "query",
            "tk": TIANDITU_API_KEY,
        }, timeout=10)
    except Exception as e:
        return [{"provider": "tianditu", "error": str(e)}]
    if resp.status_code != 200:
        return [{"provider": "tianditu", "error": f"HTTP {resp.status_code}"}]
    try:
        data = resp.json()
    except Exception as e:
        return [{"provider": "tianditu", "error": f"JSON: {e}"}]
    pois = data.get("pois", [])
    if not pois:
        return [{"provider": "tianditu", "geocodes": 0}]
    p = pois[0]
    lonlat = p.get("lonlat", "0,0").split(",")
    return [{
        "provider": "tianditu",
        "name": p.get("name", ""),
        "lon": float(lonlat[0]),
        "lat": float(lonlat[1]) if len(lonlat) > 1 else 0,
        "address": p.get("address", ""),
        "type_name": p.get("typeName", ""),
    }]


def test_osm_nominatim(name: str, address: str) -> List[Dict[str, Any]]:
    """OSM Nominatim geocoding — WGS84."""
    url = "https://nominatim.openstreetmap.org/search"
    try:
        resp = requests.get(url, params={
            "q": address,
            "format": "json",
            "limit": 1,
            "countrycodes": "cn",
        }, headers={"User-Agent": "VillagePlanningAgent/1.0"},
        timeout=10)
    except Exception as e:
        return [{"provider": "osm", "error": str(e)}]
    if resp.status_code != 200:
        return [{"provider": "osm", "error": f"HTTP {resp.status_code}"}]
    data = resp.json()
    if not data:
        return [{"provider": "osm", "geocodes": 0}]
    p = data[0]
    return [{
        "provider": "osm",
        "name": p.get("display_name", "")[:60],
        "lon": float(p["lon"]),
        "lat": float(p["lat"]),
        "category": p.get("category", ""),
        "type": p.get("type", ""),
    }]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    print("=" * 70)
    print("坐标系一性验证 — 5 provider vs 已知 WGS84 真值")
    print("判定: <50m=WGS84, <200m=drift, >200m=NOT_WGS84")
    print("=" * 70)

    all_results: List[Dict[str, Any]] = []

    for tp in TEST_POINTS:
        name = tp["name"]
        true_lon = tp["true_lon"]
        true_lat = tp["true_lat"]
        addr = tp["address"]
        cat = tp["category"]

        print(f"\n[真值] {name} = ({true_lon}, {true_lat})")
        print(f"  地址: {addr}")
        print(f"  类别: {cat}")

        providers = []
        for test_fn in [test_amap, test_baidu, test_tencent,
                        test_tianditu, test_osm_nominatim]:
            try:
                results = test_fn(name, addr)
            except Exception as e:
                results = [{"provider": test_fn.__name__, "error": str(e)}]
            providers.append({"fn": test_fn.__name__, "results": results})

        for p in providers:
            fn_name = p["fn"]
            for r in p["results"]:
                if "error" in r or "lon" not in r:
                    print(f"  [{r.get('provider', fn_name):<10}] ERROR: {r.get('error', '')[:80]}")
                    continue
                lon, lat = r["lon"], r["lat"]
                dist = haversine_m(true_lon, true_lat, lon, lat)
                v = verdict(dist)
                provider = r.get("provider", fn_name)
                print(f"  [{provider:<10}] ({lat:.5f}, {lon:.5f})  dist={dist:6.1f}m  {v}")
                all_results.append({
                    "true_point": name,
                    "provider": provider,
                    "true_lon": true_lon, "true_lat": true_lat,
                    "got_lon": lon, "got_lat": lat,
                    "distance_m": dist,
                    "verdict": v,
                })

    # 摘要
    print("\n" + "=" * 70)
    print("摘要")
    print("=" * 70)
    by_provider: Dict[str, List[float]] = {}
    for r in all_results:
        by_provider.setdefault(r["provider"], []).append(r["distance_m"])
    for p, dists in sorted(by_provider.items()):
        avg = sum(dists) / len(dists) if dists else 0
        max_d = max(dists) if dists else 0
        print(f"  {p:<10} 平均 {avg:6.1f}m  最大 {max_d:6.1f}m  ({len(dists)} 次)")

    # JSON
    output = {
        "test_points": TEST_POINTS,
        "results": all_results,
        "by_provider": by_provider,
    }
    out_path = args.output or str(
        Path(__file__).parent / "_coord_validation.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n[output] {out_path}")


if __name__ == "__main__":
    main()