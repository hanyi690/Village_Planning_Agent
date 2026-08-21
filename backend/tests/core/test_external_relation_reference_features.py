from __future__ import annotations

from types import SimpleNamespace

from app.contracts.planning.constraint_factor import ConstraintFactor
from app.contracts.planning.relation_parameters import (
    AccessParameters,
    AvoidConstraintParameters,
    ConnectParameters,
    DistanceParameters,
)
from app.contracts.planning.scenario import PlanningScenario, ScenarioFeature
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounded_problem import (
    GroundedCandidateDomain,
    GroundedPlanningProblem,
)
from app.contracts.spatial.planned_state_contracts import PlannedState, PlannedZone
from app.contracts.ports.place_resolution_contracts import PlaceResolutionCandidate
from app.domain.allocation.scenario_solver import solve_scenario
from app.domain.relations.reference_features import (
    resolve_relation_reference_features,
)
from app.domain.relations.service import RelationEvaluationContext
from app.domain.validation.relation_validation import validate_final_scenario


class _LayerGroup:
    def __init__(self, layers):
        self._layers = layers

    def keys(self):
        return list(self._layers)

    def get(self, key):
        return list(self._layers.get(key, []))


class _EvidenceGraph:
    def __init__(self, candidates):
        self.candidates = candidates

    def iter_entries(self):
        return []

    def resolve_mention(self, mention, role="unknown"):
        return SimpleNamespace(
            status="resolved" if len(self.candidates) == 1 else "ambiguous",
            candidates=list(self.candidates),
        )


def _context(candidates):
    feature = SimpleNamespace(
        geometry={"type": "Point", "coordinates": [100.0, 2.5]},
        bsm="feature:hall",
        layer_type="annotations_current",
        _raw={"source_feature_id": "source:hall"},
    )
    workspace = SimpleNamespace(
        metadata=SimpleNamespace(crs="EPSG:3857"),
        points=_LayerGroup({"annotations_current": [feature]}),
        lines=_LayerGroup({}),
        polygons=_LayerGroup({}),
    )
    return SimpleNamespace(
        workspace=workspace,
        evidence_graph=_EvidenceGraph(candidates),
        data_snapshot=SimpleNamespace(digest="sha256:bundle-test"),
        l1_snapshot_ref="l1:snapshot:test",
    )


def _road_context(candidates):
    feature = SimpleNamespace(
        geometry={"type": "LineString", "coordinates": [[50.0, -10.0], [50.0, 10.0]]},
        bsm="road:main",
        layer_type="roads_current",
        _raw={"source_feature_id": "source:road:main"},
    )
    workspace = SimpleNamespace(
        metadata=SimpleNamespace(crs="EPSG:3857"),
        points=_LayerGroup({}),
        lines=_LayerGroup({"roads_current": [feature]}),
        polygons=_LayerGroup({}),
    )
    return SimpleNamespace(
        workspace=workspace,
        evidence_graph=_EvidenceGraph(candidates),
        data_snapshot=SimpleNamespace(digest="sha256:bundle-test"),
        l1_snapshot_ref="",
    )


def _candidate(*, entity_ref="place:祠堂", bsm="feature:hall"):
    return PlaceResolutionCandidate(
        entity_ref=entity_ref,
        entity_type="landmark",
        canonical_name="祠堂",
        feature_bsm=bsm,
        source_bsm=bsm,
        source_bsms=[bsm],
        source_feature_id="source:hall",
        source_layer="annotations_current",
        score=0.95,
        evidence_refs=["l1:fact:hall"],
        l1_fact_refs=["l1:fact:hall"],
        l1_snapshot_ref="l1:snapshot:test",
        bundle_snapshot_digest="sha256:bundle-test",
    )


def _road_candidate():
    return PlaceResolutionCandidate(
        entity_ref="road:main",
        entity_type="road",
        canonical_name="主路",
        feature_bsm="road:main",
        source_bsm="road:main",
        source_bsms=["road:main"],
        source_feature_id="source:road:main",
        source_layer="roads_current",
        score=0.95,
        evidence_refs=["kg:road:main"],
        bundle_snapshot_digest="sha256:bundle-test",
    )


