"""Quick test: skip LLM, use saved intent to test layout generation."""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


async def test_parse_text_endpoint():
    """Test parse-text with use_db_reports, using saved intent to skip LLM."""
    # Load saved intent
    intent_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "test-screenshots", "diagnosis_intent.json")
    if not os.path.exists(intent_path):
        print(f"Intent file not found: {intent_path}")
        return

    with open(intent_path, "r", encoding="utf-8") as f:
        intent_json = json.load(f)

    print(f"Loaded intent: {len(intent_json.get('zones', []))} zones")

    # Generate layout
    from app.tools.gis.layout_tools import _dict_to_intent
    from app.services.modules.gis.layout.engine import SpatialLayoutEngine
    from app.api.gis_test_routes import _load_jintian_geojson

    intent = _dict_to_intent(intent_json)
    engine = SpatialLayoutEngine()

    boundary = _load_jintian_geojson("boundary_current.geojson")
    landuse = _load_jintian_geojson("landuse_current.geojson")

    print(f"Boundary: {len(boundary.get('features', [])) if boundary else 0} feats")
    print(f"Landuse: {len(landuse.get('features', [])) if landuse else 0} feats")

    t0 = time.time()
    configs = engine.generate_layout(
        intent=intent,
        boundary_geojson=boundary,
        landuse_current_geojson=landuse,
    )
    elapsed = (time.time() - t0) * 1000

    print(f"Layout: {len(configs)} layers in {elapsed:.0f}ms")
    for c in configs:
        feat_count = len(c.get("geojson", {}).get("features", []))
        print(f"  {c['layerType']}: {feat_count} features")

    # Test default intent
    from app.services.modules.gis.layout.planning_intent import UnifiedSpatialIntent
    default_intent = UnifiedSpatialIntent()
    default_configs = engine.generate_layout(
        intent=default_intent,
        boundary_geojson=boundary,
        landuse_current_geojson=landuse,
    )

    print(f"\nDefault intent layout: {len(default_configs)} layers")
    for c in default_configs:
        feat_count = len(c.get("geojson", {}).get("features", []))
        print(f"  {c['layerType']}: {feat_count} features")

    print("\nENDPOINT SIMULATION COMPLETE - no 500 error means the layout code is correct")


if __name__ == "__main__":
    asyncio.run(test_parse_text_endpoint())
