from app.contracts.planning.constraint_factor import ConstraintFactor
from app.contracts.planning.relation_parameters import DistanceParameters
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounded_problem import GroundedCandidateDomain, GroundedPlanningProblem
from app.domain.allocation.scenario_optimizer import optimize_scenarios
from app.domain.relations.service import RelationEvaluationContext


def _recommended(problem, *, scenario_id: str, evaluator_context: RelationEvaluationContext):
    scenario_set = optimize_scenarios(
        problem,
        set_id=scenario_id,
        evaluator_context=evaluator_context,
        max_scenarios=8,
    )
    assert scenario_set.recommended is not None, scenario_set.model_dump(mode="json")
    return scenario_set.recommended


def _problem(factors, geometries, domains):
    domains = [
        domain.model_copy(
            update={
                "candidate_geometry_refs": list(domain.candidate_ids),
                "status": "resolved",
            }
        )
        for domain in domains
    ]
    return GroundedPlanningProblem(
        candidate_domains=domains,
        candidate_geometries=geometries,
        constraint_factors=factors,
    )


def _geometry(candidate_id, target_id, point, score=0.5):
    return CandidateGeometry(
        candidate_id=candidate_id,
        target_id=target_id,
        kind="point",
        role="execution_geometry",
        wkt=f"POINT ({point} 0)",
        source_ref=f"source:{candidate_id}",
        evidence_refs=[f"evidence:{candidate_id}"],
        suitability_components={"suitability": score},
    )


def _polygon_geometry(candidate_id, target_id, wkt, score=0.5, *, source_bsm=""):
    return CandidateGeometry(
        candidate_id=candidate_id,
        target_id=target_id,
        kind="polygon",
        role="execution_geometry",
        materialization_role="site_footprint",
        wkt=wkt,
        crs="EPSG:3857",
        source_ref=f"source:{candidate_id}",
        source_bsms=[source_bsm] if source_bsm else [],
        l1_fact_refs=[f"l1:{candidate_id}"],
        l1_snapshot_ref="l1:snapshot:test",
        bundle_snapshot_digest="bundle:test",
        generation_operation="select_planning_subgeometry",
        hard_constraint_status="passed",
        evidence_refs=[f"evidence:{candidate_id}"],
        suitability_components={"suitability": score},
    )


def test_hard_relation_changes_feasible_set_and_soft_relation_changes_objective():
    geometries = [
        _geometry("a-near", "a", 0.0, 0.1),
        _geometry("a-far", "a", 1.0, 0.9),
        _geometry("b", "b", 0.0001, 0.5),
    ]
    hard_near = ConstraintFactor(
        factor_id="factor:near-hard",
        kind="near",
        evaluator_key="near",
        subject_ref="a",
        object_ref="b",
        hard=True,
        parameters=DistanceParameters(max_distance_m=100, metric="euclidean"),
    )
    problem = _problem(
        [hard_near],
        geometries,
        [
            GroundedCandidateDomain(target_id="a", candidate_ids=["a-near", "a-far"]),
            GroundedCandidateDomain(target_id="b", candidate_ids=["b"]),
        ],
    )
    result = _recommended(
        problem,
        scenario_id="scenario-hard",
        evaluator_context=RelationEvaluationContext(scenario_id="scenario-hard"),
    )
    assert result.status == "complete"
    assert {item.target_id: item.candidate_ids for item in result.target_selections} == {
        "a": ["a-near"], "b": ["b"]
    }
    assert result.relation_satisfactions[0].status == "satisfied"


