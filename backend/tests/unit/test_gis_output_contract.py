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
    from app.modules.spatial_ops.map_layers import build_map_layers

    layers = build_map_layers(
        [{"layerType": "planning_zone", "data": {"type": "FeatureCollection", "features": []}}],
        {"boundary_geojson": {"type": "FeatureCollection", "features": [_feature("B0")]}},
    )

    assert [layer["layerType"] for layer in layers] == ["planning_zone", "boundary"]


def test_render_builder_accepts_execute_road_shape():
    from app.modules.spatial_ops.map_layers import build_map_layers

    road = {
        "type": "Feature",
        "properties": {},
        "geometry": {
            "type": "LineString",
            "coordinates": [[116.0, 24.8], [116.1, 24.9]],
        },
    }
    layers = build_map_layers(
        [{"layer_type": "planned_road", "features": [road]}],
        {},
    )

    assert layers[0]["layerType"] == "planned_road"
    assert layers[0]["geojson"]["features"] == [road]


def test_render_builder_includes_current_roads_and_annotations():
    from app.modules.spatial_ops.map_layers import build_map_layers

    road = {
        "type": "FeatureCollection",
        "features": [],
    }
    annotation = {
        "type": "FeatureCollection",
        "features": [],
    }

    layers = build_map_layers(
        [],
        {
            "road_geojson": road,
            "annotation_geojson": annotation,
        },
    )

    assert [layer["layerType"] for layer in layers] == [
        "current_road",
        "current_annotation",
    ]


def test_pipeline_state_accepts_typed_derived_relations():
    from app.agent.deliver.gis_pipeline_state import GISPipelineState

    relations = SimpleNamespace(touches=[], nearby=[], connected=[])
    state = GISPipelineState(gis_data={"_parcel_relations": relations})

    assert state.gis_data["_parcel_relations"] is relations


def test_trace_layer_uses_real_parcel_geometry_only():
    from app.modules.spatial_ops.map_layers import build_trace_layer

    parcel = _feature("P001")

    layer = build_trace_layer(
        {
            "instructions": [
                {
                    "dimension_key": "land_use_planning",
                    "candidate_bsms": ["P001", "MISSING"],
                }
            ]
        },
        {
            "landuse_current_geojson": {
                "type": "FeatureCollection",
                "features": [parcel],
            }
        },
    )

    assert layer is not None
    assert len(layer["data"]["features"]) == 1
    assert layer["data"]["features"][0]["geometry"] == parcel["geometry"]


def test_empty_layout_fails_validation_closed():
    from app.agent.execute.execute_agent import _execution_review_node
    from app.agent.execute.execute_state import ExecuteAgentState

    result = asyncio.run(_execution_review_node(ExecuteAgentState()))

    assert result["validation_result"]["passed"] is False
    assert result["validation_result"]["reason"] == "execution_review_failed"


def test_legacy_intent_routes_declared_execute_children():
    from app.agent.execute.execute_agent import _route_tasks_node
    from app.agent.execute.execute_state import ExecuteAgentState

    state = ExecuteAgentState(
        intent={
            "facilities": [{"name": "clinic"}],
            "development_axes": [{"name": "main axis"}],
            "road_targets": [{"name": "village road"}],
        },
    )

    result = asyncio.run(_route_tasks_node(state))

    assert result["tasks_to_run"] == ["layout", "facility", "axis", "road"]


def test_road_grounding_infers_endpoints_from_kg_village_anchors():
    from app.modules.spatial_ops.resolver import resolve_spatial_anchors
    from app.modules.schema.contracts.parse_contracts import RoadTarget, SpatialPlanningIntent

    road = RoadTarget(road_level="南北向通村道路", width_m=6.0)
    intent = SpatialPlanningIntent(road_targets=[road])
    resolved = resolve_spatial_anchors(
        intent,
        village_anchors=[
            {"name": "南村", "lon": 116.01, "lat": 24.81},
            {"name": "北村", "lon": 116.02, "lat": 24.85},
        ],
    )

    assert resolved == 1
    assert road.start_anchor == (116.01, 24.81)
    assert road.end_anchor == (116.02, 24.85)


