"""GIS 执行链路诊断脚本

完全模拟规划时的 GIS 执行流程，输出详细的诊断信息。
"""

import sys
import os
import json
from pprint import pprint

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import TIANDITU_API_KEY, GIS_TIMEOUT
from src.tools.geocoding import TiandituProvider, WfsService, WFS_LAYERS, WFS_URL
from src.tools.core.gis_data_fetcher import GISDataFetcher, get_fetcher
from src.orchestration.nodes.dimension_node import (
    _get_nested_value,
    _resolve_tool_params,
    ParamSource
)


def diagnose_api_config():
    """诊断 1: API 配置验证"""
    print("\n" + "="*60)
    print("诊断 1: API 配置验证")
    print("="*60)

    api_key = TIANDITU_API_KEY
    print(f"TIANDITU_API_KEY: {api_key[:8] if api_key else 'None'}...")
    print(f"GIS_TIMEOUT: {GIS_TIMEOUT}s")

    if not api_key:
        print("API Key 未配置")
        return False
    print("API Key 已配置")
    return True


def diagnose_geocode(location: str):
    """诊断 2: 地理编码链路"""
    print("\n" + "="*60)
    print("诊断 2: 地理编码链路")
    print("="*60)

    provider = TiandituProvider()

    # 2.1 直接地理编码
    print(f"\n2.1 直接地理编码: {location}")
    result = provider.geocode(location)
    print(f"  success: {result.success}")
    print(f"  error: {result.error}")
    if result.success:
        print(f"  data: {result.data}")
        print(f"  metadata: {result.metadata}")

    # 2.2 县级边界获取
    fetcher = GISDataFetcher()
    hierarchy = fetcher.parse_location_hierarchy(location)
    print(f"\n2.2 地址层级解析: {hierarchy}")

    county_name = hierarchy.get("county", "")
    if county_name:
        print(f"\n2.3 县级边界获取: {county_name}")
        boundary_result = provider.get_boundary(county_name)
        print(f"  success: {boundary_result.success}")
        print(f"  error: {boundary_result.error}")
        if boundary_result.success:
            print(f"  center: {boundary_result.metadata.get('center')}")

    # 2.4 村级中心定位
    print(f"\n2.4 村级中心定位: {location}")
    center, metadata = fetcher.get_village_center(location)
    print(f"  center: {center}")
    print(f"  strategy_used: {metadata.get('strategy_used')}")
    print(f"  success: {metadata.get('success')}")
    print(f"  error: {metadata.get('error')}")

    return center, metadata


def diagnose_wfs_layers(center: tuple, buffer_km: float = 5.0):
    """诊断 3: WFS 图层请求"""
    print("\n" + "="*60)
    print("诊断 3: WFS 图层请求")
    print("="*60)

    if not center:
        print("无有效 center，跳过 WFS 诊断")
        return

    # 计算 bbox
    buffer_deg = buffer_km / 111.0
    bbox = (
        center[0] - buffer_deg,
        center[1] - buffer_deg,
        center[0] + buffer_deg,
        center[1] + buffer_deg
    )
    print(f"center: {center}")
    print(f"bbox: {bbox}")

    wfs = WfsService(TIANDITU_API_KEY)

    # 测试每个图层（使用正确的 TDTService: 前缀）
    all_layers = ["TDTService:LRRL", "TDTService:LRDL",
                  "TDTService:HYDA", "TDTService:HYDL",
                  "TDTService:RESA", "TDTService:RESP"]

    for idx, layer in enumerate(all_layers):
        print(f"\n3.{idx+1} 图层: {layer}")
        print(f"  请求 URL: ...TYPENAME={layer}&BBOX=...")

        result = wfs.get_wfs_data(layer, bbox, max_features=100)

        print(f"  success: {result.success}")
        print(f"  error: {result.error}")
        print(f"  metadata: {json.dumps(result.metadata, ensure_ascii=False, indent=4)}")

        if result.data and result.data.get("geojson"):
            features = result.data["geojson"].get("features", [])
            print(f"  feature_count: {len(features)}")

        # 特殊诊断：如果是 ServiceException，打印原始响应
        if result.metadata.get("response_type") == "service_exception":
            print("  [WARN] ServiceException 检测到，需要进一步诊断原始响应")