def test_no_hard_feasible_combination_fails_closed():
    geometries = [_geometry("a", "a", 0.0), _geometry("b", "b", 1.0)]
    factor = ConstraintFactor(
        factor_id="factor:near-hard",
        kind="near",
        evaluator_key="near",
        subject_ref="a",
        object_ref="b",
        hard=True,
        parameters=DistanceParameters(max_distance_m=10, metric="euclidean"),
    )
    scenario_set = optimize_scenarios(
        _problem(
            [factor],
            geometries,
            [
                GroundedCandidateDomain(target_id="a", candidate_ids=["a"]),
                GroundedCandidateDomain(target_id="b", candidate_ids=["b"]),
            ],
        ),
        set_id="scenario-failed",
        evaluator_context=RelationEvaluationContext(scenario_id="scenario-failed"),
        max_scenarios=8,
    )
    assert scenario_set.recommended is None
    assert scenario_set.feasible_scenario_ids == []
    assert scenario_set.solver_certificate.status == "infeasible"


def test_soft_relation_is_scored_without_blocking_the_scenario():
    geometries = [
        _geometry("a-near", "a", 0.0, 0.5),
        _geometry("a-far", "a", 1.0, 0.9),
        _geometry("b", "b", 0.0001, 0.5),
    ]
    soft_near = ConstraintFactor(
        factor_id="factor:near-soft",
        kind="near",
        evaluator_key="near",
        subject_ref="a",
        object_ref="b",
        hard=False,
        weight=10,
        parameters=DistanceParameters(max_distance_m=100, metric="euclidean"),
    )
    result = _recommended(
        _problem(
            [soft_near],
            geometries,
            [
                GroundedCandidateDomain(target_id="a", candidate_ids=["a-near", "a-far"]),
                GroundedCandidateDomain(target_id="b", candidate_ids=["b"]),
            ],
        ),
        scenario_id="scenario-soft",
        evaluator_context=RelationEvaluationContext(scenario_id="scenario-soft"),
    )
    assert result.status == "complete"
    selections = {item.target_id: item.candidate_ids for item in result.target_selections}
    assert selections["a"] == ["a-near"]
    assert result.metrics["relation_objective"] == 10


def test_relation_selection_measures_selected_subgeometry_and_keeps_lineage():
    geometries = [
        _polygon_geometry(
            "a-near-slice",
            "a",
            "POLYGON ((90 0, 95 0, 95 5, 90 5, 90 0))",
            score=0.1,
            source_bsm="parcel:a",
        ),
        _polygon_geometry(
            "a-far-source",
            "a",
            "POLYGON ((0 0, 5 0, 5 5, 0 5, 0 0))",
            score=0.9,
            source_bsm="parcel:a",
        ),
        _geometry("b", "b", 100.0, 0.5).model_copy(update={"crs": "EPSG:3857"}),
    ]
    hard_near = ConstraintFactor(
        factor_id="factor:near-sliced-parcel",
        kind="near",
        evaluator_key="near",
        subject_ref="a",
        object_ref="b",
        hard=True,
        parameters=DistanceParameters(max_distance_m=10, metric="euclidean"),
    )
    result = _recommended(
        _problem(
            [hard_near],
            geometries,
            [
                GroundedCandidateDomain(
                    target_id="a",
                    candidate_ids=["a-near-slice", "a-far-source"],
                ),
                GroundedCandidateDomain(target_id="b", candidate_ids=["b"]),
            ],
        ),
        scenario_id="scenario-sliced-parcel",
        evaluator_context=RelationEvaluationContext(scenario_id="scenario-sliced-parcel"),
    )

    assert result.status == "complete"
    assert {item.target_id: item.candidate_ids for item in result.target_selections} == {
        "a": ["a-near-slice"], "b": ["b"]
    }
    satisfaction = result.relation_satisfactions[0]
    assert satisfaction.status == "satisfied"
    assert satisfaction.measurement is not None
    assert satisfaction.measurement.value == 5.0
    selected = next(item for item in result.feature_intents if item.target_id == "a")
    assert selected.geometry_wkt.startswith("POLYGON ((90 0")
    assert selected.source_bsms == ["parcel:a"]
    assert selected.l1_fact_refs == ["l1:a-near-slice"]
    assert selected.l1_snapshot_ref == "l1:snapshot:test"
    assert selected.bundle_snapshot_digest == "bundle:test"
    assert selected.generation_operation == "select_planning_subgeometry"
