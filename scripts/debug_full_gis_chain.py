"""完整 GIS 数据链路诊断脚本

诊断所有地图数据源的获取、分析和可视化链路：
1. WFS 数据 - 天地图水系、道路、居民地
2. POI 数据 - 高德优先策略
3. 地图瓦片 - 前端瓦片服务
4. 路径规划 - 可达性分析、等时圈

Usage:
    python scripts/debug_full_gis_chain.py
"""

import sys
import os
import json
import asyncio
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from src.core.config import TIANDITU_API_KEY, AMAP_API_KEY, GIS_TIMEOUT
from src.tools.core.gis_data_fetcher import get_fetcher
from src.tools.core.gis_tool_wrappers import wrap_gis_data_fetch, wrap_poi_search
from src.tools.geocoding import TiandituProvider, POIProvider
from src.orchestration.nodes.dimension_node import _extract_gis_data_for_sse


def print_header(title: str):
    """Print section header"""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_result(success: bool, message: str, data: dict = None):
    """Print result with status"""
    status = "✅" if success else "❌"
    print(f"{status} {message}")
    if data:
        for key, value in data.items():
            if isinstance(value, dict):
                print(f"   - {key}: {json.dumps(value, ensure_ascii=False)[:100]}...")
            elif isinstance(value, (list, tuple)):
                print(f"   - {key}: {len(value)} items")
            else:
                print(f"   - {key}: {value}")


def diagnose_wfs_data():
    """诊断 WFS 数据获取 -> SSE 提取"""
    print_header("1. WFS 数据链路诊断")

    # 1.1 检查 API Key 配置
    print_result(
        bool(TIANDITU_API_KEY),
        f"天地图 API Key: {TIANDITU_API_KEY[:8] + '...' if TIANDITU_API_KEY else '未配置'}"
    )

    if not TIANDITU_API_KEY:
        print("⚠️  跳过 WFS 测试，请配置 TIANDITU_API_KEY")
        return

    # 1.2 测试 GIS 数据获取
    test_location = "平远县泗水镇金田村"
    print(f"\n📍 测试位置: {test_location}")

    try:
        fetcher = get_fetcher()
        result = fetcher.fetch_all_gis_data(
            location=test_location,
            buffer_km=5.0,
            max_features=100
        )

        # 检查数据格式
        print_result(bool(result), "GIS 数据获取", {
            "location": result.get("location"),
            "center": result.get("center"),
            "is_village_level": result.get("is_village_level"),
        })

        # 检查各类型数据
        water = result.get("water", {})
        road = result.get("road", {})
        residential = result.get("residential", {})

        print_result(
            water.get("success", False),
            f"水系数据: {len(water.get('geojson', {}).get('features', []))} features"
        )
        print_result(
            road.get("success", False),
            f"道路数据: {len(road.get('geojson', {}).get('features', []))} features"
        )
        print_result(
            residential.get("success", False),
            f"居民地数据: {len(residential.get('geojson', {}).get('features', []))} features"
        )

        # 1.3 测试 wrap_gis_data_fetch 包装器
        print("\n测试 wrap_gis_data_fetch 包装器...")
        wrapped_result = wrap_gis_data_fetch({
            "location": test_location,
            "buffer_km": 5.0,
            "max_features": 100
        })

        wrapped_json = json.loads(wrapped_result)
        print_result(
            wrapped_json.get("success", False),
            "包装器执行",
            {"water": wrapped_json.get("water"), "road": wrapped_json.get("road")}
        )

        # 1.4 测试 _extract_gis_data_for_sse
        print("\n测试 _extract_gis_data_for_sse 提取...")
        sse_data = _extract_gis_data_for_sse(wrapped_json)

        if sse_data:
            print_result(True, "SSE 数据提取成功", {
                "layers": len(sse_data.get("layers", [])),
                "mapOptions": sse_data.get("mapOptions"),
            })
            # 打印图层详情
            for layer in sse_data.get("layers", []):
                features = layer.get("geojson", {}).get("features", [])
                print(f"   📊 {layer.get('layerName')}: {len(features)} features, color={layer.get('color')}")
        else:
            print_result(False, "SSE 数据提取失败 - 返回 None")

    except Exception as e:
        print_result(False, f"WFS 数据获取异常: {e}")


