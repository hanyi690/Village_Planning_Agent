"""
GIS 功能测试脚本

测试内容：
1. 数据获取测试 (GISDataFetchAdapter)
2. 可视化测试 (GISVisualizationAdapter)
3. 分析测试 (GISAnalysisAdapter)

输出目录: docs/gis
"""

import json
import os
import sys
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUTPUT_DIR = "docs/gis"


def create_mock_geojson():
    """创建模拟 GeoJSON 数据用于测试"""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "name": "泗水镇",
                    "admin_level": "town",
                    "population": 15000,
                    "area_km2": 120
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [115.80, 24.50],
                            [115.90, 24.50],
                            [115.92, 24.55],
                            [115.90, 24.60],
                            [115.80, 24.60],
                            [115.78, 24.55],
                            [115.80, 24.50]
                        ]
                    ]
                }
            },
            {
                "type": "Feature",
                "properties": {
                    "name": "金田村",
                    "admin_level": "village",
                    "population": 1200,
                    "area_km2": 8.5
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [115.83, 24.52],
                            [115.87, 24.52],
                            [115.88, 24.55],
                            [115.86, 24.57],
                            [115.83, 24.57],
                            [115.82, 24.55],
                            [115.83, 24.52]
                        ]
                    ]
                }
            }
        ]
    }


def create_mock_pois():
    """创建模拟 POI 数据"""
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"name": "金田村委会", "type": "government"}, "geometry": {"type": "Point", "coordinates": [115.85, 24.545]}},
            {"type": "Feature", "properties": {"name": "金田小学", "type": "education"}, "geometry": {"type": "Point", "coordinates": [115.852, 24.547]}},
            {"type": "Feature", "properties": {"name": "村卫生站", "type": "healthcare"}, "geometry": {"type": "Point", "coordinates": [115.848, 24.543]}},
            {"type": "Feature", "properties": {"name": "便民商店", "type": "commercial"}, "geometry": {"type": "Point", "coordinates": [115.851, 24.544]}},
            {"type": "Feature", "properties": {"name": "文化广场", "type": "leisure"}, "geometry": {"type": "Point", "coordinates": [115.849, 24.546]}},
            {"type": "Feature", "properties": {"name": "农田示范区", "type": "agriculture"}, "geometry": {"type": "Point", "coordinates": [115.845, 24.535]}},
            {"type": "Feature", "properties": {"name": "水库", "type": "water"}, "geometry": {"type": "Point", "coordinates": [115.86, 24.55]}},
        ]
    }


def create_mock_land_use_data():
    """创建模拟土地利用数据用于分析测试"""
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"land_use_type": "农田", "area": 5.2}, "geometry": {"type": "Polygon", "coordinates": [[[115.83, 24.52], [115.84, 24.52], [115.84, 24.53], [115.83, 24.53], [115.83, 24.52]]]}},
            {"type": "Feature", "properties": {"land_use_type": "林地", "area": 2.1}, "geometry": {"type": "Polygon", "coordinates": [[[115.84, 24.53], [115.85, 24.53], [115.85, 24.54], [115.84, 24.54], [115.84, 24.53]]]}},
            {"type": "Feature", "properties": {"land_use_type": "住宅", "area": 1.5}, "geometry": {"type": "Polygon", "coordinates": [[[115.85, 24.54], [115.86, 24.54], [115.86, 24.55], [115.85, 24.55], [115.85, 24.54]]]}},
            {"type": "Feature", "properties": {"land_use_type": "公共设施", "area": 0.5}, "geometry": {"type": "Polygon", "coordinates": [[[115.85, 24.55], [115.851, 24.55], [115.851, 24.551], [115.85, 24.551], [115.85, 24.55]]]}},
        ]
    }


