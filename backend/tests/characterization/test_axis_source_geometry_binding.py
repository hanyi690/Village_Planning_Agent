from types import SimpleNamespace

from app.domain.materialization.nodes.axis_worker import (
    materialize_authoritative_axis_lines,
)
from app.contracts.domain.l3_contracts import PlanningIntervention
from app.contracts.domain.planning_semantics import AxisPlanningParameters
from app.domain.program.target_projection.compile import _to_axis_target


def _line(source_id: str, geometry_type: str = "LineString") -> object:
    return SimpleNamespace(
        _raw={"source_feature_id": source_id},
        geometry=(
            {
                "type": geometry_type,
                "coordinates": [[116.0, 24.8], [116.01, 24.81]],
            }
            if geometry_type == "LineString"
            else {
                "type": geometry_type,
                "coordinates": [[[116.0, 24.8], [116.01, 24.81]]],
            }
        ),
    )


def _workspace(*features: object) -> object:
    return SimpleNamespace(lines={"roads_current": list(features)})


def test_target_projection_carries_only_explicit_axis_source_ids():
    intervention = PlanningIntervention(
        intervention_id="axis-1",
        name="现状道路轴",
        category="axis",
        asset_kind="axis",
        execution_mode="spatial",
        expected_output_kind="line",
        intervention_action="upgrade",
        spatial_requirements={
            "source_feature_ids": ["road-2", "road-1", "road-2"],
        },
        axis_parameters=AxisPlanningParameters(action="upgrade"),
    )

    target = _to_axis_target(intervention)

    assert target.source_feature_ids == ["road-2", "road-1"]


def test_target_projection_accepts_existing_road_feature_id_alias_for_axis():
    intervention = PlanningIntervention(
        intervention_id="axis-alias-1",
        name="现状道路轴",
        category="axis",
        asset_kind="axis",
        execution_mode="spatial",
        expected_output_kind="line",
        intervention_action="upgrade",
        spatial_requirements={"existing_road_feature_ids": ["road-1"]},
        axis_parameters=AxisPlanningParameters(action="upgrade"),
    )

    target = _to_axis_target(intervention)

    assert target.source_feature_ids == ["road-1"]


def test_axis_without_source_ids_stays_deferred_even_with_line_workspace():
    axis = SimpleNamespace(target_id="axis-1", axis_type="primary", label="南北轴")

    features, reason = materialize_authoritative_axis_lines(
        axis,
        _workspace(_line("road-1")),
    )

    assert features == []
    assert reason == "axis_source_feature_ids_missing"


def test_axis_materializes_each_authoritative_line_without_union_or_proxy():
    axis = SimpleNamespace(
        target_id="axis-1",
        axis_type="corridor",
        label="现状道路轴",
        source_feature_ids=["road-2", "road-1"],
    )
    first = _line("road-1")
    second = _line("road-2", "MultiLineString")

    features, reason = materialize_authoritative_axis_lines(
        axis,
        _workspace(first, second),
    )

    assert reason == ""
    assert [item["properties"]["source_feature_id"] for item in features] == [
        "road-2",
        "road-1",
    ]
    assert [item["geometry"]["type"] for item in features] == [
        "MultiLineString",
        "LineString",
    ]
    assert all(item["properties"]["materialization_method"] == "authoritative_source_line" for item in features)


def test_axis_foreign_or_polygon_id_stays_deferred():
    axis = SimpleNamespace(
        target_id="axis-1",
        source_feature_ids=["parcel-1"],
    )
    polygon = SimpleNamespace(
        _raw={"source_feature_id": "parcel-1"},
        geometry={
            "type": "Polygon",
            "coordinates": [[[116.0, 24.8], [116.01, 24.8], [116.01, 24.81], [116.0, 24.8]]],
        },
    )

    features, reason = materialize_authoritative_axis_lines(axis, _workspace(polygon))

    assert features == []
    assert reason == "axis_source_feature_geometry_missing:parcel-1"