def diagnose_poi_data():
    """诊断 POI 数据获取 -> 坐标验证"""
    print_header("2. POI 数据链路诊断")

    # 2.1 检查高德 API Key
    print_result(
        bool(AMAP_API_KEY),
        f"高德 API Key: {AMAP_API_KEY[:8] + '...' if AMAP_API_KEY else '未配置'}"
    )

    # 2.2 测试坐标转换函数
    print("\n测试坐标转换 (GCJ-02 → WGS-84)...")
    try:
        from src.tools.geocoding.amap.provider import gcj02_to_wgs84

        # 北京天安门 GCJ-02 坐标 (高德)
        gcj_lon, gcj_lat = 116.397428, 39.90923
        wgs_lon, wgs_lat = gcj02_to_wgs84(gcj_lon, gcj_lat)

        print_result(True, f"坐标转换测试", {
            "GCJ-02": f"({gcj_lon}, {gcj_lat})",
            "WGS-84": f"({wgs_lon:.6f}, {wgs_lat:.6f})",
            "偏移": f"({abs(gcj_lon - wgs_lon)*111000:.1f}m, {abs(gcj_lat - wgs_lat)*111000:.1f}m)"
        })
    except Exception as e:
        print_result(False, f"坐标转换测试失败: {e}")

    # 2.3 测试 POI 搜索
    test_keyword = "学校"
    test_region = "平远县"

    print(f"\n📍 测试 POI 搜索: {test_keyword} in {test_region}")

    try:
        # 使用高德优先策略
        result = POIProvider.search_poi_in_region(test_keyword, test_region, page_size=5)

        if result.get("success"):
            pois = result.get("pois", [])
            source = result.get("source", "unknown")
            print_result(True, f"POI 搜索成功 ({source})", {"count": len(pois)})

            # 检查坐标格式
            if pois:
                first_poi = pois[0]
                lon = first_poi.get("lon")
                lat = first_poi.get("lat")
                gcj_lon = first_poi.get("lon_gcj02")
                gcj_lat = first_poi.get("lat_gcj02")

                print(f"   📍 WGS-84 坐标: ({lon:.6f}, {lat:.6f})")
                if gcj_lon and gcj_lat:
                    print(f"   📍 原始 GCJ-02: ({gcj_lon:.6f}, {gcj_lat:.6f})")
                    offset_m = abs(gcj_lon - lon) * 111000
                    print(f"   ✅ 已转换坐标，偏移约 {offset_m:.1f}m")
                else:
                    print("   ✅ 天地图 POI 使用 CGCS2000（与 WGS84 兼容）")

        else:
            print_result(False, f"POI 搜索失败: {result.get('error')}")

        # 2.4 测试 wrap_poi_search 包装器
        print("\n测试 wrap_poi_search 包装器...")
        wrapped_result = wrap_poi_search({
            "keyword": test_keyword,
            "region": test_region,
            "page_size": 5
        })

        wrapped_json = json.loads(wrapped_result)
        print_result(
            wrapped_json.get("success", False),
            "包装器执行",
            {"total_count": wrapped_json.get("total_count"), "source": wrapped_json.get("source")}
        )

        # 2.5 测试 SSE 提取
        print("\n测试 SSE 数据提取...")
        sse_data = _extract_gis_data_for_sse(wrapped_json)

        if sse_data:
            print_result(True, "SSE 数据提取成功", {
                "layers": len(sse_data.get("layers", [])),
            })
        else:
            print_result(False, "SSE 数据提取失败")

    except Exception as e:
        print_result(False, f"POI 数据获取异常: {e}")


def diagnose_tile_service():
    """诊断瓦片服务配置"""
    print_header("3. 瓦片服务配置诊断")

    # 3.1 检查后端瓦片服务
    try:
        from src.tools.geocoding.tianditu.tiles import TileService

        tile_service = TileService()

        print_result(
            bool(tile_service.api_key),
            f"后端瓦片服务 API Key: {tile_service.api_key[:8] + '...' if tile_service.api_key else '未配置'}"
        )

        # 获取瓦片模板 URL
        vec_url = tile_service.get_tile_template("vec", "c")
        print_result(True, "天地图矢量瓦片模板", {"url": vec_url[:80] + "..."})

        # 获取图层信息
        layer_info = tile_service.get_layer_info()
        print_result(True, "可用图层", {
            "base_layers": list(layer_info.get("base_layers", {}).keys()),
            "projections": layer_info.get("projections", []),
        })

    except Exception as e:
        print_result(False, f"瓦片服务诊断异常: {e}")

    # 3.2 检查前端瓦片配置
    print("\n前端瓦片配置检查:")
    frontend_env_path = project_root / "frontend" / ".env.local"

    if frontend_env_path.exists():
        env_content = frontend_env_path.read_text()
        tile_source = "未配置"
        tianditu_key = "未配置"

        for line in env_content.split("\n"):
            if line.startswith("NEXT_PUBLIC_TILE_SOURCE"):
                tile_source = line.split("=")[1].strip()
            if line.startswith("NEXT_PUBLIC_TIANDITU_KEY"):
                key_value = line.split("=")[1].strip()
                tianditu_key = key_value[:8] + "..." if key_value and key_value != "未配置" else key_value

        print_result(True, f"前端瓦片源: {tile_source}")
        print_result(bool(tianditu_key != "未配置"), f"前端天地图 Key: {tianditu_key}")

        # 推荐配置
        if tile_source == "openstreetmap":
            print("   ⚠️  当前使用 OpenStreetMap，国内访问可能不稳定")
            print("   💡 推荐切换到 geoq 或 tianditu")
        elif tile_source == "geoq":
            print("   ✅ GeoQ ArcGIS 瓦片国内可用，无需密钥")
        elif tile_source == "tianditu":
            if tianditu_key == "未配置":
                print("   ⚠️  天地图瓦片需要配置 NEXT_PUBLIC_TIANDITU_KEY")
            else:
                print("   ✅ 天地图瓦片配置完整")
                print("   ✅ 与 WFS/POI 数据坐标系一致（CGCS2000/WGS84）")

    else:
        print_result(False, f"前端环境文件不存在: {frontend_env_path}")


