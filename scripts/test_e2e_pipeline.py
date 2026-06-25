#!/usr/bin/env python3
"""
End-to-end pipeline test: Phase 0 (Conflict) + Phase 1 (Zone Gen + Render)

Loads real jintian GIS data and simulates realistic L3 summaries,
runs the full SpatialLayoutEngine pipeline, and saves output GeoJSON
files for visual inspection in any GeoJSON viewer or GIS tool.

Output:
  docs/gis/jintian_boundary/output_function_zone.geojson  - generated zones
  docs/gis/jintian_boundary/output_gis_layer_configs.json  - full GISLayerConfig list
  docs/gis/jintian_boundary/output_pipeline_report.json    - conflict + resolution report

Usage:
  python scripts/test_e2e_pipeline.py
  python scripts/test_e2e_pipeline.py --with-protection
"""

import json
import sys
import os
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services.modules.gis.layout import (
    SpatialLayoutEngine,
    ZoneGenerator,
    MapRenderer,
    ZoneIntent,
    UnifiedSpatialIntent,
    FacilityIntent,
    AxisIntent,
    Direction,
    Density,
    get_zone_color,
    ZONE_TYPE_COLORS,
)
from app.services.modules.gis.layout.conflict_detector import ConflictReport
from app.services.modules.gis.layout.conflict_resolver import ResolutionReport


# ============================================================
# Data Loading
# ============================================================

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "gis", "jintian_boundary")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "gis", "output")


def load_geojson(filename: str) -> Optional[Dict[str, Any]]:
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        print(f"  SKIP: {filename} not found")
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Any, filename: str) -> str:
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  Saved: {path}")
    return path


# ============================================================
# Realistic L3 Summaries (from jintian actual report data)
# ============================================================

def create_realistic_l3_summaries() -> Dict[str, Dict[str, Any]]:
    """Create summaries based on actual jintian L3 report metrics.

    Key conflicts expected:
    - land_use.current_construction_ha (30.17) vs settlement_planning.current_construction_ha (31.0)
    - Different forest_coverage_rate across dimensions
    - Constraint validation: planned vs upper bounds
    """
    return {
        "land_use": {
            "metrics": {
                "current_construction_ha": 30.17,
                "current_farmland_ha": 85.2,
                "current_forest_coverage_pct": 65.0,
            },
        },
        "land_use_planning": {
            "metrics": {
                "current_construction_ha": 30.17,
                "planned_construction_ha": 17.66,
                "planned_farmland_ha": 127.18,
                "planned_ecological_ha": 273.5,
                "planned_residential_ha": 8.5,
                "planned_industry_ha": 2.3,
                "planned_public_service_ha": 3.2,
                "planned_traffic_ha": 3.66,
            },
        },
        "settlement_planning": {
            "metrics": {
                "current_construction_ha": 31.0,
                "planned_construction_ha": 17.66,
                "per_capita_construction_sqm": 555.0,
                "planned_population": 318,
                "residential_area_ha": 8.5,
                "expansion_direction": "east",
            },
        },
        "superior_planning": {
            "metrics": {
                "max_construction_ha": 30.5,
                "min_farmland_ha": 120.0,
                "ecological_redline_ha": 82.5,
            },
        },
        "ecological_green": {
            "metrics": {
                "ecological_redline_ha": 82.5,
                "current_forest_coverage_pct": 68.2,
            },
        },
        "ecological": {
            "metrics": {
                "ecological_redline_ha": 82.5,
                "min_forest_coverage_pct": 65.0,
            },
        },
        "spatial_structure": {
            "metrics": {
                "structure_pattern": "一核一带三区",
                "zone_names": ["核心区", "发展带", "产业区", "生态区", "农业区"],
                "zone_count": 5,
            },
        },
        "industry": {
            "metrics": {
                "layout_direction": "东部产业集聚区",
                "zone_count": 3,
            },
        },
    }


# ============================================================
# Realistic Zone Intent (based on jintian plan)
# ============================================================

