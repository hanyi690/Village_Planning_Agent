"""
金田村 GIS 数据获取脚本

目标地点: 广东省梅州市平远县泗水镇金田村
输出格式: GeoJSON
输出目录: docs/gis/geojson_data/

采用向上定位策略:
1. 先获取平远县边界（县级）作为参考
2. 通过地理编码/POI搜索定位金田村中心坐标
3. 以中心坐标+缓冲半径构建bbox
4. 调用WFS服务获取各图层数据
"""

import json
import os
import sys
from datetime import datetime
from typing import Dict, Any, Tuple, Optional, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUTPUT_DIR = "docs/gis/geojson_data"

# 配置参数
VILLAGE_NAME = "金田村"
COUNTY_NAME = "平远县"
TOWN_NAME = "泗水镇"
BUFFER_RADIUS_KM = 2.0  # 村级尺度缓冲半径
BUFFER_RADIUS_DEG = BUFFER_RADIUS_KM / 111.0  # 约 0.02 度
MAX_FEATURES = 500


def check_environment() -> Tuple[bool, Optional[str]]:
    """检查环境配置"""
    from src.core.config import TIANDITU_API_KEY

    if TIANDITU_API_KEY:
        key_preview = TIANDITU_API_KEY[:10] + "..." + TIANDITU_API_KEY[-4:]
        return True, key_preview
    return False, None


def get_boundary(provider, location: str) -> Dict[str, Any]:
    """获取行政边界"""
    print(f"  正在获取 {location} 边界...")
    result = provider.get_boundary(location, level="county")

    if result.success:
        print(f"    成功! center={result.metadata.get('center')}")
        return {
            "success": True,
            "geojson": result.data.get("geojson"),
            "center": result.data.get("center"),
            "metadata": result.metadata
        }
    else:
        print(f"    失败: {result.error}")
        return {
            "success": False,
            "error": result.error
        }


def geocode_location(provider, address: str) -> Dict[str, Any]:
    """地理编码：地址转坐标"""
    print(f"  正在地理编码: {address}...")
    result = provider.geocode(address)

    if result.success:
        lon = result.data.get("lon")
        lat = result.data.get("lat")
        print(f"    成功! ({lon}, {lat})")
        return {
            "success": True,
            "lon": lon,
            "lat": lat,
            "formatted_address": result.data.get("formatted_address")
        }
    else:
        print(f"    失败: {result.error}")
        return {
            "success": False,
            "error": result.error
        }


def search_poi_in_region(provider, keyword: str, region: str) -> Dict[str, Any]:
    """区域内 POI 搜索"""
    print(f"  正在搜索 {keyword} (区域: {region})...")
    result = provider.search_poi_in_region(keyword, region, page_size=20)

    if result.success:
        pois = result.data.get("pois", [])
        print(f"    找到 {len(pois)} 个 POI")
        if pois:
            print(f"    第一个: {pois[0].get('name')} @ ({pois[0].get('lon')}, {pois[0].get('lat')})")
        return {
            "success": True,
            "pois": pois,
            "geojson": result.data.get("geojson"),
            "total_count": result.metadata.get("total_count", 0)
        }
    else:
        print(f"    失败: {result.error}")
        return {
            "success": False,
            "error": result.error,
            "pois": [],
            "geojson": {"type": "FeatureCollection", "features": []}
        }


def calculate_bbox(center: Tuple[float, float], radius_deg: float) -> Tuple[float, float, float, float]:
    """计算边界框"""
    lon, lat = center
    return (lon - radius_deg, lat - radius_deg, lon + radius_deg, lat + radius_deg)


def get_wfs_layer(wfs_service, layer_type: str, bbox: Tuple[float, float, float, float], max_features: int) -> Dict[str, Any]:
    """获取单个 WFS 图层"""
    layer_names = {
        "HYDA": "水系面",
        "HYDL": "水系线",
        "HYDP": "水系点",
        "LRRL": "铁路",
        "LRDL": "公路",
        "RESA": "居民地面",
        "RESP": "居民地点"
    }
    print(f"  正在获取 {layer_names.get(layer_type, layer_type)} ({layer_type})...")
    result = wfs_service.get_wfs_data(layer_type, bbox, max_features)

    if result.success:
        geojson = result.data.get("geojson", {})
        features = geojson.get("features", [])
        print(f"    成功! {len(features)} 个要素")
        return {
            "success": True,
            "geojson": geojson,
            "feature_count": len(features),
            "metadata": result.metadata
        }
    else:
        print(f"    失败: {result.error}")
        return {
            "success": False,
            "error": result.error,
            "geojson": {"type": "FeatureCollection", "features": []},
            "feature_count": 0
        }


def save_geojson(filename: str, geojson: Dict[str, Any], output_dir: str) -> str:
    """保存 GeoJSON 文件"""
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)
    return filepath