def test_external_reference_reads_bundle_geometry_and_keeps_identity_lineage():
    factor = ConstraintFactor(
        factor_id="factor:near-hall",
        kind="near",
        evaluator_key="near",
        subject_ref="target:site",
        object_ref="place:祠堂",
        object_ref_kind="entity",
        parameters=DistanceParameters(max_distance_m=10, metric="euclidean"),
        hard=True,
    )

    resolution = resolve_relation_reference_features(
        _context([_candidate()]),
        [factor],
        scenario_id="scenario:reference",
    )

    assert resolution.diagnostics == ()
    feature = resolution.features["place:祠堂"]
    assert feature.geometry_wkt == "POINT (100 2.5)"
    assert feature.source_bsms == ["feature:hall"]
    assert feature.source_feature_ids == ["source:hall"]
    assert feature.l1_fact_refs == ["l1:fact:hall"]
    assert feature.bundle_snapshot_digest == "sha256:bundle-test"
    assert feature.generation_operation == "relation_bundle_reference"


def test_external_reference_relation_changes_selection_using_bundle_geometry():
    factor = ConstraintFactor(
        factor_id="factor:near-hall",
        kind="near",
        evaluator_key="near",
        subject_ref="target:site",
        object_ref="place:祠堂",
        object_ref_kind="entity",
        parameters=DistanceParameters(max_distance_m=10, metric="euclidean"),
        hard=True,
    )
    context = _context([_candidate()])
    resolution = resolve_relation_reference_features(
        context,
        [factor],
        scenario_id="scenario:reference",
    )
    geometries = [
        CandidateGeometry(
            candidate_id="site:near",
            target_id="target:site",
            kind="polygon",
            role="execution_geometry",
            materialization_role="site_footprint",
            wkt="POLYGON ((90 0, 95 0, 95 5, 90 5, 90 0))",
            crs="EPSG:3857",
            source_ref="bundle:parcel:near",
            source_bsms=["parcel:near"],
            hard_constraint_status="passed",
        ),
        CandidateGeometry(
            candidate_id="site:far",
            target_id="target:site",
            kind="polygon",
            role="execution_geometry",
            materialization_role="site_footprint",
            wkt="POLYGON ((0 0, 5 0, 5 5, 0 5, 0 0))",
            crs="EPSG:3857",
            source_ref="bundle:parcel:far",
            source_bsms=["parcel:far"],
            hard_constraint_status="passed",
        ),
    ]
    problem = GroundedPlanningProblem(
        candidate_domains=[GroundedCandidateDomain(
            target_id="target:site",
            candidate_ids=["site:near", "site:far"],
        )],
        candidate_geometries=geometries,
        constraint_factors=[factor],
    )

    result = solve_scenario(
        problem,
        scenario_id="scenario:reference",
        evaluator_context=RelationEvaluationContext(
            scenario_id="scenario:reference",
            reference_features=resolution.features,
        ),
    )

    assert result.status == "complete"
    assert {
        item.target_id: item.candidate_ids
        for item in result.target_selections
    } == {"target:site": ["site:near"]}
    assert result.relation_satisfactions[0].status == "satisfied"
    assert result.relation_satisfactions[0].measurement.value == 5.0


def test_ambiguous_external_reference_fails_closed_without_geometry_guess():
    factor = ConstraintFactor(
        factor_id="factor:near-hall",
        kind="near",
        evaluator_key="near",
        subject_ref="target:site",
        object_ref="place:祠堂",
        object_ref_kind="place_hint",
        parameters=DistanceParameters(max_distance_m=10, metric="euclidean"),
        hard=True,
    )
    first = _candidate(entity_ref="place:hall:1", bsm="feature:hall:1")
    second = _candidate(entity_ref="place:hall:2", bsm="feature:hall:2")

    resolution = resolve_relation_reference_features(
        _context([first, second]),
        [factor],
        scenario_id="scenario:ambiguous",
    )

    assert resolution.features == {}
    assert resolution.diagnostics == (
        "external_relation_reference_ambiguous:place:祠堂:2",
    )


