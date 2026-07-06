#!/usr/bin/env python3
"""
End-to-end pipeline with REAL database reports.

Queries the actual dimension_reports table for session dc2a2e0e,
extracts metrics and spatial structure from L3 reports,
runs conflict detection → zone generation → map rendering.

Data sources:
  - DB: data/database/village_planning.db (dimension_reports table)
  - GIS: docs/gis/jintian_boundary/{boundary,landuse_current}.geojson

Output: docs/gis/output/
"""

import json
import sys
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

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
)

# ============================================================
# Config
# ============================================================

SID = "dc2a2e0e-b129-4e8e-a981-48ab6bec9082"
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "database", "village_planning.db")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "gis", "jintian_boundary")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "gis", "output")


def load_geojson(filename: str) -> Optional[Dict[str, Any]]:
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Any, filename: str) -> str:
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


# ============================================================
# Step 1: Load real L3 reports from DB
# ============================================================

def load_db_reports(session_id: str) -> Dict[str, Dict[str, Any]]:
    """Load latest L3 report per dimension from SQLite."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT dimension_key, CAST(summary AS TEXT), CAST(content AS TEXT), version "
        "FROM dimension_reports WHERE session_id = ? AND layer = 3 "
        "ORDER BY dimension_key, version DESC",
        (session_id,),
    )
    rows = cur.fetchall()
    conn.close()

    seen: Dict[str, Dict[str, Any]] = {}
    for dk, summ_str, content, ver in rows:
        if dk in seen:
            continue
        summ = {}
        try:
            summ = json.loads(summ_str) if summ_str else {}
        except json.JSONDecodeError:
            pass
        seen[dk] = {"summary": summ, "content": content, "version": ver}
    return seen


# ============================================================
# Step 2: Map DB metric names → semantics system fields
# ============================================================

def extract_semantics_summaries(reports: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Convert DB metric names to semantics-qualified field names."""

    # Map: (dimension_key, db_metric_name) → semantics field name
    FIELD_MAP = {
        ("land_use_planning", "建设用地规模_公顷"): "planned_construction_ha",
        ("land_use_planning", "耕地保有量_公顷"): "planned_farmland_ha",
        ("land_use_planning", "森林覆盖率_百分比"): "planned_forest_coverage_pct",
        ("settlement_planning", "current_population"): "current_population",
        ("settlement_planning", "target_population"): "planned_population",
        ("settlement_planning", "per_capita_construction_sqm"): "current_per_capita_construction_sqm",
        ("settlement_planning", "area_ha"): "planned_construction_ha",
        ("spatial_structure", "村庄建设边界面积_ha"): "planned_construction_ha",
        ("spatial_structure", "基本农田红线面积_ha"): "min_farmland_ha",
        ("spatial_structure", "生态保护红线面积_ha"): "min_ecological_redline_ha",
        ("spatial_structure", "人口"): "planned_population",
        ("ecological", "生态保护红线面积"): "min_ecological_redline_ha",
        ("ecological", "森林覆盖率_目标值"): "min_forest_coverage_pct",
        ("industry", "target_village_income"): "target_village_income_yuan",
        ("industry", "target_employment"): "target_employment_persons",
    }

    summaries: Dict[str, Dict[str, Any]] = {}

    for dk, report in reports.items():
        metrics = report["summary"].get("metrics", {})
        if not metrics:
            continue

        mapped: Dict[str, Any] = {}
        for db_key, db_val in metrics.items():
            qkey = f"{dk}.{db_key}"
            mapped_field = FIELD_MAP.get((dk, db_key))
            if mapped_field:
                mapped[mapped_field] = db_val
            # Also keep raw values under qualified keys for traceability
            mapped[qkey] = db_val

        # Extract structure pattern from content
        content = report.get("content", "")
        structure_pattern = _extract_structure_pattern(content)
        zone_names = _extract_zone_names(content)
        if structure_pattern:
            mapped["structure_pattern"] = structure_pattern
        if zone_names:
            mapped["zone_names"] = zone_names

        # Extract spatial & industry structure for conflict detection
        if dk == "spatial_structure" and structure_pattern:
            mapped["pattern"] = structure_pattern
        if dk == "industry":
            industry_pattern = _extract_structure_pattern(content)
            if industry_pattern:
                mapped["layout_direction"] = industry_pattern

        summaries[dk] = {"metrics": mapped}

    return summaries


