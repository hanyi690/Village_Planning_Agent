#!/usr/bin/env python3
"""
Phase 1 Test Script: ZoneGenerator + MapRenderer

Tests the function_zone GeoJSON generation from:
  1. UnifiedSpatialIntent with zone definitions
  2. landuse_current reference data (660 parcels from jintian)
  3. Boundary polygon

Validates:
  - ZoneGenerator produces valid GeoJSON with correct properties
  - Each zone feature has DLBM, DLMC, color, area_ha, zone_id
  - MapRenderer converts to GISLayerConfig format
  - SpatialLayoutEngine orchestrates the full pipeline
  - Color values match frontend PLANNING_COLORS

Usage:
  python scripts/test_zone_generator.py
"""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services.modules.gis.layout import (
    SpatialLayoutEngine,
    ZoneGenerator,
    MapRenderer,
    ZoneIntent,
    UnifiedSpatialIntent,
    Direction,
    Density,
    get_zone_color,
    ZONE_TYPE_COLORS,
)


def load_jintian_data():
    """Load jintian boundary test data."""
    base = os.path.join(os.path.dirname(__file__), "..", "docs", "gis", "jintian_boundary")

    with open(os.path.join(base, "boundary.geojson"), "r", encoding="utf-8") as f:
        boundary = json.load(f)

    with open(os.path.join(base, "landuse_current.geojson"), "r", encoding="utf-8") as f:
        landuse = json.load(f)

    return boundary, landuse


def create_jintian_intent():
    """Create a realistic UnifiedSpatialIntent for Jintian village.

    Based on actual planning data:
    - Total area: ~420 ha
    - Current construction: ~30 ha
    - Current farmland: ~85 ha
    - Forest coverage: ~65%
    """
    zones = [
        ZoneIntent(
            zone_id="residential_1",
            land_use="居住用地",
            dlbm="2121",
            area_ratio=0.08,
            direction=Direction.CENTER,
            density=Density.HIGH,
            reference_feature="村委会周边",
        ),
        ZoneIntent(
            zone_id="industry_1",
            land_use="产业用地",
            dlbm="2124",
            area_ratio=0.05,
            direction=Direction.EAST,
            density=Density.MEDIUM,
            reference_feature="村东部现有产业用地",
        ),
        ZoneIntent(
            zone_id="public_service_1",
            land_use="公共服务用地",
            dlbm="2122",
            area_ratio=0.03,
            direction=Direction.CENTER,
            density=Density.MEDIUM,
            reference_feature="村庄中心区",
        ),
        ZoneIntent(
            zone_id="agriculture_1",
            land_use="农业用地",
            dlbm="1100",
            area_ratio=0.40,
            direction=Direction.SOUTH,
            density=Density.LOW,
            reference_feature="南部农田保护区",
        ),
        ZoneIntent(
            zone_id="ecology_1",
            land_use="生态绿地",
            dlbm="1340",
            area_ratio=0.30,
            direction=Direction.NORTH,
            density=Density.LOW,
            reference_feature="北部山林地区",
        ),
        ZoneIntent(
            zone_id="water_1",
            land_use="水域",
            dlbm="3100",
            area_ratio=0.05,
            direction=Direction.CENTER,
            density=Density.LOW,
            reference_feature="金田河沿线",
        ),
        ZoneIntent(
            zone_id="transport_1",
            land_use="交通用地",
            dlbm="2200",
            area_ratio=0.03,
            direction=Direction.CENTER,
            density=Density.MEDIUM,
            reference_feature="主要道路沿线",
        ),
    ]

    return UnifiedSpatialIntent(
        zones=zones,
        metadata={"village": "金田村", "total_area_ha": 420.5},
    )


