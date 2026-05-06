"""
独立测试脚本 - 空间布局生成

测试流程:
1. 加载测试数据（村庄边界、道路）
2. 创建测试规划方案
3. 调用生成器
4. 输出GeoJSON文件

用法:
  python scripts/test_spatial_layout.py
  python scripts/test_spatial_layout.py --output output/test_layout.geojson
"""

import argparse
import json
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.tools.core.planning_schema import (
    VillagePlanningScheme,
    PlanningZone,
    FacilityPoint,
    DevelopmentAxis,
    LocationBias,
    AdjacencyRule,
)
from src.tools.core.spatial_layout_generator import generate_spatial_layout_from_json


def create_test_planning_scheme() -> VillagePlanningScheme:
    """Create a test planning scheme for demonstration"""

    zones = [
        PlanningZone(
            zone_id="Z01",
            land_use="residential",
            area_ratio=0.35,
            location_bias=LocationBias(direction="center"),
            adjacency=AdjacencyRule(
                adjacent_to=["public_service"],
                avoid_adjacent_to=["industrial"]
            ),
            density="medium",
            description="居住用地，位于村庄中心区域"
        ),
        PlanningZone(
            zone_id="Z02",
            land_use="public_service",
            area_ratio=0.15,
            location_bias=LocationBias(direction="center"),
            adjacency=AdjacencyRule(adjacent_to=["residential"]),
            density="high",
            description="公共服务用地，靠近居住区"
        ),
        PlanningZone(
            zone_id="Z03",
            land_use="agricultural",
            area_ratio=0.30,
            location_bias=LocationBias(direction="south"),
            density="low",
            description="农业用地，位于南部平坦区域"
        ),
        PlanningZone(
            zone_id="Z04",
            land_use="ecological",
            area_ratio=0.15,
            location_bias=LocationBias(direction="edge"),
            density="low",
            description="生态绿地，位于村庄边缘"
        ),
        PlanningZone(
            zone_id="Z05",
            land_use="industrial",
            area_ratio=0.05,
            location_bias=LocationBias(direction="west"),
            adjacency=AdjacencyRule(avoid_adjacent_to=["residential", "public_service"]),
            density="low",
            description="产业用地，位于西部边缘"
        ),
    ]

    facilities = [
        FacilityPoint(
            facility_id="F01",
            facility_type="村委会",
            status="existing",
            location_hint="村庄中心位置",
            service_radius=500,
            priority="high"
        ),
        FacilityPoint(
            facility_id="F02",
            facility_type="文化活动站",
            status="new",
            location_hint="靠近村委会",
            service_radius=300,
            priority="medium"
        ),
        FacilityPoint(
            facility_id="F03",
            facility_type="卫生站",
            status="new",
            location_hint="居住区内",
            service_radius=400,
            priority="high"
        ),
    ]

    axes = [
        DevelopmentAxis(
            axis_id="A01",
            axis_type="primary",
            direction="east-west",
            reference_feature="沿东西向主干道",
            description="主要发展轴"
        ),
        DevelopmentAxis(
            axis_id="A02",
            axis_type="secondary",
            direction="north-south",
            reference_feature=None,
            description="次要发展轴"
        ),
    ]

    return VillagePlanningScheme(
        zones=zones,
        facilities=facilities,
        axes=axes,
        rationale="基于现状分析和村庄发展需求，规划布局以居住和农业为主导，公共服务设施集中布局，产业用地独立设置",
        development_axes=["沿东西向主干道发展", "南北向次要发展轴"],
        total_area_km2=2.0
    )


def create_test_boundary() -> dict:
    """Create a simple rectangular test boundary"""

    # Simple rectangle around test coordinates
    # Center: 116.044146, 24.818629
    center_lon, center_lat = 116.044146, 24.818629
    offset = 0.02  # ~2km

    coords = [
        [center_lon - offset, center_lat - offset],
        [center_lon + offset, center_lat - offset],
        [center_lon + offset, center_lat + offset],
        [center_lon - offset, center_lat + offset],
        [center_lon - offset, center_lat - offset],  # Close polygon
    ]

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "测试村庄边界"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [coords]
                }
            }
        ]
    }


def create_test_roads() -> dict:
    """Create simple test road network"""

    center_lon, center_lat = 116.044146, 24.818629

    # East-West main road
    ew_road = [
        [center_lon - 0.025, center_lat],
        [center_lon + 0.025, center_lat]
    ]

    # North-South secondary road
    ns_road = [
        [center_lon, center_lat - 0.025],
        [center_lon, center_lat + 0.025]
    ]

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "东西主干道", "road_type": "primary"},
                "geometry": {"type": "LineString", "coordinates": ew_road}
            },
            {
                "type": "Feature",
                "properties": {"name": "南北次要道路", "road_type": "secondary"},
                "geometry": {"type": "LineString", "coordinates": ns_road}
            }
        ]
    }


def main():
    parser = argparse.ArgumentParser(description="测试空间布局生成")
    parser.add_argument("--output", default="output/test_spatial_layout.geojson",
                        help="输出GeoJSON文件路径")
    parser.add_argument("--verbose", action="store_true", help="显示详细日志")
    args = parser.parse_args()

    print("=" * 60)
    print("空间布局生成测试")
    print("=" * 60)

    # Step 1: Create test data
    print("\n[1] 创建测试数据...")
    boundary = create_test_boundary()
    roads = create_test_roads()
    scheme = create_test_planning_scheme()

    print(f"  - 边界: 1个多边形")
    print(f"  - 道路: 2条线")
    print(f"  - 规划方案: {len(scheme.zones)}个分区, {len(scheme.facilities)}个设施, {len(scheme.axes)}条轴线")

    # Step 2: Generate spatial layout
    print("\n[2] 执行空间布局生成...")
    result = generate_spatial_layout_from_json(
        village_boundary=boundary,
        road_network=roads,
        planning_scheme=scheme,
        fallback_grid=True,
        merge_threshold=0.01
    )

    # Step 3: Check result
    print("\n[3] 检查结果...")
    if result.get("success"):
        data = result.get("data", {})
        stats = data.get("statistics", {})

        print("  ✓ 生成成功!")
        print(f"  - 分区数: {stats.get('zone_count', 0)}")
        print(f"  - 设施数: {stats.get('facility_count', 0)}")
        print(f"  - 轴线数: {stats.get('axis_count', 0)}")
        print(f"  - 总面积: {stats.get('total_area_km2', 0)} km²")
        print(f"  - 中心坐标: {data.get('center', [0, 0])}")

        # Step 4: Save output
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        geojson = data.get("geojson", {})
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(geojson, f, ensure_ascii=False, indent=2)

        print(f"\n[4] 输出已保存: {output_path}")

        # Show zone breakdown
        zones_geojson = data.get("zones_geojson", {})
        print("\n分区详情:")
        for feature in zones_geojson.get("features", []):
            props = feature.get("properties", {})
            print(f"  - {props.get('zone_id', '?')}: {props.get('zone_type', '?')}"
                  f" ({props.get('area_km2', 0)} km²)")

        if args.verbose:
            print("\n完整GeoJSON结构:")
            print(json.dumps(geojson, ensure_ascii=False, indent=2)[:500] + "...")

        return 0

    else:
        print("  ✗ 生成失败!")
        print(f"  错误: {result.get('error', 'Unknown error')}")
        return 1


if __name__ == "__main__":
    sys.exit(main())