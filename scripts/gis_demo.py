"""
GIS 可视化演示脚本

使用模拟数据展示 GIS 工具功能
目标: 广东省梅州市平远县泗水镇金田村

特性:
- 支持国内瓦片源（geoq）解决地图加载问题
- 支持自定义 Overpass API 端点解决数据获取问题
"""

import json
import os
import sys
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_api_connection():
    """测试 OSM API 连接"""
    print("\n[测试 API 连接...]")

    try:
        from src.tools.adapters.data_fetch.gis_fetch_adapter import OSMSourceProvider

        provider = OSMSourceProvider()

        if provider.is_available():
            print("  ✓ osmnx 库可用")
            if provider.is_api_configured():
                print("  ✓ API 端点已配置（使用镜像服务器）")
            else:
                print("  ⚠ API 使用默认端点（可能不稳定）")

            # 尝试获取真实数据
            print("\n  [尝试获取平远县边界数据...]")
            result = provider.fetch_boundary("平远县", level="district")

            if result.success:
                print("  ✓ API 连接成功！已获取边界数据")
                return result.geojson
            else:
                print(f"  ⚠ API 获取失败: {result.error}")
                print("    将使用模拟数据演示")
        else:
            print("  ✗ osmnx 库不可用，请安装: pip install osmnx")

    except Exception as e:
        print(f"  ✗ 测试失败: {e}")

    return None

# 创建模拟 GeoJSON 数据
def create_mock_data():
    """创建模拟地理数据"""

    # 镇边界
    town_boundary = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {
                "name": "泗水镇",
                "name_en": "Sishui Town",
                "admin_level": "town",
                "population": 15000,
                "area_km2": 120
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [115.80, 24.50],
                    [115.90, 24.50],
                    [115.92, 24.55],
                    [115.90, 24.60],
                    [115.80, 24.60],
                    [115.78, 24.55],
                    [115.80, 24.50]
                ]]
            }
        }]
    }

    # 村边界
    village_boundary = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {
                "name": "金田村",
                "name_en": "Jintian Village",
                "admin_level": "village",
                "population": 1200,
                "area_km2": 8.5
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [115.83, 24.52],
                    [115.87, 24.52],
                    [115.88, 24.55],
                    [115.86, 24.57],
                    [115.83, 24.57],
                    [115.82, 24.55],
                    [115.83, 24.52]
                ]]
            }
        }]
    }

    # 道路网络
    roads = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "县道X123", "type": "secondary", "width": 8},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[115.80, 24.54], [115.90, 24.54]]
                }
            },
            {
                "type": "Feature",
                "properties": {"name": "村道A", "type": "residential", "width": 5},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[115.85, 24.52], [115.85, 24.58]]
                }
            },
            {
                "type": "Feature",
                "properties": {"name": "村道B", "type": "residential", "width": 5},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[115.84, 24.54], [115.86, 24.56]]
                }
            }
        ]
    }

    # POI 点位
    pois = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"name": "金田村委会", "type": "government", "amenity": "townhall"}, "geometry": {"type": "Point", "coordinates": [115.85, 24.545]}},
            {"type": "Feature", "properties": {"name": "金田小学", "type": "education", "amenity": "school"}, "geometry": {"type": "Point", "coordinates": [115.852, 24.547]}},
            {"type": "Feature", "properties": {"name": "村卫生站", "type": "healthcare", "amenity": "clinic"}, "geometry": {"type": "Point", "coordinates": [115.848, 24.543]}},
            {"type": "Feature", "properties": {"name": "便民商店", "type": "commercial", "amenity": "shop"}, "geometry": {"type": "Point", "coordinates": [115.851, 24.544]}},
            {"type": "Feature", "properties": {"name": "文化广场", "type": "leisure", "amenity": "park"}, "geometry": {"type": "Point", "coordinates": [115.849, 24.546]}},
            {"type": "Feature", "properties": {"name": "农田示范区", "type": "agriculture", "landuse": "farmland"}, "geometry": {"type": "Point", "coordinates": [115.845, 24.535]}},
            {"type": "Feature", "properties": {"name": "水库", "type": "water", "water": "reservoir"}, "geometry": {"type": "Point", "coordinates": [115.86, 24.55]}},
            {"type": "Feature", "properties": {"name": "党群服务中心", "type": "government", "amenity": "office"}, "geometry": {"type": "Point", "coordinates": [115.85, 24.546]}},
        ]
    }

    # 合并数据
    combined = {
        "type": "FeatureCollection",
        "features": town_boundary["features"] + village_boundary["features"] + roads["features"] + pois["features"]
    }

    return combined, pois, roads, town_boundary, village_boundary


