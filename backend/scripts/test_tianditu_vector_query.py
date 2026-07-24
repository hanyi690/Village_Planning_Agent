"""测试天地图 MapServer REST Query 获取矢量数据

这是 ArcMap/QGIS "导出要素" 功能的 Python 实现。
通过 ArcGIS REST API 直接查询 MapServer 图层，获取 GeoJSON 矢量数据。

用法:
    cd backend
    python -m scripts.test_tianditu_vector_query
    python -m scripts.test_tianditu_vector_query --bbox 113.2 22.5 114.2 23.5
    python -m scripts.test_tianditu_vector_query --service SQSXWPSJ --layer 0
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.modules.data.providers.tianditu.gd_service import GDSpecializedService
from app.modules.data.providers.tianditu.wfs import WfsService
from app.core.settings import TIANDITU_API_KEY, GD_TIANDITU_TOKEN
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 默认测试 bbox: 广州
DEFAULT_BBOX = (113.2, 22.5, 114.2, 23.5)

# 广东省级服务配置
GD_TEST_SERVICES = {
    "SQSXWPSJ": {
        "name": "三区三线专题图",
        "layers": [
            (0, "永久基本农田保护"),
            (1, "城镇开发边界"),
            (2, "生态保护红线"),
        ],
    },
    "GDSTBHHX": {
        "name": "生态保护红线",
        "layers": [(0, "生态保护红线")],
    },
    "DZZHD": {
        "name": "地质灾害隐患点",
        "layers": [(0, "地质灾害隐患点")],
    },
}

# 国家级 WFS 图层
NATIONAL_WFS_LAYERS = [
    ("TDTService:RESA", "居民地面"),
    ("TDTService:RESP", "居民地点"),
    ("TDTService:HYDA", "水系面"),
    ("TDTService:HYDL", "水系线"),
    ("TDTService:LRDL", "公路"),
    ("TDTService:LRRL", "铁路"),
]


def test_mapserver_query(
    bbox: tuple[float, float, float, float],
    service_id: str | None = None,
    layer_id: int | None = None,
) -> dict:
    """测试 MapServer REST Query

    Args:
        bbox: 边界框 (min_lon, min_lat, max_lon, max_lat)
        service_id: 指定服务ID，None 则测试所有
        layer_id: 指定图层ID，None 则测试所有

    Returns:
        测试结果字典
    """
    print("\n" + "=" * 60)
    print("广东省级 MapServer REST Query 测试")
    print("=" * 60)

    gd = GDSpecializedService()

    if not GD_TIANDITU_TOKEN and not TIANDITU_API_KEY:
        print("\n⚠ 跳过: GD_TIANDITU_TOKEN 和 TIANDITU_API_KEY 均未配置")
        return {}

    results = {}
    output_dir = Path(__file__).parent.parent / "output" / "tianditu_test" / "gd"
    output_dir.mkdir(parents=True, exist_ok=True)

    services_to_test = GD_TEST_SERVICES
    if service_id:
        services_to_test = {service_id: GD_TEST_SERVICES.get(service_id, {})}

    for svc_id, svc_config in services_to_test.items():
        print(f"\n服务: {svc_config.get('name', svc_id)} ({svc_id})")

        layers_to_test = svc_config.get("layers", [])
        if layer_id is not None:
            layers_to_test = [(layer_id, f"图层{layer_id}")]

        for lid, lname in layers_to_test:
            print(f"\n  图层 {lid}: {lname}")
            print(f"  bbox: {bbox}")

            result = gd.query_mapserver_layer(svc_id, lid, bbox)

            if result.success:
                geojson = result.data.get("geojson", {})
                feature_count = len(geojson.get("features", []))
                print(f"  ✓ 成功: {feature_count} 个要素")

                # 保存 GeoJSON
                safe_name = lname.replace("/", "_")
                out_file = output_dir / f"{svc_id}_{lid}_{safe_name}.geojson"
                with open(out_file, "w", encoding="utf-8") as f:
                    json.dump(geojson, f, ensure_ascii=False, indent=2)
                print(f"  📁 已保存: {out_file}")

                results[f"{svc_id}_{lid}"] = {
                    "success": True,
                    "feature_count": feature_count,
                    "file": str(out_file),
                }
            else:
                print(f"  ✗ 失败: {result.error}")
                results[f"{svc_id}_{lid}"] = {
                    "success": False,
                    "error": result.error,
                }

    return results


def test_national_wfs(
    bbox: tuple[float, float, float, float],
    layer_name: str | None = None,
) -> dict:
    """测试国家级 WFS

    Args:
        bbox: 边界框
        layer_name: 指定图层名称，None 则测试所有

    Returns:
        测试结果字典
    """
    print("\n" + "=" * 60)
    print("国家级 WFS 测试 (1:100万比例尺，粒度较粗)")
    print("=" * 60)

    if not TIANDITU_API_KEY:
        print("\n⚠ 跳过: TIANDITU_API_KEY 未配置")
        return {}

    wfs = WfsService(TIANDITU_API_KEY)

    results = {}
    output_dir = Path(__file__).parent.parent / "output" / "tianditu_test" / "national"
    output_dir.mkdir(parents=True, exist_ok=True)

    layers_to_test = NATIONAL_WFS_LAYERS
    if layer_name:
        layers_to_test = [(ln, n) for ln, n in NATIONAL_WFS_LAYERS if n == layer_name]

    for wfs_layer, name in layers_to_test:
        print(f"\n图层: {name} ({wfs_layer})")

        result = wfs.get_wfs_data(wfs_layer, bbox, max_features=100)

        if result.success:
            geojson = result.data.get("geojson", {})
            feature_count = len(geojson.get("features", []))
            print(f"  ✓ 成功: {feature_count} 个要素")

            if feature_count > 0:
                # 保存 GeoJSON
                out_file = output_dir / f"{name}.geojson"
                with open(out_file, "w", encoding="utf-8") as f:
                    json.dump(geojson, f, ensure_ascii=False, indent=2)
                print(f"  📁 已保存: {out_file}")

            results[name] = {
                "success": True,
                "feature_count": feature_count,
                "file": str(out_file) if feature_count > 0 else None,
            }
        else:
            print(f"  ✗ 失败: {result.error}")
            results[name] = {"success": False, "error": result.error}

    return results


def main():
    parser = argparse.ArgumentParser(
        description="测试天地图矢量数据获取",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m scripts.test_tianditu_vector_query
  python -m scripts.test_tianditu_vector_query --bbox 113.2 22.5 114.2 23.5
  python -m scripts.test_tianditu_vector_query --service SQSXWPSJ --layer 0
  python -m scripts.test_tianditu_vector_query --wfs-only
        """,
    )
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"),
        help="自定义边界框",
    )
    parser.add_argument(
        "--service",
        type=str,
        help="指定广东省级服务ID (如 SQSXWPSJ)",
    )
    parser.add_argument(
        "--layer",
        type=int,
        help="指定图层ID",
    )
    parser.add_argument(
        "--wfs-only",
        action="store_true",
        help="只测试国家级 WFS",
    )
    parser.add_argument(
        "--gd-only",
        action="store_true",
        help="只测试广东省级 MapServer",
    )

    args = parser.parse_args()

    bbox = tuple(args.bbox) if args.bbox else DEFAULT_BBOX

    print("=" * 60)
    print("天地图矢量数据获取测试")
    print("=" * 60)
    print(f"测试区域 bbox: {bbox}")
    print(f"GD_TIANDITU_TOKEN: {'已配置' if GD_TIANDITU_TOKEN or TIANDITU_API_KEY else '未配置'}")
    print(f"TIANDITU_API_KEY: {'已配置' if TIANDITU_API_KEY else '未配置'}")

    gd_results = {}
    wfs_results = {}

    if not args.wfs_only:
        gd_results = test_mapserver_query(bbox, args.service, args.layer)

    if not args.gd_only:
        wfs_results = test_national_wfs(bbox, args.layer)

    # 汇总
    print("\n" + "=" * 60)
    print("测试汇总")
    print("=" * 60)

    gd_success = sum(1 for r in gd_results.values() if r.get("success"))
    gd_total = len(gd_results)
    wfs_success = sum(1 for r in wfs_results.values() if r.get("success"))
    wfs_total = len(wfs_results)

    print(f"\n广东省级 MapServer: {gd_success}/{gd_total} 成功")
    print(f"国家级 WFS: {wfs_success}/{wfs_total} 成功")

    # 提示数据精度
    print("\n" + "-" * 60)
    print("数据精度说明:")
    print("  - 广东省级 MapServer: 坐标系 CGCS2000，精度取决于服务发布时的数据源")
    print("  - 国家级 WFS: 1:100万比例尺 (2017版)，粒度较粗，主要城市数据较多")
    print("\n更高精度数据获取途径:")
    print("  - webmap.cn: 1:25万全国基础地理数据 (需注册下载)")
    print("  - 各省天地图节点: 可能提供更详细的本地矢量数据")
    print("=" * 60)


if __name__ == "__main__":
    main()
