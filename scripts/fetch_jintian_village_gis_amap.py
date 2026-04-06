"""
金田村 GIS 数据获取脚本 - 高德地图版本

目标地点: 广东省梅州市平远县泗水镇金田村
数据源: 高德地图 API + 天地图 WFS
输出格式: GeoJSON
输出目录: docs/gis/geojson_data/

数据获取策略:
1. 高德地图: 行政区划边界、地理编码、POI 搜索
2. 天地图 WFS: 水系、道路、居民地矢量数据

注意: 高德地图不支持村级边界，本脚本获取:
- 平远县边界 (县级，含边界坐标)
- 泗水镇信息 (镇级，无边界)
- 金田村中心坐标 (地理编码)
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
CITY_NAME = "梅州市"
PROVINCE_NAME = "广东省"
BUFFER_RADIUS_KM = 2.0
BUFFER_RADIUS_DEG = BUFFER_RADIUS_KM / 111.0
MAX_FEATURES = 500

# POI 搜索类型
POI_CATEGORIES = [
    ("学校", "141000"),
    ("医院", "090100"),
    ("政府机构", "130100"),
    ("超市", "060100"),
    ("银行", "160100"),
    ("公园", "110100"),
    ("餐饮", "050000"),
    ("加油站", "010100"),
]


def check_amap_key() -> Tuple[bool, Optional[str]]:
    """检查高德地图 API Key"""
    from src.core.config import AMAP_API_KEY
    if AMAP_API_KEY:
        key_preview = AMAP_API_KEY[:8] + "..." + AMAP_API_KEY[-4:]
        return True, key_preview
    return False, None


def check_tianditu_key() -> Tuple[bool, Optional[str]]:
    """检查天地图 API Key"""
    from src.core.config import TIANDITU_API_KEY
    if TIANDITU_API_KEY:
        key_preview = TIANDITU_API_KEY[:8] + "..." + TIANDITU_API_KEY[-4:]
        return True, key_preview
    return False, None


def get_district_with_boundary(provider, keywords: str, subdistrict: int = 1) -> Dict[str, Any]:
    """获取行政区划（含边界坐标）"""
    print(f"  正在获取 {keywords} 行政区划（含边界）...")
    result = provider.get_district(
        keywords=keywords,
        subdistrict=subdistrict,
        extensions="all"  # 返回边界坐标
    )

    if result.success:
        district = result.data.get("district", {})
        geojson = result.data.get("geojson")
        print(f"    成功! name={district.get('name')}, adcode={district.get('adcode')}")
        if geojson:
            features = geojson.get("features", [])
            print(f"    边界坐标: {len(features)} 个要素")
        return {
            "success": True,
            "district": district,
            "geojson": geojson,
            "subdistricts": result.data.get("districts", [])
        }
    else:
        print(f"    失败: {result.error}")
        return {"success": False, "error": result.error}


def get_district_basic(provider, keywords: str, subdistrict: int = 0) -> Dict[str, Any]:
    """获取行政区划基本信息（不含边界）"""
    print(f"  正在获取 {keywords} 行政区划（基本信息）...")
    result = provider.get_district(
        keywords=keywords,
        subdistrict=subdistrict,
        extensions="base"
    )

    if result.success:
        district = result.data.get("district", {})
        print(f"    成功! name={district.get('name')}, adcode={district.get('adcode')}")
        return {
            "success": True,
            "district": district
        }
    else:
        print(f"    失败: {result.error}")
        return {"success": False, "error": result.error}


def geocode_address(provider, address: str, city: Optional[str] = None) -> Dict[str, Any]:
    """地理编码"""
    print(f"  正在地理编码: {address}...")
    result = provider.geocode(address, city)

    if result.success:
        lon = result.data.get("lon")
        lat = result.data.get("lat")
        formatted = result.data.get("formatted_address", "")
        level = result.data.get("level", "")
        print(f"    成功! ({lon}, {lat})")
        print(f"    地址: {formatted}")
        print(f"    级别: {level}")
        return {
            "success": True,
            "lon": lon,
            "lat": lat,
            "formatted_address": formatted,
            "level": level,
            "adcode": result.data.get("adcode", "")
        }
    else:
        print(f"    失败: {result.error}")
        return {"success": False, "error": result.error}


def search_pois(provider, keywords: str, location: Tuple[float, float], radius: int = 2000) -> Dict[str, Any]:
    """周边 POI 搜索"""
    print(f"  正在搜索 {keywords} (半径 {radius}m)...")
    result = provider.search_poi_nearby(
        keywords=keywords,
        location=location,
        radius=radius,
        page_size=25
    )

    if result.success:
        pois = result.data.get("pois", [])
        total = result.data.get("total", 0)
        print(f"    找到 {len(pois)}/{total} 个 POI")
        return {
            "success": True,
            "pois": pois,
            "total": total,
            "geojson": create_poi_geojson(pois)
        }
    else:
        print(f"    失败: {result.error}")
        return {"success": False, "error": result.error, "pois": []}


def search_pois_by_type(provider, types: str, location: Tuple[float, float], radius: int = 2000) -> Dict[str, Any]:
    """按类型码搜索 POI"""
    result = provider.search_poi_by_types(
        types=types,
        location=location,
        radius=radius,
        page_size=25
    )

    if result.success:
        pois = result.data.get("pois", [])
        total = result.data.get("total", 0)
        return {
            "success": True,
            "pois": pois,
            "total": total
        }
    else:
        return {"success": False, "error": result.error, "pois": []}


def create_poi_geojson(pois: List[Dict]) -> Dict[str, Any]:
    """创建 POI GeoJSON"""
    features = []
    for poi in pois:
        lon = poi.get("lon", 0)
        lat = poi.get("lat", 0)
        if lon and lat:
            features.append({
                "type": "Feature",
                "properties": {
                    "name": poi.get("name", ""),
                    "category": poi.get("category", ""),
                    "address": poi.get("address", ""),
                    "distance": poi.get("distance", 0),
                    "typecode": poi.get("typecode", ""),
                    "tel": poi.get("tel", "")
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat]
                }
            })

    return {
        "type": "FeatureCollection",
        "features": features
    }


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


def calculate_bbox(center: Tuple[float, float], radius_deg: float) -> Tuple[float, float, float, float]:
    """计算边界框"""
    lon, lat = center
    return (lon - radius_deg, lat - radius_deg, lon + radius_deg, lat + radius_deg)


def get_wfs_layer(wfs_service, layer_type: str, bbox: Tuple[float, float, float, float], max_features: int) -> Dict[str, Any]:
    """获取 WFS 图层（天地图）"""
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
            "feature_count": len(features)
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


def generate_metadata(results: Dict[str, Any], center: Optional[Tuple[float, float]]) -> Dict[str, Any]:
    """生成元数据"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    metadata = {
        "fetch_time": timestamp,
        "target_location": f"{VILLAGE_NAME}, {TOWN_NAME}, {COUNTY_NAME}",
        "buffer_radius_km": BUFFER_RADIUS_KM,
        "center": center,
        "data_sources": ["amap", "tianditu_wfs"],
        "amap_data": {},
        "wfs_data": {},
        "status": "unknown"
    }

    # 高德数据统计
    amap_success = 0
    if results.get("county_boundary", {}).get("success"):
        amap_success += 1
        metadata["amap_data"]["county_boundary"] = True
    if results.get("village_geocode", {}).get("success"):
        amap_success += 1
        metadata["amap_data"]["village_center"] = True
    if results.get("pois"):
        total_pois = sum(
            len(p.get("pois", []))
            for p in results["pois"].values()
            if p.get("success")
        )
        metadata["amap_data"]["poi_count"] = total_pois
        amap_success += 1

    # WFS 数据统计
    wfs_success = 0
    total_features = 0
    for key in ["hyda", "hydl", "hydp", "lrrl", "lrdl", "resa", "resp"]:
        if key in results and results[key].get("success"):
            wfs_success += 1
            fc = results[key].get("feature_count", 0)
            total_features += fc
            metadata["wfs_data"][key] = {"success": True, "count": fc}

    metadata["wfs_total_features"] = total_features

    # 整体状态
    if amap_success >= 2 and wfs_success >= 5:
        metadata["status"] = "complete"
    elif amap_success >= 1 or wfs_success >= 3:
        metadata["status"] = "partial"
    else:
        metadata["status"] = "failed"

    return metadata


