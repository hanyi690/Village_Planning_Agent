"""Test KG builder → new query templates → PARSE tool call integration.

Bare-metal test: builds the KG from real Jintian data, runs every query template,
and verifies the PARSE agent tool execution flow. No LLM calls — pure data path.

Usage:
  cd backend
  python scripts/test_kg_parse_integration.py
"""

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure backend is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "gis" / "jintian"


# ── Helpers ──────────────────────────────────────────────────────────


def load_gis_data() -> Dict[str, Any]:
    """Load all current + planned GeoJSON layers.

    Delegates to catalog.loaders for unified loading.
    """
    from app.modules.gis.data.catalog.loaders import load_all

    return load_all()


def print_section(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def print_result(ok: bool, label: str, detail: str = "") -> None:
    icon = "✅" if ok else "❌"
    extra = f" — {detail}" if detail else ""
    print(f"  {icon} {label}{extra}")


# ── Main test ────────────────────────────────────────────────────────


def main():
    total_start = time.time()
    failures: List[str] = []

    # ── Step 1: Load data ──────────────────────────────────────────
    print_section("Step 1: Load GIS data")
    gis_data = load_gis_data()
    keys = sorted(gis_data.keys())
    for k in keys:
        fc = gis_data[k]
        n = len(fc.get("features", [])) if isinstance(fc, dict) else "?"
        print(f"  {k}: {n} features")
    print_result(len(gis_data) >= 4, "GIS data loaded", f"{len(gis_data)} layers")

    landuse = gis_data.get("landuse_current_geojson")
    if not landuse:
        print("  ❌ landuse_current_geojson not found — aborting")
        return

    # ── Step 2: Build KG ───────────────────────────────────────────
    print_section("Step 2: Build PlanningKG")

    from app.modules.kg.builder import PlanningKG

    # Ingest typed parcels
    from app.modules.data import ingest_current_landuse
    landuse_path = DATA_DIR / "current" / "landuse.geojson"
    typed_parcels, _warnings = ingest_current_landuse(str(landuse_path))
    print(f"  Typed parcels: {len(typed_parcels)}")

    # Ingest annotations
    from app.modules.data import ingest_feature
    ann_path = DATA_DIR / "current" / "annotation.geojson"
    annotations = []
    if ann_path.exists():
        annotations, _ = ingest_feature(str(ann_path), "current_annotation")
        print(f"  Annotations: {len(annotations)}")

    # Ingest roads
    road_path = DATA_DIR / "current" / "road.geojson"
    roads = []
    if road_path.exists():
        roads, _ = ingest_feature(str(road_path), "current_road")
        print(f"  Roads: {len(roads)}")

    # Build KG
    t0 = time.time()
    kg = PlanningKG(village_name="金田村")
    kg.build_from_reports(
        reports={},
        parcels=typed_parcels,
        landuse_geojson=landuse,
        gis_data=gis_data,
    )
    if annotations:
        kg.add_annotations(annotations)
    if roads:
        kg.add_roads(roads)
    build_time = time.time() - t0

    triples = kg.get_triple_count()
    print_result(triples > 1000, "KG built", f"{triples} triples in {build_time:.1f}s")

    # ── Step 3: Register KG with manager ───────────────────────────
    from app.modules.kg.manager import get_kg_manager
    manager = get_kg_manager()
    manager.register_session("test_integration", kg)
    print(f"  KGManager: session registered")

    # ── Step 4: Test every query template ──────────────────────────
    print_section("Step 3: Test query templates")

    from app.modules.kg.query import QUERY_TEMPLATES, query_kg

    # Template → expected min rows (None = no minimum, just that it runs)
    template_expectations = {
        # Original templates
        "get_constraints": 1,
        "get_constraint_by_field": 0,  # needs field_name param
        "get_parcels_by_dlbm": 0,      # needs dlbm param
        "get_parcels_by_zone_type": 0, # needs zone_type param
        "count_by_zone_type": 1,
        "get_zone_restrictions": 0,
        "get_indicators": 0,
        "check_protected_parcels": 1,
        "get_adjacent_parcels": 1,
        "get_all_projects": 0,
        "get_project_indicators": 0,
        "get_regulation_impacts": 0,
        "get_facility_serve_areas": 0,
        "get_facility_locations": 1,
        "get_road_network": 1,
        "get_water_bodies": 1,
        "get_parcels_by_facility": 0,
        "get_designated_zones": 1,
        "count_entity_types": 1,

        # === NEW P0 templates ===
        "get_village_parcels": 100,           # Should have 100+ parcels
        "get_parcel_neighbors": 0,             # Needs bsm param
        "get_parcel_detail": 0,                # Needs bsm param
        "count_by_vne": 1,                     # Should have VNE classes
        "count_by_planning_zone": 1,           # Should have planning zones
        "get_facilities_by_type": 1,           # Should have facilities
        "get_protected_parcels_detail": 0,     # Depends on spatial containment
        "get_parcels_near_point": 0,           # Needs coordinate params

        # === NEW P1 templates ===
        "get_three_zones": 1,                  # Should have 三区 data
        "get_three_lines": 1,                  # Should have 三线 data
        "get_village_anchors": 1,              # Should have village anchors

        # === NEW P2 templates (reserved — should run without error) ===
        "get_terrain_profile": 0,              # No DEM data yet
        "get_parcels_by_slope": 0,             # No DEM data yet
        "get_parcels_by_aspect": 0,            # No DEM data yet
    }

    results: Dict[str, Dict] = {}
    for tname, min_rows in template_expectations.items():
        try:
            # Supply required params for templates that need them
            params = {}
            if tname == "get_parcels_by_dlbm":
                params["dlbm"] = "3100"
            elif tname == "get_parcels_by_zone_type":
                params["zone_type"] = "农业用地"
            elif tname == "get_constraint_by_field":
                params["field_name"] = "farmland"
            elif tname == "get_parcel_neighbors":
                # Find a parcel BSM with neighbors
                adj = query_kg(kg, "get_adjacent_parcels")
                if adj and len(adj) > 0:
                    params["bsm"] = adj[0].get("a_bsm", "")
            elif tname == "get_parcel_detail":
                # Pick first parcel BSM from village_parcels
                all_p = query_kg(kg, "get_village_parcels")
                if all_p and len(all_p) > 0:
                    params["bsm"] = all_p[0].get("bsm", "")
            elif tname == "get_parcels_near_point":
                params = {"min_lon": "114", "max_lon": "115", "min_lat": "24", "max_lat": "25"}

            rows = query_kg(kg, tname, **params)
            n = len(rows)
            ok = n >= min_rows if min_rows > 0 else True

            # For 0-min templates, check at least no error
            if isinstance(rows, list) and len(rows) > 0:
                first = rows[0]
                if isinstance(first, dict) and "error" in first:
                    ok = False

            results[tname] = {"rows": n, "ok": ok, "min": min_rows}
            detail = f"{n} rows (min={min_rows})"
            if n > 0 and min_rows == 0:
                detail += " 🎉 has data!"
            print_result(ok, tname, detail)
            if not ok:
                failures.append(f"Template '{tname}': {n} rows < {min_rows} expected")

        except Exception as e:
            print_result(False, tname, str(e)[:100])
            failures.append(f"Template '{tname}': {e}")

    # ── Step 5: Test PARSE tool call flow ──────────────────────────
    print_section("Step 4: Test PARSE tool call flow")

    import asyncio
    from app.agent.gis.parse.agent import _execute_tool_call, _get_current_parse_kg
    from app.agent.gis.parse.agent import set_spatial_context
    from app.modules.spatial_ops import compute_spatial_context

    # Compute spatial context
    ctx = compute_spatial_context(gis_data)
    print(f"  SpatialContext: {ctx.parcel_count} parcels, "
          f"{len(ctx.natural_villages)} villages, "
          f"{len(ctx.facility_anchors)} facility anchors, "
          f"terrain_profile={'present' if ctx.terrain_profile else 'none'}")

    set_spatial_context(ctx)

    # Test KG tool calls via _execute_tool_call (same path PARSE agent uses)
    async def test_parse_tool_calls():
        tests = []

        # Test 1: count_by_zone_type
        r = await _execute_tool_call("query_village_kg", {"template_name": "count_by_zone_type"})
        data = json.loads(r)
        ok = isinstance(data, list) and len(data) > 0
        tests.append(("count_by_zone_type", ok, f"{len(data)} zone types"))

        # Test 2: count_by_vne
        r = await _execute_tool_call("query_village_kg", {"template_name": "count_by_vne"})
        data = json.loads(r)
        ok = isinstance(data, list) and len(data) > 0
        tests.append(("count_by_vne", ok, f"{len(data)} VNE classes"))

        # Test 3: get_three_zones
        r = await _execute_tool_call("query_village_kg", {"template_name": "get_three_zones"})
        data = json.loads(r)
        ok = isinstance(data, list)
        tests.append(("get_three_zones", ok, f"{len(data)} zones"))

        # Test 4: get_three_lines
        r = await _execute_tool_call("query_village_kg", {"template_name": "get_three_lines"})
        data = json.loads(r)
        ok = isinstance(data, list)
        tests.append(("get_three_lines", ok, f"{len(data)} lines"))

        # Test 5: get_village_anchors
        r = await _execute_tool_call("query_village_kg", {"template_name": "get_village_anchors"})
        data = json.loads(r)
        ok = isinstance(data, list) and len(data) > 0
        tests.append(("get_village_anchors", ok, f"{len(data)} villages"))

        # Test 6: get_facilities_by_type
        r = await _execute_tool_call("query_village_kg", {"template_name": "get_facilities_by_type"})
        data = json.loads(r)
        ok = isinstance(data, list) and len(data) > 0
        tests.append(("get_facilities_by_type", ok, f"{len(data)} facilities"))

        # Test 7: get_protected_parcels_detail
        r = await _execute_tool_call("query_village_kg", {"template_name": "get_protected_parcels_detail"})
        data = json.loads(r)
        ok = isinstance(data, list)
        tests.append(("get_protected_parcels_detail", ok, f"{len(data)} protected parcels"))

        # Test 8: get_road_network (optimized — check road_level field)
        r = await _execute_tool_call("query_village_kg", {"template_name": "get_road_network"})
        data = json.loads(r)
        ok = isinstance(data, list) and "road_level" in (data[0] if data else {})
        tests.append(("get_road_network (+road_level)", ok, f"{len(data)} roads"))

        # Test 9: get_parcel_neighbors (with real BSM)
        r_all = await _execute_tool_call("query_village_kg", {"template_name": "get_adjacent_parcels"})
        adj_data = json.loads(r_all)
        if adj_data and len(adj_data) > 0:
            bsm = adj_data[0].get("a_bsm", "")
            r = await _execute_tool_call("query_village_kg", {"template_name": "get_parcel_neighbors", "bsm": bsm})
            data = json.loads(r)
            ok = isinstance(data, list) and len(data) > 0
            tests.append(("get_parcel_neighbors", ok, f"{len(data)} neighbors of {bsm}"))
        else:
            tests.append(("get_parcel_neighbors (no adjacency)", True, "skipped — no edges"))

        # Test 10: resolve_place (Tier 0 from spatial context)
        # Use a village name from the annotation data (not the main admin village name)
        ann_names = [getattr(v, 'name', '') for v in ctx.natural_villages if getattr(v, 'name', '')]
        test_name = ann_names[0] if ann_names else '八社村'
        r = await _execute_tool_call("resolve_place", {"place_name": test_name})
        data = json.loads(r)
        ok = isinstance(data, dict) and data.get("method", "").startswith(("annotation", "natural_village"))
        tests.append(("resolve_place", ok, f"'{test_name}' → {data.get('method', '?')}"))

        return tests

    tool_tests = asyncio.run(test_parse_tool_calls())
    for name, ok, detail in tool_tests:
        print_result(ok, f"PARSE tool: {name}", detail)
        if not ok:
            failures.append(f"PARSE tool '{name}': failed")

    # ── Step 6: KG entity type breakdown ──────────────────────────
    print_section("Step 5: KG entity type breakdown")
    entity_counts = query_kg(kg, "count_entity_types")
    for entry in entity_counts:
        etype = entry.get("type", "?").replace(str(kg.g.namespace_manager.store.namespace("")), "pln:")
        count = entry.get("count", 0)
        print(f"  {etype}: {count}")

    # ── Report ──────────────────────────────────────────────────────
    total_time = time.time() - total_start
    total_tests = len(results) + len(tool_tests)
    passed = total_tests - len(failures)

    print_section("Test Summary")
    print(f"  Total tests: {total_tests}")
    print(f"  Passed: {passed}")
    print(f"  Failed: {len(failures)}")
    print(f"  KG triples: {triples}")
    print(f"  KG build time: {build_time:.1f}s")
    print(f"  Total time: {total_time:.1f}s")

    if failures:
        print(f"\n  Failures:")
        for f in failures:
            print(f"    ❌ {f}")
        return 1
    else:
        print(f"\n  🎉 ALL TESTS PASSED")
        return 0


if __name__ == "__main__":
    sys.exit(main())