def test_zone_generator():
    """Test ZoneGenerator with jintian reference data."""
    print("\n" + "=" * 60)
    print("TEST 1: ZoneGenerator with Jintian Reference Data")
    print("=" * 60)

    try:
        boundary, landuse = load_jintian_data()
    except FileNotFoundError as e:
        print(f"  SKIP: Reference data not found: {e}")
        return True

    intent = create_jintian_intent()
    print(f"\n  Intent: {len(intent.zones)} zones, total ratio={intent.total_area_ratio:.2f}")
    for z in intent.zones:
        print(f"    {z.zone_id}: {z.land_use} ({z.dlbm}) ratio={z.area_ratio:.2f}")

    generator = ZoneGenerator()
    result = generator.generate(
        intent=intent,
        boundary_geojson=boundary,
        landuse_current_geojson=landuse,
    )

    all_pass = True

    # Verify output is valid GeoJSON FeatureCollection
    print(f"\n  Output: {len(result.get('features', []))} features")
    if result.get("type") != "FeatureCollection":
        print("  FAIL: Output is not a FeatureCollection")
        all_pass = False
    else:
        print("  PASS: Output is a FeatureCollection")

    # Verify each feature has required properties
    required_props = ["zone_id", "land_use", "DLBM", "DLMC", "color", "area_ha"]
    for feature in result.get("features", []):
        props = feature.get("properties", {})
        missing = [p for p in required_props if p not in props]
        if missing:
            print(f"  FAIL: Feature {props.get('zone_id', '?')} missing: {missing}")
            all_pass = False
        else:
            zone_id = props["zone_id"]
            land_use = props["land_use"]
            area = props["area_ha"]
            color = props["color"]
            print(f"    {zone_id}: {land_use}, area={area:.2f}ha, color={color}")

    # Verify colors match PLANNING_COLORS
    print(f"\n  Color validation:")
    for feature in result.get("features", []):
        props = feature.get("properties", {})
        land_use = props.get("land_use", "")
        actual_color = props.get("color", "")
        expected = get_zone_color(land_use)
        if actual_color == expected["fill"]:
            print(f"    PASS: {land_use} color={actual_color}")
        else:
            print(f"    FAIL: {land_use} color={actual_color}, expected={expected['fill']}")
            all_pass = False

    # Verify geometry is not empty
    print(f"\n  Geometry validation:")
    empty_count = 0
    for feature in result.get("features", []):
        geom = feature.get("geometry", {})
        coords = geom.get("coordinates", [])
        if not coords:
            empty_count += 1
    if empty_count == 0:
        print(f"    PASS: All features have geometry")
    else:
        print(f"    FAIL: {empty_count} features have empty geometry")
        all_pass = False

    return all_pass


def test_map_renderer():
    """Test MapRenderer conversion to GISLayerConfig."""
    print("\n" + "=" * 60)
    print("TEST 2: MapRenderer → GISLayerConfig")
    print("=" * 60)

    try:
        boundary, landuse = load_jintian_data()
    except FileNotFoundError:
        print("  SKIP: Reference data not found")
        return True

    intent = create_jintian_intent()
    generator = ZoneGenerator()
    function_zone = generator.generate(
        intent=intent,
        boundary_geojson=boundary,
        landuse_current_geojson=landuse,
    )

    renderer = MapRenderer()
    configs = renderer.render(
        layers={"function_zone": function_zone},
        boundary_geojson=boundary,
    )

    all_pass = True

    print(f"\n  Rendered {len(configs)} layer configs:")
    for config in configs:
        layer_type = config.get("layerType", "")
        layer_name = config.get("layerName", "")
        features = config.get("geojson", {}).get("features", [])
        print(f"    {layer_name}: type={layer_type}, features={len(features)}")

    # Verify GISLayerConfig structure
    required_keys = ["geojson", "layerType", "layerName"]
    for config in configs:
        missing = [k for k in required_keys if k not in config]
        if missing:
            print(f"  FAIL: Config missing keys: {missing}")
            all_pass = False
        else:
            print(f"  PASS: Config has all required keys")

    # Verify boundary layer included
    boundary_configs = [c for c in configs if c["layerType"] == "boundary"]
    if boundary_configs:
        print(f"  PASS: Boundary layer included")
    else:
        print(f"  FAIL: Boundary layer missing")
        all_pass = False

    # Verify function_zone layer
    fz_configs = [c for c in configs if c["layerType"] == "function_zone"]
    if fz_configs:
        print(f"  PASS: function_zone layer included")
    else:
        print(f"  FAIL: function_zone layer missing")
        all_pass = False

    return all_pass


