"""
Test Real GIS Render - 使用真实GIS数据测试出图效果

测试脚本：
1. 加载缓存的真实GIS数据（道路、水系、POI、边界）
2. 根据数据类型构建规划图层
3. 调用 render_planning_map 生成HTML地图
"""

import json
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.tools.core.map_renderer import render_planning_map, PLANNING_STYLES


def load_geojson(filename: str) -> dict:
    """加载GeoJSON文件"""
    filepath = project_root / "docs" / "gis" / "geojson_data" / filename
    if not filepath.exists():
        print(f"警告: 文件不存在 - {filepath}")
        return {"type": "FeatureCollection", "features": []}

    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def enhance_features_for_rendering(geojson: dict, layer_type: str) -> dict:
    """
    增强GeoJSON features属性以匹配渲染样式要求

    Args:
        geojson: 原始GeoJSON
        layer_type: 图层类型 (development_axis, facility_point等)

    Returns:
        增强后的GeoJSON
    """
    enhanced = {"type": "FeatureCollection", "features": []}

    for feature in geojson.get("features", []):
        props = feature.get("properties", {})

        # 根据图层类型添加必要属性
        if layer_type == "development_axis":
            # 道路/轴线数据 - 添加axis_type
            if "RN" in props:  # WFS道路数据有RN字段
                props["name"] = props.get("NAME", props.get("RN", "道路"))
                props["axis_type"] = "发展主轴"  # 默认类型
            elif "axis_type" not in props:
                props["axis_type"] = "发展主轴"

        elif layer_type == "facility_point":
            # POI数据 - 添加facility_type和status
            if "category" in props:  # 高德POI数据
                category = props.get("category", "")
                if "政府" in category:
                    props["facility_type"] = "便民服务中心"
                elif "医疗" in category or "医院" in category:
                    props["facility_type"] = "医院"
                elif "教育" in category or "学校" in category:
                    props["facility_type"] = "小学"
                else:
                    props["facility_type"] = "便民服务中心"
                props["status"] = "现状保留"

        elif layer_type == "infrastructure":
            # 基础设施数据 - 道路/水系
            if "RN" in props:  # WFS道路数据有RN字段
                rn = props.get("RN", "")
                props["name"] = props.get("NAME", rn)
                if rn.startswith("Y"):
                    props["infrastructure_type"] = "乡道"
                elif rn.startswith("X"):
                    props["infrastructure_type"] = "县道"
                else:
                    props["infrastructure_type"] = "道路"
            elif "GB" in props:  # 水系数据有GB字段
                props["infrastructure_type"] = "河流"
                props["name"] = props.get("NAME", "水系")

        elif layer_type == "function_zone":
            # 功能区数据 - 添加zone_type
            if "zone_type" not in props:
                props["zone_type"] = "居住用地"

        enhanced_feature = {
            "type": "Feature",
            "geometry": feature.get("geometry", {}),
            "properties": props,
        }
        enhanced["features"].append(enhanced_feature)

    return enhanced


def main():
    """主测试函数"""
    print("=" * 60)
    print("测试: 真实GIS数据出图效果")
    print("=" * 60)

    # 金田村中心坐标（WGS84）
    CENTER = (116.044146, 24.818629)

    # 加载真实GIS数据
    print("\n加载GIS数据...")

    road_data = load_geojson("wfs_lrdl.geojson")  # 道路线数据 (Y124等)
    water_data = load_geojson("wfs_hydl.geojson")  # 水系线数据 (金田河)
    poi_data = load_geojson("amap_pois_all.geojson")  # POI设施点
    boundary_data = load_geojson("amap_boundary_pingyuan.geojson")  # 平远县边界
    resa_data = load_geojson("wfs_resa.geojson")  # 居民地面数据
    resp_data = load_geojson("wfs_resp.geojson")  # 居民地点数据
    hyda_data = load_geojson("wfs_hyda.geojson")  # 水系面数据

    print(f"  道路数据: {len(road_data.get('features', []))} 条")
    print(f"  水系数据: {len(water_data.get('features', []))} 条")
    print(f"  POI数据: {len(poi_data.get('features', []))} 个")
    print(f"  边界数据: {len(boundary_data.get('features', []))} 个")
    print(f"  居民地面: {len(resa_data.get('features', []))} 个")
    print(f"  居民地点: {len(resp_data.get('features', []))} 个")
    print(f"  水系面: {len(hyda_data.get('features', []))} 个")

    # 构建图层列表
    print("\n构建图层...")

    # 1. 道路图层（基础设施）
    road_layer = {
        "geojson": enhance_features_for_rendering(road_data, "infrastructure"),
        "layer_type": "infrastructure",
        "layer_name": "道路网络",
    }

    # 2. 水系图层（基础设施）
    water_layer = {
        "geojson": enhance_features_for_rendering(water_data, "infrastructure"),
        "layer_type": "infrastructure",
        "layer_name": "水系网络",
    }

    # 3. POI设施点图层
    poi_layer = {
        "geojson": enhance_features_for_rendering(poi_data, "facility_point"),
        "layer_type": "facility_point",
        "layer_name": "现状设施",
    }

    # 4. 居民地面图层（功能区）
    resa_layer = {
        "geojson": enhance_features_for_rendering(resa_data, "function_zone"),
        "layer_type": "function_zone",
        "layer_name": "居民用地",
    }
    for f in resa_layer["geojson"]["features"]:
        f["properties"]["zone_type"] = "居住用地"

    # 5. 水系面图层（功能区 - 水域）
    hyda_layer = {
        "geojson": enhance_features_for_rendering(hyda_data, "function_zone"),
        "layer_type": "function_zone",
        "layer_name": "水域",
    }
    for f in hyda_layer["geojson"]["features"]:
        f["properties"]["zone_type"] = "水域"

    # 合并所有图层
    layers = [
        road_layer,
        water_layer,
        poi_layer,
        resa_layer,
        hyda_layer,
    ]

    print(f"总图层数: {len(layers)}")

    # 调用渲染函数
    print("\n调用 render_planning_map...")
    result = render_planning_map(
        layers=layers,
        title="金田村现状图 - 真实GIS数据",
        center=CENTER,
        zoom_start=14,
        show_legend=True,
        output_format="html",
    )

    # 输出结果
    if result.get("success"):
        print("\n渲染成功!")
        data = result.get("data", {})
        print(f"  地图标题: {data.get('title')}")
        print(f"  地图中心: {data.get('center')}")
        print(f"  图层信息:")
        for layer_info in data.get("layer_info", []):
            print(f"    - {layer_info['name']}: {layer_info['feature_count']} features")

        # 保存HTML
        output_path = project_root / "output" / "planning_map.html"
        map_html = data.get("map_html", "")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(map_html)

        print(f"\nHTML地图已保存: {output_path}")
        print(f"HTML大小: {len(map_html)} 字符")

    else:
        print(f"\n渲染失败: {result.get('error')}")

    # 输出样式配置信息
    print("\n" + "-" * 40)
    print("PLANNING_STYLES 配置:")
    for layer_type, styles in PLANNING_STYLES.items():
        if layer_type == "facility_type_icons":
            continue
        print(f"  {layer_type}: {len(styles)} 种样式")
        for subtype, style in styles.items():
            if "fill_color" in style:
                print(f"    - {subtype}: {style.get('fill_color')}")
            elif "color" in style:
                print(f"    - {subtype}: {style.get('color')}")

    print("=" * 60)
    print("测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()