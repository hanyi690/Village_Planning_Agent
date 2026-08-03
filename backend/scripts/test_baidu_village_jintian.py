"""百度地图 API 探测 — 梅州市平远县泗水镇金田村

百度 place/v3/region 支持区县级 region_limit=true, 可绕过 AMap citylimit 失效问题。

用法:
    cd backend
    python -m scripts.test_baidu_village_jintian

输出:
    终端摘要 + backend/scripts/_baidu_probe_jintian.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.modules.data.providers.baidu.provider import BaiduProvider
from app.core.settings import BAIDU_API_KEY
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 真值
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
}

QPS_INTERVAL_S = 0.10  # 百度默认 10 QPS, 留 buffer


def _sleep_qps() -> None:
    time.sleep(QPS_INTERVAL_S)


def _save_json(path: str, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[output] {path}")


def _hit_rate(results: Dict[str, Any], names: List[str]) -> str:
    hit = sum(
        1 for n in names
        if results.get(n, {}).get("hit") or results.get(n, {}).get("count", 0) > 0
    )
    return f"{hit}/{len(names)} ({hit / len(names):.0%})"


def path_search_region_one(
    baidu: BaiduProvider, name: str, region: str,
    region_limit: bool = True, tag: str = None,
) -> Dict[str, Any]:
    """place/v3/region 单个 name 搜索"""
    try:
        r = baidu.search_region(
            query=name, region=region,
            region_limit=region_limit, tag=tag,
            page_size=20,
        )
    except Exception as e:
        return {"query": name, "error": str(e)}

    if not r.success:
        return {"query": name, "error": r.error}

    results = r.data.get("results", [])
    total = r.data.get("total", 0)

    pois = BaiduProvider._parse_pois(results)
    return {
        "query": name,
        "hit": len(pois) > 0,
        "count": len(pois),
        "total": total,
        "all_names": [p["name"] for p in pois],
        "first": pois[0] if pois else None,
        "result_type": r.data.get("result_type", ""),
    }


def path_search_region_batch(
    baidu: BaiduProvider, names: List[str], region: str,
    region_limit: bool = True, tag: str = None,
) -> Dict[str, Any]:
    """批量 place/v3/region"""
    out = {}
    for n in names:
        out[n] = path_search_region_one(
            baidu, n, region, region_limit=region_limit, tag=tag
        )
        _sleep_qps()
    return out


def path_search_city_one(
    baidu: BaiduProvider, name: str, region: str,
    city_limit: bool = True,
) -> Dict[str, Any]:
    """place/v2/search 城市级"""
    try:
        r = baidu.search_city(
            query=name, region=region, city_limit=city_limit,
            page_size=20,
        )
    except Exception as e:
        return {"query": name, "error": str(e)}

    if not r.success:
        return {"query": name, "error": r.error}

    results = r.data.get("results", [])
    pois = BaiduProvider._parse_pois(results)
    return {
        "query": name,
        "hit": len(pois) > 0,
        "count": len(pois),
        "all_names": [p["name"] for p in pois],
        "first": pois[0] if pois else None,
    }


def path_suggestion(
    baidu: BaiduProvider, query: str, region: str,
) -> Dict[str, Any]:
    """place/v2/suggestion 联想"""
    try:
        r = baidu.search_suggestion(query=query, region=region)
    except Exception as e:
        return {"query": query, "error": str(e)}

    if not r.success:
        return {"query": query, "error": r.error}

    results = r.data.get("results", [])
    return {
        "query": query,
        "count": len(results),
        "all_names": [r["name"] for r in results],
        "first_with_loc": next(
            (r for r in results if r.get("lon") and r.get("lat")), None
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="百度 API 探测 (金田村)")
    parser.add_argument("--village", default=DEFAULT_CONFIG["village"])
    parser.add_argument("--township", default=DEFAULT_CONFIG["township"])
    parser.add_argument("--county", default=DEFAULT_CONFIG["county"])
    parser.add_argument("--city", default=DEFAULT_CONFIG["city"])
    parser.add_argument("--province", default=DEFAULT_CONFIG["province"])
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    cfg = {**DEFAULT_CONFIG,
           "village": args.village, "township": args.township,
           "county": args.county, "city": args.city,
           "province": args.province}

    print("=" * 70)
    print(f"百度探测: {cfg['province']}{cfg['city']}{cfg['county']}"
          f"{cfg['township']}{cfg['village']}村")
    print(f"真值: {len(JINTIAN_NATURAL_VILLAGES)} 自然村"
          f" + {len(JINTIAN_NEIGHBORS)} 邻村")
    print(f"QPS: 1/{QPS_INTERVAL_S * 1000:.0f}ms ≈ {1 / QPS_INTERVAL_S:.0f} QPS")
    print("=" * 70)

    if not BAIDU_API_KEY:
        print("BAIDU_API_KEY 未配置, 检查 .env")
        sys.exit(1)

    baidu = BaiduProvider()

    # B1: place/v3/region 自然村 × 12 (区县级 region)
    print("\n[B1] place/v3/region × 12 (region=梅州市平远县, region_limit=true)")
    b1 = path_search_region_batch(
        baidu, JINTIAN_NATURAL_VILLAGES,
        region=f"{cfg['city']}{cfg['county']}",
        region_limit=True,
    )
    print(f"  命中: {_hit_rate(b1, JINTIAN_NATURAL_VILLAGES)}")

    # B2: place/v3/region 邻村 × 4
    print("\n[B2] place/v3/region × 4 邻村")
    b2 = path_search_region_batch(
        baidu, JINTIAN_NEIGHBORS,
        region=f"{cfg['city']}{cfg['county']}",
        region_limit=True,
    )
    print(f"  命中: {_hit_rate(b2, JINTIAN_NEIGHBORS)}")

    # B3: place/v3/region query=村, region=梅州市平远县
    print("\n[B3] place/v3/region query=村 (行政区划级, 含行政村村委会)")
    b3 = path_search_region_one(
        baidu, "村", region=f"{cfg['city']}{cfg['county']}",
        region_limit=True,
    )
    print(f"  count={b3.get('count')}, total={b3.get('total')}, "
          f"sample={b3.get('all_names', [])[:5]}")

    # B4: place/v3/region query=学校
    print("\n[B4] place/v3/region query=学校")
    b4 = path_search_region_one(
        baidu, "学校", region=f"{cfg['city']}{cfg['county']}",
        region_limit=True,
    )
    print(f"  count={b4.get('count')}, sample={b4.get('all_names', [])[:5]}")

    # B5: place/v3/region query=医院
    print("\n[B5] place/v3/region query=医院")
    b5 = path_search_region_one(
        baidu, "医院", region=f"{cfg['city']}{cfg['county']}",
        region_limit=True,
    )
    print(f"  count={b5.get('count')}, sample={b5.get('all_names', [])[:5]}")

    # B6: place/v3/region query=公交站
    print("\n[B6] place/v3/region query=公交站")
    b6 = path_search_region_one(
        baidu, "公交站", region=f"{cfg['city']}{cfg['county']}",
        region_limit=True,
    )
    print(f"  count={b6.get('count')}, sample={b6.get('all_names', [])[:5]}")

    # B7: place/v3/region query=河
    print("\n[B7] place/v3/region query=河")
    b7 = path_search_region_one(
        baidu, "河", region=f"{cfg['city']}{cfg['county']}",
        region_limit=True,
    )
    print(f"  count={b7.get('count')}, sample={b7.get('all_names', [])[:5]}")

    # B8: place/v3/region query=水库
    print("\n[B8] place/v3/region query=水库")
    b8 = path_search_region_one(
        baidu, "水库", region=f"{cfg['city']}{cfg['county']}",
        region_limit=True,
    )
    print(f"  count={b8.get('count')}, sample={b8.get('all_names', [])[:5]}")

    # B9: place/v3/region query=路
    print("\n[B9] place/v3/region query=路")
    b9 = path_search_region_one(
        baidu, "路", region=f"{cfg['city']}{cfg['county']}",
        region_limit=True,
    )
    print(f"  count={b9.get('count')}, sample={b9.get('all_names', [])[:5]}")

    # B10: suggestion × 3 关键字 (无 region_limit, 轻量联想)
    print("\n[B10] place/v2/suggestion × 3")
    b10a = path_suggestion(baidu, "金田", cfg["city"])
    _sleep_qps()
    b10b = path_suggestion(baidu, "泗水", cfg["city"])
    _sleep_qps()
    b10c = path_suggestion(baidu, "平远", cfg["city"])

    # B11: place/v2/search (城市级, 对照 AMap)
    print("\n[B11] place/v2/search × 12 (region=梅州, city_limit=true)")
    b11 = {}
    for n in JINTIAN_NATURAL_VILLAGES:
        b11[n] = path_search_city_one(baidu, n, region=cfg["city"], city_limit=True)
        _sleep_qps()
    print(f"  命中: {_hit_rate(b11, JINTIAN_NATURAL_VILLAGES)}")

    # ===== 摘要 =====
    print("\n" + "=" * 70)
    print("摘要")
    print("=" * 70)
    print(f"B1 v3 region 自然村: {_hit_rate(b1, JINTIAN_NATURAL_VILLAGES)}")
    print(f"B2 v3 region 邻村:   {_hit_rate(b2, JINTIAN_NEIGHBORS)}")
    print(f"B3 v3 region '村'   : count={b3.get('count')}, "
          f"sample={b3.get('all_names', [])[:3]}")
    print(f"B4 学校  : count={b4.get('count')}")
    print(f"B5 医院  : count={b5.get('count')}")
    print(f"B6 公交站: count={b6.get('count')}")
    print(f"B7 河    : count={b7.get('count')}, sample={b7.get('all_names', [])[:3]}")
    print(f"B8 水库  : count={b8.get('count')}, sample={b8.get('all_names', [])[:3]}")
    print(f"B9 路    : count={b9.get('count')}, sample={b9.get('all_names', [])[:3]}")
    print(f"B10 suggestion:")
    print(f"  '金田': count={b10a.get('count')}, sample={b10a.get('all_names', [])[:3]}")
    print(f"  '泗水': count={b10b.get('count')}, sample={b10b.get('all_names', [])[:3]}")
    print(f"  '平远': count={b10c.get('count')}, sample={b10c.get('all_names', [])[:3]}")
    print(f"B11 v2 search 自然村: {_hit_rate(b11, JINTIAN_NATURAL_VILLAGES)}")

    # ===== JSON 输出 =====
    output = {
        "config": cfg,
        "b1_v3_region_natural": b1,
        "b2_v3_region_neighbors": b2,
        "b3_v3_region_village_committee": b3,
        "b4_school": b4,
        "b5_hospital": b5,
        "b6_bus_station": b6,
        "b7_river": b7,
        "b8_reservoir": b8,
        "b9_road": b9,
        "b10a_suggestion_jintian": b10a,
        "b10b_suggestion_sishui": b10b,
        "b10c_suggestion_pingyuan": b10c,
        "b11_v2_search_natural": b11,
    }
    out_path = args.output or str(
        Path(__file__).parent / "_baidu_probe_jintian.json")
    _save_json(out_path, output)


if __name__ == "__main__":
    main()