def _extract_structure_pattern(content: str) -> str:
    """Extract spatial structure pattern like '一核一带三区'."""
    import re
    for pattern in [
        r"[一-鿿]+[一-鿿]+[一-鿿]+[一-鿿]+",
    ]:
        # Look for patterns with Chinese numbers: 一X 两X 三X etc.
        m = re.search(r'([一两三四五六七八九十]+[核带轴区组团心片圈廊点极]+[一两三四五六七八九十]+[核带轴区组团心片圈廊点极]+(?:[一两三四五六七八九十]+[核带轴区组团心片圈廊点极]+)*)', content)
        if m:
            return m.group(1)
    return ""


def _extract_zone_names(content: str) -> List[str]:
    """Extract zone names from function zone tables."""
    import re
    zones = []
    # Match zone names in table rows like | 生态农业发展区 | 1960.70 |
    for m in re.finditer(r'\|\s*([一-鿿]+[区带核组团心片])\s*\|', content):
        name = m.group(1)
        if name not in zones and len(name) >= 4:
            zones.append(name)
    return zones


# ============================================================
# Step 3: Build UnifiedSpatialIntent from real land use data
# ============================================================

def create_intent_from_report(reports: Dict[str, Dict[str, Any]]) -> UnifiedSpatialIntent:
    """Build zone intents from the real land_use_planning table data.

    Based on the land use table:
      - 耕地: 85.20 ha (3.62%) → 农业用地
      - 林地: 2193.30 ha (93.22%) → 生态绿地
      - 建设用地: 30.50 ha (1.30%) → split by DLBM
      - 水域: 35.99 ha (1.53%)
      - 其他土地: 7.90 ha (0.33%)

    The 土地用途分区 table:
      - 农田保护区: 78.83 ha (3.35%)
      - 一般农业区: 1881.54 ha (79.97%)
      - 村庄建设区: 30.50 ha (1.30%)
      - 生态保护区: 362.02 ha (15.38%)
    """
    total_area = 2352.56  # ha from the actual report

    # Extract spatial directions from content
    spatial_content = reports.get("spatial_structure", {}).get("content", "")
    settlement_content = reports.get("settlement_planning", {}).get("content", "")

    zones = [
        ZoneIntent(
            zone_id="residential_1",
            land_use="居住用地",
            dlbm="2121",
            area_ratio=10.50 / total_area,  # 现状宅基地 10.50 ha
            direction=Direction.CENTER,
            density=Density.MEDIUM,
            reference_feature="园寨、社前中心集聚组团",
        ),
        ZoneIntent(
            zone_id="industry_1",
            land_use="产业用地",
            dlbm="2124",
            area_ratio=5.33 / total_area,  # 80亩 ≈ 5.33ha 特色农业基地+加工
            direction=Direction.SOUTHWEST,
            density=Density.LOW,
            reference_feature="社前、田坑烤烟林芝种植基地",
        ),
        ZoneIntent(
            zone_id="public_service_1",
            land_use="公共服务用地",
            dlbm="2122",
            area_ratio=0.20 / total_area,  # 村级综合服务中心 0.20 ha
            direction=Direction.CENTER,
            density=Density.MEDIUM,
            reference_feature="园寨村级综合服务中心",
        ),
        ZoneIntent(
            zone_id="agriculture_1",
            land_use="农业用地",
            dlbm="1100",
            area_ratio=1881.54 / total_area,  # 一般农业区
            direction=Direction.SOUTH,
            density=Density.LOW,
            reference_feature="村域西南部生态农业发展区",
        ),
        ZoneIntent(
            zone_id="ecology_1",
            land_use="生态绿地",
            dlbm="1340",
            area_ratio=362.02 / total_area,  # 生态保护区
            direction=Direction.NORTHEAST,
            density=Density.LOW,
            reference_feature="东北部生态保育屏障区",
        ),
        ZoneIntent(
            zone_id="water_1",
            land_use="水域",
            dlbm="3100",
            area_ratio=35.99 / total_area,  # 水域
            direction=Direction.CENTER,
            density=Density.LOW,
            reference_feature="金田河沿线",
        ),
        ZoneIntent(
            zone_id="transport_1",
            land_use="交通用地",
            dlbm="2200",
            area_ratio=0.33 / total_area,  # 新增建设用地 (道路+设施)
            direction=Direction.CENTER,
            density=Density.LOW,
            reference_feature="Y122乡道及村道系统",
        ),
    ]

    return UnifiedSpatialIntent(
        zones=zones,
        metadata={
            "village": "金田村",
            "total_area_ha": total_area,
            "session_id": SID,
            "source": "dimension_reports from DB",
            "spatial_structure": "一核引领、一带串联、三区协同",
            "planning_year": 2035,
        },
    )