def test_external_reference_is_available_to_network_relation_subproblem():
    factor = ConstraintFactor(
        factor_id="factor:connect-hall",
        kind="connect_network",
        evaluator_key="connect",
        subject_ref="target:site",
        object_ref="place:祠堂",
        object_ref_kind="entity",
        parameters=ConnectParameters(
            network_kind="road",
            endpoint_tolerance_m=15,
            network_ref="network:road:test",
        ),
        hard=True,
    )
    context = _context([_candidate()])
    resolution = resolve_relation_reference_features(
        context,
        [factor],
        scenario_id="scenario:network-reference",
    )

    target = CandidateGeometry(
        candidate_id="site:point",
        target_id="target:site",
        kind="point",
        role="execution_geometry",
        wkt="POINT (0 2.5)",
        crs="EPSG:3857",
        source_ref="bundle:parcel:anchor",
    )
    problem = GroundedPlanningProblem(
        candidate_domains=[GroundedCandidateDomain(
            target_id="target:site",
            candidate_ids=[target.candidate_id],
        )],
        candidate_geometries=[target],
        constraint_factors=[factor],
    )

    class _Network:
        network_ref = "network:road:test"

        def route(self, subject, object_):
            from app.spatial.network.network_graph import NetworkRoute

            return NetworkRoute(True, distance_m=100.0, travel_time_min=2.0)

        def nearest_node(self, feature):
            return ("node:test", 0.0)

    result = solve_scenario(
        problem,
        scenario_id="scenario:network-reference",
        evaluator_context=RelationEvaluationContext(
            scenario_id="scenario:network-reference",
            networks={"network:road:test": _Network()},
            reference_features=resolution.features,
        ),
    )

    assert result.status == "complete"
    assert result.relation_satisfactions[0].status == "satisfied"
    assert result.relation_satisfactions[0].object_feature_refs


def test_external_reference_is_available_to_access_relation_subproblem():
    factor = ConstraintFactor(
        factor_id="factor:access-hall",
        kind="provide_access",
        evaluator_key="access_via",
        subject_ref="target:site",
        object_ref="place:祠堂",
        object_ref_kind="place_hint",
        parameters=AccessParameters(
            max_travel_time_min=5,
            network_ref="network:road:test",
        ),
        hard=True,
    )
    context = _context([_candidate()])
    resolution = resolve_relation_reference_features(
        context,
        [factor],
        scenario_id="scenario:access-reference",
    )
    target = CandidateGeometry(
        candidate_id="site:point",
        target_id="target:site",
        kind="point",
        role="execution_geometry",
        wkt="POINT (0 2.5)",
        crs="EPSG:3857",
        source_ref="bundle:parcel:anchor",
    )
    problem = GroundedPlanningProblem(
        candidate_domains=[GroundedCandidateDomain(
            target_id="target:site",
            candidate_ids=[target.candidate_id],
        )],
        candidate_geometries=[target],
        constraint_factors=[factor],
    )

    class _Network:
        network_ref = "network:road:test"

        def route(self, subject, object_):
            from app.spatial.network.network_graph import NetworkRoute

            return NetworkRoute(True, distance_m=100.0, travel_time_min=2.0)

    result = solve_scenario(
        problem,
        scenario_id="scenario:access-reference",
        evaluator_context=RelationEvaluationContext(
            scenario_id="scenario:access-reference",
            networks={"network:road:test": _Network()},
            reference_features=resolution.features,
        ),
    )

    assert result.status == "complete"
    assert result.relation_satisfactions[0].status == "satisfied"
    assert result.relation_satisfactions[0].measurement.value == 2.0