def test_data_fetch():
    """测试数据获取适配器"""
    print("\n" + "=" * 60)
    print("1. 数据获取测试 (GISDataFetchAdapter)")
    print("=" * 60)

    from src.tools.adapters.data_fetch.gis_fetch_adapter import GISDataFetchAdapter

    adapter = GISDataFetchAdapter()
    # 注意：使用 run() 方法而不是 execute()，run() 会自动处理初始化和依赖检查

    print(f"\n[适配器状态] 可用: {adapter.is_available}")

    results = {}

    # 1.1 行政边界获取
    print("\n[1.1] 获取平远县行政边界...")
    result = adapter.run(
        analysis_type="boundary_fetch",
        location="平远县",
        level="district"
    )

    if result.success:
        geojson = result.data.get("geojson")
        if geojson:
            filepath = os.path.join(OUTPUT_DIR, "gis_boundary_pingyuan.geojson")
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(geojson, f, ensure_ascii=False, indent=2)
            print(f"  保存: {filepath}")
            results["boundary"] = {"success": True, "file": filepath}
        else:
            print("  获取成功但数据为空")
            results["boundary"] = {"success": False, "error": "数据为空"}
    else:
        print(f"  获取失败: {result.error}")
        print("  使用模拟数据替代...")
        mock_boundary = create_mock_geojson()
        filepath = os.path.join(OUTPUT_DIR, "gis_boundary_mock.geojson")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(mock_boundary, f, ensure_ascii=False, indent=2)
        print(f"  保存: {filepath}")
        results["boundary"] = {"success": False, "error": result.error, "mock": filepath}

    # 1.2 道路网络获取
    print("\n[1.2] 获取泗水镇道路网络...")
    result = adapter.run(
        analysis_type="road_fetch",
        location="泗水镇",
        network_type="drive"
    )

    if result.success:
        geojson = result.data.get("geojson")
        if geojson:
            filepath = os.path.join(OUTPUT_DIR, "gis_roads_sishui.geojson")
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(geojson, f, ensure_ascii=False, indent=2)
            print(f"  保存: {filepath}")
            results["roads"] = {"success": True, "file": filepath}
        else:
            print("  获取成功但数据为空")
            results["roads"] = {"success": False, "error": "数据为空"}
    else:
        print(f"  获取失败: {result.error}")
        print("  道路网络获取需要 OSM API 连接，跳过此测试")
        results["roads"] = {"success": False, "error": result.error}

    # 1.3 POI 获取
    print("\n[1.3] 获取教育类 POI...")
    result = adapter.run(
        analysis_type="poi_fetch",
        location="平远县",
        poi_type="education"
    )

    if result.success:
        geojson = result.data.get("geojson")
        if geojson:
            filepath = os.path.join(OUTPUT_DIR, "gis_poi_education.geojson")
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(geojson, f, ensure_ascii=False, indent=2)
            print(f"  保存: {filepath}")
            results["poi"] = {"success": True, "file": filepath}
        else:
            print("  获取成功但数据为空")
            results["poi"] = {"success": False, "error": "数据为空"}
    else:
        print(f"  获取失败: {result.error}")
        print("  使用模拟 POI 数据替代...")
        mock_poi = create_mock_pois()
        filepath = os.path.join(OUTPUT_DIR, "gis_poi_mock.geojson")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(mock_poi, f, ensure_ascii=False, indent=2)
        print(f"  保存: {filepath}")
        results["poi"] = {"success": False, "error": result.error, "mock": filepath}

    return results