def create_jintian_intent_from_plan() -> UnifiedSpatialIntent:
    """Create zone intent matching jintian's actual planning ratios.

    Total village area ~420 ha, breakdown:
    - 农业用地: ~40% (168 ha) - farmland is the dominant use
    - 生态绿地: ~30% (126 ha) - forested hills in north
    - 居住用地: ~8% (33.6 ha) - village center residential
    - 水域: ~5% (21 ha) - rivers and ponds
    - 产业用地: ~5% (21 ha) - eastern industrial cluster
    - 公共服务用地: ~3% (12.6 ha) - public facilities
    - 交通用地: ~3% (12.6 ha) - roads and paths
    - 商业用地: ~2% (8.4 ha) - commercial services
    """
    zones = [
        ZoneIntent(
            zone_id="residential_1",
            land_use="居住用地",
            dlbm="2121",
            area_ratio=0.08,
            direction=Direction.CENTER,
            density=Density.HIGH,
            reference_feature="村委会周边集中居住区",
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
            reference_feature="村庄中心公共服务区",
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
        ZoneIntent(
            zone_id="commercial_1",
            land_use="商业用地",
            dlbm="0500",
            area_ratio=0.02,
            direction=Direction.CENTER,
            density=Density.MEDIUM,
            reference_feature="村口商业服务点",
        ),
    ]

    return UnifiedSpatialIntent(
        zones=zones,
        metadata={
            "village": "金田村",
            "total_area_ha": 420.5,
            "planning_year": 2035,
            "source": "actual L3 report data",
        },
    )


# ============================================================
# Pipeline Execution
# ============================================================

def run_e2e_pipeline(with_protection: bool = False) -> Dict[str, Any]:
    """Run the full Phase 0 + Phase 1 pipeline with real data."""
    print("\n" + "=" * 70)
    print("  END-TO-END PIPELINE: Phase 0 + Phase 1 (Jintian Village)")
    print("=" * 70)

    # ---- Load GIS Data ----
    print("\n[1/5] Loading GIS reference data...")
    boundary = load_geojson("boundary.geojson")
    landuse = load_geojson("landuse_current.geojson")
    farmland_protection = load_geojson("farmland_protection.geojson") if with_protection else None
    ecological_protection = load_geojson("ecological_protection.geojson") if with_protection else None
    historical_protection = load_geojson("historical_protection.geojson") if with_protection else None

    if not boundary:
        print("  FATAL: boundary.geojson not found, cannot proceed")
        sys.exit(1)
    if not landuse:
        print("  FATAL: landuse_current.geojson not found, cannot proceed")
        sys.exit(1)

    # Count landuse parcels
    parcel_count = len(landuse.get("features", []))
    print(f"  Boundary: {len(boundary.get('features', []))} feature(s)")
    print(f"  Landuse current: {parcel_count} parcels")

    # DLBM distribution
    dlbm_counts: Dict[str, int] = {}
    for f in landuse.get("features", []):
        dlbm = str(f.get("properties", {}).get("DLBM", "unknown")).strip()
        dlbm_counts[dlbm] = dlbm_counts.get(dlbm, 0) + 1
    print(f"  DLBM distribution: {dict(sorted(dlbm_counts.items()))}")

    protection_zones = {}
    if with_protection:
        if farmland_protection:
            protection_zones["farmland"] = farmland_protection
            print(f"  Farmland protection: {len(farmland_protection.get('features', []))} features")
        if ecological_protection:
            protection_zones["ecological"] = ecological_protection
            print(f"  Ecological protection: {len(ecological_protection.get('features', []))} features")
        if historical_protection:
            protection_zones["historical"] = historical_protection
            print(f"  Historical protection: {len(historical_protection.get('features', []))} features")

    # ---- Create Inputs ----
    print("\n[2/5] Creating pipeline inputs...")
    summaries = create_realistic_l3_summaries()
    intent = create_jintian_intent_from_plan()
    print(f"  Summaries: {len(summaries)} dimensions")
    print(f"  Intent: {len(intent.zones)} zones, total ratio={intent.total_area_ratio:.2f}")
    for z in intent.zones:
        print(f"    {z.zone_id}: {z.land_use} ({z.dlbm}) ratio={z.area_ratio:.2f} dir={z.direction.value}")

    # ---- Run Pipeline ----
    print("\n[3/5] Running SpatialLayoutEngine.full_pipeline()...")
    engine = SpatialLayoutEngine()

    t0 = time.time()
    conflict_report, resolution_report, configs = engine.full_pipeline(
        summaries=summaries,
        intent=intent,
        boundary_geojson=boundary,
        landuse_current_geojson=landuse,
        protection_zones=protection_zones if protection_zones else None,
    )
    elapsed = time.time() - t0

    # ---- Phase 0 Results ----
    print(f"\n[4/5] Phase 0 Results (conflict detection + resolution):")
    print(f"  Total conflicts: {conflict_report.total_count}")
    print(f"  Metric conflicts: {len(conflict_report.metric_conflicts)}")
    for c in conflict_report.metric_conflicts:
        print(f"    {c.description}")
    print(f"  Constraint violations: {len(conflict_report.constraint_violations)}")
    for v in conflict_report.constraint_violations:
        print(f"    {v.description}")
    print(f"  Spatial conflicts: {len(conflict_report.spatial_conflicts)}")
    for s in conflict_report.spatial_conflicts:
        print(f"    {s.dimension_a}: {s.structure_a} vs {s.dimension_b}: {s.structure_b}")

    print(f"\n  Resolutions:")
    print(f"  Metric resolutions: {len(resolution_report.metric_resolutions)}")
    for r in resolution_report.metric_resolutions:
        print(f"    {r.description}")
    print(f"  Constraint resolutions: {len(resolution_report.constraint_resolutions)}")
    for r in resolution_report.constraint_resolutions:
        print(f"    {r.description}")
    print(f"  Spatial resolutions: {len(resolution_report.spatial_resolutions)}")
    for r in resolution_report.spatial_resolutions:
        print(f"    {r.winner_dimension}: {r.winner_structure} "
              f"(over {r.loser_dimension}: {r.loser_structure}), reason={r.reason}")

    # ---- Phase 1 Results ----
    print(f"\n[5/5] Phase 1 Results (zone generation + rendering):")
    print(f"  Layer configs: {len(configs)}")
    total_features = 0
    for config in configs:
        lt = config.get("layerType", "?")
        ln = config.get("layerName", "?")
        feats = config.get("geojson", {}).get("features", [])
        total_features += len(feats)
        print(f"  Layer: {ln} (type={lt}, features={len(feats)})")

        # Detailed zone info for function_zone
        if lt == "function_zone":
            total_area = 0
            for f in feats:
                props = f.get("properties", {})
                area = props.get("area_ha", 0)
                total_area += area
                land_use = props.get("land_use", "?")
                color = props.get("color", "?")
                zone_id = props.get("zone_id", "?")
                target = props.get("target_ratio", 0)
                actual = props.get("area_ratio", 0)
                print(f"    {zone_id}: {land_use} area={area:.2f}ha "
                      f"(target={target:.1%}, actual={actual:.1%}) color={color}")
            print(f"    TOTAL: {total_area:.2f} ha")

    print(f"\n  Pipeline completed in {elapsed:.2f}s")
    print(f"  Total features generated: {total_features}")

    # ---- Save Outputs ----
    print("\n" + "-" * 70)
    print("Saving output files...")

    # 1. Save function_zone GeoJSON
    fz_configs = [c for c in configs if c["layerType"] == "function_zone"]
    if fz_configs:
        save_json(fz_configs[0]["geojson"], "output_function_zone.geojson")

    # 2. Save all GISLayerConfigs
    configs_serializable = []
    for c in configs:
        configs_serializable.append(c)
    save_json(configs_serializable, "output_gis_layer_configs.json")

    # 3. Save pipeline report
    report = {
        "village": "金田村",
        "elapsed_seconds": round(elapsed, 2),
        "input": {
            "parcel_count": parcel_count,
            "dlbm_distribution": dlbm_counts,
            "zone_count": len(intent.zones),
            "dimension_count": len(summaries),
        },
        "phase0": {
            "total_conflicts": conflict_report.total_count,
            "metric_conflicts": [
                {
                    "concept": c.concept.value,
                    "semantics": c.semantics.value,
                    "dimension_a": c.dimension_a,
                    "value_a": c.value_a,
                    "dimension_b": c.dimension_b,
                    "value_b": c.value_b,
                    "relative_diff": round(c.relative_diff, 4),
                }
                for c in conflict_report.metric_conflicts
            ],
            "constraint_violations": [
                {
                    "concept": v.concept.value,
                    "planned": f"{v.planned_dimension}.{v.planned_field}={v.planned_value}",
                    "constraint": f"{v.constraint_dimension}.{v.constraint_field}={v.constraint_value}",
                    "type": v.constraint_type.value,
                }
                for v in conflict_report.constraint_violations
            ],
            "metric_resolutions": [
                {
                    "concept": r.concept.value,
                    "winner": r.winner_dimension,
                    "adopted_value": r.adopted_value,
                    "losers": [l.dimension for l in r.overridden],
                }
                for r in resolution_report.metric_resolutions
            ],
        },
        "phase1": {
            "layer_count": len(configs),
            "total_features": total_features,
            "function_zone_features": len(fz_configs[0]["geojson"]["features"]) if fz_configs else 0,
            "zone_summary": [
                {
                    "zone_id": f["properties"].get("zone_id"),
                    "land_use": f["properties"].get("land_use"),
                    "area_ha": f["properties"].get("area_ha"),
                    "target_ratio": f["properties"].get("target_ratio"),
                    "actual_ratio": f["properties"].get("area_ratio"),
                    "color": f["properties"].get("color"),
                }
                for f in (fz_configs[0]["geojson"]["features"] if fz_configs else [])
            ],
        },
    }
    save_json(report, "output_pipeline_report.json")

    # ---- Validation ----
    print("\n" + "-" * 70)
    print("Validation:")

    all_pass = True

    # Check function_zone output
    if not fz_configs:
        print("  FAIL: No function_zone layer generated")
        all_pass = False
    else:
        fz = fz_configs[0]["geojson"]
        if fz.get("type") != "FeatureCollection":
            print("  FAIL: Output is not FeatureCollection")
            all_pass = False
        else:
            print(f"  PASS: function_zone is FeatureCollection with {len(fz['features'])} features")

        # Check required properties
        required = ["zone_id", "land_use", "DLBM", "DLMC", "color", "area_ha"]
        for f in fz.get("features", []):
            props = f.get("properties", {})
            missing = [p for p in required if p not in props]
            if missing:
                print(f"  FAIL: Feature {props.get('zone_id', '?')} missing: {missing}")
                all_pass = False

        # Check geometry
        empty_geom = sum(1 for f in fz["features"] if not f.get("geometry", {}).get("coordinates"))
        if empty_geom:
            print(f"  WARN: {empty_geom} features have empty geometry")
        else:
            print(f"  PASS: All features have geometry")

        # Compare with reference landuse_planned if available
        landuse_planned = load_geojson("landuse_planned.geojson")
        if landuse_planned:
            planned_count = len(landuse_planned.get("features", []))
            generated_count = len(fz["features"])
            print(f"  INFO: Reference landuse_planned has {planned_count} features vs generated {generated_count}")

            # Area comparison by DLBM
            planned_areas: Dict[str, float] = {}
            for f in landuse_planned.get("features", []):
                dlbm = str(f.get("properties", {}).get("DLBM", "")).strip()
                area = f.get("properties", {}).get("DLMJ", 0) or f.get("properties", {}).get("SHAPE_Area", 0)
                planned_areas[dlbm] = planned_areas.get(dlbm, 0) + (area / 10000 if area > 1000 else area)

            generated_areas: Dict[str, float] = {}
            for f in fz["features"]:
                land_use = f["properties"].get("land_use", "")
                area = f["properties"].get("area_ha", 0)
                generated_areas[land_use] = generated_areas.get(land_use, 0) + area

            print(f"\n  Area Comparison (reference vs generated):")
            all_zone_types = sorted(set(list(planned_areas.keys()) + list(generated_areas.keys())))
            for zt in all_zone_types:
                ref = planned_areas.get(zt, 0)
                gen = generated_areas.get(zt, 0)
                marker = ""
                if ref > 0 and gen > 0:
                    diff_pct = abs(ref - gen) / ref * 100
                    marker = "OK" if diff_pct < 50 else "DIFF"
                elif gen > 0:
                    marker = "NEW"
                else:
                    marker = "MISS"
                print(f"    {zt}: ref={ref:.2f}ha gen={gen:.2f}ha [{marker}]")

    # Check boundary layer
    boundary_configs = [c for c in configs if c["layerType"] == "boundary"]
    if boundary_configs:
        print(f"  PASS: Boundary layer included")
    else:
        print(f"  WARN: No boundary layer in output")

    status = "PASS" if all_pass else "FAIL"
    print(f"\n  Overall: {status}")

    return {
        "passed": all_pass,
        "conflict_report": conflict_report,
        "resolution_report": resolution_report,
        "configs": configs,
    }


# ============================================================
# Main
# ============================================================

def main():
    with_protection = "--with-protection" in sys.argv

    print("=" * 70)
    print("  Village Planning Agent - End-to-End Pipeline Test")
    print("  Village: 金田村 (Jintian)")
    print("=" * 70)

    if with_protection:
        print("  Mode: with protection zone constraints")
    else:
        print("  Mode: without protection zones (use --with-protection to enable)")

    result = run_e2e_pipeline(with_protection=with_protection)

    if not result["passed"]:
        sys.exit(1)

    print("\n" + "=" * 70)
    print("  DONE. Check output files in docs/gis/output/")
    print("  - output_function_zone.geojson  (load in geojson.io or QGIS)")
    print("  - output_gis_layer_configs.json  (full GISLayerConfig)")
    print("  - output_pipeline_report.json    (conflict + zone report)")
    print("  - jintian_function_zone.html     (interactive map)")
    print("  - map_render.png                 (static comparison)")
    print("=" * 70)


if __name__ == "__main__":
    main()
