"""金田村广东省天地图专题服务测试脚本

测试内容:
1. 服务连通性测试（各服务HTTP响应）
2. 数据获取测试（农田保护/生态红线/地质灾害点）
3. 坐标转换验证
4. 约束验证功能测试

金田村参数:
- village_name: 金田村委会
- village_code: 441426108004
- bbox: (115.9, 24.7, 116.2, 24.95) WGS84
- center: (116.04, 24.82)
"""
import os
import sys
import json
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from src.tools.geocoding.tianditu.gd_service import GDSpecializedService
from src.tools.geocoding.tianditu.gd_constants import (
    GD_SPECIALIZED_SERVICES,
    GD_LAYER_SERVICE_MAP,
    GD_LAYER_2_TYPES,
)
from src.orchestration.shared_gis_context import SharedGISContext
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 金田村测试参数
JINTIAN_PARAMS = {
    "village_name": "金田村委会",
    "village_code": "441426108004",
    "bbox": (115.9, 24.7, 116.2, 24.95),  # WGS84
    "center": (116.04, 24.82),
}


def test_service_availability():
    """测试服务连通性"""
    print("\n" + "="*60)
    print("1. 服务连通性测试")
    print("="*60)

    gd_service = GDSpecializedService()

    for service_id, service_info in GD_SPECIALIZED_SERVICES.items():
        print(f"\n测试服务: {service_id} - {service_info.get('name', '')}")

        result = gd_service.check_service_availability(service_id)

        if result.success:
            print(f"  ✅ 可用 (状态码: {result.metadata.get('status_code')})")
        else:
            print(f"  ❌ 不可用: {result.error}")

    print("\n连通性测试完成")


def test_fetch_constraint_data():
    """测试约束数据获取"""
    print("\n" + "="*60)
    print("2. 约束数据获取测试")
    print("="*60)

    gd_service = GDSpecializedService()
    bbox = JINTIAN_PARAMS["bbox"]

    for layer_type in GD_LAYER_2_TYPES:
        print(f"\n获取图层: {layer_type}")

        result = gd_service.fetch_constraint_data(layer_type, bbox)

        if result.success:
            data = result.data

            # WFS 数据
            if data.get("geojson"):
                geojson = data["geojson"]
                feature_count = len(geojson.get("features", []))
                print(f"  ✅ WFS 数据获取成功")
                print(f"  特征数量: {feature_count}")
                print(f"  数据来源: {result.metadata.get('source')}")

                # 输出示例特征
                if feature_count > 0:
                    first_feature = geojson["features"][0]
                    props = first_feature.get("properties", {})
                    print(f"  示例属性: {list(props.keys())[:5]}...")

            # WMS 瓦片
            elif data.get("wms_url"):
                print(f"  ✅ WMS 瓦片服务可用")
                print(f"  服务ID: {data.get('service_id')}")
                print(f"  服务名称: {data.get('service_name')}")
                print(f"  WMS URL: {data.get('wms_url')[:80]}...")

        else:
            print(f"  ❌ 获取失败: {result.error}")

    print("\n约束数据获取测试完成")


def test_shared_gis_context_integration():
    """测试 SharedGISContext 集成"""
    print("\n" + "="*60)
    print("3. SharedGISContext 集成测试")
    print("="*60)

    context = SharedGISContext(
        village_name=JINTIAN_PARAMS["village_name"],
        buffer_km=3.0
    )

    print(f"\n村庄名称: {context.village_name}")
    print(f"中心点: {context.center}")
    print(f"边界范围: {context.bbox}")

    # 测试 get_gd_constraint_data 方法
    for layer_type in ["farmland_protection", "ecological_protection", "three_zones_three_lines"]:
        print(f"\n获取约束数据: {layer_type}")

        data = context.get_gd_constraint_data(layer_type)

        if data:
            if data.get("type") == "tile_service":
                print(f"  ✅ 瓦片服务")
                print(f"  服务名称: {data.get('service_name')}")
            else:
                feature_count = len(data.get("features", []))
                print(f"  ✅ GeoJSON 数据")
                print(f"  特征数量: {feature_count}")
                print(f"  数据来源: {context._data_sources.get(layer_type, 'unknown')}")
        else:
            print(f"  ❌ 无数据")

    print("\nSharedGISContext 集成测试完成")


def test_coordinate_transform():
    """测试坐标转换"""
    print("\n" + "="*60)
    print("4. 坐标转换验证")
    print("="*60)

    gd_service = GDSpecializedService()

    # WGS84 bbox
    bbox_wgs84 = JINTIAN_PARAMS["bbox"]
    print(f"\nWGS84 bbox: {bbox_wgs84}")

    # 测试墨卡托转换
    bbox_mercator = gd_service._transform_bbox_for_request(bbox_wgs84, "EPSG:3857")
    print(f"墨卡托 bbox: {bbox_mercator}")

    # 测试 CGCS2000 转换（兼容）
    bbox_cgcs2000 = gd_service._transform_bbox_for_request(bbox_wgs84, "EPSG:4547")
    print(f"CGCS2000 bbox: {bbox_cgcs2000}")

    # 测试 GeoJSON 转换
    test_geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [12900000, 2850000]  # 墨卡托坐标
            },
            "properties": {"name": "test_point"}
        }]
    }

    try:
        import geopandas as gpd
        transformed = gd_service._transform_crs(test_geojson, "EPSG:3857")
        if transformed.get("features"):
            coords = transformed["features"][0]["geometry"]["coordinates"]
            print(f"\n墨卡托 -> WGS84 转换测试:")
            print(f"  墨卡托: [12900000, 2850000]")
            print(f"  WGS84: {coords}")
            print(f"  ✅ 坐标转换成功")
    except ImportError:
        print("\n⚠️ geopandas 未安装，跳过 GeoJSON 转换测试")

    print("\n坐标转换验证完成")