def test_full_pipeline():
    """Test SpatialLayoutEngine full pipeline."""
    print("\n" + "=" * 60)
    print("TEST 3: SpatialLayoutEngine Full Pipeline")
    print("=" * 60)

    try:
        boundary, landuse = load_jintian_data()
    except FileNotFoundError:
        print("  SKIP: Reference data not found")
        return True

    # Phase 0 data
    summaries = {
        "land_use": {
            "metrics": {
                "current_construction_ha": 30.17,
                "current_farmland_ha": 85.2,
                "forest_coverage_rate": 65.0,
            }
        },
        "land_use_planning": {
            "metrics": {
                "current_construction_ha": 30.17,
                "planned_construction_ha": 17.66,
                "planned_farmland_ha": 127.18,
            }
        },
        "settlement_planning": {
            "metrics": {
                "current_construction_ha": 31.0,
                "planned_construction_ha": 17.66,
            }
        },
    }

    intent = create_jintian_intent()
    engine = SpatialLayoutEngine()

    conflict_report, resolution_report, configs = engine.full_pipeline(
        summaries=summaries,
        intent=intent,
        boundary_geojson=boundary,
        landuse_current_geojson=landuse,
    )

    all_pass = True

    # Phase 0 results
    print(f"\n  Phase 0: {conflict_report.total_count} conflicts, "
          f"{len(resolution_report.metric_resolutions)} resolutions")

    # Phase 1 results
    print(f"  Phase 1: {len(configs)} layer configs")
    for config in configs:
        print(f"    {config.get('layerName', '?')}: {config.get('layerType', '?')}")

    # Verify complete output
    if configs:
        print(f"  PASS: Full pipeline produces output")
    else:
        print(f"  FAIL: No output from full pipeline")
        all_pass = False

    return all_pass


def test_colors_sync():
    """Test that backend colors match frontend PLANNING_COLORS."""
    print("\n" + "=" * 60)
    print("TEST 4: Color Synchronization Check")
    print("=" * 60)

    # Frontend PLANNING_COLORS.function_zone (from gis.ts)
    frontend_colors = {
        "居住用地": "#FFD700",
        "产业用地": "#FF6B6B",
        "公共服务用地": "#4A90D9",
        "生态绿地": "#90EE90",
        "交通用地": "#808080",
        "水域": "#87CEEB",
        "农业用地": "#8B4513",
        "商业用地": "#FFA500",
    }

    all_pass = True
    for zone_type, expected_fill in frontend_colors.items():
        backend_color = get_zone_color(zone_type)
        actual_fill = backend_color.get("fill", "")
        if actual_fill == expected_fill:
            print(f"  PASS: {zone_type} fill={actual_fill}")
        else:
            print(f"  FAIL: {zone_type} fill={actual_fill}, expected={expected_fill}")
            all_pass = False

    return all_pass


def test_extended_dlbm_mapping():
    """Test that extended DLBM codes from jintian data are properly mapped."""
    print("\n" + "=" * 60)
    print("TEST 5: Extended DLBM Mapping")
    print("=" * 60)

    from app.services.modules.gis.layout.zone_generator import resolve_zone_type_for_dlbm

    # DLBM codes found in actual jintian landuse_current data
    jintian_dlbms = {
        "1100": "农业用地",   # 耕地
        "1200": "农业用地",   # 园地
        "1400": "生态绿地",   # 草地
        "2121": "居住用地",   # 宅基地
        "3100": "水域",       # 水域
        "1340": "生态绿地",   # 商品林
        "1350": "生态绿地",   # 生态林
        "1510": "农业用地",   # 设施农用地
        "2122": "公共服务用地", # 公共服务设施用地
        "2124": "产业用地",   # 经营性建设用地
        "2125": "公共服务用地", # 公共服务设施用地
        "2126": "交通用地",   # 村内交通用地
        "2200": "交通用地",   # 对外交通用地
        "2270": "农业用地",   # 水利设施用地
        "3200": "农业用地",   # 自然保留地
    }

    all_pass = True
    for dlbm, expected_zone in jintian_dlbms.items():
        result = resolve_zone_type_for_dlbm(dlbm)
        if result == expected_zone:
            print(f"  PASS: DLBM={dlbm} -> {result}")
        else:
            print(f"  FAIL: DLBM={dlbm} -> {result}, expected={expected_zone}")
            all_pass = False

    return all_pass


def main():
    """Run all Phase 1 tests."""
    print("=" * 60)
    print("Phase 1 Test Suite: ZoneGenerator + MapRenderer")
    print("=" * 60)

    results = {
        "ZoneGenerator": test_zone_generator(),
        "MapRenderer": test_map_renderer(),
        "Full Pipeline": test_full_pipeline(),
        "Color Sync": test_colors_sync(),
        "Extended DLBM": test_extended_dlbm_mapping(),
    }

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")

    total = len(results)
    passed = sum(1 for v in results.values() if v)
    print(f"\n  {passed}/{total} tests passed")

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
