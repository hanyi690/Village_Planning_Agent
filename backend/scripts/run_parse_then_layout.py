"""Minimal PARSE → LAYOUT pipeline.

Usage: cd backend && python -m scripts.run_parse_then_layout
"""

import asyncio, json, sys, time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "gis" / "jintian"
PARSE_CACHE_DIR = ROOT / "output" / "parse_cache"
PARSE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
DOCS_DIR = ROOT / "docs"


def load_gis():
    layer_map = {
        "landuse_current_geojson": "current/landuse.geojson",
        "boundary_geojson": "current/boundary.geojson",
        "admin_boundary_line_geojson": "current/admin_boundary_line.geojson",
        "road_geojson": "current/road.geojson",
        "annotation_geojson": "current/annotation.geojson",
        "construction_boundary_geojson": "planned/construction_zone.geojson",
        "farmland_protection_geojson": "planned/farmland_protection.geojson",
        "ecological_protection_geojson": "planned/ecological_protection.geojson",
        "geological_hazard_geojson": "planned/geological_hazard_points.geojson",
        "historical_protection_geojson": "planned/historical_protection.geojson",
    }
    gis = {}
    for key, rel in layer_map.items():
        fp = DATA_DIR / rel
        if fp.exists():
            with open(str(fp), "r", encoding="utf-8") as f:
                gis[key] = json.load(f)
    print(f"  GIS: {len(gis)} layers loaded", flush=True)
    return gis


async def main():
    print("=" * 60, flush=True)
    print("STEP 1: Load GIS data + planning text", flush=True)
    print("=" * 60, flush=True)
    gis_data = load_gis()

    md_files = sorted(DOCS_DIR.glob("MinerU_markdown_*村庄规划*文本*.md"))
    if not md_files:
        print(f"  ERROR: no markdown found in {DOCS_DIR}", flush=True)
        return
    planning_text = md_files[0].read_text(encoding="utf-8")
    print(f"  Text: {md_files[0].name}, {len(planning_text)} chars", flush=True)

    print("\n" + "=" * 60, flush=True)
    print("STEP 2: Build KG + run PARSE Agent", flush=True)
    print("=" * 60, flush=True)

    from app.modules.kg import PlanningKG
    from app.modules.kg.manager import get_kg_manager

    kg = PlanningKG(village_name="金田村")
    landuse = gis_data.get("landuse_current_geojson")
    kg.build_from_reports(reports={}, landuse_geojson=landuse, gis_data=gis_data)
    kg.add_protection_zones(gis_data)

    annotations = gis_data.get("annotation_geojson", {}).get("features", [])
    roads = gis_data.get("road_geojson", {}).get("features", [])
    if annotations:
        kg.add_annotations(annotations)
    if roads:
        kg.add_roads(roads)

    get_kg_manager().register_session("parse_pipeline", kg)
    print(f"  KG: {kg.get_triple_count()} triples, {len(annotations)} annotations", flush=True)

    from app.agent.gis.parse.agent import build_parse_agent_graph, set_context_blocks
    from app.agent.gis.parse.state import ParseAgentState
    import app.agent.gis.parse.agent as pa
    from app.modules.parsing.gazetteer import PlaceNameResolver

    set_context_blocks([])
    pa._gazetteer = PlaceNameResolver([])

    graph = build_parse_agent_graph()
    state = ParseAgentState(
        planning_text=planning_text[:12000],
        village_name="金田村",
    )
    result = await graph.ainvoke(state.model_dump())
    print(f"  PARSE Agent completed", flush=True)

    planning_intent = result.get("planning_intent", {})
    zone_targets = (
        planning_intent.zone_targets
        if hasattr(planning_intent, "zone_targets")
        else planning_intent.get("zone_targets", [])
    )
    facilities = (
        planning_intent.facilities
        if hasattr(planning_intent, "facilities")
        else planning_intent.get("facilities", [])
    )
    axes = (
        planning_intent.development_axes
        if hasattr(planning_intent, "development_axes")
        else planning_intent.get("development_axes", [])
    )
    print(f"  Zones: {len(zone_targets)}, Facilities: {len(facilities)}, Axes: {len(axes)}", flush=True)

    # Serialize Pydantic models to dict
    def serialize(obj):
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if isinstance(obj, list):
            return [serialize(x) for x in obj]
        if isinstance(obj, dict):
            return {k: serialize(v) for k, v in obj.items()}
        return obj

    parse_cache = {
        "planning_intent": serialize(planning_intent),
        "operation_sequence": serialize(result.get("operation_sequence", [])),
        "constraint_set": serialize(result.get("constraint_set", [])),
        "validation_errors": result.get("validation_errors", []),
        "spatial_context": {"facility_anchors": []},
        "kg_summary": {
            "triple_count": kg.get_triple_count(),
            "parcel_count": len(landuse.get("features", [])) if landuse else 0,
        },
        "gis_summary": {k: len(v.get("features", [])) for k, v in gis_data.items()},
        "village_name": "金田村",
    }
    ts = time.strftime("%Y%m%d_%H%M%S")
    cache_path = PARSE_CACHE_DIR / f"jintian_mineru_{ts}.json"
    cache_path.write_text(json.dumps(parse_cache, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n  Parse cache saved: {cache_path.name}", flush=True)

    print("\n" + "=" * 60, flush=True)
    print("STEP 3: Run LAYOUT pipeline", flush=True)
    print("=" * 60, flush=True)

    from scripts.run_layout_pipeline import run_pipeline

    await run_pipeline(village_name="金田村", parse_cache_path=cache_path)
    print("\nDone!", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
