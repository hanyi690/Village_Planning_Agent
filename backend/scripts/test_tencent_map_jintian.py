"""腾讯地图 API 探测 — 梅州市平远县泗水镇金田村

腾讯 WebService API 端点: https://apis.map.qq.com/ws/place/v1/search
参数格式 (与高德/百度完全不同):
  - keyword: 单关键字 (96字节以内)
  - boundary: 必填, 格式 boundary=region(city_name [,auto_extend] [,lat,lng])
                              或 boundary=nearby(lat,lng,radius[,auto_extend])
                              或 boundary=rectangle(lat1,lng1,lat2,lng2)
  - filter: category=分类1,分类2 (最多5个) 或 category<>排除
  - page_size: 最大 20
  - page_index: 从 1 开始

返回:
  {status: 0, message: "ok", data: [{id,title,address,tel,category,type,
   location{lat,lng},_distance, ad_info{adcode}}, ...]}

注意:
  - 周边搜索 radius 范围: 200-1000米 (我之前用 5000 是错的)
  - location 顺序: lat,lng (我之前用 lon,lat 是错的)
  - type: 0=普通POI/1=公交/2=地铁/3=公交线路/4=行政区划

用法:
    cd backend
    python -m scripts.test_tencent_map_jintian

输出:
    scripts/_tencent_map_probe_jintian.json
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

from app.core.settings import TECENT_MAP_API_KEY
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 端点
SEARCH_URL = "https://apis.map.qq.com/ws/place/v1/search"

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
    "adcode": "441426",  # 平远县 adcode
}

# 泗水镇中心 (从之前 geocode 拿到的: 116.0244, 24.7527)
CENTER_LON, CENTER_LAT = 116.0244, 24.7527

QPS_INTERVAL_S = 0.20  # 腾讯默认 5 QPS, 留 buffer

# POI 分类过滤 (腾讯分类关键词)
FILTER_SCHOOL = "category=中学,小学"
FILTER_HOSPITAL = "category=医院"
FILTER_BUS = "category=公交车站"


def _sleep_qps() -> None:
    time.sleep(QPS_INTERVAL_S)


def _save_json(path: str, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[output] {path}")


def tencent_search(
    keyword: str,
    boundary: str,
    filter_: str = "",
    page_size: int = 20,
    page_index: int = 1,
    extra_params: Optional[Dict] = None,
) -> Dict[str, Any]:
    """调用腾讯 place/v1/search API.

    Args:
        keyword: 单关键字
        boundary: 必填, 格式如 "region(梅州市平远县,0)" 或 "nearby(24.75,116.02,1000)"
        filter_: 可选, 如 "category=中学,小学"
    """
    params = {
        "keyword": keyword,
        "boundary": boundary,
        "page_size": str(page_size),
        "page_index": str(page_index),
        "key": TECENT_MAP_API_KEY,
    }
    if filter_:
        params["filter"] = filter_
    if extra_params:
        params.update(extra_params)

    try:
        resp = requests.get(SEARCH_URL, params=params, timeout=15)
    except Exception as e:
        return {"keyword": keyword, "boundary": boundary, "error": str(e)}

    if resp.status_code != 200:
        return {
            "keyword": keyword, "boundary": boundary,
            "error": f"HTTP {resp.status_code}",
            "raw": resp.text[:200],
        }

    try:
        data = resp.json()
    except Exception as e:
        return {"keyword": keyword, "boundary": boundary,
                "error": f"JSON parse: {e}", "raw": resp.text[:200]}

    if data.get("status") != 0:
        return {
            "keyword": keyword, "boundary": boundary,
            "status": data.get("status"),
            "message": data.get("message"),
            "raw": data,
        }

    pois = data.get("data", [])
    return {
        "keyword": keyword,
        "boundary": boundary,
        "filter": filter_,
        "count": len(pois),
        "total_count": data.get("count", 0),
        "all_names": [p.get("title", "") for p in pois],
        "all_categories": list({p.get("category", "") for p in pois}),
        "first_3": [{
            "id": p.get("id"),
            "title": p.get("title"),
            "address": p.get("address"),
            "category": p.get("category"),
            "type": p.get("type"),
            "location": p.get("location"),
            "_distance": p.get("_distance"),
            "ad_info": p.get("ad_info"),
        } for p in pois[:3]],
    }


def _hit_rate(results: Dict[str, Any], names: List[str]) -> str:
    hit = sum(
        1 for n in names
        if results.get(n, {}).get("count", 0) > 0
    )
    return f"{hit}/{len(names)} ({hit / len(names):.0%})"


def main() -> None:
    parser = argparse.ArgumentParser(description="腾讯 API 探测 (金田村)")
    parser.add_argument("--village", default=DEFAULT_CONFIG["village"])
    parser.add_argument("--township", default=DEFAULT_CONFIG["township"])
    parser.add_argument("--county", default=DEFAULT_CONFIG["county"])
    parser.add_argument("--adcode", default=DEFAULT_CONFIG["adcode"])
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    cfg = {**DEFAULT_CONFIG,
           "village": args.village,
           "township": args.township,
           "county": args.county,
           "adcode": args.adcode}

    # 多种 region 写法
    county_full = f"{cfg['city']}{cfg['county']}"  # "梅州市平远县"
    county_adcode = cfg['adcode']  # "441426"

    print("=" * 70)
    print(f"腾讯地图探测: {cfg['province']}{cfg['city']}{cfg['county']}"
          f"{cfg['township']}{cfg['village']}村")
    print(f"真值: {len(JINTIAN_NATURAL_VILLAGES)} 自然村 + "
          f"{len(JINTIAN_NEIGHBORS)} 邻村")
    print(f"QPS: 1/{QPS_INTERVAL_S * 1000:.0f}ms")
    print("=" * 70)

    if not TECENT_MAP_API_KEY:
        print("TECENT_MAP_API_KEY 未配置")
        sys.exit(1)

    # 第一次测试: 验证 AK
    print("\n[TEST] AK 验证 (边界=region adcode)")
    test = tencent_search(
        keyword="金田",
        boundary=f"region({county_adcode},0)",
    )
    print(f"  status: {test.get('status')}, message: {test.get('message')}")
    print(f"  count: {test.get('count', 0)}")
    if test.get("error"):
        print(f"  ERROR: {test['error']}")
        sys.exit(2)

    results = {"config": cfg, "ak_test": test}

    # T1: 行政村村委会 — 搜 "村" in region
    print("\n[T1] boundary=region 搜 '村' (含行政村村委会)")
    t1 = tencent_search(
        keyword="村",
        boundary=f"region({county_adcode},0)",
        page_size=20,
    )
    results["t1_village_committee"] = t1
    print(f"  count={t1.get('count')}, sample={t1.get('all_names', [])[:5]}")
    _sleep_qps()

    # T2: 学校 (filter=category=中学,小学)
    print("\n[T2] 学校 filter=category=中学,小学")
    t2 = tencent_search(
        keyword="学校",
        boundary=f"region({county_adcode},0)",
        filter_=FILTER_SCHOOL,
    )
    results["t2_school"] = t2
    print(f"  count={t2.get('count')}, sample={t2.get('all_names', [])[:5]}")
    _sleep_qps()

    # T3: 医院
    print("\n[T3] 医院 filter=category=医院")
    t3 = tencent_search(
        keyword="医院",
        boundary=f"region({county_adcode},0)",
        filter_=FILTER_HOSPITAL,
    )
    results["t3_hospital"] = t3
    print(f"  count={t3.get('count')}, sample={t3.get('all_names', [])[:5]}")
    _sleep_qps()

    # T4: 公交站
    print("\n[T4] 公交站 filter=category=公交车站")
    t4 = tencent_search(
        keyword="公交站",
        boundary=f"region({county_adcode},0)",
        filter_=FILTER_BUS,
    )
    results["t4_bus"] = t4
    print(f"  count={t4.get('count')}, sample={t4.get('all_names', [])[:5]}")
    _sleep_qps()

    # T5: 搜本村 "金田"
    print("\n[T5] 搜本村 '金田'")
    t5 = tencent_search(
        keyword="金田",
        boundary=f"region({county_adcode},0)",
        page_size=20,
    )
    results["t5_jintian"] = t5
    print(f"  count={t5.get('count')}, sample={t5.get('all_names', [])[:5]}")
    _sleep_qps()

    # T6: 12 个自然村 × region search
    print(f"\n[T6] 12 个自然村 × region search")
    t6 = {}
    for name in JINTIAN_NATURAL_VILLAGES:
        r = tencent_search(
            keyword=name,
            boundary=f"region({county_adcode},0)",
            page_size=5,
        )
        t6[name] = {
            "count": r.get("count", 0),
            "all_names": r.get("all_names", []),
            "first": (r.get("first_3") or [None])[0],
            "error": r.get("error"),
        }
        _sleep_qps()
    results["t6_natural_village"] = t6
    print(f"  命中: {_hit_rate(t6, JINTIAN_NATURAL_VILLAGES)}")

    # T7: 4 个邻村
    print(f"\n[T7] 4 个邻村 × region search")
    t7 = {}
    for name in JINTIAN_NEIGHBORS:
        r = tencent_search(
            keyword=name,
            boundary=f"region({county_adcode},0)",
            page_size=5,
        )
        t7[name] = {
            "count": r.get("count", 0),
            "all_names": r.get("all_names", []),
            "first": (r.get("first_3") or [None])[0],
        }
        _sleep_qps()
    results["t7_neighbors"] = t7
    print(f"  命中: {_hit_rate(t7, JINTIAN_NEIGHBORS)}")

    # T8: 周边搜索 (radius 1000m, center=泗水镇中心)
    #    注意: lat,lng 顺序 + radius max 1000
    print(f"\n[T8] 周边 1000m 搜 '金田'")
    t8 = tencent_search(
        keyword="金田",
        boundary=f"nearby({CENTER_LAT},{CENTER_LON},1000,1)",
        extra_params={"orderby": "_distance"},
        page_size=20,
    )
    results["t8_nearby_jintian"] = t8
    print(f"  count={t8.get('count')}, sample={t8.get('all_names', [])[:5]}")
    _sleep_qps()

    # T9: 周边 1000m 搜 学校/医院/公交
    print(f"\n[T9] 周边 1000m 搜 学校")
    t9a = tencent_search(
        keyword="学校",
        boundary=f"nearby({CENTER_LAT},{CENTER_LON},1000,1)",
        filter_=FILTER_SCHOOL,
    )
    results["t9a_nearby_school"] = t9a
    print(f"  count={t9a.get('count')}, sample={t9a.get('all_names', [])[:5]}")
    _sleep_qps()

    # T10: 中文 region name (不只用 adcode, 试中文)
    print(f"\n[T10] 用中文 region='{county_full}' 搜 '村'")
    t10 = tencent_search(
        keyword="村",
        boundary=f"region({county_full},0)",
        page_size=20,
    )
    results["t10_chinese_region"] = t10
    print(f"  count={t10.get('count')}, sample={t10.get('all_names', [])[:5]}")

    # ===== 摘要 =====
    print("\n" + "=" * 70)
    print("摘要")
    print("=" * 70)
    print(f"AK test: status={test.get('status')}, msg={test.get('message')}")
    print(f"T1 行政村 '村' (adcode): count={t1.get('count')}")
    print(f"T2 学校: count={t2.get('count')}")
    print(f"T3 医院: count={t3.get('count')}")
    print(f"T4 公交站: count={t4.get('count')}")
    print(f"T5 搜本村 '金田': count={t5.get('count')}")
    print(f"T6 12 自然村: {_hit_rate(t6, JINTIAN_NATURAL_VILLAGES)}")
    print(f"T7 4 邻村: {_hit_rate(t7, JINTIAN_NEIGHBORS)}")
    print(f"T8 周边 1000m '金田': count={t8.get('count')}")
    print(f"T9a 周边 1000m 学校: count={t9a.get('count')}")
    print(f"T10 中文 region '村': count={t10.get('count')}")

    # 保存
    out_path = args.output or str(
        Path(__file__).parent / "_tencent_map_probe_jintian.json")
    _save_json(out_path, results)


if __name__ == "__main__":
    main()