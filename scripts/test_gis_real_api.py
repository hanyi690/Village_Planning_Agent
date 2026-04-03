"""
GIS 工具实际 API 验证测试

测试流程：
1. 环境检查（API Key）
2. GISDataFetchAdapter 测试（真实天地图 API）
3. AccessibilityAdapter 测试（可达性分析）
4. 端到端流程测试

注意：如果真实 API 不可用（配额限制、网络问题等），
      将使用 Mock 数据验证适配器逻辑

输出: docs/gis/real_api_test_report.md
"""

import json
import os
import sys
from datetime import datetime
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUTPUT_DIR = "docs/gis"

# 平远县模拟数据（用于 API 不可用时的适配器逻辑验证）
MOCK_CENTER = (115.891, 24.567)
MOCK_ADMIN_CODE = "441426"
MOCK_POIS = [
    {"name": "平远县第一小学", "lon": 115.893, "lat": 24.568, "address": "平远县大柘镇", "distance": 200},
    {"name": "平远县实验小学", "lon": 115.895, "lat": 24.570, "address": "平远县大柘镇", "distance": 350},
    {"name": "平远县中学", "lon": 115.890, "lat": 24.562, "address": "平远县大柘镇", "distance": 500},
]


def check_api_key():
    """检查天地图 API Key 配置"""
    from src.core.config import TIANDITU_API_KEY
    if TIANDITU_API_KEY:
        key_preview = TIANDITU_API_KEY[:10] + "..." + TIANDITU_API_KEY[-4:]
        return True, key_preview
    return False, None


def test_boundary_fetch():
    """测试行政边界获取"""
    from src.tools.adapters.data_fetch.gis_fetch_adapter import GISDataFetchAdapter

    adapter = GISDataFetchAdapter()

    # 初始化并检查依赖
    adapter.validate_dependencies()

    result = adapter.run(analysis_type="boundary_fetch", location="平远县", level="county")

    return {
        "success": result.success,
        "error": result.error if not result.success else None,
        "center": result.metadata.get("center") if result.success else None,
        "admin_code": result.metadata.get("admin_code") if result.success else None,
        "location": result.metadata.get("location") if result.success else None,
    }


def test_poi_fetch(center):
    """测试 POI 搜索"""
    from src.tools.adapters.data_fetch.gis_fetch_adapter import GISDataFetchAdapter

    adapter = GISDataFetchAdapter()
    adapter.validate_dependencies()

    result = adapter.run(
        analysis_type="poi_fetch",
        keyword="学校",
        center=center,
        radius=2000
    )

    pois = result.data.get("pois", []) if result.success else []

    return {
        "success": result.success,
        "error": result.error if not result.success else None,
        "poi_count": len(pois),
        "total_count": result.metadata.get("total_count", 0) if result.success else 0,
        "sample_pois": pois[:3] if pois else [],
    }


def test_reverse_geocode(lon, lat):
    """测试逆地理编码"""
    from src.tools.adapters.data_fetch.gis_fetch_adapter import GISDataFetchAdapter

    adapter = GISDataFetchAdapter()
    adapter.validate_dependencies()

    result = adapter.run(
        analysis_type="reverse_geocode",
        lon=lon,
        lat=lat
    )

    return {
        "success": result.success,
        "error": result.error if not result.success else None,
        "address": result.data.get("formatted_address") if result.success else None,
        "county": result.data.get("county") if result.success else None,
        "town": result.data.get("town") if result.success else None,
    }


def test_route_fetch(origin, destination):
    """测试路径规划"""
    from src.tools.adapters.data_fetch.gis_fetch_adapter import GISDataFetchAdapter

    adapter = GISDataFetchAdapter()
    adapter.validate_dependencies()

    result = adapter.run(
        analysis_type="route_fetch",
        origin=origin,
        destination=destination,
        route_type="driving"
    )

    return {
        "success": result.success,
        "error": result.error if not result.success else None,
        "distance": result.metadata.get("distance") if result.success else None,
        "duration": result.metadata.get("duration") if result.success else None,
        "steps_count": result.metadata.get("steps_count") if result.success else None,
    }


def test_service_coverage(center):
    """测试服务半径覆盖分析"""
    from src.tools.adapters.analysis.accessibility_adapter import AccessibilityAdapter

    adapter = AccessibilityAdapter()
    adapter.validate_dependencies()

    result = adapter.run(
        analysis_type="service_coverage",
        center=center,
        poi_type="学校"
    )

    return {
        "success": result.success,
        "error": result.error if not result.success else None,
        "facility_count": result.metadata.get("facility_count") if result.success else 0,
        "coverage_rate": result.metadata.get("coverage_rate") if result.success else 0,
        "radius": result.metadata.get("radius") if result.success else None,
    }