def generate_report(results: Dict[str, Any], metadata: Dict[str, Any], files: Dict[str, str]) -> str:
    """生成获取报告"""
    timestamp = metadata.get("fetch_time")

    lines = [
        "# 金田村 GIS 数据获取报告（高德地图版）",
        "",
        f"**获取时间**: {timestamp}",
        "",
        f"**目标地点**: {metadata.get('target_location')}",
        "",
        f"**数据源**: 高德地图 API + 天地图 WFS",
        "",
        f"**中心坐标**: `{metadata.get('center')}`",
        "",
        f"**缓冲半径**: {metadata.get('buffer_radius_km')} km",
        "",
        "## 获取状态",
        "",
        f"| 状态 | 说明 |",
        f"|------|------|",
        f"| {metadata.get('status')} | 高德数据 + WFS 数据 |",
        "",
        "## 高德地图数据",
        "",
        "| 数据项 | 状态 | 说明 |",
        "|--------|------|------|",
    ]

    # 高德数据状态
    county = results.get("county_boundary", {})
    status = "成功" if county.get("success") else "失败"
    lines.append(f"| 平远县边界 | {status} | 含边界坐标 |")

    town = results.get("town_info", {})
    status = "成功" if town.get("success") else "失败"
    lines.append(f"| 泗水镇信息 | {status} | adcode + 中心坐标 |")

    village = results.get("village_geocode", {})
    status = "成功" if village.get("success") else "失败"
    if village.get("success"):
        lines.append(f"| 金田村坐标 | {status} | ({village.get('lon')}, {village.get('lat')}) |")
    else:
        lines.append(f"| 金田村坐标 | {status} | - |")

    # POI 统计
    lines.extend([
        "",
        "### POI 数据统计",
        "",
        "| 类型 | 数量 |",
        "|------|------|",
    ])

    pois = results.get("pois", {})
    for cat_name, poi_result in pois.items():
        count = len(poi_result.get("pois", [])) if poi_result.get("success") else 0
        lines.append(f"| {cat_name} | {count} |")

    # WFS 数据
    lines.extend([
        "",
        "## 天地图 WFS 数据",
        "",
        "| 图层 | 类型 | 要素数 |",
        "|------|------|--------|",
    ])

    layer_names = {
        "hyda": ("水系面", "HYDA"),
        "hydl": ("水系线", "HYDL"),
        "hydp": ("水系点", "HYDP"),
        "lrrl": ("铁路", "LRRL"),
        "lrdl": ("公路", "LRDL"),
        "resa": ("居民地面", "RESA"),
        "resp": ("居民地点", "RESP")
    }

    for key, (name, code) in layer_names.items():
        if key in results:
            fc = results[key].get("feature_count", 0)
            lines.append(f"| {name} | {code} | {fc} |")

    # 输出文件
    lines.extend([
        "",
        "## 输出文件",
        "",
        "| 文件名 | 说明 |",
        "|--------|------|",
    ])

    for filename, desc in sorted(files.items()):
        lines.append(f"| {filename} | {desc} |")

    lines.extend([
        "",
        "## 说明",
        "",
        "- 高德地图行政区划 API 不支持村级边界，仅支持县级及以上",
        "- 本脚本获取平远县边界作为参考区域",
        "- 金田村中心坐标通过地理编码获取",
        "- POI 数据来自高德地图，覆盖半径 2km",
        "- 矢量数据（水系、道路、居民地）来自天地图 WFS 服务",
        "",
        "---",
        "",
        f"*报告生成于 {timestamp}*"
    ])

    return "\n".join(lines)


