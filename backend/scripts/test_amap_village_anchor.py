"""高德 API 数据探查 — 梅州市平远县泗水镇金田村

11 条路径覆盖: 自然村锚点 / 邻村归属 / typecode 全扫 / 周边 POI /
逆地理编码 / district API / 路径规划 / 批量关键字。

用法:
    cd backend
    python -m scripts.test_amap_village_anchor
    python -m scripts.test_amap_village_anchor --village 金田 --county 平远 --township 泗水镇

输出:
    终端摘要 + backend/scripts/_amap_probe_jintian.json

约束:
    - QPS 限速 30ms/req (≈33 QPS), 贴近 30 QPS 限额
    - P9 batched keyword 若被拒, 写入 JSON 作为"高德不支持 batched"结论
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.modules.data.providers.amap.provider import AmapProvider
from app.core.settings import AMAP_API_KEY
from app.utils.logger import get_logger

logger = get_logger(__name__)

JINTIAN_NATURAL_VILLAGES = [
    "田坑", "黄竹", "园寨", "社前", "分水", "清明",
    "塘笃", "长塘", "炉池", "肩丰", "营仔", "新山",
]
JINTIAN_NEIGHBORS = ["八社村", "上举村", "符坑村", "文贵村"]
ALL_NAMES = JINTIAN_NATURAL_VILLAGES + JINTIAN_NEIGHBORS

DEFAULT_CONFIG = {
    "province": "广东省",
    "city": "梅州市",
    "county": "平远县",
    "township": "泗水镇",
    "village": "金田",
    "adcode": "441426",
}

QPS_INTERVAL_S = 0.030


def _sleep_qps() -> None:
    time.sleep(QPS_INTERVAL_S)


def _save_json(path: str, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[output] {path}")


def _hit_rate(results: Dict[str, Any], names: List[str]) -> str:
    hit = sum(
        1 for n in names
        if results.get(n, {}).get("hit") or results.get(n, {}).get("level")
    )
    return f"{hit}/{len(names)} ({hit / len(names):.0%})"


def path_keyword(amap: AmapProvider, names: List[str],
                 city: str, citylimit: bool, label: str) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    for n in names:
        try:
            r = amap.search_poi_keyword(n, city=city, citylimit=citylimit,
                                        page_size=5)
        except Exception as e:
            results[n] = {"error": str(e)}
            _sleep_qps()
            continue
        if not r.success:
            results[n] = {"error": r.error}
            _sleep_qps()
            continue
        pois = r.data.get("pois", [])
        results[n] = {
            "hit": len(pois) > 0,
            "count": len(pois),
            "all_names": [p["name"] for p in pois],
            "first": pois[0] if pois else None,
            "total": r.metadata.get("total_count"),
        }
        _sleep_qps()
    print(f"  [{label}] 命中 {_hit_rate(results, names)}")
    return results


def path_geocode(amap: AmapProvider, names: List[str],
                 cfg: Dict[str, str], label: str) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    for n in names:
        addr = f"{cfg['province']}{cfg['city']}{cfg['county']}{cfg['township']}{n}"
        try:
            r = amap.geocode(addr, city=cfg["county"])
        except Exception as e:
            results[n] = {"error": str(e)}
            _sleep_qps()
            continue
        if not r.success:
            results[n] = {"error": r.error}
            _sleep_qps()
            continue
        d = r.data
        results[n] = {
            "hit": d.get("lon", 0) != 0,
            "level": d.get("level", ""),
            "formatted_address": d.get("formatted_address", ""),
            "lon": d.get("lon"),
            "lat": d.get("lat"),
            "adcode": d.get("adcode", ""),
        }
        _sleep_qps()
    print(f"  [{label}] 命中 {_hit_rate(results, names)}")
    return results


def path_typecode(amap: AmapProvider, type_codes: List[str],
                  center: tuple, radius: int = 8000) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    for tc in type_codes:
        try:
            r = amap.search_poi_by_types(tc, center, radius, page_size=25)
        except Exception as e:
            results[tc] = {"error": str(e)}
            _sleep_qps()
            continue
        if not r.success:
            results[tc] = {"error": r.error}
            _sleep_qps()
            continue
        pois = r.data.get("pois", [])
        results[tc] = {
            "count": len(pois),
            "total": r.metadata.get("total_count"),
            "all_names": [p["name"] for p in pois],
            "typecodes_seen": sorted({p.get("typecode") for p in pois}),
            "first": pois[0] if pois else None,
        }
        _sleep_qps()
    return results


def path_nearby(amap: AmapProvider, keyword: str,
                center: tuple, radius: int = 8000) -> Dict[str, Any]:
    try:
        r = amap.search_poi_nearby(keyword, center, radius, page_size=25)
    except Exception as e:
        return {"error": str(e)}
    if not r.success:
        return {"error": r.error}
    pois = r.data.get("pois", [])
    return {
        "count": len(pois),
        "total": r.metadata.get("total_count"),
        "all_names": [p["name"] for p in pois],
        "typecodes_seen": sorted({p.get("typecode") for p in pois}),
        "village_match": [p["name"] for p in pois
                          if any(v in p["name"] for v in JINTIAN_NATURAL_VILLAGES)],
        "first_5": [{
            "name": p["name"],
            "address": p["address"],
            "typecode": p["typecode"],
            "distance": p.get("distance"),
        } for p in pois[:5]],
    }


def path_reverse(amap: AmapProvider, lonlat: Dict[str, tuple],
                 names: List[str]) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    for n in names:
        ll = lonlat.get(n)
        if not ll or ll[0] == 0:
            results[n] = {"skip": "no coords"}
            continue
        try:
            r = amap.reverse_geocode(ll[0], ll[1])
        except Exception as e:
            results[n] = {"error": str(e)}
            _sleep_qps()
            continue
        if not r.success:
            results[n] = {"error": r.error}
            _sleep_qps()
            continue
        d = r.data
        fmt = d.get("formatted_address", "") or ""
        results[n] = {
            "towncode": d.get("towncode", ""),
            "street": d.get("street", ""),
            "number": d.get("number", ""),
            "formatted_address": fmt,
            "adcode": d.get("adcode", ""),
            "is_internal": ("金田" in fmt),
        }
        _sleep_qps()
    return results


def path_district(amap: AmapProvider, keyword: str,
                  subdistrict: int, label: str) -> Dict[str, Any]:
    try:
        r = amap.get_district(keyword, subdistrict=subdistrict, extensions="base")
    except Exception as e:
        return {"error": str(e)}
    if not r.success:
        return {"error": r.error}
    d = r.data
    main = d.get("district", {})
    subs = main.get("districts") or []
    return {
        "label": label,
        "name": main.get("name"),
        "adcode": main.get("adcode"),
        "level": main.get("level"),
        "sub_count": len(subs),
        "sub_names": [s.get("name") for s in subs],
        "sub_levels": sorted({s.get("level") for s in subs if s.get("level")}),
    }


def path_routing(amap: AmapProvider, center: tuple,
                 radius_km: float = 5.0) -> List[Dict[str, Any]]:
    rd = radius_km / 111.0
    rd_lon = rd / math.cos(math.radians(center[1]))
    grid = [
        (center[0] - rd_lon, center[1] - rd),
        (center[0] + rd_lon, center[1] - rd),
        (center[0] + rd_lon, center[1] + rd),
        (center[0] - rd_lon, center[1] + rd),
    ]
    pairs = [(grid[0], grid[2]), (grid[0], grid[3]), (grid[1], grid[3])]
    results: List[Dict[str, Any]] = []
    for i, (o, d) in enumerate(pairs):
        try:
            r = amap.plan_route_driving(o, d)
        except Exception as e:
            results.append({"route_id": i, "error": str(e)})
            _sleep_qps()
            continue
        if not r.success:
            results.append({"route_id": i, "error": r.error})
            _sleep_qps()
            continue
        coords = r.data["geojson"]["features"][0]["geometry"]["coordinates"]
        results.append({
            "route_id": i,
            "distance_m": r.data["route"]["distance"],
            "duration_s": r.data["route"]["duration"],
            "coord_count": len(coords),
            "first_coord": coords[0] if coords else None,
            "last_coord": coords[-1] if coords else None,
        })
        _sleep_qps()
    return results


def path_batched(amap: AmapProvider, names: List[str],
                 city: str) -> Dict[str, Any]:
    """P9: 单次 keyword 调用, 传入 pipe-separated names.
    高德文档称 keywords 只支持一个关键字; 若返回 0 或拒绝, 写入结论.
    """
    kw = "|".join(names)
    try:
        r = amap.search_poi_keyword(kw, city=city, citylimit=True, page_size=25)
    except Exception as e:
        return {"kw": kw, "error": str(e),
                "conclusion": "高德不支持 batched keyword (exception)"}
    if not r.success:
        return {"kw": kw, "error": r.error,
                "conclusion": f"高德不支持 batched keyword ({r.error})"}
    pois = r.data.get("pois", [])
    return {
        "kw": kw,
        "count": len(pois),
        "all_names": [p["name"] for p in pois],
        "matched_known": [p["name"] for p in pois
                          if any(v in p["name"] for v in names)],
        "conclusion": ("batch 命中 (高德允许 pipe-separated)"
                       if pois else "高德不支持 batched keyword (0 结果)"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="AMap 数据探查 (金田村)")
    parser.add_argument("--village", default=DEFAULT_CONFIG["village"])
    parser.add_argument("--township", default=DEFAULT_CONFIG["township"])
    parser.add_argument("--county", default=DEFAULT_CONFIG["county"])
    parser.add_argument("--adcode", default=DEFAULT_CONFIG["adcode"])
    parser.add_argument("--output", default=None)
    parser.add_argument("--radius-m", type=int, default=8000,
                        help="周边搜索半径 (米)")
    args = parser.parse_args()

    cfg = {**DEFAULT_CONFIG,
           "village": args.village,
           "township": args.township,
           "county": args.county,
           "adcode": args.adcode,
           "radius_m": args.radius_m}

    print("=" * 70)
    print(f"探查: {cfg['province']}{cfg['city']}{cfg['county']}"
          f"{cfg['township']}{cfg['village']}村")
    print(f"真值: {len(JINTIAN_NATURAL_VILLAGES)} 自然村"
          f" + {len(JINTIAN_NEIGHBORS)} 邻村")
    print(f"QPS: 1/{QPS_INTERVAL_S * 1000:.0f}ms ≈ {1 / QPS_INTERVAL_S:.0f} QPS")
    print("=" * 70)

    if not AMAP_API_KEY:
        print("AMAP_API_KEY 未配置, 检查 .env")
        sys.exit(1)

    amap = AmapProvider()

    print("\n[Step 0] geocode 泗水镇 → 拿中心点")
    geo = amap.geocode(
        f"{cfg['province']}{cfg['city']}{cfg['county']}{cfg['township']}",
        city=cfg["county"],
    )
    _sleep_qps()
    if not geo.success:
        print(f"geocode 失败: {geo.error}")
        sys.exit(2)
    center = (geo.data["lon"], geo.data["lat"])
    print(f"  中心: ({center[0]:.4f}, {center[1]:.4f}) level={geo.data.get('level')}")
    print(f"  formatted_address: {geo.data.get('formatted_address')}")
    print(f"  adcode: {geo.data.get('adcode')}")

    print("\n[P1] search_poi_keyword × 12 (city='平远县', citylimit=True)")
    p1 = path_keyword(amap, JINTIAN_NATURAL_VILLAGES, cfg["county"], True, "P1")

    print("\n[P2] search_poi_keyword × 12 (city='441426', citylimit=True)")
    p2 = path_keyword(amap, JINTIAN_NATURAL_VILLAGES, cfg["adcode"], True, "P2")

    print("\n[P3] geocode(完整地址) × 12")
    p3 = path_geocode(amap, JINTIAN_NATURAL_VILLAGES, cfg, "P3")

    print("\n[P3b] geocode(完整地址) × 4 (邻村)")
    p3b = path_geocode(amap, JINTIAN_NEIGHBORS, cfg, "P3b")

    print("\n[P4] typecode 全扫 × 8")
    p4 = path_typecode(
        amap,
        ["190100", "190106", "180000", "190000",
         "141200", "090100", "150700", "150900"],
        center,
        radius=cfg["radius_m"],
    )

    print("\n[P5a-d] 周边 POI")
    p5a = path_nearby(amap, "村", center, radius=cfg["radius_m"])
    _sleep_qps()
    p5b = path_nearby(amap, "路", center, radius=cfg["radius_m"])
    _sleep_qps()
    p5c = path_nearby(amap, "河", center, radius=cfg["radius_m"])
    _sleep_qps()
    p5d = path_nearby(amap, "桥", center, radius=cfg["radius_m"])

    print("\n[P6] reverse_geocode × 16")
    lonlat: Dict[str, tuple] = {}
    for src in (p3, p3b):
        for n, r in src.items():
            if r.get("lon") and r.get("lat"):
                lonlat[n] = (r["lon"], r["lat"])
    p6 = path_reverse(amap, lonlat, ALL_NAMES)

    print("\n[P7] district API")
    p7a = path_district(amap, cfg["county"], 3, "平远县-sub3")
    _sleep_qps()
    p7b = path_district(amap, cfg["city"], 2, "梅州市-sub2")

    print("\n[P8] 路径规划 × 3")
    p8 = path_routing(amap, center)

    print("\n[P9] batched keyword (单次尝试)")
    p9 = path_batched(amap, JINTIAN_NATURAL_VILLAGES, cfg["county"])

    # ===== 摘要 =====
    print("\n" + "=" * 70)
    print("摘要")
    print("=" * 70)
    print(f"P1  keyword + citylimit : {_hit_rate(p1, JINTIAN_NATURAL_VILLAGES)}")
    print(f"P2  keyword + adcode    : {_hit_rate(p2, JINTIAN_NATURAL_VILLAGES)}")
    print(f"P3  full geocode        : {_hit_rate(p3, JINTIAN_NATURAL_VILLAGES)}")
    print(f"P3b 邻村 geocode        : {_hit_rate(p3b, JINTIAN_NEIGHBORS)}")
    print(f"P9  batched keyword     : count={p9.get('count', 0)} "
          f"matched={len(p9.get('matched_known', []))}")
    print(f"    conclusion: {p9.get('conclusion')}")

    print("\nP4 typecode 计数:")
    for tc, r in p4.items():
        print(f"  {tc}: count={r.get('count', 0)} "
              f"names_sample={r.get('all_names', [])[:3]}")

    print("\nP5 周边 POI:")
    p5_map = {"村": p5a, "路": p5b, "河": p5c, "桥": p5d}
    for k in ("村", "路", "河", "桥"):
        r = p5_map[k]
        names = r.get("all_names", [])[:3]
        print(f"  '{k}': count={r.get('count', 0)} typecodes={r.get('typecodes_seen', [])[:3]} "
              f"sample={names}")

    internal = sum(1 for r in p6.values() if r.get("is_internal"))
    print(f"\nP6 reverse: internal={internal} external={len(p6) - internal}")

    print(f"\nP7 district: {cfg['county']} sub={p7a.get('sub_count', 0)} "
          f"({cfg['city']} sub={p7b.get('sub_count', 0)})")

    total_dist = sum(r.get("distance_m", 0) or 0 for r in p8)
    print(f"\nP8 routing: {len(p8)} 条路线, 总距离={total_dist / 1000:.1f}km")

    # ===== JSON 输出 =====
    output = {
        "config": cfg,
        "center": {"lon": center[0], "lat": center[1],
                   "level": geo.data.get("level"),
                   "formatted_address": geo.data.get("formatted_address"),
                   "adcode": geo.data.get("adcode")},
        "p1": p1,
        "p2": p2,
        "p3": p3,
        "p3b": p3b,
        "p4_typecodes": p4,
        "p5a_village": p5a,
        "p5b_road": p5b,
        "p5c_river": p5c,
        "p5d_bridge": p5d,
        "p6_reverse_geocode": p6,
        "p7a_county_sub3": p7a,
        "p7b_city_sub2": p7b,
        "p8_routing": p8,
        "p9_batched": p9,
    }
    out_path = args.output or str(
        Path(__file__).parent / "_amap_probe_jintian.json")
    _save_json(out_path, output)


if __name__ == "__main__":
    main()