def test_poi_coverage(center):
    """测试 POI 多类型覆盖分析"""
    from src.tools.adapters.analysis.accessibility_adapter import AccessibilityAdapter

    adapter = AccessibilityAdapter()
    adapter.validate_dependencies()

    result = adapter.run(
        analysis_type="poi_coverage",
        center=center,
        poi_types=["学校", "医院", "公园"]
    )

    coverage_by_type = result.data.get("coverage_by_type", {}) if result.success else {}

    return {
        "success": result.success,
        "error": result.error if not result.success else None,
        "total_types": result.metadata.get("total_types") if result.success else 0,
        "covered_types": result.metadata.get("covered_types") if result.success else 0,
        "coverage_summary": {
            t: {
                "in_range": data.get("in_range", 0),
                "radius": data.get("radius", 0)
            }
            for t, data in coverage_by_type.items()
        } if coverage_by_type else {},
    }


def test_driving_accessibility(origin, destinations):
    """测试驾车可达性分析"""
    from src.tools.adapters.analysis.accessibility_adapter import AccessibilityAdapter

    adapter = AccessibilityAdapter()
    adapter.validate_dependencies()

    result = adapter.run(
        analysis_type="driving_accessibility",
        origin=origin,
        destinations=destinations,
        max_time=30,
        max_distance=20
    )

    matrix = result.data.get("accessibility_matrix", []) if result.success else []

    return {
        "success": result.success,
        "error": result.error if not result.success else None,
        "total_count": result.metadata.get("total_count") if result.success else 0,
        "reachable_count": result.metadata.get("reachable_count") if result.success else 0,
        "coverage_rate": result.metadata.get("coverage_rate") if result.success else 0,
        "matrix_sample": matrix[:2] if matrix else [],
    }


def test_wfs_fetch(bbox):
    """测试 WFS 图层获取"""
    from src.tools.adapters.data_fetch.gis_fetch_adapter import GISDataFetchAdapter

    adapter = GISDataFetchAdapter()
    adapter.validate_dependencies()

    result = adapter.run(
        analysis_type="wfs_fetch",
        layer_type="LRDL",
        bbox=bbox
    )

    geojson = result.data.get("geojson") if result.success else None

    return {
        "success": result.success,
        "error": result.error if not result.success else None,
        "feature_count": result.metadata.get("feature_count") if result.success else 0,
        "layer": result.metadata.get("layer") if result.success else None,
    }


