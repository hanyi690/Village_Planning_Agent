"""GIS formal-output contract tests."""

import asyncio
import json
from types import SimpleNamespace


def _feature(bsm: str, coordinates=None):
    return {
        "type": "Feature",
        "properties": {"BSM": bsm},
        "geometry": {
            "type": "Polygon",
            "coordinates": coordinates
            or [[[116.0, 24.8], [116.1, 24.8], [116.1, 24.9], [116.0, 24.8]]],
        },
    }


def test_render_builder_returns_frontend_layers():
    from app.tools.gis.render import build_map_layers

    layers = build_map_layers(
        [{"layerType": "planning_zone", "data": {"type": "FeatureCollection", "features": []}}],
        {"boundary_geojson": {"type": "FeatureCollection", "features": [_feature("B0")]}},
    )

    assert [layer["layerType"] for layer in layers] == ["planning_zone", "boundary"]


def test_fetch_reuses_caller_bundle_and_preserves_overrides():
    from app.agent.gis.layout_pipeline import _fetch_gis_data_node
    from app.agent.gis.state import GISPipelineState

    base = {"type": "FeatureCollection", "features": [_feature("BASE")]}
    override = {"type": "FeatureCollection", "features": [_feature("USER")]}
    bundle = SimpleNamespace(to_geojson_dict=lambda: {"landuse_current_geojson": base})
    state = GISPipelineState(
        village_name="test",
        gis_bundle=bundle,
        gis_data={"landuse_current_geojson": override},
    )

    result = asyncio.run(_fetch_gis_data_node(state))

    assert result["gis_bundle"] is bundle
    assert result["gis_data"]["landuse_current_geojson"] is override


def test_trace_layer_uses_real_parcel_geometry_only():
    from app.agent.gis.layout_pipeline import _build_trace_layer
    from app.agent.gis.state import GISPipelineState

    parcel = _feature("P001")
    state = GISPipelineState(
        gis_data={
            "landuse_current_geojson": {
                "type": "FeatureCollection",
                "features": [parcel],
            }
        },
        explore_instructions={
            "instructions": [
                {
                    "dimension_key": "land_use_planning",
                    "candidate_bsms": ["P001", "MISSING"],
                }
            ]
        },
    )

    layer = _build_trace_layer(state)

    assert layer is not None
    assert len(layer["data"]["features"]) == 1
    assert layer["data"]["features"][0]["geometry"] == parcel["geometry"]


def test_empty_layout_fails_validation_closed():
    from app.agent.gis.execute.agent import _validate_node
    from app.agent.gis.execute.state import ExecuteAgentState

    result = asyncio.run(_validate_node(ExecuteAgentState()))

    assert result["validation_result"]["passed"] is False
    assert result["validation_result"]["reason"] == "no_layout"


def test_export_is_blocked_when_validation_failed(tmp_path, monkeypatch):
    from app.agent.gis.layout_pipeline import _export_gdb_node
    from app.agent.gis.state import GISPipelineState

    monkeypatch.chdir(tmp_path)
    state = GISPipelineState(
        village_name="test",
        validation_result={"passed": False},
    )

    result = asyncio.run(_export_gdb_node(state))

    assert result["export_result"]["status"] == "blocked"
    assert not list(tmp_path.iterdir())


def test_export_package_includes_road_and_manifest(tmp_path):
    from app.tools.gis.export import export_gdb_package

    road = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "planned road"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[116.0, 24.8], [116.1, 24.9]],
                },
            }
        ],
    }
    result = export_gdb_package(
        layout_configs=[{"layerType": "planned_road_candidates", "data": road}],
        allocated_geojson=None,
        gis_data={},
        village_name="test",
        session_id="session-1",
        validation_result={"passed": True},
        output_dir=str(tmp_path),
    )

    assert result["status"] == "completed"
    assert (tmp_path / "planned" / "road.geojson").exists()
    manifest = json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["session_id"] == "session-1"
    assert manifest["validation"]["passed"] is True
