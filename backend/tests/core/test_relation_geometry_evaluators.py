from __future__ import annotations

from app.contracts.planning.constraint_factor import ConstraintFactor
from app.contracts.planning.relation_parameters import (
    AccessParameters,
    CoLocateParameters,
    ConnectParameters,
    DistanceParameters,
)
from app.contracts.planning.scenario import ScenarioFeature
from app.domain.relations.service import RelationEvaluationContext, evaluate_relations


def _feature(feature_id: str, target_id: str, geometry_wkt: str, crs: str = "EPSG:3857"):
    return ScenarioFeature(
        feature_id=feature_id,
        scenario_id="scenario-1",
        target_id=target_id,
        candidate_id=f"candidate:{feature_id}",
        geometry_kind="point" if geometry_wkt.startswith("POINT") else "polygon",
        geometry_wkt=geometry_wkt,
        crs=crs,
        generation_operation="test",
        source_refs=["fixture:test"],
    )


def _factor(key: str, subject: str = "a", object_: str = "b", parameters=None):
    return ConstraintFactor(
        factor_id=f"factor:{key}-1",
        kind="near" if key in {"near", "far"} else "co_locate",
        evaluator_key=key,
        subject_ref=subject,
        object_ref=object_,
        parameters=parameters,
        hard=True,
    )


def test_near_and_far_use_projected_meter_measurements() -> None:
    features = [_feature("a", "a", "POINT (0 0)"), _feature("b", "b", "POINT (10 0)")]
    near = _factor("near", parameters=DistanceParameters(max_distance_m=20, metric="euclidean"))
    far = _factor("far", parameters=DistanceParameters(max_distance_m=5, metric="euclidean"))

    results = evaluate_relations([near, far], features, RelationEvaluationContext(scenario_id="scenario-1"))

    assert [item.status for item in results] == ["satisfied", "satisfied"]
    assert results[0].measurement is not None
    assert results[0].measurement.unit == "m"
    assert results[0].measurement.crs == "EPSG:3857"


def test_contain_avoid_adjacent_and_colocate_are_deterministic() -> None:
    outer = _feature("outer", "outer", "POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0))")
    inner = _feature("inner", "inner", "POINT (5 5)")
    touching = _feature("touching", "touching", "POINT (10 5)")
    contain = ConstraintFactor(
        factor_id="factor:contain-1", kind="within_allowed_area", evaluator_key="contain",
        subject_ref="outer", object_ref="inner", hard=True,
    )
    avoid = ConstraintFactor(
        factor_id="factor:avoid-1", kind="avoid_constraint", evaluator_key="avoid",
        subject_ref="outer", object_ref="touching", hard=True,
    )
    adjacent = ConstraintFactor(
        factor_id="factor:adjacent-1", kind="co_locate", evaluator_key="adjacent",
        subject_ref="outer", object_ref="touching", hard=True,
    )
    colocate = _factor("co_locate", "inner", "touching", CoLocateParameters(max_distance_m=4))

    results = evaluate_relations(
        [contain, avoid, adjacent, colocate],
        [outer, inner, touching],
        RelationEvaluationContext(scenario_id="scenario-1"),
    )

    assert [item.status for item in results] == ["satisfied", "violated", "satisfied", "violated"]


def test_missing_geometry_or_crs_never_satisfies_distance() -> None:
    missing = _factor("near", parameters=DistanceParameters(max_distance_m=10, metric="euclidean"))
    missing_crs = _feature("a", "a", "POINT (0 0)").model_copy(update={"crs": ""})
    result = evaluate_relations(
        [missing],
        [missing_crs],
        RelationEvaluationContext(scenario_id="scenario-1"),
    )[0]
    assert result.status == "not_evaluable"


def test_connect_and_access_via_fail_closed_without_network_artifacts() -> None:
    features = [_feature("a", "a", "POINT (0 0)"), _feature("b", "b", "POINT (1 1)")]
    connect = ConstraintFactor(
        factor_id="factor:connect-1", kind="connect_network", evaluator_key="connect",
        subject_ref="a", object_ref="b", parameters=ConnectParameters(
            network_kind="road", endpoint_tolerance_m=5, network_ref="network:missing"
        ), hard=True,
    )
    access = ConstraintFactor(
        factor_id="factor:access-1", kind="provide_access", evaluator_key="access_via",
        subject_ref="a", object_ref="b", parameters=AccessParameters(
            max_travel_time_min=15, network_ref="network:missing"
        ), hard=True,
    )

    results = evaluate_relations(
        [connect, access], features, RelationEvaluationContext(scenario_id="scenario-1")
    )

    assert [item.status for item in results] == ["not_evaluable", "not_evaluable"]


class _Network:
    def is_connected(self, subject, object_):
        return True

    def travel_time_min(self, subject, object_):
        return 10


def test_connect_and_access_via_use_network_measurements() -> None:
    features = [_feature("a", "a", "POINT (0 0)"), _feature("b", "b", "POINT (1 1)")]
    connect = ConstraintFactor(
        factor_id="factor:connect-1", kind="connect_network", evaluator_key="connect",
        subject_ref="a", object_ref="b", parameters=ConnectParameters(
            network_kind="road", endpoint_tolerance_m=5, network_ref="network:road"
        ), hard=True,
    )
    access = ConstraintFactor(
        factor_id="factor:access-1", kind="provide_access", evaluator_key="access_via",
        subject_ref="a", object_ref="b", parameters=AccessParameters(
            max_travel_time_min=15, network_ref="network:road"
        ), hard=True,
    )

    results = evaluate_relations(
        [connect, access],
        features,
        RelationEvaluationContext(
            scenario_id="scenario-1", networks={"network:road": _Network()}
        ),
    )

    assert [item.status for item in results] == ["satisfied", "satisfied"]
    assert results[1].measurement is not None
    assert results[1].measurement.unit == "min"