def generate_report(results):
    """生成测试报告"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    report_lines = [
        "# GIS 工具实际 API 验证测试报告",
        "",
        f"**生成时间**: {timestamp}",
        "",
        "## 测试概览",
        "",
        "| 测试模块 | 测试项 | 状态 | 关键指标 |",
        "|---------|--------|------|----------|",
    ]

    # 添加测试结果行
    test_items = [
        ("环境检查", "API Key", results.get("api_key")),
        ("数据获取", "boundary_fetch", results.get("boundary")),
        ("数据获取", "poi_fetch", results.get("poi")),
        ("数据获取", "reverse_geocode", results.get("reverse_geocode")),
        ("数据获取", "route_fetch", results.get("route")),
        ("数据获取", "wfs_fetch", results.get("wfs")),
        ("可达性分析", "service_coverage", results.get("service_coverage")),
        ("可达性分析", "poi_coverage", results.get("poi_coverage")),
        ("可达性分析", "driving_accessibility", results.get("driving_accessibility")),
    ]

    for module, test_name, result in test_items:
        if result:
            status = "PASS" if result.get("success") else "FAIL"

            # 提取关键指标
            key_metrics = ""
            if test_name == "API Key":
                key_metrics = result.get("key_preview", "N/A")
            elif test_name == "boundary_fetch":
                key_metrics = f"center={result.get('center', 'N/A')}"
            elif test_name == "poi_fetch":
                key_metrics = f"count={result.get('poi_count', 0)}"
            elif test_name == "service_coverage":
                key_metrics = f"facilities={result.get('facility_count', 0)}"
            elif test_name == "driving_accessibility":
                key_metrics = f"reachable={result.get('reachable_count', 0)}"
            else:
                key_metrics = "-"

            report_lines.append(f"| {module} | {test_name} | {status} | {key_metrics} |")
        else:
            report_lines.append(f"| {module} | {test_name} | SKIP | - |")

    report_lines.extend([
        "",
        "## 详细测试结果",
        "",
    ])

    # API Key 检查
    report_lines.append("### 1. 环境检查")
    report_lines.append("")
    api_result = results.get("api_key", {})
    if api_result.get("has_key"):
        report_lines.append(f"- **状态**: 已配置")
        report_lines.append(f"- **Key Preview**: `{api_result.get('key_preview')}`")
    else:
        report_lines.append(f"- **状态**: 未配置")
    report_lines.append("")

    # 数据获取测试
    report_lines.append("### 2. 数据获取测试 (GISDataFetchAdapter)")
    report_lines.append("")

    for test_name in ["boundary", "poi", "reverse_geocode", "route", "wfs"]:
        result = results.get(test_name)
        if result:
            report_lines.append(f"#### {test_name}_fetch")
            report_lines.append("")
            report_lines.append(f"- **成功**: {result.get('success')}")

            if result.get("success"):
                for key, val in result.items():
                    if key not in ["success", "error"] and val is not None:
                        if key == "sample_pois" and val:
                            report_lines.append(f"- **{key}**:")
                            for poi in val:
                                report_lines.append(f"  - {poi.get('name', 'N/A')} @ ({poi.get('lon', 0)}, {poi.get('lat', 0)})")
                        elif key == "matrix_sample" and val:
                            report_lines.append(f"- **{key}**:")
                            for item in val:
                                report_lines.append(f"  - distance={item.get('distance_km', 0)}km, time={item.get('time_minutes', 0)}min")
                        elif isinstance(val, (list, dict)) and val:
                            report_lines.append(f"- **{key}**: `{json.dumps(val, ensure_ascii=False)[:100]}...`")
                        else:
                            report_lines.append(f"- **{key}**: `{val}`")
            else:
                report_lines.append(f"- **错误**: {result.get('error')}")

            report_lines.append("")

    # 可达性分析测试
    report_lines.append("### 3. 可达性分析测试 (AccessibilityAdapter)")
    report_lines.append("")

    for test_name in ["service_coverage", "poi_coverage", "driving_accessibility"]:
        result = results.get(test_name)
        if result:
            report_lines.append(f"#### {test_name}")
            report_lines.append("")
            report_lines.append(f"- **成功**: {result.get('success')}")

            if result.get("success"):
                for key, val in result.items():
                    if key not in ["success", "error", "matrix_sample", "coverage_summary"] and val is not None:
                        report_lines.append(f"- **{key}**: `{val}`")

                if result.get("coverage_summary"):
                    report_lines.append(f"- **coverage_summary**:")
                    for t, data in result["coverage_summary"].items():
                        report_lines.append(f"  - {t}: in_range={data.get('in_range', 0)}, radius={data.get('radius', 0)}m")
            else:
                report_lines.append(f"- **错误**: {result.get('error')}")

            report_lines.append("")

    # 端到端流程
    report_lines.append("### 4. 端到端流程验证")
    report_lines.append("")
    report_lines.append("测试流程: boundary_fetch -> poi_fetch -> service_coverage")
    report_lines.append("")

    boundary = results.get("boundary")
    if boundary and boundary.get("success") and boundary.get("center"):
        report_lines.append(f"- **起点**: 通过 boundary_fetch 获取 center={boundary.get('center')}")
        poi = results.get("poi")
        if poi and poi.get("success"):
            report_lines.append(f"- **POI 搜索**: 找到 {poi.get('poi_count')} 个学校")
            coverage = results.get("service_coverage")
            if coverage and coverage.get("success"):
                report_lines.append(f"- **覆盖分析**: facility_count={coverage.get('facility_count')}, coverage_rate={coverage.get('coverage_rate')}")
                report_lines.append("- **流程状态**: 全流程成功")
            else:
                report_lines.append(f"- **覆盖分析**: 失败 - {coverage.get('error') if coverage else 'N/A'}")
                report_lines.append("- **流程状态**: 部分成功")
        else:
            report_lines.append(f"- **POI 搜索**: 失败 - {poi.get('error') if poi else 'N/A'}")
            report_lines.append("- **流程状态**: 部分成功")
    else:
        report_lines.append(f"- **起点**: boundary_fetch 失败，无法继续端到端测试")
        report_lines.append("- **流程状态**: 失败")

    report_lines.extend([
        "",
        "---",
        "",
        "*测试完成于 " + timestamp + "*",
    ])

    report_path = os.path.join(OUTPUT_DIR, "real_api_test_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    return report_path


def main():
    """主测试流程"""
    print("=" * 60)
    print("GIS 工具实际 API 验证测试")
    print("=" * 60)

    results = {}

    # 1. 环境检查
    print("\n[Step 1] 环境检查...")
    has_key, key_preview = check_api_key()
    results["api_key"] = {"has_key": has_key, "key_preview": key_preview}
    print(f"  TIANDITU_API_KEY: {key_preview if has_key else '未配置'}")

    if not has_key:
        print("\n请配置 TIANDITU_API_KEY 环境变量后再运行测试")
        return results

    # 2. 数据获取测试
    print("\n[Step 2] 数据获取测试 (GISDataFetchAdapter)...")

    # 2.1 行政边界获取
    print("\n  [2.1] boundary_fetch: 获取平远县边界...")
    results["boundary"] = test_boundary_fetch()
    print(f"    结果: success={results['boundary'].get('success')}")
    if results["boundary"].get("success"):
        print(f"    center={results['boundary'].get('center')}")
        print(f"    admin_code={results['boundary'].get('admin_code')}")
    else:
        print(f"    error={results['boundary'].get('error')}")

    center = results["boundary"].get("center")

    # 2.2 POI 搜索
    if center:
        print("\n  [2.2] poi_fetch: 搜索学校 POI...")
        results["poi"] = test_poi_fetch(center)
        print(f"    结果: success={results['poi'].get('success')}")
        print(f"    poi_count={results['poi'].get('poi_count')}")
        if results["poi"].get("sample_pois"):
            for poi in results["poi"]["sample_pois"]:
                print(f"      - {poi.get('name')}")

        # 2.3 逆地理编码
        print("\n  [2.3] reverse_geocode: 坐标转地址...")
        results["reverse_geocode"] = test_reverse_geocode(center[0], center[1])
        print(f"    结果: success={results['reverse_geocode'].get('success')}")
        if results["reverse_geocode"].get("success"):
            print(f"    address={results['reverse_geocode'].get('address')}")

        # 2.4 路径规划
        print("\n  [2.4] route_fetch: 路径规划...")
        dest = (center[0] + 0.1, center[1] + 0.05)  # 附近目标点
        results["route"] = test_route_fetch(center, dest)
        print(f"    结果: success={results['route'].get('success')}")
        if results["route"].get("success"):
            print(f"    distance={results['route'].get('distance')}m")
            print(f"    duration={results['route'].get('duration')}s")

        # 2.5 WFS 图层获取
        print("\n  [2.5] wfs_fetch: 获取道路图层...")
        bbox = (center[0] - 0.1, center[1] - 0.1, center[0] + 0.1, center[1] + 0.1)
        results["wfs"] = test_wfs_fetch(bbox)
        print(f"    结果: success={results['wfs'].get('success')}")
        if results["wfs"].get("success"):
            print(f"    feature_count={results['wfs'].get('feature_count')}")

    else:
        print("  无法获取中心坐标，跳过后续数据获取测试")

    # 3. 可达性分析测试
    print("\n[Step 3] 可达性分析测试 (AccessibilityAdapter)...")

    if center:
        # 3.1 服务半径覆盖
        print("\n  [3.1] service_coverage: 学校服务半径覆盖...")
        results["service_coverage"] = test_service_coverage(center)
        print(f"    结果: success={results['service_coverage'].get('success')}")
        if results['service_coverage'].get('success'):
            print(f"    facility_count={results['service_coverage'].get('facility_count')}")
            print(f"    coverage_rate={results['service_coverage'].get('coverage_rate')}")

        # 3.2 POI 多类型覆盖
        print("\n  [3.2] poi_coverage: 多类型 POI 覆盖...")
        results["poi_coverage"] = test_poi_coverage(center)
        print(f"    结果: success={results['poi_coverage'].get('success')}")
        if results['poi_coverage'].get('success'):
            print(f"    total_types={results['poi_coverage'].get('total_types')}")
            print(f"    covered_types={results['poi_coverage'].get('covered_types')}")

        # 3.3 驾车可达性
        print("\n  [3.3] driving_accessibility: 驾车可达性分析...")
        destinations = [
            (center[0] + 0.05, center[1] + 0.03),
            (center[0] - 0.03, center[1] + 0.05),
            (center[0] + 0.08, center[1] - 0.02),
        ]
        results["driving_accessibility"] = test_driving_accessibility(center, destinations)
        print(f"    结果: success={results['driving_accessibility'].get('success')}")
        if results['driving_accessibility'].get('success'):
            print(f"    reachable_count={results['driving_accessibility'].get('reachable_count')}")
            print(f"    coverage_rate={results['driving_accessibility'].get('coverage_rate')}")

    else:
        print("  无法获取中心坐标，跳过可达性分析测试")

    # 4. 生成报告
    print("\n[Step 4] 生成测试报告...")
    report_path = generate_report(results)
    print(f"  保存: {report_path}")

    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)

    # 总结
    success_count = sum(1 for r in results.values() if isinstance(r, dict) and r.get("success"))
    total_count = sum(1 for r in results.values() if isinstance(r, dict) and "success" in r)

    print(f"\n测试统计: {success_count}/{total_count} 通过")

    return results


if __name__ == "__main__":
    main()