def main():
    """主流程"""
    print("=" * 60)
    print("金田村 GIS 数据获取脚本（高德地图版）")
    print("=" * 60)
    print(f"目标: {VILLAGE_NAME}, {TOWN_NAME}, {COUNTY_NAME}")
    print(f"缓冲半径: {BUFFER_RADIUS_KM} km")
    print()

    results = {}
    files = {}

    # Step 1: 环境检查
    print("[Step 1] 环境检查...")

    has_amap, amap_key = check_amap_key()
    print(f"  AMAP_API_KEY: {amap_key if has_amap else '未配置'}")

    has_tianditu, tianditu_key = check_tianditu_key()
    print(f"  TIANDITU_API_KEY: {tianditu_key if has_tianditu else '未配置'}")

    if not has_amap:
        print("\n错误: 请配置 AMAP_API_KEY 环境变量")
        return {"status": "failed", "error": "AMAP API Key 未配置"}

    # 初始化 Provider
    from src.tools.geocoding.amap.provider import AmapProvider
    amap_provider = AmapProvider()

    # 天地图 WFS（可选）
    wfs_service = None
    if has_tianditu:
        from src.tools.geocoding.tianditu.provider import TiandituProvider
        tianditu_provider = TiandituProvider()
        wfs_service = tianditu_provider.wfs_service

    # Step 2: 高德地图行政区划获取
    print("\n[Step 2] 行政区划获取（高德地图）...")

    # 2.1 获取平远县边界（含边界坐标）
    county_result = get_district_with_boundary(amap_provider, COUNTY_NAME, subdistrict=1)
    results["county_boundary"] = county_result

    if county_result.get("success") and county_result.get("geojson"):
        files["amap_boundary_pingyuan.geojson"] = save_geojson(
            "amap_boundary_pingyuan.geojson",
            county_result["geojson"],
            OUTPUT_DIR
        )
        print(f"  已保存: {files['amap_boundary_pingyuan.geojson']}")

    # 2.2 获取泗水镇信息（基本信息，无边界）
    town_result = get_district_basic(amap_provider, f"{COUNTY_NAME}{TOWN_NAME}")
    results["town_info"] = town_result

    # 2.3 地理编码获取金田村中心坐标
    village_address = f"{PROVINCE_NAME}{CITY_NAME}{COUNTY_NAME}{TOWN_NAME}{VILLAGE_NAME}"
    village_result = geocode_address(amap_provider, village_address, CITY_NAME)
    results["village_geocode"] = village_result

    # 确定中心坐标
    center = None
    if village_result.get("success"):
        center = (village_result["lon"], village_result["lat"])
    elif county_result.get("success"):
        district = county_result.get("district", {})
        center_str = district.get("center", "")
        if center_str and isinstance(center_str, tuple):
            center = center_str

    if center is None:
        print("\n警告: 无法获取中心坐标，使用默认坐标")
        center = (115.891, 24.567)

    print(f"  最终中心坐标: ({center[0]}, {center[1]})")

    # 保存中心点
    center_geojson = create_center_point_geojson(center[0], center[1], VILLAGE_NAME)
    files["amap_center_point.geojson"] = save_geojson(
        "amap_center_point.geojson", center_geojson, OUTPUT_DIR
    )

    # Step 3: POI 搜索
    print("\n[Step 3] POI 搜索（高德地图）...")

    pois_results = {}
    all_pois = []

    for cat_name, type_code in POI_CATEGORIES:
        poi_result = search_pois(amap_provider, cat_name, center, int(BUFFER_RADIUS_KM * 1000))
        pois_results[cat_name] = poi_result
        if poi_result.get("success"):
            all_pois.extend(poi_result.get("pois", []))

    results["pois"] = pois_results

    # 合并所有 POI
    all_poi_geojson = create_poi_geojson(all_pois)
    files["amap_pois_all.geojson"] = save_geojson(
        "amap_pois_all.geojson", all_poi_geojson, OUTPUT_DIR
    )
    print(f"\n  POI 总计: {len(all_pois)} 个")
    print(f"  已保存: {files['amap_pois_all.geojson']}")

    # Step 4: 天地图 WFS 数据获取
    print("\n[Step 4] 天地图 WFS 数据获取...")

    if wfs_service is None:
        print("  天地图 API Key 未配置，跳过 WFS 数据获取")
    else:
        # 构建 bbox
        bbox = calculate_bbox(center, BUFFER_RADIUS_DEG)
        print(f"  bbox: ({bbox[0]:.4f}, {bbox[1]:.4f}, {bbox[2]:.4f}, {bbox[3]:.4f})")

        # 水系数据
        print("\n  [水系数据]")
        for layer_type in ["HYDA", "HYDL", "HYDP"]:
            result = get_wfs_layer(wfs_service, layer_type, bbox, MAX_FEATURES)
            key = layer_type.lower()
            results[key] = result
            files[f"wfs_{key}.geojson"] = save_geojson(
                f"wfs_{key}.geojson",
                result.get("geojson", {"type": "FeatureCollection", "features": []}),
                OUTPUT_DIR
            )

        # 道路数据
        print("\n  [道路数据]")
        for layer_type in ["LRRL", "LRDL"]:
            result = get_wfs_layer(wfs_service, layer_type, bbox, MAX_FEATURES)
            key = layer_type.lower()
            results[key] = result
            files[f"wfs_{key}.geojson"] = save_geojson(
                f"wfs_{key}.geojson",
                result.get("geojson", {"type": "FeatureCollection", "features": []}),
                OUTPUT_DIR
            )

        # 居民地数据
        print("\n  [居民地数据]")
        for layer_type in ["RESA", "RESP"]:
            result = get_wfs_layer(wfs_service, layer_type, bbox, MAX_FEATURES)
            key = layer_type.lower()
            results[key] = result
            files[f"wfs_{key}.geojson"] = save_geojson(
                f"wfs_{key}.geojson",
                result.get("geojson", {"type": "FeatureCollection", "features": []}),
                OUTPUT_DIR
            )

    # Step 5: 生成元数据和报告
    print("\n[Step 5] 生成元数据和报告...")

    metadata = generate_metadata(results, center)
    files["amap_metadata.json"] = save_geojson(
        "amap_metadata.json", metadata, OUTPUT_DIR
    )
    print(f"  已保存: {files['amap_metadata.json']}")

    # 添加文件描述
    file_descriptions = {
        "amap_boundary_pingyuan.geojson": "平远县边界（高德地图）",
        "amap_center_point.geojson": "金田村中心点",
        "amap_pois_all.geojson": "POI 数据合集",
        "amap_metadata.json": "元数据摘要",
        "wfs_hyda.geojson": "水系面（天地图 WFS）",
        "wfs_hydl.geojson": "水系线（天地图 WFS）",
        "wfs_hydp.geojson": "水系点（天地图 WFS）",
        "wfs_lrrl.geojson": "铁路（天地图 WFS）",
        "wfs_lrdl.geojson": "公路（天地图 WFS）",
        "wfs_resa.geojson": "居民地面（天地图 WFS）",
        "wfs_resp.geojson": "居民地点（天地图 WFS）",
        "amap_fetch_report.md": "获取报告"
    }

    report_content = generate_report(results, metadata, file_descriptions)
    files["amap_fetch_report.md"] = os.path.join(OUTPUT_DIR, "amap_fetch_report.md")
    with open(files["amap_fetch_report.md"], "w", encoding="utf-8") as f:
        f.write(report_content)
    print(f"  已保存: {files['amap_fetch_report.md']}")

    # 总结
    print("\n" + "=" * 60)
    print("数据获取完成!")
    print("=" * 60)

    print(f"\n状态: {metadata.get('status')}")
    print(f"POI 总数: {len(all_pois)}")
    print(f"WFS 要素数: {metadata.get('wfs_total_features', 0)}")

    print("\n输出文件:")
    for filename in sorted(files.keys()):
        print(f"  - {filename}")

    return {
        "status": metadata.get("status"),
        "metadata": metadata,
        "files": files,
        "results": results
    }


if __name__ == "__main__":
    main()