def test_missing_zone_targets_are_not_replaced_with_current_landuse():
    from app.agent.execute.execute_agent import _zone_worker_node
    from app.agent.execute.execute_state import ExecuteAgentState

    state = ExecuteAgentState(
        intent=SimpleNamespace(zone_targets=[]),
        gis_data={
            "landuse_current_geojson": {
                "type": "FeatureCollection",
                "features": [_feature("P001")],
            }
        },
    )

    result = asyncio.run(_zone_worker_node(state))

    assert result["execution_errors"][0]["code"] == "missing_zone_targets"
    assert "layout_configs" not in result


def test_execution_errors_fail_validation_closed():
    from app.agent.execute.execute_agent import _execution_review_node
    from app.agent.execute.execute_state import ExecuteAgentState

    state = ExecuteAgentState(
        layout_configs=[{"layerType": "facility_point", "data": {}}],
        execution_errors=[
            {
                "stage": "layout",
                "code": "missing_zone_targets",
                "message": "missing",
            }
        ],
    )

    result = asyncio.run(_execution_review_node(state))

    assert result["validation_result"]["passed"] is False
    assert result["validation_result"]["reason"] == "execution_review_failed"


def test_zone_table_preserves_absolute_area_target():
    from app.modules.parsing.tables import _extract_zone_tables

    targets = _extract_zone_tables(
        """
| 分区名称 | 面积（公顷） |
| --- | ---: |
| 村庄建设区 | 12.5 |
| 一般农业区 | 30.0 |
"""
    )

    assert [target.area_ha for target in targets] == [12.5, 30.0]


def test_parse_prefers_authoritative_zone_table_over_regex_noise():
    from app.modules.parsing.text_parser import parse

    result = parse(
        """
规划期限至2035年，目标比例35%。

| 分区名称 | 面积（公顷） | 占比 |
| --- | ---: | ---: |
| 村庄建设区 | 12.5 | 25% |
| 一般农业区 | 30.0 | 75% |
"""
    )

    assert [target.land_use for target in result.intent.zone_targets] == [
        "村庄建设区",
        "一般农业区",
    ]


def test_execute_checkpoint_output_converts_numpy_scalars():
    import numpy as np

    from app.agent.execute.execute_agent import _checkpoint_safe

    result = _checkpoint_safe(
        {"score": np.float64(1.25), "coords": [np.int64(2)]}
    )

    assert result == {"score": 1.25, "coords": [2]}
    assert type(result["score"]) is float


def test_parse_extracts_structured_road_table():
    from app.modules.parsing.text_parser import parse

    result = parse(
        """
| 道路类型 | 道路名称 | 宽度(m) | 连接功能 |
| :--- | :--- | :--- | :--- |
| 对外交通干道 | Y122乡道 | 7.0 | 衔接X038县道 |
| 村内主干道 | 南北向通村道路 | 6.0 | 串联自然村 |
"""
    )

    assert [(road.road_level, road.width_m) for road in result.intent.road_targets] == [
        ("Y122乡道", 7.0),
        ("南北向通村道路", 6.0),
    ]


def test_export_package_includes_road_and_manifest(tmp_path):
    from app.modules.spatial_ops.export_package import export_gdb_package

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


def test_export_uses_allocated_landuse_for_balance_without_current_gis(tmp_path):
    from app.modules.spatial_ops.export_package import export_gdb_package

    allocated = {
        "type": "FeatureCollection",
        "features": [
            {
                **_feature("P001"),
                "properties": {
                    "BSM": "P001",
                    "DLBM": "0101",
                    "DLMJ": 10000,
                },
            }
        ],
    }

    export_gdb_package(
        layout_configs=[],
        allocated_geojson=allocated,
        gis_data={},
        village_name="test",
        output_dir=str(tmp_path),
    )

    assert (tmp_path / "tables" / "land_balance.json").exists()


