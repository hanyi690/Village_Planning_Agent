"""Diagnose why SpatialLayoutEngine.generate_layout() produces 0 features.

Tests the full pipeline: DB reports → parse intent → generate_layout
with detailed logging at each step.
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database.engine import get_db_path


def load_db_reports():
    """Load L3 reports from DB."""
    import sqlite3
    db_path = get_db_path()
    print(f"[DB] Path: {db_path}")
    print(f"[DB] Exists: {os.path.exists(db_path)}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Find latest session
    cur = conn.execute(
        "SELECT session_id FROM dimension_reports WHERE layer = 3 "
        "ORDER BY generated_at DESC LIMIT 1"
    )
    row = cur.fetchone()
    if not row:
        print("[DB] No L3 reports found!")
        return None, None

    session_id = row["session_id"]
    print(f"[DB] Latest session: {session_id}")

    # Load all L3 reports for this session
    cur = conn.execute(
        "SELECT dimension_key, summary FROM dimension_reports "
        "WHERE session_id = ? AND layer = 3",
        (session_id,),
    )
    rows = cur.fetchall()
    conn.close()

    reports = {}
    for r in rows:
        dk = r["dimension_key"]
        summary_text = r["summary"] or ""
        parsed = json.loads(summary_text) if summary_text else {}
        reports[dk] = {
            "summary": {
                "metrics": parsed.get("metrics", {}),
                "key_points": parsed.get("key_points", []),
                "text_summary": parsed.get("text_summary", ""),
            },
            "content": parsed.get("text_summary", ""),
        }

    print(f"[DB] Loaded {len(reports)} L3 reports: {list(reports.keys())}")
    return session_id, reports


def test_parse_intent(reports, village_name="金田村"):
    """Test _parse_reports_to_intent with real DB reports."""
    from app.tools.gis.layout_tools import _parse_reports_to_intent

    print("\n" + "=" * 60)
    print("STEP 1: Parse reports to intent")
    print("=" * 60)

    result = _parse_reports_to_intent(reports=reports, village_name=village_name)
    print(f"[Parse] Success: {result.get('success')}")
    if not result.get("success"):
        print(f"[Parse] Error: {result.get('error')}")
        return None

    data = result.get("data", {})
    print(f"[Parse] Zone count: {data.get('zone_count')}")
    print(f"[Parse] Facility count: {data.get('facility_count')}")
    print(f"[Parse] Axis count: {data.get('axis_count')}")
    print(f"[Parse] Constraint count: {data.get('constraint_count')}")
    print(f"[Parse] Zones summary: {data.get('zones')}")

    intent_json = data.get("intent_json", {})
    zones = intent_json.get("zones", [])
    print(f"\n[Parse] Zone details:")
    for z in zones:
        print(f"  - {z.get('zone_id')}: {z.get('land_use')} "
              f"(area_ratio={z.get('area_ratio')}, "
              f"dlbm={z.get('dlbm')})")

    return intent_json


def test_generate_layout(intent_json):
    """Test generate_layout with parsed intent + real GIS data."""
    from app.services.modules.gis.layout.engine import SpatialLayoutEngine
    from app.tools.gis.layout_tools import _dict_to_intent

    print("\n" + "=" * 60)
    print("STEP 2: Generate layout")
    print("=" * 60)

    # Load real GIS data
    gis_data = _load_gis_data()
    if not gis_data:
        print("[GIS] Failed to load GIS data!")
        return None

    # Convert intent dict to UnifiedSpatialIntent
    intent = _dict_to_intent(intent_json)
    print(f"[Intent] {len(intent.zones)} zones, {len(intent.facilities)} facilities, "
          f"{len(intent.axes)} axes")
    for z in intent.zones:
        print(f"  zone: {z.zone_id} land_use='{z.land_use}' area_ratio={z.area_ratio} "
              f"dlbm='{z.dlbm}' direction={z.direction}")

    # Generate layout
    engine = SpatialLayoutEngine()

    # Test 1: Direct zone generator test
    print("\n--- Direct ZoneGenerator test ---")
    _test_zone_generator_direct(intent, gis_data)

    # Test 2: Full layout generation
    print("\n--- Full SpatialLayoutEngine test ---")
    configs = engine.generate_layout(
        intent=intent,
        boundary_geojson=gis_data.get("boundary_geojson"),
        landuse_current_geojson=gis_data.get("landuse_current_geojson"),
        protection_zones=gis_data.get("protection_zones"),
        road_geojson=gis_data.get("road_geojson"),
        hazard_points_geojson=gis_data.get("hazard_points_geojson"),
    )

    print(f"\n[Layout] Generated {len(configs)} layer configs")
    for c in configs:
        geojson = c.get("geojson", {})
        feat_count = len(geojson.get("features", []))
        print(f"  - {c.get('layerType')}: {feat_count} features "
              f"(name={c.get('layerName')})")

    return configs


def _test_zone_generator_direct(intent, gis_data):
    """Test ZoneGenerator directly with debug logging."""
    from app.services.modules.gis.layout.zone_generator import ZoneGenerator
    from app.services.modules.gis.utils.geojson_utils import geojson_to_geodataframe

    zg = ZoneGenerator()
    landuse_geojson = gis_data.get("landuse_current_geojson")
    boundary_geojson = gis_data.get("boundary_geojson")

    # Step A: Check landuse loading
    print(f"  [A] landuse_geojson has features: "
          f"{len(landuse_geojson.get('features', [])) if landuse_geojson else 'None'}")

    landuse_gdf = geojson_to_geodataframe(landuse_geojson) if landuse_geojson else None
    if landuse_gdf is None:
        print("  [A] FAIL: geojson_to_geodataframe returned None!")
        return

    print(f"  [A] GDF rows: {len(landuse_gdf)}, columns: {list(landuse_gdf.columns)}")
    print(f"  [A] CRS: {landuse_gdf.crs}")

    # Step B: Check DLBM values
    if "DLBM" in landuse_gdf.columns:
        dlbm_counts = landuse_gdf["DLBM"].value_counts().to_dict()
        print(f"  [B] DLBM values: {dict((str(k), v) for k, v in dlbm_counts.items())}")
    else:
        print("  [B] FAIL: No DLBM column in GDF!")
        print(f"  [B] Available columns: {list(landuse_gdf.columns)}")

    # Step C: Classify parcels
    parcel_zones = zg._classify_parcels(landuse_gdf)
    print(f"  [C] Classified zone types: "
          f"{dict((k, len(v)) for k, v in parcel_zones.items())}")

    # Step D: Match intent land_use against parcel_zones
    print(f"  [D] Intent zone land_use values vs parcel_zones keys:")
    for zone in intent.zones:
        matched = zone.land_use in parcel_zones
        print(f"    zone '{zone.zone_id}' land_use='{zone.land_use}' "
              f"→ matched={matched} "
              f"(parcel count: {len(parcel_zones.get(zone.land_use, []))})")

    # Step E: Compute boundary area
    landuse_projected = landuse_gdf.to_crs("EPSG:3857") if landuse_gdf.crs and landuse_gdf.crs.is_geographic else landuse_gdf
    boundary_area_sqm = zg._compute_boundary_area(boundary_geojson, landuse_projected)
    print(f"  [E] boundary_area_sqm: {boundary_area_sqm:.2f} "
          f"({boundary_area_sqm / 10000:.2f} ha)")

    # Step F: Build zone features one by one
    print(f"  [F] Building zone features:")
    for zone in intent.zones:
        feature = zg._build_zone_feature(
            zone, parcel_zones, boundary_area_sqm,
            landuse_gdf, landuse_projected
        )
        if feature:
            area_ha = feature["properties"].get("area_ha", 0)
            print(f"    {zone.zone_id} ({zone.land_use}): OK, area={area_ha} ha")
        else:
            # Diagnose WHY None
            land_use = zone.land_use
            parcel_indices = parcel_zones.get(land_use, [])
            print(f"    {zone.zone_id} ({zone.land_use}): NONE!")
            print(f"      parcel_indices: {len(parcel_indices)}")
            if parcel_indices:
                matched_gdf = landuse_gdf.loc[parcel_indices]
                valid_geoms = [g for g in matched_gdf.geometry if g is not None and not g.is_empty]
                print(f"      valid geometries: {len(valid_geoms)}")
                if valid_geoms:
                    from shapely.ops import unary_union
                    merged = unary_union(valid_geoms)
                    print(f"      merged.is_empty: {merged.is_empty}")
                    print(f"      merged.area (4326): {merged.area}")

    # Step G: Full generate
    result_geojson = zg.generate(
        intent=intent,
        boundary_geojson=boundary_geojson,
        landuse_current_geojson=landuse_geojson,
    )
    print(f"  [G] ZoneGenerator.generate() result: "
          f"{len(result_geojson.get('features', []))} features")


def _load_gis_data():
    """Load real GIS data for Jintian village."""
    # GIS data lives in docs/gis/jintian_boundary/ at project root
    # Resolve from this script's location: backend/scripts/diagnose_layout.py
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.normpath(os.path.join(script_dir, "..", ".."))
    data_dir = os.path.join(project_root, "docs", "gis", "jintian_boundary")
    print(f"[GIS] Data dir: {data_dir}")
    print(f"[GIS] Exists: {os.path.exists(data_dir)}")

    gis_data = {}

    # Boundary (Jintian village, NOT Pingyuan county)
    boundary_file = os.path.join(data_dir, "boundary_current.geojson")
    if os.path.exists(boundary_file):
        with open(boundary_file, "r", encoding="utf-8") as f:
            gis_data["boundary_geojson"] = json.load(f)
        feat_count = len(gis_data["boundary_geojson"].get("features", []))
        print(f"[GIS] boundary_current.geojson: {feat_count} features")
    else:
        print(f"[GIS] boundary_current.geojson NOT FOUND at {boundary_file}")

    # Landuse
    landuse_file = os.path.join(data_dir, "landuse_current.geojson")
    if os.path.exists(landuse_file):
        with open(landuse_file, "r", encoding="utf-8") as f:
            gis_data["landuse_current_geojson"] = json.load(f)
        feat_count = len(gis_data["landuse_current_geojson"].get("features", []))
        print(f"[GIS] landuse_current.geojson: {feat_count} features")
    else:
        print(f"[GIS] landuse_current.geojson NOT FOUND")

    # Roads
    road_file = os.path.join(data_dir, "roads_osm.geojson")
    if os.path.exists(road_file):
        with open(road_file, "r", encoding="utf-8") as f:
            gis_data["road_geojson"] = json.load(f)
        feat_count = len(gis_data["road_geojson"].get("features", []))
        print(f"[GIS] roads_osm.geojson: {feat_count} features")

    # Protection zones
    gis_data["protection_zones"] = {}

    # Hazard points
    gis_data["hazard_points_geojson"] = None

    return gis_data


def main():
    print("DIAGNOSIS: Why does generate_layout() produce 0 features?")
    print("=" * 60)

    # Step 0: Load DB reports
    session_id, reports = load_db_reports()
    if not reports:
        print("FAIL: No reports loaded from DB")
        return

    # Step 1: Parse intent
    intent_json = test_parse_intent(reports)
    if not intent_json:
        print("FAIL: Intent parsing failed")
        return

    # Save intent for reference
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "..", "test-screenshots")
    os.makedirs(out_dir, exist_ok=True)
    intent_path = os.path.join(out_dir, "diagnosis_intent.json")
    with open(intent_path, "w", encoding="utf-8") as f:
        json.dump(intent_json, f, ensure_ascii=False, indent=2)
    print(f"\n[Save] Intent saved to {intent_path}")

    # Step 2: Generate layout
    configs = test_generate_layout(intent_json)

    print("\n" + "=" * 60)
    print("DIAGNOSIS COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
