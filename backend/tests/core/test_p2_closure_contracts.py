from __future__ import annotations

import pytest

from app.contracts.planning.constraint_factor import ConstraintFactor
from app.contracts.planning.scenario import MasterCertificatePayload, ScenarioFeature
from app.domain.allocation.master_coordinator import MasterCandidate, coordinate_master
from app.domain.demand.facility_demand_model import FacilityDemandPoint, build_demand_snapshot
from app.domain.network.snapshot import NetworkEdgeRef, NetworkNodeRef, build_network_snapshot, network_readiness
from app.domain.relations.service import RelationEvaluationContext, evaluate_relations
from app.domain.relations.registry import build_default_relation_registry


def _feature(ref: str, wkt: str) -> ScenarioFeature:
    return ScenarioFeature(
        feature_id=ref, scenario_id="p2", target_id=ref, candidate_id=f"candidate:{ref}",
        geometry_kind="polygon" if wkt.startswith("POLYGON") else "point", geometry_wkt=wkt,
        crs="EPSG:3857", generation_operation="test", source_refs=["fixture:p2"], relation_ids=[f"r:{ref}"]
    )


def test_snapshot_roundtrip_and_fingerprint_are_stable():
    point = FacilityDemandPoint(demand_id="d1", geometry_wkt="POINT (0 0)", demand_value=2)
    first = build_demand_snapshot("demand:p2", [point], source_refs=["source:d"], source_binding="binding:d", version="v1", declared_total_demand=2)
    second = build_demand_snapshot("demand:p2", [point], source_refs=["source:d"], source_binding="binding:d", version="v1", declared_total_demand=2)
    assert first.availability == "ready"
    assert first.fingerprint == second.fingerprint
    assert type(first).model_validate(first.model_dump(mode="python", exclude={"fingerprint"})).fingerprint == first.fingerprint

    network = build_network_snapshot("network:p2", nodes=[NetworkNodeRef(node_id="n1")], edges=[NetworkEdgeRef(edge_id="e1", from_node="n1", to_node="n1")], crs="EPSG:4326", metric_crs="EPSG:3857", version="v1", source_binding="binding:n", source_refs=["source:n"])
    assert network.readiness == "ready"
    assert type(network).model_validate(network.model_dump(mode="python")).fingerprint == network.fingerprint


def test_missing_network_and_demand_are_not_successful_inputs():
    pending = build_demand_snapshot("demand:p2", [])
    assert pending.readiness == "pending"
    blocked = build_network_snapshot("network:p2", nodes=[], edges=[], crs="EPSG:4326", metric_crs="EPSG:3857")
    assert blocked.readiness == "blocked"


@pytest.mark.parametrize(("key", "object_wkt"), [("intersects", "POLYGON ((1 1, 5 1, 5 5, 1 5, 1 1))"), ("overlaps", "POLYGON ((5 5, 12 5, 12 12, 5 12, 5 5))"), ("contains", "POLYGON ((1 1, 5 1, 5 5, 1 5, 1 1))"), ("adjacent", "POLYGON ((10 2, 12 2, 12 8, 10 8, 10 2))")])
def test_topology_registry_is_deterministic(key: str, object_wkt: str):
    features = [_feature("outer", "POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0))"), _feature("inner", object_wkt)]
    factor = ConstraintFactor(kind="intersects", evaluator_key=key, subject_ref="outer", object_ref="inner", hard=True)
    result = evaluate_relations([factor], features, RelationEvaluationContext(scenario_id="p2"))[0]
    assert result.status == "satisfied"
    assert result.measurement is not None
    assert result.evaluation_trace
    assert result.evaluator_version


def test_master_blocks_shared_parcel_capacity_and_keeps_stable_ids():
    result = coordinate_master([
        MasterCandidate(target_id="t1", candidate_id="c1", parcel_refs=("p1",)),
        MasterCandidate(target_id="t2", candidate_id="c2", parcel_refs=("p1",)),
    ], parcel_capacity={"p1": 1})
    assert result.status == "bounded_infeasible"
    assert result.selected_candidate_ids == {}
    assert "parcel:p1" in result.conflict_refs


def test_incomplete_hard_relation_and_readiness_registry_fail_closed():
    factor = ConstraintFactor(
        kind="intersects",
        evaluator_key="intersects",
        subject_ref="a",
        object_ref="b",
        hard=True,
        input_status="missing",
    )
    result = evaluate_relations(
        [factor],
        [_feature("a", "POINT (0 0)"), _feature("b", "POINT (0 0)")],
        RelationEvaluationContext(scenario_id="p2"),
    )[0]
    assert result.status in {"deferred", "not_evaluable"}
    assert result.status != "satisfied"
    assert {"contains", "within", "intersects", "overlaps", "access", "serve"}.issubset(
        set(build_default_relation_registry().keys())
    )


def test_callable_only_network_is_not_typed_ready():
    class CallableOnlyNetwork:
        network_ref = "network:callable-only"

        def route(self, _subject, _object):
            return None

    readiness, diagnostics = network_readiness(
        CallableOnlyNetwork(),
        "network:callable-only",
    )
    assert readiness == "blocked"
    assert diagnostics == ("legacy_network_snapshot_incomplete",)


def test_complete_legacy_network_is_still_pending_until_typed_binding():
    class LegacyNetwork:
        network_ref = "network:legacy"
        nodes = (object(),)
        edges = (object(),)
        fingerprint = "legacy-fingerprint"

        def is_connected(self, _left, _right):
            return True

        def travel_time_min(self, _left, _right):
            return 1.0

    readiness, diagnostics = network_readiness(LegacyNetwork(), "network:legacy")
    assert readiness == "blocked"
    assert diagnostics == ("legacy_network_snapshot_untyped",)


def test_master_certificate_requires_nested_backend_binding():
    from app.contracts.planning.scenario import (
        BackendCertificatePayload,
        SolverCertificate,
        derive_backend_selection_digest,
        derive_solver_model_digest,
    )

    master = MasterCertificatePayload(status="feasible", selected_candidate_ids={})
    proof = BackendCertificatePayload(
        backend_id="test-backend",
        backend_version="1.0",
        problem_kind="single_choice",
        problem_fingerprint="problem:p2",
        input_digest="input:p2",
        solver_config={
            "deterministic_seed": 0,
            "search_limit": 0,
            "time_limit_seconds": None,
            "max_scenarios": 1,
            "objective_definitions": [],
            "backend_version": "1.0",
            "replay_settings": {},
        },
        selection_digest=derive_backend_selection_digest({}, []),
        status="feasible",
    )
    with pytest.raises(ValueError, match="not bound"):
        SolverCertificate(
            problem_fingerprint="problem:p2",
            model_digest=derive_solver_model_digest(proof, deterministic_seed=0, search_limit=0),
            solver_version="test-backend:1.0",
            status="feasible",
            problem_kind="single_choice",
            backend_id="test-backend",
            backend_version="1.0",
            feasible_scenario_count=0,
            backend_certificate=proof,
            master_certificate=MasterCertificatePayload(
                status="deferred",
                blocker_refs=["different-master"],
            ),
        )