def test_export_land_balance_treats_missing_area_as_zero(tmp_path):
    from app.modules.spatial_ops.export_package import export_gdb_package

    allocated = {
        "type": "FeatureCollection",
        "features": [
            {
                **_feature("P001"),
                "properties": {
                    "BSM": "P001",
                    "DLBM": "0101",
                    "DLMJ": None,
                    "area_sqm": 10000,
                },
            },
            {
                **_feature("P002"),
                "properties": {
                    "BSM": "P002",
                    "DLBM": "0701",
                    "DLMJ": None,
                },
            },
        ],
    }

    export_gdb_package(
        layout_configs=[],
        allocated_geojson=allocated,
        gis_data={},
        village_name="test",
        output_dir=str(tmp_path),
    )

    balance = json.loads(
        (tmp_path / "tables" / "land_balance.json").read_text(encoding="utf-8")
    )
    assert balance["total_area_ha"] == 1.0


def test_uploaded_landuse_uses_canonical_bundle_layer():
    from app.modules.data.catalog.catalog import _merge_geojson_into_bundle
    from app.modules.schema.types.canonical import VillageBundle, VillageMetadata

    feature = _feature("P001")
    feature["properties"].update({"DLBM": "0101", "area_sqm": 10000})
    bundle = VillageBundle(
        village_name="test",
        metadata=VillageMetadata(village_name="test"),
    )

    count = _merge_geojson_into_bundle(
        bundle,
        "landuse_current",
        {"type": "FeatureCollection", "features": [feature]},
    )

    assert count == 1
    assert len(bundle.polygons.get("landuse_current")) == 1
    assert not bundle.polygons.get("upload_landuse_current")
    assert bundle.metadata.provider_sources == ["upload:landuse_current"]


def test_static_preview_uses_actual_extent(tmp_path):
    from PIL import Image

    from app.tools.gis.static_render import render_map_preview

    layer = {
        "geojson": {
            "type": "FeatureCollection",
            "features": [_feature("P001")],
        },
        "layerType": "planning_zone",
        "layerName": "规划分区",
        "color": "#54A24B",
    }

    invalid_axis = {
        "geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {"type": "Point", "coordinates": [0, 0]},
                }
            ],
        },
        "layerType": "infrastructure",
        "layerName": "invalid_axis",
    }
    boundary = {
        **layer,
        "layerType": "boundary",
        "layerName": "boundary",
    }

    artifact = render_map_preview(
        [layer, invalid_axis, boundary],
        str(tmp_path),
        "测试村",
    )

    assert artifact["status"] == "completed"
    assert artifact["extent"][0] == 116.0
    assert artifact["layer_count"] == 2
    preview = tmp_path / "planning_preview.png"
    assert preview.exists()
    with Image.open(preview) as image:
        assert image.size == (1800, 1300)


def test_interactive_html_map_is_self_contained(tmp_path):
    from app.tools.gis.html_render import render_interactive_map

    layer = {
        "geojson": {
            "type": "FeatureCollection",
            "features": [_feature("P001")],
        },
        "layerType": "boundary",
        "layerName": "boundary",
        "color": "#3388ff",
    }

    artifact = render_interactive_map(
        [layer],
        str(tmp_path),
        "测试村",
        issues=[{"code": "planned_roads_unresolved", "message": "道路未落位"}],
        project_summary={
            "roads": [{"name": "村内主干道", "status": "未落位", "detail": "等待空间锚点"}]
        },
    )

    html_path = tmp_path / "planning_map.html"
    content = html_path.read_text(encoding="utf-8")
    assert artifact["status"] == "completed"
    assert artifact["self_contained"] is True
    assert "https://" not in content
    assert "planned_roads_unresolved" in content
    assert "村内主干道" in content
    assert 'data-target="layer-0"' in content
    assert "mouseenter" in content
    assert "map-tooltip" in content