# ============================================================
# Main Pipeline
# ============================================================

def run_real_data_pipeline():
    print("\n" + "=" * 70)
    print("  REAL DATA PIPELINE: DB Reports → Conflict → Zones → Map")
    print(f"  Session: {SID}")
    print("=" * 70)

    # ---- Step 1: Load from DB ----
    print("\n[1/6] Loading L3 reports from database...")
    reports = load_db_reports(SID)
    print(f"  Loaded {len(reports)} dimensions: {sorted(reports.keys())}")
    for dk, r in reports.items():
        metrics = r["summary"].get("metrics", {})
        v = r["version"]
        print(f"    {dk} (v{v}): {len(metrics)} metrics, content={len(r['content'])} chars")

    # ---- Step 2: Map to semantics fields ----
    print("\n[2/6] Mapping DB metrics → semantics fields...")
    summaries = extract_semantics_summaries(reports)
    total_metrics = sum(len(s["metrics"]) for s in summaries.values())
    print(f"  Mapped {total_metrics} fields across {len(summaries)} dimensions")
    for dk, s in summaries.items():
        print(f"    {dk}: {json.dumps(s['metrics'], ensure_ascii=False, indent=2)[:300]}")

    # ---- Step 3: Load GIS data ----
    print("\n[3/6] Loading GIS reference data...")
    boundary = load_geojson("boundary.geojson")
    landuse = load_geojson("landuse_current.geojson")
    farmland = load_geojson("farmland_protection.geojson")
    eco = load_geojson("ecological_protection.geojson")
    hist = load_geojson("historical_protection.geojson")
    road = load_geojson("road_current.geojson")
    constr = load_geojson("construction_zone.geojson")
    hazard = load_geojson("geological_hazard_points.geojson")
    if not boundary or not landuse:
        print("  FATAL: GIS data not found")
        sys.exit(1)
    print(f"  Boundary: {len(boundary['features'])} features")
    print(f"  Landuse: {len(landuse['features'])} parcels")
    print(f"  Farmland protection: {len(farmland['features']) if farmland else 0} features")
    print(f"  Ecological protection: {len(eco['features']) if eco else 0} features")
    print(f"  Historical protection: {len(hist['features']) if hist else 0} features")
    print(f"  Roads: {len(road['features']) if road else 0} features")
    print(f"  Construction zones: {len(constr['features']) if constr else 0} features")
    print(f"  Hazard points: {len(hazard['features']) if hazard else 0} features")

    protection_zones = {}
    if farmland: protection_zones["farmland"] = farmland
    if eco: protection_zones["ecological"] = eco
    if hist: protection_zones["historical"] = hist

    # ---- Step 4: Build intent ----
    print("\n[4/6] Building UnifiedSpatialIntent from real land use data...")
    intent = create_intent_from_report(reports)
    print(f"  Intent: {len(intent.zones)} zones, total_area={intent.metadata['total_area_ha']} ha")
    print(f"  Structure: {intent.metadata['spatial_structure']}")
    for z in intent.zones:
        target_area = z.area_ratio * intent.metadata['total_area_ha']
        print(f"    {z.zone_id}: {z.land_use} target={target_area:.1f}ha ({z.area_ratio:.2%}) dir={z.direction.value}")

    # ---- Step 5: Run pipeline ----
    print("\n[5/6] Running Phase 0 + Phase 1 pipeline...")
    engine = SpatialLayoutEngine()
    t0 = time.time()

    conflict_report, resolution_report, configs = engine.full_pipeline(
        summaries=summaries,
        intent=intent,
        boundary_geojson=boundary,
        landuse_current_geojson=landuse,
        protection_zones=protection_zones if protection_zones else None,
        road_geojson=road,
        construction_zone_geojson=constr,
        hazard_points_geojson=hazard,
    )

    elapsed = time.time() - t0

    # Phase 0 results
    print(f"\n  Phase 0: {conflict_report.total_count} conflicts detected")
    for c in conflict_report.metric_conflicts:
        print(f"    [Metric] {c.description}")
    for v in conflict_report.constraint_violations:
        print(f"    [Constraint] {v.description}")
    for s in conflict_report.spatial_conflicts:
        print(f"    [Spatial] {s.dimension_a}: {s.structure_a} vs {s.dimension_b}: {s.structure_b}")

    if conflict_report.total_count > 0:
        print(f"\n  Resolutions:")
        for r in resolution_report.metric_resolutions:
            print(f"    [Metric] {r.winner_dimension} wins, value={r.adopted_value}")
        for r in resolution_report.constraint_resolutions:
            print(f"    [Constraint] planned={r.planned_value} {r.constraint_type.value}={r.constraint_value}")
        for r in resolution_report.spatial_resolutions:
            print(f"    [Spatial] {r.winner_dimension} ({r.winner_structure}) over {r.loser_dimension} ({r.loser_structure})")
    else:
        print(f"  No conflicts — all cross-dimension metrics consistent!")

    # Phase 1 results
    print(f"\n  Phase 1: {len(configs)} layer configs ({elapsed:.2f}s)")
    total_features = 0
    for cfg in configs:
        lt = cfg.get("layerType", "?")
        nf = len(cfg.get("geojson", {}).get("features", []))
        total_features += nf
        print(f"    {cfg.get('layerName')}: type={lt} features={nf}")

        if lt == "function_zone":
            total_gen_area = 0
            for f in cfg["geojson"]["features"]:
                p = f["properties"]
                area = p.get("area_ha", 0)
                total_gen_area += area
                print(f"      {p['zone_id']}: {p['land_use']} area={area:.2f}ha color={p['color']} actual_ratio={p.get('area_ratio', 0):.4f}")
            print(f"      TOTAL generated area: {total_gen_area:.2f} ha")

    # ---- Step 6: Save outputs ----
    print(f"\n[6/6] Saving outputs to {OUTPUT_DIR}...")

    # Save function_zone
    fz_configs = [c for c in configs if c["layerType"] == "function_zone"]
    if fz_configs:
        save_json(fz_configs[0]["geojson"], "output_function_zone.geojson")

    # Save GISLayerConfigs
    save_json(configs, "output_gis_layer_configs.json")

    # Save summary → metrics mapping for traceability
    trace = {
        "session_id": SID,
        "elapsed_seconds": round(elapsed, 2),
        "dimensions_loaded": sorted(reports.keys()),
        "semantic_summaries": {dk: s["metrics"] for dk, s in summaries.items()},
        "intent_zones": [
            {"zone_id": z.zone_id, "land_use": z.land_use, "area_ratio": z.area_ratio, "direction": z.direction.value}
            for z in intent.zones
        ],
        "phase0": {
            "total_conflicts": conflict_report.total_count,
            "metric_conflicts": [
                {"concept": c.concept.value, "semantics": c.semantics.value,
                 "a": f"{c.dimension_a}.{c.field_a}={c.value_a}",
                 "b": f"{c.dimension_b}.{c.field_b}={c.value_b}"}
                for c in conflict_report.metric_conflicts
            ],
            "constraint_violations": [
                {"concept": v.concept.value, "planned": v.planned_value, "constraint": v.constraint_value}
                for v in conflict_report.constraint_violations
            ],
            "spatial_conflicts": [
                {"a": s.dimension_a, "b": s.dimension_b}
                for s in conflict_report.spatial_conflicts
            ],
        },
        "phase1": {
            "layer_count": len(configs),
            "total_features": total_features,
            "zone_summary": [
                {"zone_id": f["properties"]["zone_id"], "land_use": f["properties"]["land_use"],
                 "area_ha": f["properties"]["area_ha"], "color": f["properties"]["color"]}
                for f in (fz_configs[0]["geojson"]["features"] if fz_configs else [])
            ],
        },
    }
    save_json(trace, "output_pipeline_report.json")

    print("\n" + "=" * 70)
    print("  DONE. Output files in docs/gis/output/:")
    print("  - output_function_zone.geojson   (function zone GeoJSON)")
    print("  - output_gis_layer_configs.json  (full GISLayerConfig)")
    print("  - output_pipeline_report.json    (traceable pipeline report)")
    print("=" * 70)

    return conflict_report, resolution_report, configs


if __name__ == "__main__":
    run_real_data_pipeline()
