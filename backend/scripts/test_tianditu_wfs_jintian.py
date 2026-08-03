"""天地图 WFS 探测 — 梅州市平远县泗水镇金田村 bbox

天地图 WFS 提供国家级矢量数据:
  LRRL: 铁路 LineString
  LRDL: 公路 LineString
  HYDA: 水系面 Polygon
  HYDL: 水系线 LineString
  RESA: 居民地面 Polygon
  RESP: 居民地点 Point

用法:
    cd backend
    python -m scripts.test_tianditu_wfs_jintian

输出:
    终端摘要 + backend/scripts/_tianditu_wfs_probe_jintian.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.modules.data.providers.tianditu.wfs import WfsService
from app.core.settings import TIANDITU_API_KEY
from app.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_CONFIG = {
    "province": "广东省",
    "city": "梅州市",
    "county": "平远县",
    "township": "泗水镇",
    "village": "金田",
}

# 金田村近似 bbox (从本地 boundary.geojson 估)
# 中心约 (116.04, 24.82), 半径 ~5km
# bbox = (min_lon, min_lat, max_lon, max_lat)
DEFAULT_BBOX = (116.0, 24.77, 116.10, 24.87)

# 6 个 WFS layer (项目已有)
WFS_LAYERS = [
    ("TDTService:RESP", "居民地点", "Point"),
    ("TDTService:RESA", "居民地面", "Polygon"),
    ("TDTService:HYDA", "水系面", "Polygon"),
    ("TDTService:HYDL", "水系线", "LineString"),
    ("TDTService:LRDL", "公路", "LineString"),
    ("TDTService:LRRL", "铁路", "LineString"),
]


def _save_json(path: str, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[output] {path}")


def fetch_layer(wfs: WfsService, layer_name: str,
                bbox: Tuple[float, float, float, float],
                max_features: int = 500) -> Dict[str, Any]:
    """拉取单个 WFS layer"""
    try:
        r = wfs.get_wfs_data(layer_name, bbox, max_features)
    except Exception as e:
        return {"layer": layer_name, "error": str(e)}

    if not r.success:
        return {"layer": layer_name, "error": r.error}

    geojson = r.data.get("geojson", {})
    features = geojson.get("features", [])

    # 抽样前 5 个 feature 的 properties
    sample = []
    for f in features[:5]:
        sample.append({
            "type": f.get("geometry", {}).get("type", ""),
            "properties": f.get("properties", {}),
        })

    return {
        "layer": layer_name,
        "count": len(features),
        "feature_types": sorted({f.get("geometry", {}).get("type", "") for f in features}),
        "sample_properties": sample,
        "response_type": r.metadata.get("response_type", ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="天地图 WFS 探测 (金田村)")
    parser.add_argument("--bbox", nargs=4, type=float, default=list(DEFAULT_BBOX),
                        metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"))
    parser.add_argument("--max-features", type=int, default=500)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    bbox = tuple(args.bbox)
    print("=" * 70)
    print(f"天地图 WFS 探测")
    print(f"bbox: {bbox}")
    print(f"max_features: {args.max_features}")
    print("=" * 70)

    if not TIANDITU_API_KEY:
        print("TIANDITU_API_KEY 未配置, 检查 .env")
        sys.exit(1)

    wfs = WfsService(api_key=TIANDITU_API_KEY)

    results: Dict[str, Any] = {
        "config": {"bbox": bbox, "max_features": args.max_features},
        "layers": {},
    }

    print("\n[探测 6 个 WFS layer]")
    for layer_name, label, expected_geom in WFS_LAYERS:
        print(f"\n--- {layer_name} ({label}) ---")
        layer_result = fetch_layer(wfs, layer_name, bbox, args.max_features)
        results["layers"][layer_name] = layer_result

        if "error" in layer_result:
            print(f"  ERROR: {layer_result['error']}")
        else:
            print(f"  count={layer_result['count']}")
            print(f"  geometry_types={layer_result['feature_types']}")
            print(f"  sample_props[:2]:")
            for sp in layer_result.get("sample_properties", [])[:2]:
                print(f"    {sp}")

    # ===== 摘要 =====
    print("\n" + "=" * 70)
    print("摘要")
    print("=" * 70)
    for layer_name, label, _ in WFS_LAYERS:
        r = results["layers"][layer_name]
        if "error" in r:
            print(f"  {layer_name:<22}: ERROR - {r['error'][:50]}")
        else:
            print(f"  {layer_name:<22}: count={r['count']}, "
                  f"geom_types={r['feature_types']}")

    # 检查 RESP 中是否含自然村/行政村名
    print("\n--- RESP 名字分析 (是否含 金田/自然村/邻村) ---")
    resp = results["layers"].get("TDTService:RESP", {})
    if "sample_properties" in resp:
        names = [sp["properties"].get("name", "")
                 for sp in resp["sample_properties"]]
        print(f"  sample names: {names}")

    out_path = args.output or str(
        Path(__file__).parent / "_tianditu_wfs_probe_jintian.json")
    _save_json(out_path, results)


if __name__ == "__main__":
    main()