"""OSM Overpass API 探测 — 梅州市平远县泗水镇金田村 bbox

OSM 中国乡村覆盖稀疏, 需实测验证能拿到什么数据.
overpass-api.de 国内访问慢, 优先用镜像.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.logger import get_logger

logger = get_logger(__name__)

# 探测金田 bbox — Overpass 格式: south,west,north,east
BBOX = "24.77,116.00,24.87,116.10"

# Overpass 镜像 (优先国内镜像)
OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]

QUERIES: Dict[str, str] = {
    "villages_bbox": """
[out:json][timeout:25];
node["place"="village"]({bbox});
out center;
""",

    "amenities_nodes": """
[out:json][timeout:25];
node["amenity"~"school|hospital|clinic|pharmacy|bank|post_office|bus_station|police"]({bbox});
out center;
""",

    "admin_boundary_township": """
[out:json][timeout:25];
relation["boundary"="administrative"]["admin_level"="8"]({bbox});
out center;
""",

    "admin_boundary_village": """
[out:json][timeout:25];
relation["boundary"="administrative"]["admin_level"="10"]({bbox});
out center;
""",

    "roads_bbox": """
[out:json][timeout:25];
way["highway"~"residential|unclassified|tertiary|secondary|primary"]({bbox});
out center;
""",

    "natural_water": """
[out:json][timeout:25];
way["natural"="water"]({bbox});
out center;
""",

    "any_named_node": """
[out:json][timeout:25];
node["name"]({bbox});
out center;
""",
}


def query_overpass(query: str, url: str, timeout: int = 60) -> Dict[str, Any]:
    """POST Overpass QL to endpoint."""
    try:
        # Overpass requires form-encoded 'data' parameter
        resp = requests.post(
            url,
            data={"data": query.strip()},
            headers={
                "User-Agent": "VillagePlanningAgent/1.0",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=timeout,
        )
    except Exception as e:
        return {"error": str(e), "url": url}

    if resp.status_code != 200:
        return {
            "error": f"HTTP {resp.status_code}",
            "url": url,
            "raw": resp.text[:500],
        }

    try:
        return {"data": resp.json(), "url": url}
    except Exception as e:
        return {"error": f"JSON parse: {e}", "url": url, "raw": resp.text[:500]}


def extract_pois(elements: List[Dict]) -> List[Dict[str, Any]]:
    """Extract POI-like summaries from OSM elements."""
    pois = []
    for e in elements:
        tags = e.get("tags", {})
        lat = e.get("lat") or e.get("center", {}).get("lat")
        lon = e.get("lon") or e.get("center", {}).get("lon")
        if lat is None or lon is None:
            continue
        pois.append({
            "id": e.get("id"),
            "type": e.get("type"),
            "name": tags.get("name", ""),
            "name_zh": tags.get("name:zh", ""),
            "lat": lat,
            "lon": lon,
            "tags": {k: v for k, v in tags.items()
                     if k in ("place", "amenity", "highway", "natural",
                              "admin_level", "boundary", "name:en")},
        })
    return pois


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bbox", default=BBOX)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    print("=" * 70)
    print(f"OSM Overpass 探测 — bbox={args.bbox}")
    print(f"尝试镜像: {len(OVERPASS_URLS)} 个")
    print("=" * 70)

    results: Dict[str, Any] = {
        "config": {"bbox": args.bbox, "urls": OVERPASS_URLS},
        "queries": {},
    }

    # 1. 探测哪个 URL 通
    print("\n[URL 健康检查] (timeout=30s)")
    working_urls = []
    for url in OVERPASS_URLS:
        # bbox: south,west,north,east
        test_q = "[out:json];node(24.81,116.04,24.82,116.05);out;"
        r = query_overpass(test_q, url, timeout=30)
        if "data" in r:
            print(f"  ✓ {url} 通 (response OK)")
            working_urls.append(url)
        else:
            err = r.get('error', 'unknown')[:120]
            print(f"  ✗ {url} 失败: {err}")
        time.sleep(2)

    if not working_urls:
        print("\n[FAIL] 所有 Overpass 镜像都不可达")
        results["working_urls"] = []
        out_path = args.output or str(
            Path(__file__).parent / "_osm_probe_jintian.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n[output] {out_path}")
        return

    # 选最快的 URL
    best_url = working_urls[0]
    print(f"\n使用 URL: {best_url}")

    # 2. 跑所有查询
    for qname, qtext in QUERIES.items():
        print(f"\n[{qname}]")
        full_q = qtext.format(bbox=args.bbox)
        r = query_overpass(full_q, best_url, timeout=60)

        if "data" not in r:
            print(f"  ERROR: {r.get('error', 'unknown')[:100]}")
            results["queries"][qname] = {"error": r.get("error", "unknown")}
            time.sleep(2)
            continue

        data = r["data"]
        elements = data.get("elements", [])
        pois = extract_pois(elements)
        results["queries"][qname] = {
            "url": best_url,
            "element_count": len(elements),
            "poi_count": len(pois),
            "sample_pois": pois[:5],
            "all_names": [p["name"] for p in pois if p["name"]],
            "tag_distribution": data.get("elements", []) and
                _count_tags(elements),
        }
        print(f"  element_count={len(elements)}, poi_count={len(pois)}")
        if pois:
            print(f"  sample_names: {[p['name'] for p in pois[:5] if p['name']]}")
        time.sleep(2)

    # 摘要
    print("\n" + "=" * 70)
    print("摘要")
    print("=" * 70)
    total = 0
    for qname, qres in results["queries"].items():
        if "error" in qres:
            print(f"  {qname:<32}: ERROR")
            continue
        n = qres.get("poi_count", 0)
        total += n
        print(f"  {qname:<32}: {n} POIs")
    print(f"  {'TOTAL':<32}: {total} POIs")

    out_path = args.output or str(
        Path(__file__).parent / "_osm_probe_jintian.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n[output] {out_path}")


def _count_tags(elements: List[Dict]) -> Dict[str, int]:
    """统计 tag 出现频次."""
    counts: Dict[str, int] = {}
    for e in elements:
        for k in e.get("tags", {}).keys():
            counts[k] = counts.get(k, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1])[:10])


if __name__ == "__main__":
    main()