def diagnose_route_data():
    """诊断路径规划链路"""
    print_header("4. 路径规划链路诊断")

    if not TIANDITU_API_KEY:
        print("⚠️  跳过路径规划测试，请配置 TIANDITU_API_KEY")
        return

    try:
        provider = TiandituProvider()

        # 测试坐标（平远县附近）
        origin = (115.85, 24.55)
        destination = (115.90, 24.60)

        print(f"\n📍 测试路径规划: {origin} -> {destination}")

        # 4.1 测试路径规划
        route_result = provider.plan_route(origin, destination, "walk")

        if route_result.success:
            route_data = route_result.data
            print_result(True, "路径规划成功", {
                "distance": route_data.get("distance"),
                "duration": route_data.get("duration"),
            })

            # 检查是否有 GeoJSON
            geojson = route_data.get("geojson")
            if geojson:
                features = geojson.get("features", [])
                print_result(True, f"GeoJSON 路线数据: {len(features)} features")
            else:
                print_result(False, "无 GeoJSON 路线数据")
        else:
            print_result(False, f"路径规划失败: {route_result.error}")

        # 4.2 测试可达性分析
        print("\n测试可达性分析...")
        from src.tools.core.accessibility_core import run_accessibility_analysis

        accessibility_result = run_accessibility_analysis(
            analysis_type="service_coverage",
            origin=origin,
            destinations=[destination, (115.92, 24.58), (115.88, 24.62)],
            center=(115.85, 24.55),
            travel_mode="walk",
            max_time_minutes=30
        )

        if accessibility_result.get("success"):
            data = accessibility_result.get("data", {})
            summary = data.get("summary", {})
            print_result(True, "可达性分析成功", {
                "coverage_rate": summary.get("coverage_rate"),
                "reachable": summary.get("reachable"),
            })

            # 检查 GeoJSON
            geojson = data.get("geojson")
            if geojson:
                features = geojson.get("features", [])
                print_result(True, f"GeoJSON 可达性数据: {len(features)} features")

            # 测试 SSE 提取
            sse_data = _extract_gis_data_for_sse(accessibility_result)
            if sse_data:
                print_result(True, "SSE 数据提取成功")
            else:
                print_result(False, "SSE 数据提取失败")
        else:
            print_result(False, f"可达性分析失败: {accessibility_result.get('error')}")

    except Exception as e:
        print_result(False, f"路径规划诊断异常: {e}")


def diagnose_coordinate_system():
    """诊断坐标系一致性"""
    print_header("5. 坐标系一致性诊断")

    print("坐标系说明:")
    print("  - WGS84: 国际通用坐标系，Leaflet 默认使用")
    print("  - GCJ-02: 中国加密坐标系，高德地图使用")
    print("  - CGCS2000: 中国大地坐标系，天地图使用（与 WGS84 兼容）")

    print("\n数据源坐标系:")
    print_result(True, "天地图 WFS 数据", {"坐标系": "CGCS2000（兼容 WGS84）"})
    print_result(True, "天地图 POI 数据", {"坐标系": "CGCS2000（兼容 WGS84）"})
    print_result(True, "天地图瓦片", {"坐标系": "经纬度投影（兼容 WGS84）"})

    if AMAP_API_KEY:
        print_result(True, "高德 POI 数据", {"坐标系": "GCJ-02（需转换）"})
        print("   ⚠️  高德 POI 坐标需要 GCJ-02 -> WGS84 转换")
    else:
        print_result(False, "高德 POI 数据", {"状态": "未配置 API Key"})


def main():
    """运行所有诊断"""
    print("\n" + "=" * 60)
    print("  GIS 数据到可视化完整链路诊断")
    print("=" * 60)

    diagnose_wfs_data()
    diagnose_poi_data()
    diagnose_tile_service()
    diagnose_route_data()
    diagnose_coordinate_system()

    print("\n" + "=" * 60)
    print("  诊断完成")
    print("=" * 60)

    # 总结
    print("\n📋 问题总结:")
    print("1. WFS 数据: 检查 _extract_gis_data_for_sse 是否能提取嵌套格式数据")
    print("2. POI 数据: 检查高德 GCJ-02 坐标是否需要转换")
    print("3. 瓦片服务: 检查前端是否使用国内可用瓦片源")
    print("4. 路径规划: 检查可达性分析 GeoJSON 数据流转")


if __name__ == "__main__":
    main()