def test_final_validation_reuses_external_bundle_reference_without_orphan_finding():
    factor = ConstraintFactor(
        factor_id="factor:near-hall",
        kind="near",
        evaluator_key="near",
        subject_ref="target:site",
        object_ref="place:祠堂",
        object_ref_kind="entity",
        parameters=DistanceParameters(max_distance_m=10, metric="euclidean"),
        hard=True,
    )
    context = _context([_candidate()])
    resolution = resolve_relation_reference_features(
        context,
        [factor],
        scenario_id="scenario:final-reference",
    )
    intent = ScenarioFeature(
        feature_id="feature:scenario:final-reference:target:site:site:near",
        scenario_id="scenario:final-reference",
        target_id="target:site",
        candidate_id="site:near",
        geometry_kind="polygon",
        geometry_wkt="POLYGON ((90 0, 95 0, 95 5, 90 5, 90 0))",
        crs="EPSG:3857",
        generation_operation="select_planning_subgeometry",
        source_refs=["bundle:parcel:near"],
        relation_ids=["near-hall"],
    )
    scenario = PlanningScenario(
        scenario_id="scenario:final-reference",
        baseline_ref="baseline:test",
        problem_fingerprint="problem:final-reference",
        feature_intents=[intent],
    )
    planned_state = PlannedState(
        scenario_id="scenario:final-reference",
        zones=[PlannedZone(
            zone_id="site:near",
            target_ref="target:site",
            geometry="POLYGON ((90 0, 95 0, 95 5, 90 5, 90 0))",
            relation_ids=["near-hall"],
        )],
    )
    problem = GroundedPlanningProblem(constraint_factors=[factor])

    report = validate_final_scenario(
        scenario,
        planned_state,
        problem,
        RelationEvaluationContext(
            scenario_id="scenario:final-reference",
            metric_crs="EPSG:3857",
            reference_features=resolution.features,
        ),
    )

    assert report.passed
    assert report.satisfactions[0].status == "satisfied"
    assert report.satisfactions[0].measurement.value == 5.0
    assert not any(item.code == "relation_orphan_feature_ref" for item in report.findings)


def test_linear_constraint_buffer_changes_large_parcel_candidate_selection():
    factor = ConstraintFactor(
        factor_id="factor:avoid-road-buffer",
        kind="avoid_constraint",
        evaluator_key="avoid_constraint",
        subject_ref="target:site",
        object_ref="road:main",
        object_ref_kind="constraint",
        parameters=AvoidConstraintParameters(
            constraint_refs=["road:main"],
            buffer_m=10,
        ),
        hard=True,
    )
    context = _road_context([_road_candidate()])
    resolution = resolve_relation_reference_features(
        context,
        [factor],
        scenario_id="scenario:road-buffer",
    )
    geometries = [
        CandidateGeometry(
            candidate_id="site:inside-buffer",
            target_id="target:site",
            kind="polygon",
            role="execution_geometry",
            materialization_role="site_footprint",
            wkt="POLYGON ((40 0, 45 0, 45 5, 40 5, 40 0))",
            crs="EPSG:3857",
            source_ref="bundle:parcel:inside",
            source_bsms=["parcel:inside"],
            hard_constraint_status="passed",
        ),
        CandidateGeometry(
            candidate_id="site:outside-buffer",
            target_id="target:site",
            kind="polygon",
            role="execution_geometry",
            materialization_role="site_footprint",
            wkt="POLYGON ((0 0, 5 0, 5 5, 0 5, 0 0))",
            crs="EPSG:3857",
            source_ref="bundle:parcel:outside",
            source_bsms=["parcel:outside"],
            hard_constraint_status="passed",
        ),
    ]
    problem = GroundedPlanningProblem(
        candidate_domains=[GroundedCandidateDomain(
            target_id="target:site",
            candidate_ids=["site:inside-buffer", "site:outside-buffer"],
        )],
        candidate_geometries=geometries,
        constraint_factors=[factor],
    )

    result = solve_scenario(
        problem,
        scenario_id="scenario:road-buffer",
        evaluator_context=RelationEvaluationContext(
            scenario_id="scenario:road-buffer",
            metric_crs="EPSG:3857",
            reference_features=resolution.features,
        ),
    )

    assert result.status == "complete"
    assert {
        item.target_id: item.candidate_ids
        for item in result.target_selections
    } == {"target:site": ["site:outside-buffer"]}
    assert result.relation_satisfactions[0].status == "satisfied"
    assert result.relation_satisfactions[0].measurement.method == "disjoint_buffered_constraint"