def test_visualization():
    """测试可视化适配器"""
    print("\n" + "=" * 60)
    print("2. 可视化测试 (GISVisualizationAdapter)")
    print("=" * 60)

    from src.tools.adapters.visualization.gis_visualization_adapter import GISVisualizationAdapter

    adapter = GISVisualizationAdapter()
    adapter.initialize()

    print(f"\n[适配器状态] 可用: {adapter.is_available}")

    results = {}

    # 准备测试数据
    combined_data = create_mock_geojson()
    pois = create_mock_pois()

    # 合并数据
    combined_data["features"].extend(pois["features"])

    # 2.1 交互式地图
    print("\n[2.1] 生成交互式地图 (使用 geoq 瓦片源)...")
    result = adapter.execute(
        analysis_type="interactive_map",
        data=combined_data,
        location=[24.55, 115.85],
        zoom_start=13,
        tiles="geoq"
    )

    if result.success:
        html_content = result.data.get("content")
        if html_content:
            filepath = os.path.join(OUTPUT_DIR, "gis_interactive_map.html")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html_content)
            print(f"  保存: {filepath}")
            results["interactive_map"] = {"success": True, "file": filepath}
        else:
            print("  生成成功但内容为空")
            results["interactive_map"] = {"success": False, "error": "内容为空"}
    else:
        print(f"  生成失败: {result.error}")
        results["interactive_map"] = {"success": False, "error": result.error}

    # 2.2 热力图
    print("\n[2.2] 生成 POI 热力图...")
    poi_points = []
    for f in pois["features"]:
        coords = f["geometry"]["coordinates"]
        poi_points.append([coords[1], coords[0], 1])

    result = adapter.execute(
        analysis_type="heatmap",
        points=poi_points,
        zoom_start=14,
        radius=25,
        tiles="geoq"
    )

    if result.success:
        html_content = result.data.get("content")
        if html_content:
            filepath = os.path.join(OUTPUT_DIR, "gis_heatmap.html")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html_content)
            print(f"  保存: {filepath}")
            results["heatmap"] = {"success": True, "file": filepath}
        else:
            print("  生成成功但内容为空")
            results["heatmap"] = {"success": False, "error": "内容为空"}
    else:
        print(f"  生成失败: {result.error}")
        results["heatmap"] = {"success": False, "error": result.error}

    # 2.3 智能可视化
    print("\n[2.3] 智能可视化测试...")
    result = adapter.execute(
        analysis_type="smart_visualize",
        data=combined_data,
        location=[24.55, 115.85],
        zoom_start=12,
        tiles="geoq",
        prompt="生成交互地图"
    )

    if result.success:
        html_content = result.data.get("content")
        if html_content:
            filepath = os.path.join(OUTPUT_DIR, "gis_smart_visualize.html")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html_content)
            print(f"  保存: {filepath}")
            results["smart_visualize"] = {"success": True, "file": filepath}
        else:
            print("  生成成功但内容为空")
            results["smart_visualize"] = {"success": False, "error": "内容为空"}
    else:
        print(f"  生成失败: {result.error}")
        results["smart_visualize"] = {"success": False, "error": result.error}

    return results


def test_analysis():
    """测试分析适配器"""
    print("\n" + "=" * 60)
    print("3. 分析测试 (GISAnalysisAdapter)")
    print("=" * 60)

    from src.tools.adapters.analysis.gis_analysis_adapter import GISAnalysisAdapter

    adapter = GISAnalysisAdapter()
    adapter.initialize()

    print(f"\n[适配器状态] 可用: {adapter.is_available}")

    results = {}

    # 创建模拟土地利用数据文件
    land_use_data = create_mock_land_use_data()
    land_use_path = os.path.join(OUTPUT_DIR, "gis_land_use_mock.geojson")
    with open(land_use_path, "w", encoding="utf-8") as f:
        json.dump(land_use_data, f, ensure_ascii=False, indent=2)
    print(f"\n[准备测试数据] {land_use_path}")

    # 3.1 土地利用分析
    print("\n[3.1] 土地利用分析...")
    result = adapter.execute(
        analysis_type="land_use_analysis",
        geo_data_path=land_use_path,
        land_use_column="land_use_type"
    )

    if result.success:
        print(f"  分析成功!")
        print(f"  总面积: {result.data.get('total_area', 0)} km²")
        print(f"  土地类型: {len(result.data.get('land_use_types', []))} 种")
        results["land_use"] = {"success": True, "data": result.data}
    else:
        print(f"  分析失败: {result.error}")
        results["land_use"] = {"success": False, "error": result.error}

    # 3.2 Schema 检查
    print("\n[3.2] Schema 检查...")
    schema = adapter.get_schema()
    print(f"  支持的分析类型: {schema.get('supported_analyses', [])}")
    results["schema"] = {"success": True, "data": schema}

    return results