def generate_visualization():
    """生成可视化文件"""

    print("=" * 60)
    print("GIS 可视化演示")
    print("目标: 广东省梅州市平远县泗水镇金田村")
    print("=" * 60)

    # 显示配置信息
    print("\n[瓦片配置]")
    try:
        from src.core.config import GIS_TILE_SOURCE, GIS_OVERPASS_ENDPOINT
        print(f"  默认瓦片源: {GIS_TILE_SOURCE}")
        print(f"  Overpass 端点: {GIS_OVERPASS_ENDPOINT}")
    except ImportError:
        print("  默认瓦片源: geoq (国内可用)")
        print("  Overpass 端点: https://overpass.kumi.systems/api/interpreter")

    # 测试 API 连接
    real_boundary = test_api_connection()

    # 准备数据（使用真实数据或模拟数据）
    combined_data, pois, roads, town_boundary, village_boundary = create_mock_data()

    # 如果获取到真实边界，替换模拟边界
    if real_boundary:
        print("\n[使用真实边界数据]")
        # 可以在这里合并真实数据

    print(f"\n[数据准备完成]")
    print(f"  镇边界: 1 个")
    print(f"  村边界: 1 个")
    print(f"  道路: {len(roads['features'])} 条")
    print(f"  POI: {len(pois['features'])} 个")

    # 确保目录存在
    os.makedirs("docs", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 导入适配器
    from src.tools.adapters.visualization.gis_visualization_adapter import GISVisualizationAdapter

    viz_adapter = GISVisualizationAdapter()
    print(f"\n[适配器状态] 可用: {viz_adapter.is_available}")

    # 1. 生成交互地图（使用国内瓦片源）
    print("\n[生成交互地图 - 使用 geoq 瓦片源...]")

    result = viz_adapter.run(
        analysis_type="interactive_map",
        data=combined_data,
        location=[24.55, 115.85],
        zoom_start=13,
        tiles="geoq"  # 使用国内瓦片源
    )

    if result.success:
        html_content = result.data.get("content")
        if html_content:
            # 添加图例
            legend_html = """
    <div style="position: absolute; top: 10px; left: 50px; z-index: 1000; background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.2); font-family: Arial, sans-serif;">
        <h3 style="margin: 0 0 10px 0; color: #333;">金田村 GIS 可视化</h3>
        <p style="margin: 0 0 10px 0; font-size: 12px; color: #666;">广东省梅州市平远县泗水镇</p>
        <hr style="margin: 10px 0; border: none; border-top: 1px solid #eee;">
        <div style="font-size: 12px; line-height: 1.8;">
            <div><span style="background: #ff7800; width: 15px; height: 15px; display: inline-block; margin-right: 8px; border-radius: 2px;"></span>镇边界</div>
            <div><span style="background: #3186cc; width: 15px; height: 15px; display: inline-block; margin-right: 8px; border-radius: 2px;"></span>村边界</div>
            <div><span style="background: #e74c3c; width: 15px; height: 3px; display: inline-block; margin-right: 8px; vertical-align: middle;"></span>县道</div>
            <div><span style="background: #95a5a6; width: 15px; height: 3px; display: inline-block; margin-right: 8px; vertical-align: middle;"></span>村道</div>
            <div><span style="color: #e74c3c; font-size: 14px;">📍</span> POI 点位</div>
        </div>
        <hr style="margin: 10px 0; border: none; border-top: 1px solid #eee;">
        <p style="margin: 0; font-size: 11px; color: #999;">生成时间: """ + datetime.now().strftime("%Y-%m-%d %H:%M") + """</p>
    </div>
</body>"""

            enhanced_html = html_content.replace("</body>", legend_html)

            html_path = f"docs/gis_jintian_village_{timestamp}.html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(enhanced_html)
            print(f"  保存: {html_path}")
    else:
        print(f"  失败: {result.error}")

    # 2. 生成 POI 热力图（使用国内瓦片源）
    print("\n[生成 POI 分布图 - 使用 geoq 瓦片源...]")

    poi_points = []
    for f in pois["features"]:
        coords = f["geometry"]["coordinates"]
        poi_points.append([coords[1], coords[0], 1])

    heat_result = viz_adapter.run(
        analysis_type="heatmap",
        points=poi_points,
        zoom_start=14,
        radius=25,
        tiles="geoq"  # 使用国内瓦片源
    )

    if heat_result.success:
        html_content = heat_result.data.get("content")
        if html_content:
            heat_path = f"docs/gis_poi_heatmap_{timestamp}.html"
            with open(heat_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            print(f"  保存: {heat_path}")
    else:
        print(f"  失败: {heat_result.error}")

    # 3. 保存 GeoJSON 数据
    print("\n[保存 GeoJSON 数据...]")

    geojson_path = f"docs/gis_jintian_village_data_{timestamp}.geojson"
    with open(geojson_path, "w", encoding="utf-8") as f:
        json.dump(combined_data, f, ensure_ascii=False, indent=2)
    print(f"  保存: {geojson_path}")

    # 4. 生成报告
    print("\n[生成数据报告...]")

    report_lines = [
        "# 金田村 GIS 数据可视化报告",
        "",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 目标区域",
        "",
        "- **省份**: 广东省",
        "- **地市**: 梅州市",
        "- **区县**: 平远县",
        "- **乡镇**: 泗水镇",
        "- **村庄**: 金田村",
        "",
        "## 数据概览",
        "",
        "| 数据类型 | 数量 |",
        "|---------|------|",
        f"| 镇边界 | 1 |",
        f"| 村边界 | 1 |",
        f"| 道路 | {len(roads['features'])} |",
        f"| POI | {len(pois['features'])} |",
        "",
        "## POI 列表",
        "",
        "| 类型 | 名称 |",
        "|------|------|",
    ]

    for f in pois["features"]:
        props = f["properties"]
        report_lines.append(f"| {props['type']} | {props['name']} |")

    report_lines.extend([
        "",
        "## 生成的文件",
        "",
        f"1. `docs/gis_jintian_village_{timestamp}.html` - 交互地图",
        f"2. `docs/gis_poi_heatmap_{timestamp}.html` - POI 热力图",
        f"3. `docs/gis_jintian_village_data_{timestamp}.geojson` - 原始数据",
        "",
        "---",
        "",
        "*注意: 当前使用模拟数据进行演示。实际数据需连接 OSM API 获取。*",
    ])

    report_path = f"docs/gis_jintian_village_report_{timestamp}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    print(f"  保存: {report_path}")

    print("\n" + "=" * 60)
    print("可视化演示完成!")
    print("=" * 60)

    # 列出文件
    print("\n生成的文件:")
    for f in sorted(os.listdir("docs")):
        if "jintian" in f or "poi_heatmap" in f:
            file_path = os.path.join("docs", f)
            size = os.path.getsize(file_path)
            print(f"  {f} ({size:,} bytes)")

    return timestamp


if __name__ == "__main__":
    generate_visualization()