def compare_with_jintian_test_data():
    """与现有金田村测试数据对比"""
    print("\n" + "="*60)
    print("5. 与金田村现有数据对比")
    print("="*60)

    jintian_data_dir = project_root / "docs" / "gis" / "jintian_boundary"

    if not jintian_data_dir.exists():
        print(f"⚠️ 金田村测试数据目录不存在: {jintian_data_dir}")
        return

    # 加载现有边界数据
    boundary_file = jintian_data_dir / "boundary.geojson"
    if boundary_file.exists():
        print(f"\n加载现有边界数据: {boundary_file}")
        with open(boundary_file, 'r', encoding='utf-8') as f:
            boundary_data = json.load(f)

        features = boundary_data.get("features", [])
        print(f"  特征数量: {len(features)}")

        if features:
            # 计算边界 bbox
            coords = []
            for feature in features:
                geom = feature.get("geometry", {})
                if geom.get("type") == "Polygon":
                    for ring in geom.get("coordinates", []):
                        coords.extend(ring)
                elif geom.get("type") == "MultiPolygon":
                    for polygon in geom.get("coordinates", []):
                        for ring in polygon:
                            coords.extend(ring)

            if coords:
                min_lon = min(c[0] for c in coords)
                max_lon = max(c[0] for c in coords)
                min_lat = min(c[1] for c in coords)
                max_lat = max(c[1] for c in coords)
                existing_bbox = (min_lon, min_lat, max_lon, max_lat)
                print(f"  现有数据 bbox: {existing_bbox}")

                # 与测试 bbox 对比
                test_bbox = JINTIAN_PARAMS["bbox"]
                print(f"\n  对比分析:")
                print(f"    测试 bbox: {test_bbox}")
                print(f"    现有 bbox: {existing_bbox}")

                # 计算差异
                lon_diff = abs(test_bbox[2] - test_bbox[0] - (existing_bbox[2] - existing_bbox[0]))
                lat_diff = abs(test_bbox[3] - test_bbox[1] - (existing_bbox[3] - existing_bbox[1]))
                print(f"    经度范围差异: {lon_diff:.3f}°")
                print(f"    纬度范围差异: {lat_diff:.3f}°")
    else:
        print(f"⚠️ 边界数据文件不存在: {boundary_file}")

    print("\n数据对比完成")


def generate_test_report():
    """生成测试报告"""
    print("\n" + "="*60)
    print("6. 测试报告")
    print("="*60)

    report = {
        "test_date": "2026-04-27",
        "village": JINTIAN_PARAMS,
        "services": {},
        "results": {}
    }

    gd_service = GDSpecializedService()

    # 服务状态汇总
    for service_id, service_info in GD_SPECIALIZED_SERVICES.items():
        result = gd_service.check_service_availability(service_id)
        report["services"][service_id] = {
            "name": service_info.get("name"),
            "available": result.success,
            "error": result.error if not result.success else None,
        }

    # 数据获取汇总
    bbox = JINTIAN_PARAMS["bbox"]
    for layer_type in GD_LAYER_2_TYPES:
        result = gd_service.fetch_constraint_data(layer_type, bbox)
        report["results"][layer_type] = {
            "success": result.success,
            "data_type": "geojson" if result.data.get("geojson") else "tile_service",
            "feature_count": len(result.data.get("geojson", {}).get("features", [])),
            "error": result.error if not result.success else None,
        }

    # 输出报告
    output_dir = project_root / "output"
    output_dir.mkdir(exist_ok=True)

    report_file = output_dir / "gd_tianditu_test_report.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n测试报告已保存: {report_file}")
    print(f"\n服务可用性汇总:")
    for service_id, info in report["services"].items():
        status = "✅" if info["available"] else "❌"
        print(f"  {status} {service_id}: {info['name']}")

    print(f"\n数据获取汇总:")
    for layer_type, info in report["results"].items():
        status = "✅" if info["success"] else "❌"
        data_type = info["data_type"] if info["success"] else "失败"
        print(f"  {status} {layer_type}: {data_type}")


def main():
    """运行所有测试"""
    print("\n" + "="*60)
    print("广东省天地图专题服务 - 金田村测试")
    print("="*60)

    # 检查环境配置
    gd_token = os.getenv("GD_TIANDITU_TOKEN")
    tianditu_key = os.getenv("TIANDITU_API_KEY")

    print(f"\n环境配置:")
    print(f"  GD_TIANDITU_TOKEN: {'已配置' if gd_token else '未配置'}")
    print(f"  TIANDITU_API_KEY: {'已配置' if tianditu_key else '未配置'}")

    if not gd_token and not tianditu_key:
        print("\n⚠️ 请配置 GD_TIANDITU_TOKEN 或 TIANDITU_API_KEY")
        return

    # 运行测试
    test_service_availability()
    test_fetch_constraint_data()
    test_shared_gis_context_integration()
    test_coordinate_transform()
    compare_with_jintian_test_data()
    generate_test_report()

    print("\n" + "="*60)
    print("测试完成")
    print("="*60)


if __name__ == "__main__":
    main()