def generate_report(fetch_results, viz_results, analysis_results):
    """生成测试报告"""
    print("\n" + "=" * 60)
    print("4. 生成测试报告")
    print("=" * 60)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    report_lines = [
        "# GIS 功能测试报告",
        "",
        f"**生成时间**: {timestamp}",
        "",
        "## 测试概览",
        "",
        "| 测试模块 | 测试项 | 状态 |",
        "|---------|--------|------|",
    ]

    # 数据获取测试结果
    for key, val in fetch_results.items():
        status = val.get("success", False)
        status_icon = "PASS" if status else "FAIL"
        report_lines.append(f"| 数据获取 | {key} | {status_icon} |")

    # 可视化测试结果
    for key, val in viz_results.items():
        status = val.get("success", False)
        status_icon = "PASS" if status else "FAIL"
        report_lines.append(f"| 可视化 | {key} | {status_icon} |")

    # 分析测试结果
    for key, val in analysis_results.items():
        status = val.get("success", False)
        status_icon = "PASS" if status else "FAIL"
        report_lines.append(f"| 分析 | {key} | {status_icon} |")

    report_lines.extend([
        "",
        "## 生成的文件",
        "",
    ])

    # 列出所有生成的文件
    for f in sorted(os.listdir(OUTPUT_DIR)):
        filepath = os.path.join(OUTPUT_DIR, f)
        size = os.path.getsize(filepath)
        report_lines.append(f"- `{f}` ({size:,} bytes)")

    report_lines.extend([
        "",
        "## 详细结果",
        "",
        "### 数据获取测试",
        "",
    ])

    for key, val in fetch_results.items():
        report_lines.append(f"#### {key}")
        report_lines.append("")
        if val.get("success"):
            report_lines.append(f"- 状态: 成功")
            report_lines.append(f"- 文件: `{val.get('file', 'N/A')}`")
        else:
            report_lines.append(f"- 状态: 失败")
            report_lines.append(f"- 错误: {val.get('error', 'N/A')}")
            if val.get("mock"):
                report_lines.append(f"- 模拟数据: `{val.get('mock')}`")
        report_lines.append("")

    report_lines.extend([
        "### 可视化测试",
        "",
    ])

    for key, val in viz_results.items():
        report_lines.append(f"#### {key}")
        report_lines.append("")
        if val.get("success"):
            report_lines.append(f"- 状态: 成功")
            report_lines.append(f"- 文件: `{val.get('file', 'N/A')}`")
        else:
            report_lines.append(f"- 状态: 失败")
            report_lines.append(f"- 错误: {val.get('error', 'N/A')}")
        report_lines.append("")

    report_lines.extend([
        "### 分析测试",
        "",
    ])

    for key, val in analysis_results.items():
        report_lines.append(f"#### {key}")
        report_lines.append("")
        if val.get("success"):
            report_lines.append(f"- 状态: 成功")
            if val.get("data"):
                report_lines.append(f"- 数据: `{json.dumps(val.get('data'), ensure_ascii=False)[:100]}...`")
        else:
            report_lines.append(f"- 状态: 失败")
            report_lines.append(f"- 错误: {val.get('error', 'N/A')}")
        report_lines.append("")

    report_lines.extend([
        "---",
        "",
        "*注意: 部分 API 测试可能因网络原因失败，已使用模拟数据替代。*",
    ])

    report_path = os.path.join(OUTPUT_DIR, "gis_test_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    print(f"\n保存报告: {report_path}")

    return report_path


def main():
    """主测试流程"""
    print("=" * 60)
    print("GIS 功能测试")
    print(f"输出目录: {OUTPUT_DIR}")
    print("=" * 60)

    # 确保输出目录存在
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1. 数据获取测试
    fetch_results = test_data_fetch()

    # 2. 可视化测试
    viz_results = test_visualization()

    # 3. 分析测试
    analysis_results = test_analysis()

    # 4. 生成报告
    report_path = generate_report(fetch_results, viz_results, analysis_results)

    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)

    # 列出所有生成的文件
    print(f"\n生成的文件 ({OUTPUT_DIR}):")
    for f in sorted(os.listdir(OUTPUT_DIR)):
        filepath = os.path.join(OUTPUT_DIR, f)
        size = os.path.getsize(filepath)
        print(f"  {f} ({size:,} bytes)")

    return True


if __name__ == "__main__":
    main()