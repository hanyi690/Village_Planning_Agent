"""
天地图扩展服务测试脚本

测试以下功能：
1. 逆地理编码（坐标→地址）
2. POI 搜索（关键词+范围）
3. WFS 数据获取（道路/水系图层）
4. 路径规划（驾车/步行）
5. 可达性分析
"""

import os
import sys
import json
from typing import Dict, Any

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()


def print_result(title: str, result: Dict[str, Any]):
    """打印测试结果"""
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}")

    if result.get("success"):
        print("✅ 成功")
        # 打印关键字段
        for key in ["address", "formatted_address", "total_count", "distance", "duration"]:
            if key in result:
                print(f"  {key}: {result[key]}")

        # 打印数据概要
        if "pois" in result:
            print(f"  POI 数量: {len(result['pois'])}")
            if result['pois']:
                print(f"  示例: {result['pois'][0]}")

        if "geojson" in result:
            features = result["geojson"].get("features", [])
            print(f"  要素数量: {len(features)}")

        if "geometry" in result:
            print(f"  路径点数: {len(result['geometry'])}")
    else:
        print(f"❌ 失败: {result.get('error', '未知错误')}")


def test_reverse_geocode():
    """测试逆地理编码"""
    from src.tools.geocoding.tianditu_extended import get_extended_service

    service = get_extended_service()

    # 测试坐标：梅州市平远县泗水镇金田村附近
    lon, lat = 115.891, 24.567

    result = service.reverse_geocode(lon, lat)
    print_result("逆地理编码测试", result.to_dict())

    return result.success


def test_poi_search():
    """测试 POI 搜索"""
    from src.tools.geocoding.tianditu_extended import get_extended_service

    service = get_extended_service()

    # 搜索梅州市附近的学校
    center = (116.1, 24.3)  # 梅州市中心
    result = service.search_poi_nearby(
        keyword="学校",
        center=center,
        radius=5000
    )
    print_result("POI 搜索测试", result.to_dict())

    return result.success


def test_wfs_fetch():
    """测试 WFS 数据获取"""
    from src.tools.geocoding.tianditu_extended import get_extended_service, WFSLayerType

    service = get_extended_service()

    # 获取梅州市附近的道路数据
    bbox = (115.8, 24.2, 116.4, 24.6)  # 梅州市范围
    result = service.fetch_road_network(bbox)

    print_result("WFS 道路数据获取测试", result.to_dict())

    # 获取水系数据
    water_result = service.fetch_water_system(bbox, include_lines=True, include_areas=True)
    print(f"\n水系数据获取:")
    for layer_type, layer_result in water_result.items():
        print(f"  {layer_type}: {'成功' if layer_result.success else '失败'}")

    return result.success


def test_route_planning():
    """测试路径规划"""
    from src.tools.geocoding.tianditu_extended import get_extended_service, RouteType

    service = get_extended_service()

    # 规划从平远县到梅州市的路线
    origin = (115.891, 24.567)  # 平远县附近
    destination = (116.1, 24.3)  # 梅州市

    result = service.driving_route(origin, destination)
    print_result("驾车路径规划测试", result.to_dict())

    return result.success


def test_accessibility_adapter():
    """测试可达性分析适配器"""
    from src.tools.adapters.analysis.accessibility_adapter import AccessibilityAdapter

    adapter = AccessibilityAdapter()

    # 测试驾车可达性
    origin = (115.891, 24.567)  # 金田村附近
    destinations = [
        (116.1, 24.3),   # 梅州市
        (115.7, 24.5),   # 附近点
    ]

    result = adapter.execute(
        "driving_accessibility",
        origin=origin,
        destinations=destinations,
        max_time=60,  # 最大 60 分钟
        max_distance=50  # 最大 50 公里
    )

    print_result("驾车可达性分析测试", result.to_dict())

    return result.success


def test_gis_fetch_adapter():
    """测试 GIS 数据获取适配器"""
    from src.tools.adapters.data_fetch.gis_fetch_adapter import GISDataFetchAdapter

    adapter = GISDataFetchAdapter()

    # 测试边界获取
    result = adapter.execute("boundary_fetch", location="平远县", level="county")
    print_result("边界获取测试", result.to_dict())

    # 测试 POI 获取
    poi_result = adapter.execute(
        "poi_fetch",
        keyword="学校",
        center=(116.1, 24.3),
        radius=5000
    )
    print_result("适配器 POI 获取测试", poi_result.to_dict())

    return result.success


def test_tool_registry():
    """测试工具注册"""
    from src.tools.registry import ToolRegistry

    print("\n" + "="*60)
    print(" 工具注册测试")
    print("="*60)

    tools = ToolRegistry.list_tools()
    print(f"已注册工具数量: {len(tools)}")
    print("\n已注册工具列表:")
    for name, func_name in tools.items():
        print(f"  - {name}: {func_name}")

    # 检查新工具是否注册
    new_tools = [
        "accessibility_analysis",
        "poi_search",
        "wfs_data_fetch",
        "route_planning",
        "reverse_geocode"
    ]

    print("\n新工具注册状态:")
    for tool_name in new_tools:
        registered = tool_name in tools
        status = "✅" if registered else "❌"
        print(f"  {status} {tool_name}")

    return all(t in tools for t in new_tools)


def main():
    """运行所有测试"""
    print("\n" + "="*60)
    print(" 天地图扩展服务测试")
    print("="*60)

    # 检查 API Key
    api_key = os.getenv("TIANDITU_API_KEY", "")
    if not api_key:
        print("\n⚠️ 警告: TIANDITU_API_KEY 未配置，部分测试将失败")
        print("请在 .env 文件中设置 TIANDITU_API_KEY")
    else:
        print(f"\n✅ API Key 已配置: {api_key[:8]}...")

    # 运行测试
    tests = [
        ("逆地理编码", test_reverse_geocode),
        ("POI 搜索", test_poi_search),
        ("WFS 数据获取", test_wfs_fetch),
        ("路径规划", test_route_planning),
        ("可达性分析适配器", test_accessibility_adapter),
        ("GIS 数据获取适配器", test_gis_fetch_adapter),
        ("工具注册", test_tool_registry),
    ]

    results = {}
    for name, test_func in tests:
        try:
            results[name] = test_func()
        except Exception as e:
            print(f"\n❌ {name} 测试异常: {e}")
            results[name] = False

    # 汇总
    print("\n" + "="*60)
    print(" 测试汇总")
    print("="*60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, success in results.items():
        status = "✅ 通过" if success else "❌ 失败"
        print(f"  {name}: {status}")

    print(f"\n总计: {passed}/{total} 通过")

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)