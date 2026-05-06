#!/usr/bin/env python
"""金田村道路数据 OSM 获取测试

验证 OSM 数据补充村级道路的效果，对比天地图 WFS 数据。

运行方式:
    python scripts/fetch_jintian_roads_osm.py

输出:
    docs/gis/jintian_boundary/roads_osm.geojson
"""

import json
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.tools.geocoding.osm import OSMProvider, VILLAGE_RELEVANT_HIGHWAYS

# 金田村边界范围（从 metadata.json 提取）
# 中心坐标: (116.044146, 24.818629)
# 边界范围约 3km x 3km
JINTIAN_BBOX = (24.79, 116.01, 24.83, 116.07)  # (south, west, north, east)


def main():
    print("=" * 60)
    print("金田村道路数据 OSM 获取测试")
    print("=" * 60)

    provider = OSMProvider()

    # 检查 OSMnx 是否可用
    if not provider.is_available():
        print("ERROR: osmnx 库未安装")
        print("请运行: pip install osmnx")
        return 1

    print(f"\n边界范围 (bbox):")
    print(f"  South: {JINTIAN_BBOX[0]}")
    print(f"  West:  {JINTIAN_BBOX[1]}")
    print(f"  North: {JINTIAN_BBOX[2]}")
    print(f"  East:  {JINTIAN_BBOX[3]}")

    # 获取道路数据
    print("\n正在获取 OSM 道路数据...")
    result = provider.get_road_network(JINTIAN_BBOX, network_type="drive")

    if not result.success:
        print(f"\nERROR: {result.error}")
        return 1

    print(f"\n✅ 成功获取道路数据")

    # 输出统计信息
    print(f"\n道路总数: {result.total_features}")
    print(f"村级相关道路: {result.highway_stats.get('residential', 0) + result.highway_stats.get('unclassified', 0) + result.highway_stats.get('track', 0)}")

    # 按道路类型统计
    print("\n道路类型分布:")
    highway_stats = result.highway_stats
    sorted_stats = sorted(highway_stats.items(), key=lambda x: -x[1])

    for highway_type, count in sorted_stats:
        is_village_relevant = highway_type in VILLAGE_RELEVANT_HIGHWAYS
        marker = "✓" if is_village_relevant else " "
        desc = HIGHWAY_CLASSES.get(highway_type, highway_type)
        print(f"  [{marker}] {highway_type}: {count}条 ({desc})")

    # 村级道路详情
    print("\n村级道路详情:")
    village_count = 0
    for h in VILLAGE_RELEVANT_HIGHWAYS:
        if h in highway_stats:
            village_count += highway_stats[h]
            print(f"  - {h}: {highway_stats[h]}条")

    print(f"\n村级道路合计: {village_count}条")
    print(f"占总道路比例: {village_count / result.total_features * 100:.1f}%")

    # 对比天地图 WFS
    print("\n与天地图 WFS 对比:")
    print(f"  天地图 WFS: ~1-5条 (仅县级以上道路)")
    print(f"  OSM:        {result.total_features}条 (含村级道路)")
    print(f"  提升:       {result.total_features / 5:.0f}倍以上")

    # 保存结果
    output_dir = project_root / "docs" / "gis" / "jintian_boundary"
    output_file = output_dir / "roads_osm.geojson"

    output_dir.mkdir(parents=True, exist_ok=True)

    if provider.save_geojson(result, str(output_file)):
        print(f"\n✅ GeoJSON 已保存: {output_file}")
    else:
        print(f"\n❌ 保存失败")

    # 保存统计报告
    report_file = output_dir / "roads_osm_report.json"
    report = {
        "test_time": str(result.metadata),
        "bbox": JINTIAN_BBOX,
        "total_features": result.total_features,
        "highway_stats": highway_stats,
        "village_relevant_count": village_count,
        "village_relevant_percentage": round(village_count / result.total_features * 100, 1),
        "comparison": {
            "tianditu_wfs": "1-5条（仅县级以上道路）",
            "osm": f"{result.total_features}条（含村级道路）",
            "improvement_factor": round(result.total_features / 5, 0),
        },
    }

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"✅ 统计报告已保存: {report_file}")

    return 0


# 导入 HIGHWAY_CLASSES 用于输出描述
from src.tools.geocoding.osm.constants import HIGHWAY_CLASSES


if __name__ == "__main__":
    sys.exit(main())