def create_center_point_geojson(lon: float, lat: float, name: str) -> Dict[str, Any]:
    """创建中心点 GeoJSON"""
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {
                "name": name,
                "type": "village_center"
            },
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat]
            }
        }]
    }


def create_empty_geojson() -> Dict[str, Any]:
    """创建空 GeoJSON"""
    return {"type": "FeatureCollection", "features": []}


def combine_geojsons(geojsons: List[Dict[str, Any]]) -> Dict[str, Any]:
    """合并多个 GeoJSON"""
    all_features = []
    for geojson in geojsons:
        features = geojson.get("features", [])
        all_features.extend(features)
    return {"type": "FeatureCollection", "features": all_features}


def generate_metadata(results: Dict[str, Any], center: Optional[Tuple[float, float]], bbox: Optional[Tuple[float, float, float, float]]) -> Dict[str, Any]:
    """生成元数据摘要"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    metadata = {
        "fetch_time": timestamp,
        "target_location": f"{VILLAGE_NAME}, {TOWN_NAME}, {COUNTY_NAME}",
        "buffer_radius_km": BUFFER_RADIUS_KM,
        "max_features_per_layer": MAX_FEATURES,
        "center": center,
        "bbox": bbox,
        "layers": {},
        "status": "unknown"
    }

    # 统计各图层状态
    total_success = 0
    total_failed = 0
    total_features = 0

    layer_keys = ["hyda", "hydl", "hydp", "lrrl", "lrdl", "resa", "resp"]

    for key in layer_keys:
        if key in results and results[key].get("success"):
            total_success += 1
            fc = results[key].get("feature_count", 0)
            total_features += fc
            metadata["layers"][key] = {
                "success": True,
                "feature_count": fc
            }
        else:
            total_failed += 1
            metadata["layers"][key] = {
                "success": False,
                "error": results.get(key, {}).get("error", "unknown")
            }

    # 确定整体状态
    if total_success == len(layer_keys):
        metadata["status"] = "complete"
    elif total_success > 0:
        metadata["status"] = "partial"
    else:
        metadata["status"] = "failed"

    metadata["summary"] = {
        "total_layers": len(layer_keys),
        "success_layers": total_success,
        "failed_layers": total_failed,
        "total_features": total_features
    }

    return metadata


def generate_report(results: Dict[str, Any], metadata: Dict[str, Any], files: Dict[str, str]) -> str:
    """生成获取报告 Markdown"""
    timestamp = metadata.get("fetch_time")

    lines = [
        "# 金田村 GIS 数据获取报告",
        "",
        f"**获取时间**: {timestamp}",
        "",
        f"**目标地点**: {metadata.get('target_location')}",
        "",
        f"**缓冲半径**: {metadata.get('buffer_radius_km')} km",
        "",
        f"**中心坐标**: `{metadata.get('center')}`",
        "",
        f"**边界框**: `{metadata.get('bbox')}`",
        "",
        "## 获取状态概览",
        "",
        f"| 状态 | 说明 |",
        f"|------|------|",
        f"| {metadata.get('status')} | {metadata.get('summary', {}).get('success_layers')}/{metadata.get('summary', {}).get('total_layers')} 图层成功 |",
        "",
        "## 图层详情",
        "",
        "| 图层 | 类型 | 状态 | 要素数 |",
        "|------|------|------|--------|",
    ]

    layer_names = {
        "hyda": "水系面",
        "hydl": "水系线",
        "hydp": "水系点",
        "lrrl": "铁路",
        "lrdl": "公路",
        "resa": "居民地面",
        "resp": "居民地点"
    }

    for key, info in metadata.get("layers", {}).items():
        status = "成功" if info.get("success") else "失败"
        count = info.get("feature_count", 0) if info.get("success") else "-"
        lines.append(f"| {layer_names.get(key, key)} | {key.upper()} | {status} | {count} |")

    lines.extend([
        "",
        "## 输出文件",
        "",
        "| 文件名 | 说明 |",
        "|--------|------|",
    ])

    file_descriptions = {
        "metadata.json": "元数据摘要",
        "boundary_pingyuan.geojson": "平远县边界（参考）",
        "center_point.geojson": "金田村中心点",
        "water_hyda.geojson": "水系面",
        "water_hydl.geojson": "水系线",
        "water_hydp.geojson": "水系点",
        "water_combined.geojson": "水系合并",
        "road_lrrl.geojson": "铁路",
        "road_lrdl.geojson": "公路",
        "road_combined.geojson": "道路合并",
        "residential_resa.geojson": "居民地面",
        "residential_resp.geojson": "居民地点",
        "residential_combined.geojson": "居民地合并",
        "fetch_report.md": "获取报告"
    }

    for filename, desc in file_descriptions.items():
        lines.append(f"| {filename} | {desc} |")

    lines.extend([
        "",
        "## 定位策略说明",
        "",
        "采用向上定位策略:",
        "",
        "1. 获取平远县边界作为参考区域",
        "2. 尝试泗水镇边界（可能不支持）",
        "3. 通过地理编码定位金田村中心坐标",
        "4. 若地理编码失败，尝试区域内POI搜索",
        "5. 以中心坐标 + 缓冲半径构建 bbox",
        "",
        "---",
        "",
        f"*报告生成于 {timestamp}*"
    ])

    return "\n".join(lines)


def main():
    """主流程"""
    print("=" * 60)
    print("金田村 GIS 数据获取脚本")
    print("=" * 60)
    print(f"目标: {VILLAGE_NAME}, {TOWN_NAME}, {COUNTY_NAME}")
    print(f"缓冲半径: {BUFFER_RADIUS_KM} km")
    print(f"最大要素数: {MAX_FEATURES}")
    print()

    results = {}
    files = {}

    # Step 1: 环境检查
    print("[Step 1] 环境检查...")
    has_key, key_preview = check_environment()
    print(f"  TIANDITU_API_KEY: {key_preview if has_key else '未配置'}")

    if not has_key:
        print("\n错误: 请配置 TIANDITU_API_KEY 环境变量")
        return {"status": "failed", "error": "API Key 未配置"}

    # 初始化 Provider
    from src.tools.geocoding.tianditu.provider import TiandituProvider
    provider = TiandituProvider()
    wfs_service = provider.wfs_service

    # Step 2: 向上定位
    print("\n[Step 2] 向上定位策略...")

    # 2.1 获取平远县边界（县级参考）
    county_result = get_boundary(provider, COUNTY_NAME)
    results["boundary_county"] = county_result

    if county_result.get("success"):
        county_geojson = county_result.get("geojson")
        files["boundary_pingyuan.geojson"] = save_geojson(
            "boundary_pingyuan.geojson", county_geojson, OUTPUT_DIR
        )
        print(f"  已保存: {files['boundary_pingyuan.geojson']}")

    # 2.2 尝试泗水镇边界
    town_result = get_boundary(provider, f"{COUNTY_NAME}{TOWN_NAME}")
    results["boundary_town"] = town_result
    # 镇级可能不支持，不强制要求成功

    # 2.3 尝试地理编码定位金田村
    village_address = f"{COUNTY_NAME}{TOWN_NAME}{VILLAGE_NAME}"
    geocode_result = geocode_location(provider, village_address)
    results["geocode"] = geocode_result

    # 2.4 确定中心坐标
    center = None

    if geocode_result.get("success"):
        lon = geocode_result.get("lon")
        lat = geocode_result.get("lat")
        center = (lon, lat)
        print(f"  定位成功! 中心坐标: ({lon}, {lat})")
    else:
        # 尝试 POI 搜索定位
        print("  地理编码失败，尝试 POI 搜索...")
        poi_result = search_poi_in_region(provider, VILLAGE_NAME, COUNTY_NAME)
        results["poi_search"] = poi_result

        if poi_result.get("success") and poi_result.get("pois"):
            # 取第一个 POI 作为中心
            first_poi = poi_result["pois"][0]
            lon = first_poi.get("lon")
            lat = first_poi.get("lat")
            center = (lon, lat)
            print(f"  通过 POI 定位成功! 中心坐标: ({lon}, {lat})")

        # 如果仍无法定位，使用县级中心
        if center is None and county_result.get("success"):
            county_center = county_result.get("center")
            if county_center:
                center = county_center
                print(f"  使用县级中心作为参考: ({center[0]}, {center[1]})")

    if center is None:
        print("\n警告: 无法获取中心坐标，使用默认坐标")
        center = (115.891, 24.567)  # 平远县默认坐标
        print(f"  默认中心坐标: ({center[0]}, {center[1]})")

    # 保存中心点
    center_geojson = create_center_point_geojson(center[0], center[1], VILLAGE_NAME)
    files["center_point.geojson"] = save_geojson(
        "center_point.geojson", center_geojson, OUTPUT_DIR
    )
    print(f"  已保存: {files['center_point.geojson']}")

    # Step 3: 构建 bbox
    print("\n[Step 3] 构建边界框...")
    bbox = calculate_bbox(center, BUFFER_RADIUS_DEG)
    print(f"  bbox: ({bbox[0]:.4f}, {bbox[1]:.4f}, {bbox[2]:.4f}, {bbox[3]:.4f})")

    # Step 4: WFS 数据获取
    print("\n[Step 4] WFS 数据获取...")

    # 4.1 水系数据
    print("\n  [水系数据]")

    hyda_result = get_wfs_layer(wfs_service, "HYDA", bbox, MAX_FEATURES)
    results["hyda"] = hyda_result
    files["water_hyda.geojson"] = save_geojson(
        "water_hyda.geojson",
        hyda_result.get("geojson", create_empty_geojson()),
        OUTPUT_DIR
    )

    hydl_result = get_wfs_layer(wfs_service, "HYDL", bbox, MAX_FEATURES)
    results["hydl"] = hydl_result
    files["water_hydl.geojson"] = save_geojson(
        "water_hydl.geojson",
        hydl_result.get("geojson", create_empty_geojson()),
        OUTPUT_DIR
    )

    hydp_result = get_wfs_layer(wfs_service, "HYDP", bbox, MAX_FEATURES)
    results["hydp"] = hydp_result
    files["water_hydp.geojson"] = save_geojson(
        "water_hydp.geojson",
        hydp_result.get("geojson", create_empty_geojson()),
        OUTPUT_DIR
    )

    # 合并水系
    water_combined = combine_geojsons([
        hyda_result.get("geojson", create_empty_geojson()),
        hydl_result.get("geojson", create_empty_geojson()),
        hydp_result.get("geojson", create_empty_geojson())
    ])
    files["water_combined.geojson"] = save_geojson(
        "water_combined.geojson", water_combined, OUTPUT_DIR
    )
    print(f"    水系合并: {len(water_combined.get('features', []))} 个要素")

    # 4.2 道路数据
    print("\n  [道路数据]")

    lrrl_result = get_wfs_layer(wfs_service, "LRRL", bbox, MAX_FEATURES)
    results["lrrl"] = lrrl_result
    files["road_lrrl.geojson"] = save_geojson(
        "road_lrrl.geojson",
        lrrl_result.get("geojson", create_empty_geojson()),
        OUTPUT_DIR
    )

    lrdl_result = get_wfs_layer(wfs_service, "LRDL", bbox, MAX_FEATURES)
    results["lrdl"] = lrdl_result
    files["road_lrdl.geojson"] = save_geojson(
        "road_lrdl.geojson",
        lrdl_result.get("geojson", create_empty_geojson()),
        OUTPUT_DIR
    )

    # 合并道路
    road_combined = combine_geojsons([
        lrrl_result.get("geojson", create_empty_geojson()),
        lrdl_result.get("geojson", create_empty_geojson())
    ])
    files["road_combined.geojson"] = save_geojson(
        "road_combined.geojson", road_combined, OUTPUT_DIR
    )
    print(f"    道路合并: {len(road_combined.get('features', []))} 个要素")

    # 4.3 居民地数据
    print("\n  [居民地数据]")

    resa_result = get_wfs_layer(wfs_service, "RESA", bbox, MAX_FEATURES)
    results["resa"] = resa_result
    files["residential_resa.geojson"] = save_geojson(
        "residential_resa.geojson",
        resa_result.get("geojson", create_empty_geojson()),
        OUTPUT_DIR
    )

    resp_result = get_wfs_layer(wfs_service, "RESP", bbox, MAX_FEATURES)
    results["resp"] = resp_result
    files["residential_resp.geojson"] = save_geojson(
        "residential_resp.geojson",
        resp_result.get("geojson", create_empty_geojson()),
        OUTPUT_DIR
    )

    # 合并居民地
    residential_combined = combine_geojsons([
        resa_result.get("geojson", create_empty_geojson()),
        resp_result.get("geojson", create_empty_geojson())
    ])
    files["residential_combined.geojson"] = save_geojson(
        "residential_combined.geojson", residential_combined, OUTPUT_DIR
    )
    print(f"    居民地合并: {len(residential_combined.get('features', []))} 个要素")

    # Step 5: 生成元数据和报告
    print("\n[Step 5] 生成元数据和报告...")

    metadata = generate_metadata(results, center, bbox)
    files["metadata.json"] = save_geojson(
        "metadata.json", metadata, OUTPUT_DIR
    )
    print(f"  已保存: {files['metadata.json']}")

    report_content = generate_report(results, metadata, files)
    files["fetch_report.md"] = os.path.join(OUTPUT_DIR, "fetch_report.md")
    with open(files["fetch_report.md"], "w", encoding="utf-8") as f:
        f.write(report_content)
    print(f"  已保存: {files['fetch_report.md']}")

    # 总结
    print("\n" + "=" * 60)
    print("数据获取完成!")
    print("=" * 60)

    summary = metadata.get("summary", {})
    print(f"\n状态: {metadata.get('status')}")
    print(f"成功图层: {summary.get('success_layers')}/{summary.get('total_layers')}")
    print(f"总要素数: {summary.get('total_features')}")

    print("\n输出文件:")
    for filename, filepath in files.items():
        print(f"  - {filename}: {filepath}")

    return {
        "status": metadata.get("status"),
        "metadata": metadata,
        "files": files,
        "results": results
    }


if __name__ == "__main__":
    main()