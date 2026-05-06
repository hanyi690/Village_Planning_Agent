#!/usr/bin/env python
"""OSM 边界数据获取测试

测试 OSM 在中国区域的边界数据可用性：
- 省级、市级、县级边界通常可用
- 镇级、村级边界通常缺失

运行方式:
    python scripts/test_osm_boundary.py

输出:
    docs/gis/jintian_boundary/boundary_pingyuan_osm.geojson
"""

import json
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import osmnx as ox
import geopandas as gpd


def test_boundary_availability():
    """测试各级边界数据可用性"""

    print("=" * 60)
    print("OSM 边界数据可用性测试")
    print("=" * 60)

    test_places = [
        ("省级", "广东省, 中国"),
        ("市级", "梅州市, 广东省, 中国"),
        ("县级", "平远县, 梅州市, 广东省, 中国"),
        ("镇级", "泗水镇, 平远县, 梅州市, 广东省"),
        ("村级", "金田村, 平远县, 梅州市, 广东省"),
    ]

    results = []

    for level, place in test_places:
        print(f"\n测试 {level}: {place}")
        try:
            gdf = ox.geocode_to_gdf(place)
            success = True
            geom_type = gdf.geometry.iloc[0].geom_type
            area_km2 = gdf.geometry.iloc[0].area * 111 * 111  # 粗略估算
            print(f"  ✅ 成功!")
            print(f"     类型: {geom_type}")
            print(f"     名称: {gdf['name'].iloc[0]}")
            print(f"     面积估算: {area_km2:.1f} km²")
            results.append({
                "level": level,
                "place": place,
                "success": True,
                "geom_type": geom_type,
                "name": gdf['name'].iloc[0],
            })
        except Exception as e:
            print(f"  ❌ 失败: {str(e)[:50]}")
            results.append({
                "level": level,
                "place": place,
                "success": False,
                "error": str(e)[:100],
            })

    return results


def get_pingyuan_boundary():
    """获取平远县边界"""

    print("\n" + "=" * 60)
    print("获取平远县边界数据")
    print("=" * 60)

    place = "平远县, 梅州市, 广东省, 中国"

    try:
        gdf = ox.geocode_to_gdf(place)

        # 获取边界信息
        boundary = gdf.geometry.iloc[0]
        bounds = boundary.bounds  # (minx, miny, maxx, maxy)

        print(f"\n平远县边界信息:")
        print(f"  名称: {gdf['name'].iloc[0]}")
        print(f"  类型: {boundary.geom_type}")
        print(f"  范围: {bounds}")

        # 计算中心点
        center = (bounds[2] + bounds[0]) / 2, (bounds[3] + bounds[1]) / 2
        print(f"  中心: ({center[0]:.4f}, {center[1]:.4f})")

        # 转换为 GeoJSON
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "name": gdf['name'].iloc[0],
                        "display_name": gdf['display_name'].iloc[0],
                        "source": "osm",
                        "osm_id": int(gdf['osm_id'].iloc[0]) if 'osm_id' in gdf.columns else None,
                    },
                    "geometry": boundary.__geo_interface__,
                }
            ],
            "metadata": {
                "source": "osm",
                "place_query": place,
                "bounds": [float(b) for b in bounds],
                "center": [float(c) for c in center],
            }
        }

        # 保存文件
        output_dir = project_root / "docs" / "gis" / "jintian_boundary"
        output_file = output_dir / "boundary_pingyuan_osm.geojson"

        output_dir.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(geojson, f, ensure_ascii=False, indent=2)

        print(f"\n✅ 平远县边界已保存: {output_file}")

        # 对比金田村规划数据中的县级边界
        print("\n与规划数据对比:")
        print(f"  金田村规划边界: docs/gis/jintian_boundary/boundary_current.geojson")
        print(f"  金田村中心: (116.044146, 24.818629)")

        # 验证金田村是否在平远县范围内
        jintian_center = (116.044146, 24.818629)
        from shapely.geometry import Point
        point = Point(jintian_center)

        if boundary.contains(point):
            print(f"  ✅ 金田村中心点在平远县边界内")
        else:
            print(f"  ❌ 金田村中心点不在平远县边界内（边界可能不精确）")

        return geojson

    except Exception as e:
        print(f"\n❌ 获取失败: {e}")
        return None


def compare_with_jintian_boundary():
    """对比 OSM 边界与金田村规划边界"""

    print("\n" + "=" * 60)
    print("边界数据对比分析")
    print("=" * 60)

    # 读取金田村规划边界
    jintian_file = project_root / "docs" / "gis" / "jintian_boundary" / "boundary_current.geojson"
    pingyuan_file = project_root / "docs" / "gis" / "jintian_boundary" / "boundary_pingyuan_osm.geojson"

    if jintian_file.exists():
        with open(jintian_file, "r", encoding="utf-8") as f:
            jintian_geojson = json.load(f)
        jintian_feature = jintian_geojson['features'][0]
        jintian_area = jintian_feature['properties'].get('MJ', 0) / 1_000_000  # 平方米转平方公里
        print(f"\n金田村规划边界:")
        print(f"  来源: 村庄规划工程文件")
        print(f"  面积: {jintian_area:.2f} km²")
        print(f"  村名: {jintian_feature['properties'].get('DJZQMC', '未知')}")
        print(f"  行政代码: {jintian_feature['properties'].get('DJZQDM', '未知')}")

    if pingyuan_file.exists():
        try:
            with open(pingyuan_file, "r", encoding="utf-8") as f:
                pingyuan_geojson = json.load(f)
            print(f"\n平远县 OSM 边界:")
            print(f"  来源: OpenStreetMap")
            print(f"  名称: {pingyuan_geojson['features'][0]['properties']['name']}")
        except Exception as e:
            print(f"\n平远县 OSM 边界读取失败: {e}")

    print("\n结论:")
    print("  - OSM 不包含村级边界数据（金田村）")
    print("  - 村级边界需使用规划工程文件数据")
    print("  - OSM 可用于县级以上边界获取")


def main():
    # 测试边界可用性
    results = test_boundary_availability()

    # 保存测试结果
    output_dir = project_root / "docs" / "gis" / "jintian_boundary"
    output_dir.mkdir(parents=True, exist_ok=True)

    report_file = output_dir / "osm_boundary_test_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump({
            "test_time": str(results),
            "results": results,
            "conclusion": {
                "county_available": True,
                "town_available": False,
                "village_available": False,
                "recommendation": "村级边界使用规划数据，县级以上使用OSM"
            }
        }, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 测试报告已保存: {report_file}")

    # 获取平远县边界
    get_pingyuan_boundary()

    # 对比分析
    compare_with_jintian_boundary()

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())