def diagnose_raw_wfs_response(center: tuple, buffer_km: float = 5.0):
    """诊断 4: WFS 原始响应（绕过解析，直接看响应内容）"""
    print("\n" + "="*60)
    print("诊断 4: WFS 原始响应")
    print("="*60)

    if not center:
        print("无有效 center，跳过")
        return

    import requests

    buffer_deg = buffer_km / 111.0
    bbox = (
        center[0] - buffer_deg,
        center[1] - buffer_deg,
        center[0] + buffer_deg,
        center[1] + buffer_deg
    )

    # 测试一个水系图层和居民地图层，验证正确格式
    test_layers = ["TDTService:HYDA", "TDTService:RESA"]

    for idx, layer in enumerate(test_layers):
        print(f"\n4.{idx+1} 图层: {layer}")

        url = (
            f"{WFS_URL}?SERVICE=WFS&VERSION=1.0.0&REQUEST=GetFeature"
            f"&TYPENAME={layer}&MAXFEATURES=100"
            f"&BBOX={bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
            f"&OUTPUTFORMAT=application/json&tk={TIANDITU_API_KEY}"
        )

        print(f"  完整 URL: {url}")

        try:
            resp = requests.get(url, timeout=30)
            print(f"  HTTP status: {resp.status_code}")
            print(f"  Content-Type: {resp.headers.get('Content-Type', 'N/A')}")

            # 尝试解析 JSON
            try:
                data = resp.json()
                print(f"  [OK] JSON 解析成功")
                print(f"  type: {data.get('type')}")
                print(f"  features: {len(data.get('features', []))}")
            except ValueError:
                print(f"  [FAIL] JSON 解析失败，原始响应:")
                print(f"  --- 响应内容前 500 字符 ---")
                print(resp.text[:500])
                print(f"  --- 响应内容结束 ---")

                # 手动解析 XML
                if "<?xml" in resp.text:
                    print(f"\n  XML 结构分析:")
                    import xml.etree.ElementTree as ET
                    try:
                        root = ET.fromstring(resp.text)
                        print(f"  root tag: {root.tag}")
                        # 找所有子元素
                        for child in root:
                            print(f"    child: {child.tag}")
                            for subchild in child:
                                text_preview = subchild.text[:100] if subchild.text else ''
                                print(f"      subchild: {subchild.tag} = '{text_preview}'")
                                if subchild.attrib:
                                    print(f"        attrib: {subchild.attrib}")
                    except ET.ParseError as e:
                        print(f"  XML 解析错误: {e}")

        except Exception as e:
            print(f"  [FAIL] 请求异常: {e}")


def diagnose_data_flow(location: str):
    """诊断 5: 数据流转链路"""
    print("\n" + "="*60)
    print("诊断 5: 数据流转链路")
    print("="*60)

    # 模拟 knowledge_preload_node 的 GIS 数据获取
    print("\n5.1 模拟 knowledge_preload_node GIS 数据获取")

    fetcher = get_fetcher()
    result = fetcher.fetch_all_gis_data(
        location=location,
        buffer_km=5.0,
        max_features=500
    )

    # 检查是否有任何数据成功
    has_data = any([
        result.get('water', {}).get('success'),
        result.get('road', {}).get('success'),
        result.get('residential', {}).get('success')
    ])
    print(f"  success (有数据): {has_data}")
    print(f"  location: {result.get('location')}")
    print(f"  center: {result.get('center')}")
    print(f"  is_village_level: {result.get('is_village_level')}")

    # 检查各数据类别
    for cat in ["water", "road", "residential"]:
        cat_result = result.get(cat, {})
        print(f"\n  {cat}:")
        print(f"    success: {cat_result.get('success')}")
        print(f"    error: {cat_result.get('error')}")
        if cat_result.get("geojson"):
            features = cat_result["geojson"].get("features", [])
            print(f"    feature_count: {len(features)}")

    # 模拟 gis_analysis_results 存储
    print("\n5.2 模拟 gis_analysis_results 存储")
    gis_analysis_results = {"_auto_fetched": result}

    print(f"  _auto_fetched keys: {list(result.keys())}")
    print(f"  _auto_fetched.center: {result.get('center')}")

    # 模拟参数解析
    print("\n5.3 模拟 _resolve_tool_params 参数解析")

    tool_params_config = {
        "center": {"source": "gis_cache", "path": "_auto_fetched.center"},
        "analysis_type": {"source": "literal", "value": "service_coverage"}
    }

    context = {
        "gis_analysis_results": gis_analysis_results,
        "config": {},
        "village_name": location
    }

    resolved = _resolve_tool_params(tool_params_config, context)
    print(f"  resolved params: {resolved}")
    print(f"  center resolved: {resolved.get('center')}")

    # 手动验证嵌套取值
    print("\n5.4 手动验证 _get_nested_value")
    center_value = _get_nested_value(gis_analysis_results, "_auto_fetched.center")
    print(f"  _get_nested_value('_auto_fetched.center'): {center_value}")


def main():
    """运行完整诊断"""
    # 使用用户日志中的实际地址
    location = "平远县泗水镇金田村"

    print("="*60)
    print("GIS 执行链路诊断脚本")
    print(f"测试地址: {location}")
    print("="*60)

    # 诊断 1: API 配置
    api_ok = diagnose_api_config()
    if not api_ok:
        print("\n[CRITICAL] API Key 未配置，终止诊断")
        return

    # 诊断 2: 地理编码
    center, metadata = diagnose_geocode(location)

    # 诊断 3: WFS 图层
    diagnose_wfs_layers(center, buffer_km=5.0)

    # 诊断 4: WFS 原始响应（深度诊断）
    diagnose_raw_wfs_response(center, buffer_km=5.0)

    # 诊断 5: 数据流转
    diagnose_data_flow(location)

    print("\n" + "="*60)
    print("[DONE] 诊断完成")
    print("="*60)


if __name__ == "__main__":
    main()