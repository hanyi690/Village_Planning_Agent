import pytest
from pydantic import ValidationError

from app.contracts.planning.constraint_factor import ConstraintFactor
from app.contracts.planning.relation_parameters import (
    AccessParameters,
    ConnectParameters,
    DistanceParameters,
    MutuallyExclusiveParameters,
    ServiceParameters,
)
from app.contracts.domain.l3_contracts import PlanningIntervention, PlanningProgram
from app.contracts.planning.scenario import ScenarioSet, SolverCertificate
from app.contracts.planning.solver import BackendResult, SolverConfig
from app.contracts.planning.intent_graph import PlanningIntentGraph
from app.contracts.planning.scenario import ScenarioFeature
from app.contracts.spatial.grounding_contracts import CandidateSite
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounded_problem import (
    GroundedCandidateDomain,
    GroundingFinding,
    GroundedPlanningProblem,
    GroundedTargetDomain,
    derive_parcel_resource_pool,
)
from app.domain.allocation.solver_portfolio import (
    DeterministicChoiceBackend,
    SolverBackendRegistry,
    build_solver_problem_view,
    default_solver_registry,
)
from app.domain.allocation.refined_candidate_catalog import _partition_shared_parcel_candidates
from app.domain.allocation.scenario_optimizer import optimize_scenarios
from app.domain.allocation.approval_input import build_approved_execution_input
from app.domain.relations.service import RelationEvaluationContext
from app.domain.ground.aggregate import _build_grounded_problem
from app.domain.program.target_projection.intent_graph_compiler import compile_intent_graph_v2
from app.domain.demand.facility_demand_model import FacilityDemandPoint, build_demand_snapshot
from app.spatial.network.network_graph import build_network_graph


def _problem(*, solver_kind: str = "auto") -> GroundedPlanningProblem:
    geometry = CandidateGeometry(
        candidate_id="site-a",
        target_id="target-a",
        kind="point",
        role="execution_geometry",
        wkt="POINT (0 0)",
        crs="EPSG:3857",
        source_ref="source:site-a",
        evidence_refs=["evidence:site-a"],
        hard_constraint_status="passed",
        suitability_components={"suitability": 0.8},
    )
    return GroundedPlanningProblem(
        solver_kind=solver_kind,
        target_domains=[GroundedTargetDomain(
            target_id="target-a",
            target_kind="facility",
            expected_output_kind="point",
            candidate_site_refs=["site-a"],
            geometry_roles=["execution_geometry"],
            status="resolved",
        )],
        candidate_domains=[GroundedCandidateDomain(
            target_id="target-a",
            candidate_ids=["site-a"],
            candidate_geometry_refs=["site-a"],
            selection_mode="choose_one",
            status="resolved",
        )],
        candidate_geometries=[geometry],
    )


def test_view_derives_typed_single_choice_kind_and_required_refs():
    view = build_solver_problem_view(_problem())

    assert view.problem_kind == "single_choice"
    assert view.problem_fingerprint
    assert "source:site-a" in view.required_input_refs
    assert view.target_ids == ("target-a",)


def test_default_registry_resolves_deterministic_choice_for_single_choice():
    registry = default_solver_registry()
    view = build_solver_problem_view(_problem())
    resolution = registry.resolve(_problem(), view)

    assert resolution.backend is not None
    assert resolution.backend.backend_id == "deterministic_choice"
    assert resolution.support.supported is True


def test_unknown_solver_kind_fails_closed_without_fallback():
    problem = _problem(solver_kind="network_path")
    view = build_solver_problem_view(problem)
    registry = SolverBackendRegistry([DeterministicChoiceBackend()])
    resolution = registry.resolve(problem, view)

    assert resolution.backend is None
    assert resolution.support.supported is False
    assert "UNSUPPORTED_SOLVER_KIND" in resolution.support.reason_codes
    assert view.problem_kind == "network_path"
    assert view.input_complete is False


def test_backend_certificate_carries_replay_settings_and_lineage():
    problem = _problem()
    view = build_solver_problem_view(problem)
    backend = DeterministicChoiceBackend()

    result = backend.solve(
        problem,
        view,
        config=SolverConfig(search_limit=10, deterministic_seed=7),
    )

    assert result.certificate.backend_id == "deterministic_choice"
    assert result.certificate.backend_version == backend.backend_version
    assert result.certificate.problem_kind == "single_choice"
    assert result.certificate.input_digest
    assert result.certificate.required_input_refs == list(view.required_input_refs)
    assert result.scenario_set is not None


def test_scenario_optimizer_facade_records_selected_backend_route():
    result = optimize_scenarios(
        _problem(),
        set_id="slice1-route",
        evaluator_context=RelationEvaluationContext(scenario_id="slice1-route"),
    )

    assert result.solver_certificate.backend_id == "deterministic_choice"
    assert result.solver_certificate.backend_version == "1.0"
    assert result.solver_certificate.problem_kind == "single_choice"
    assert result.solver_certificate.backend_certificate.input_digest


def test_scenario_optimizer_explicit_unsupported_kind_is_diagnostic_only():
    result = optimize_scenarios(
        _problem(solver_kind="network_path"),
        set_id="slice1-unsupported",
        evaluator_context=RelationEvaluationContext(scenario_id="slice1-unsupported"),
    )

    assert result.solver_certificate.status == "unknown"
    assert result.feasible_scenario_ids == []
    assert "UNSUPPORTED_SOLVER_KIND" in result.solver_certificate.termination_reason


def test_network_relation_backend_solves_when_network_snapshot_and_reference_are_bound():
    base = _problem()
    factor = ConstraintFactor(
        kind="connect_network",
        evaluator_key="connect",
        subject_ref="target-a",
        object_ref="existing:road",
        object_ref_kind="entity",
        hard=True,
        parameters=ConnectParameters(
            network_kind="road",
            endpoint_tolerance_m=5,
            network_ref="network:road:test",
        ),
    )
    problem = GroundedPlanningProblem(**{
        **base.model_dump(exclude={"fingerprint", "candidate_completeness"}),
        "constraint_factors": [factor],
    })
    network = build_network_graph(
        [{"geometry": {"type": "LineString", "coordinates": [[0, 0], [100, 0]]}, "crs": "EPSG:3857"}],
        impedance="travel_time_min",
        network_ref="network:road:test",
        source_crs="EPSG:3857",
        metric_crs="EPSG:3857",
        snap_tolerance_m=5,
    )
    reference = ScenarioFeature(
        feature_id="feature:existing-road",
        scenario_id="network-positive",
        target_id="existing:road",
        candidate_id="reference:road",
        geometry_kind="point",
        geometry_wkt="POINT (100 0)",
        crs="EPSG:3857",
        generation_operation="test_reference",
        source_refs=["road:existing"],
        relation_ids=["connect:existing-road"],
    )
    context = RelationEvaluationContext(
        scenario_id="network-positive",
        networks={"network:road:test": network},
        reference_features={"existing:road": reference},
    )

    view = build_solver_problem_view(problem, evaluator_context=context)
    result = optimize_scenarios(problem, set_id="network-positive", evaluator_context=context)

    assert view.problem_kind == "network_path"
    assert view.input_complete is True
    assert result.solver_certificate.backend_id == "network_relation_bounded"
    assert result.feasible_scenario_ids
    assert result.recommended is not None
    assert any(
        satisfaction.status == "satisfied"
        for satisfaction in result.recommended.relation_satisfactions
    )


def test_coverage_relation_backend_requires_typed_demand_snapshot():
    base = _problem()
    factor = ConstraintFactor(
        kind="serve",
        evaluator_key="service",
        subject_ref="target-a",
        object_ref="demand:village",
        object_ref_kind="entity",
        hard=True,
        parameters=ServiceParameters(
            demand_ref="demand:village",
            facility_type="clinic",
            max_travel_time_min=15,
            min_coverage_ratio=0.8,
            capacity=100,
            capacity_unit="person",
            network_ref="network:road:test",
        ),
    )
    problem = GroundedPlanningProblem(**{
        **base.model_dump(exclude={"fingerprint", "candidate_completeness"}),
        "constraint_factors": [factor],
    })
    network = build_network_graph(
        [{"geometry": {"type": "LineString", "coordinates": [[0, 0], [100, 0]]}, "crs": "EPSG:3857"}],
        impedance="travel_time_min",
        network_ref="network:road:test",
        source_crs="EPSG:3857",
        metric_crs="EPSG:3857",
        snap_tolerance_m=5,
    )
    demand = build_demand_snapshot(
        "demand:village",
        [FacilityDemandPoint(
            demand_id="demand-1",
            geometry_wkt="POINT (100 0)",
            crs="EPSG:3857",
            demand_value=50,
            demand_unit="person",
            facility_types=("clinic",),
        )],
    )
    context = RelationEvaluationContext(
        scenario_id="coverage-positive",
        networks={"network:road:test": network},
        demands={"demand:village": demand},
    )

    view = build_solver_problem_view(problem, evaluator_context=context)
    result = optimize_scenarios(problem, set_id="coverage-positive", evaluator_context=context)

    assert view.problem_kind == "coverage"
    assert view.input_complete is True
    assert result.solver_certificate.backend_id == "network_relation_bounded"
    assert result.feasible_scenario_ids


@pytest.mark.parametrize(
    ("problem", "expected_kind"),
    [
        (
            lambda: GroundedPlanningProblem(
                **{
                    **_problem().model_dump(exclude={"fingerprint", "candidate_completeness"}),
                    "constraint_factors": [ConstraintFactor(
                        kind="connect_network",
                        evaluator_key="connect",
                        subject_ref="target-a",
                        object_ref="existing:road",
                        object_ref_kind="entity",
                        hard=True,
                        parameters=ConnectParameters(
                            network_kind="road",
                            endpoint_tolerance_m=10,
                            network_ref="network:road:1",
                        ),
                    )],
                }
            ),
            "network_path",
        ),
        (
            lambda: GroundedPlanningProblem(
                **{
                    **_problem().model_dump(exclude={"fingerprint", "candidate_completeness"}),
                    "constraint_factors": [ConstraintFactor(
                        kind="serve",
                        evaluator_key="service",
                        subject_ref="target-a",
                        object_ref="demand:village",
                        object_ref_kind="entity",
                        hard=True,
                        parameters=ServiceParameters(
                            demand_ref="demand:village",
                            facility_type="clinic",
                            max_travel_time_min=15,
                            min_coverage_ratio=0.8,
                            capacity=100,
                            capacity_unit="person",
                            network_ref="network:road:1",
                        ),
                    )],
                }
            ),
            "coverage",
        ),
        (
            lambda: GroundedPlanningProblem(
                **{
                    **_problem().model_dump(exclude={"fingerprint", "candidate_completeness"}),
                    "shared_resource_refs": ["parcel-pool:v1"],
                }
            ),
            "parcel_assignment",
        ),
        (
            lambda: GroundedPlanningProblem(
                **{
                    **_problem().model_dump(exclude={"fingerprint", "candidate_completeness"}),
                    "constraint_factors": [ConstraintFactor(
                        kind="mutually_exclusive",
                        evaluator_key="topology_layout",
                        subject_ref="target-a",
                        object_ref="target-b",
                        hard=True,
                        geometry_scope="global",
                        parameters=MutuallyExclusiveParameters(scope_ref="layout:v1"),
                    )],
                }
            ),
            "topology_layout",
        ),
    ],
)
def test_auto_complex_problem_kinds_fail_closed(problem, expected_kind):
    grounded = problem()
    view = build_solver_problem_view(grounded)
    result = optimize_scenarios(
        grounded,
        set_id=f"slice1-{expected_kind}",
        evaluator_context=RelationEvaluationContext(scenario_id=f"slice1-{expected_kind}"),
    )

    assert view.problem_kind == expected_kind
    assert result.solver_certificate.status == "unknown"
    assert result.feasible_scenario_ids == []
    assert "UNSUPPORTED_SOLVER_KIND" in result.solver_certificate.termination_reason


def test_final_model_digest_covers_route_config_and_typed_input():
    base = optimize_scenarios(
        _problem(),
        set_id="slice1-digest",
        evaluator_context=RelationEvaluationContext(scenario_id="slice1-digest"),
        deterministic_seed=3,
        search_limit=9,
    )
    changed = optimize_scenarios(
        _problem(),
        set_id="slice1-digest",
        evaluator_context=RelationEvaluationContext(scenario_id="slice1-digest"),
        deterministic_seed=4,
        search_limit=9,
    )

    assert base.solver_certificate.model_digest != changed.solver_certificate.model_digest
    proof = base.solver_certificate.backend_certificate
    assert proof is not None
    assert proof.solver_config["deterministic_seed"] == 3
    assert proof.input_digest

    version_problem = _problem()
    version_view = build_solver_problem_view(version_problem)
    version_config = SolverConfig(deterministic_seed=3, search_limit=9)
    original_backend = DeterministicChoiceBackend().solve(
        version_problem,
        version_view,
        config=version_config,
        set_id="slice1-version-digest",
    )
    upgraded_backend = DeterministicChoiceBackend()
    upgraded_backend.backend_version = "2.0"
    upgraded = upgraded_backend.solve(
        version_problem,
        version_view,
        config=version_config,
        set_id="slice1-version-digest",
    )
    assert original_backend.scenario_set is not None
    assert upgraded.scenario_set is not None
    assert (
        upgraded.scenario_set.solver_certificate.model_digest
        != original_backend.scenario_set.solver_certificate.model_digest
    )


def test_formal_scenario_set_rejects_missing_or_forged_backend_proof():
    formal = optimize_scenarios(
        _problem(),
        set_id="slice1-proof",
        evaluator_context=RelationEvaluationContext(scenario_id="slice1-proof"),
    )
    payload = formal.model_dump(mode="python", exclude={"fingerprint"})
    payload["solver_certificate"]["backend_certificate"] = None
    payload["solver_certificate"]["fingerprint"] = ""
    with pytest.raises(ValidationError, match="backend certificate"):
        ScenarioSet(**payload)

    forged = formal.model_dump(mode="python", exclude={"fingerprint"})
    forged["solver_certificate"]["backend_certificate"]["backend_id"] = "forged"
    forged["solver_certificate"]["fingerprint"] = ""
    with pytest.raises(ValidationError, match="backend_id"):
        ScenarioSet(**forged)

    forged_digest = formal.model_dump(mode="python", exclude={"fingerprint"})
    forged_digest["solver_certificate"]["backend_certificate"]["input_digest"] = "forged"
    forged_digest["solver_certificate"]["fingerprint"] = ""
    with pytest.raises(ValidationError, match="model_digest"):
        ScenarioSet(**forged_digest)

    incomplete_config = formal.model_dump(mode="python", exclude={"fingerprint"})
    incomplete_config["solver_certificate"]["backend_certificate"][
        "solver_config"
    ].pop("objective_definitions")
    incomplete_config["solver_certificate"]["fingerprint"] = ""
    with pytest.raises(ValidationError, match="solver_config is incomplete"):
        ScenarioSet(**incomplete_config)

    with pytest.raises(ValidationError, match="backend id and version"):
        ScenarioSet(
            set_id="slice1-bounded-no-proof",
            problem_fingerprint="problem:bounded",
            solver_certificate=SolverCertificate(
                problem_fingerprint="problem:bounded",
                model_digest="legacy-empty-proof",
                solver_version="legacy:test",
                status="bounded",
            ),
        )


def test_backend_result_rejects_scenario_set_certificate_mismatch():
    problem = _problem()
    view = build_solver_problem_view(problem)
    result = DeterministicChoiceBackend().solve(
        problem,
        view,
        config=SolverConfig(search_limit=10),
    )
    payload = result.model_dump(mode="python")
    payload["certificate"]["backend_version"] = "forged"

    with pytest.raises(ValidationError, match="backend certificate"):
        BackendResult(**payload)


def test_ground_compiles_and_audits_specialized_solver_kind():
    base = _problem()
    candidate = CandidateSite(
        site_id="site-a",
        target_ref="target-a",
        target_kind="facility",
        expected_output_kind="point",
        evidence_refs=["evidence:site-a"],
        geometry=base.candidate_geometries[0],
    )
    factor = ConstraintFactor(
        kind="serve",
        evaluator_key="service",
        subject_ref="target-a",
        object_ref="demand:village",
        object_ref_kind="entity",
        hard=True,
        parameters=ServiceParameters(
            demand_ref="demand:village",
            facility_type="clinic",
            max_travel_time_min=15,
            min_coverage_ratio=0.8,
            capacity=100,
            capacity_unit="person",
            network_ref="network:road:1",
        ),
    )

    grounded = _build_grounded_problem(
        [candidate],
        [],
        [factor],
        [],
        PlanningIntentGraph(),
    )

    assert grounded.solver_kind == "coverage"
    assert grounded.solver_kind_reasons == ["typed_service_coverage_factor"]
    assert any(item.startswith("solver_kind:coverage:") for item in grounded.diagnostics)


def test_explicit_bounded_kind_cannot_override_typed_network_facts():
    base = _problem()
    problem = GroundedPlanningProblem(
        **{
            **base.model_dump(exclude={"fingerprint", "candidate_completeness"}),
            "solver_kind": "bounded_multiobjective",
            "constraint_factors": [ConstraintFactor(
                kind="connect_network",
                evaluator_key="connect",
                subject_ref="target-a",
                object_ref="existing:road",
                object_ref_kind="entity",
                hard=True,
                parameters=ConnectParameters(
                    network_kind="road",
                    endpoint_tolerance_m=10,
                    network_ref="network:road:1",
                ),
            )],
        }
    )

    view = build_solver_problem_view(problem)
    result = optimize_scenarios(
        problem,
        set_id="slice1-explicit-conflict",
        evaluator_context=RelationEvaluationContext(scenario_id="slice1-explicit-conflict"),
    )

    assert view.problem_kind == "network_path"
    assert "solver_kind_conflict:bounded_multiobjective:network_path" in view.routing_reason_codes
    assert result.solver_certificate.status == "unknown"


@pytest.mark.parametrize(
    ("updates", "expected_kind"),
    [
        (
            {"constraint_factors": [ConstraintFactor(
                kind="serve",
                evaluator_key="service",
                subject_ref="target-a",
                object_ref="demand:village",
                object_ref_kind="entity",
                hard=True,
                parameters=ServiceParameters(
                    demand_ref="demand:village",
                    facility_type="clinic",
                    max_travel_time_min=15,
                    min_coverage_ratio=0.8,
                    capacity=100,
                    capacity_unit="person",
                    network_ref="network:road:1",
                ),
            )]},
            "coverage",
        ),
        ({"shared_resource_refs": ["parcel-pool:v1"]}, "parcel_assignment"),
        (
            {"constraint_factors": [ConstraintFactor(
                kind="mutually_exclusive",
                evaluator_key="topology_layout",
                subject_ref="target-a",
                object_ref="target-b",
                hard=True,
                geometry_scope="global",
                parameters=MutuallyExclusiveParameters(scope_ref="layout:v1"),
            )]},
            "topology_layout",
        ),
    ],
)
def test_explicit_bounded_kind_cannot_override_other_specialized_facts(
    updates,
    expected_kind,
):
    base = _problem()
    problem = GroundedPlanningProblem(**{
        **base.model_dump(exclude={"fingerprint", "candidate_completeness"}),
        "solver_kind": "bounded_multiobjective",
        **updates,
    })

    view = build_solver_problem_view(problem)
    result = optimize_scenarios(
        problem,
        set_id=f"slice1-explicit-{expected_kind}",
        evaluator_context=RelationEvaluationContext(
            scenario_id=f"slice1-explicit-{expected_kind}"
        ),
    )

    assert view.problem_kind == expected_kind
    assert (
        f"solver_kind_conflict:bounded_multiobjective:{expected_kind}"
        in view.routing_reason_codes
    )
    assert result.solver_certificate.status == "unknown"


@pytest.mark.parametrize(
    ("category", "materialization_role"),
    [
        ("protection", "protection_overlay"),
        ("restoration", "restoration_overlay"),
        ("zone", "functional_overlay"),
        ("site_area", "site_footprint"),
    ],
)
def test_uncoupled_polygon_intents_do_not_compile_as_parcel_assignment(
    category,
    materialization_role,
):
    intervention = PlanningIntervention(
        intervention_id=f"target:{category}",
        target_id=f"target:{category}",
        name=f"typed {category}",
        planning_role="spatial_intervention",
        execution_mode="spatial",
        expected_output_kind="polygon",
        category=category,
        materialization_role=materialization_role,
    )

    graph = compile_intent_graph_v2(PlanningProgram(interventions=[intervention]))

    assert graph.solver_kind == "auto"
    assert graph.solver_kind_reasons == ["no_specialized_solver_fact"]


def test_intent_compiler_emits_parcel_kind_only_for_explicit_resource_coupling():
    intervention = PlanningIntervention(
        intervention_id="target:land-use",
        target_id="target:land-use",
        name="typed land-use assignment",
        planning_role="spatial_intervention",
        execution_mode="spatial",
        expected_output_kind="polygon",
        category="zone",
        materialization_role="land_use_assignment",
        spatial_requirements={
            "shared_resource_refs": ["parcel-pool:v1"],
        },
    )

    graph = compile_intent_graph_v2(PlanningProgram(interventions=[intervention]))

    assert graph.solver_kind == "parcel_assignment"
    assert graph.solver_kind_reasons == ["typed_shared_resource"]
    assert graph.shared_resource_refs == ["parcel-pool:v1"]
    candidate = CandidateSite(
        site_id="parcel:1",
        target_ref="target:land-use",
        target_kind="zone",
        expected_output_kind="polygon",
        geometry=CandidateGeometry(
            candidate_id="parcel:1",
            target_id="target:land-use",
            kind="polygon",
            role="execution_geometry",
            materialization_role="land_use_assignment",
            wkt="POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))",
            source_ref="parcel:source:1",
        ),
    )

    grounded = _build_grounded_problem([candidate], [], [], [], graph)

    assert grounded.solver_kind == "parcel_assignment"
    assert grounded.shared_resource_refs == ["parcel-pool:v1"]


@pytest.mark.parametrize(
    "materialization_role",
    ["protection_overlay", "restoration_overlay", "functional_overlay"],
)
def test_ground_rejects_upstream_parcel_kind_without_coupling_facts(materialization_role):
    base = _problem()
    candidate = CandidateSite(
        site_id="site-a",
        target_ref="target-a",
        target_kind="site_area",
        expected_output_kind="polygon",
        geometry=base.candidate_geometries[0].model_copy(update={
            "kind": "polygon",
            "wkt": "POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))",
            "materialization_role": materialization_role,
        }),
    )
    graph = PlanningIntentGraph(
        solver_kind="parcel_assignment",
        solver_kind_reasons=["upstream_claim"],
    )

    grounded = _build_grounded_problem([candidate], [], [], [], graph)

    assert grounded.solver_kind == "parcel_assignment"
    assert any("explicit_solver_kind_missing_typed_facts:parcel_assignment" in item for item in grounded.solver_kind_reasons)


@pytest.mark.parametrize(
    "solver_kind",
    ["network_path", "coverage", "parcel_assignment", "topology_layout"],
)
def test_explicit_specialized_kind_without_typed_facts_stays_fail_closed_end_to_end(
    solver_kind,
):
    base = _problem()
    candidate = CandidateSite(
        site_id="site-a",
        target_ref="target-a",
        target_kind="facility",
        expected_output_kind="point",
        geometry=base.candidate_geometries[0],
    )
    graph = PlanningIntentGraph(
        solver_kind=solver_kind,
        solver_kind_reasons=[f"explicit_solver_kind:{solver_kind}"],
    )

    grounded = _build_grounded_problem([candidate], [], [], [], graph)
    view = build_solver_problem_view(grounded)
    resolution = default_solver_registry().resolve(grounded, view)
    result = optimize_scenarios(
        grounded,
        set_id=f"slice1-missing-fact-{solver_kind}",
        evaluator_context=RelationEvaluationContext(
            scenario_id=f"slice1-missing-fact-{solver_kind}"
        ),
    )

    assert grounded.solver_kind == solver_kind
    assert view.problem_kind == solver_kind
    assert view.input_complete is False
    assert f"missing:typed_solver_fact:{solver_kind}" in view.missing_input_refs
    if solver_kind == "network_path":
        assert "missing:network_ref" in view.missing_input_refs
    if solver_kind == "coverage":
        assert "missing:network_ref" in view.missing_input_refs
        assert "missing:demand_ref" in view.missing_input_refs
    assert resolution.backend is None
    assert resolution.support.input_complete is False
    assert "SOLVER_INPUT_INCOMPLETE" in resolution.support.reason_codes
    assert view.missing_input_refs[0] in resolution.support.required_input_refs
    assert result.solver_certificate.status == "unknown"
    assert result.solver_certificate.backend_id == "unresolved"


@pytest.mark.parametrize(
    "solver_kind",
    ["network_path", "coverage", "parcel_assignment", "topology_layout"],
)
def test_specialized_missing_fact_precedes_grounding_incomplete_diagnostic_enumeration(
    solver_kind,
):
    problem = GroundedPlanningProblem(
        solver_kind=solver_kind,
        target_domains=[GroundedTargetDomain(
            target_id="target:unresolved",
            target_kind="facility",
            expected_output_kind="point",
            status="unresolved",
            unresolved_reason="missing candidate",
        )],
        unresolved=[GroundingFinding(
            code="UNRESOLVED_TARGET",
            message="target has no grounded candidate",
            target_id="target:unresolved",
        )],
    )
    assert problem.can_solve is False

    result = optimize_scenarios(
        problem,
        set_id=f"slice1-unresolved-missing-{solver_kind}",
        evaluator_context=RelationEvaluationContext(
            scenario_id=f"slice1-unresolved-missing-{solver_kind}"
        ),
    )

    assert result.solver_certificate.status == "unknown"
    assert result.solver_certificate.backend_id == "unresolved"
    assert result.scenarios == []
    assert result.feasible_scenario_ids == []
    assert result.pareto_scenario_ids == []
    proof = result.solver_certificate.backend_certificate
    assert proof is not None
    assert f"missing:typed_solver_fact:{solver_kind}" in proof.required_input_refs


@pytest.mark.parametrize(
    "factor",
    [
        ConstraintFactor(
            kind="connect_network",
            evaluator_key="connect",
            parameters=ConnectParameters(
                network_kind="road",
                endpoint_tolerance_m=10,
                network_ref="network:connect",
            ),
        ),
        ConstraintFactor(
            kind="provide_access",
            evaluator_key="access_via",
            parameters=AccessParameters(
                max_travel_time_min=10,
                network_ref="network:access",
            ),
        ),
        ConstraintFactor(
            kind="serve",
            evaluator_key="service",
            parameters=ServiceParameters(
                demand_ref="demand:village",
                facility_type="clinic",
                max_travel_time_min=15,
                min_coverage_ratio=0.8,
                capacity=100,
                capacity_unit="person",
                network_ref="network:service",
            ),
        ),
        ConstraintFactor(
            kind="near",
            evaluator_key="near",
            parameters=DistanceParameters(
                max_distance_m=500,
                metric="network",
                network_ref="network:distance",
            ),
        ),
    ],
)
def test_ground_and_solver_proof_collect_typed_parameter_network_refs(factor):
    base = _problem()
    candidate = CandidateSite(
        site_id="site-a",
        target_ref="target-a",
        target_kind="facility",
        expected_output_kind="point",
        geometry=base.candidate_geometries[0],
    )
    expected_ref = factor.parameters.network_ref

    grounded = _build_grounded_problem(
        [candidate],
        [],
        [factor],
        [],
        PlanningIntentGraph(),
    )
    view = build_solver_problem_view(grounded)
    result = optimize_scenarios(
        grounded,
        set_id=f"slice1-network-ref-{factor.parameters.parameter_type}",
        evaluator_context=RelationEvaluationContext(
            scenario_id=f"slice1-network-ref-{factor.parameters.parameter_type}"
        ),
    )

    assert grounded.network_refs == [expected_ref]
    assert expected_ref in view.required_input_refs
    assert expected_ref in view.snapshot_refs
    assert expected_ref in result.solver_certificate.required_input_refs


def test_unknown_scenario_set_cannot_hide_complete_scenario():
    formal = optimize_scenarios(
        _problem(),
        set_id="slice1-hidden-complete-source",
        evaluator_context=RelationEvaluationContext(scenario_id="slice1-hidden-complete-source"),
    )
    diagnostic = optimize_scenarios(
        _problem(solver_kind="network_path"),
        set_id="slice1-hidden-complete-diagnostic",
        evaluator_context=RelationEvaluationContext(scenario_id="slice1-hidden-complete-diagnostic"),
    )
    payload = diagnostic.model_dump(mode="python", exclude={"fingerprint"})
    payload["scenarios"] = [formal.recommended.model_copy(update={
        "problem_fingerprint": diagnostic.problem_fingerprint,
        "fingerprint": "",
    })]

    with pytest.raises(ValidationError, match="complete scenarios must be formal feasible"):
        ScenarioSet(**payload)


def test_approval_rejects_diagnostic_set_even_if_complete_member_is_hidden():
    formal = optimize_scenarios(
        _problem(),
        set_id="slice1-approval-source",
        evaluator_context=RelationEvaluationContext(scenario_id="slice1-approval-source"),
    )
    scenario = formal.recommended
    diagnostic_set = type("DiagnosticSet", (), {
        "set_id": "diagnostic:set",
        "problem_fingerprint": scenario.problem_fingerprint,
        "baseline_ref": "",
        "scenarios": [scenario],
        "feasible_scenario_ids": [],
        "pareto_scenario_ids": [],
        "recommended_scenario_id": "",
        "solver_certificate": type("Certificate", (), {
            "status": "unknown",
            "backend_id": "unresolved",
            "backend_version": "1.0",
            "backend_certificate": object(),
        })(),
    })()

    approval = build_approved_execution_input(
        scenario_set=diagnostic_set,
        scenario=scenario,
        scenario_set_ref="diagnostic:set",
        scenario_ref=scenario.scenario_id,
        approval_id="approval:hidden",
        approval_status="human_approved",
        approved_by="reviewer:1",
        approval_reason="manual selection",
        execution_plan_digest="plan:digest",
    )

    assert approval is None


def test_approval_policy_requires_recommendation_or_explicit_human_choice():
    formal = optimize_scenarios(
        _problem(),
        set_id="slice1-approval-policy",
        evaluator_context=RelationEvaluationContext(scenario_id="slice1-approval-policy"),
    )
    recommended = formal.recommended
    alternative = recommended.__class__(**{
        **recommended.model_dump(mode="python", exclude={"fingerprint"}),
        "scenario_id": "slice1-approval-policy:alternative",
        "feature_intents": [],
    })
    certificate = SolverCertificate(**{
        **formal.solver_certificate.model_dump(
            mode="python",
            exclude={"fingerprint"},
        ),
        "feasible_scenario_count": 2,
    })
    scenario_set = ScenarioSet(
        set_id=formal.set_id,
        problem_fingerprint=formal.problem_fingerprint,
        scenarios=[recommended, alternative],
        feasible_scenario_ids=[recommended.scenario_id, alternative.scenario_id],
        pareto_scenario_ids=[recommended.scenario_id, alternative.scenario_id],
        recommended_scenario_id=recommended.scenario_id,
        objective_definitions=formal.objective_definitions,
        objective_vectors={
            recommended.scenario_id: recommended.objective_vector,
            alternative.scenario_id: alternative.objective_vector,
        },
        solver_certificate=certificate,
    )
    common = {
        "scenario_set": scenario_set,
        "scenario": alternative,
        "scenario_set_ref": scenario_set.set_id,
        "scenario_ref": alternative.scenario_id,
        "approval_id": "approval:alternative",
        "execution_plan_digest": "plan:digest",
    }

    assert build_approved_execution_input(
        **common,
        approval_status="auto",
    ) is None
    assert build_approved_execution_input(
        **common,
        approval_status="human_approved",
        approved_by="reviewer:1",
    ) is None
    assert build_approved_execution_input(
        **common,
        approval_status="human_approved",
        approved_by="reviewer:1",
        approval_reason="selected from the feasible frontier",
    ) is not None


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("required_input_refs", ["forged:ref"], "backend certificate"),
        (
            "solver_config",
            {"search_limit": 999},
            "backend certificate",
        ),
        (
            "deterministic_settings",
            {"deterministic_seed": 999},
            "backend certificate",
        ),
        ("termination_reason", "forged termination", "backend certificate"),
        ("selected_candidate_ids", {"target-a": ["forged:candidate"]}, "selected_candidate_ids"),
        ("route_refs", ["forged:route"], "route_refs"),
    ],
)
def test_backend_result_rejects_any_forged_proof_or_output(field, value, message):
    problem = _problem()
    result = DeterministicChoiceBackend().solve(
        problem,
        build_solver_problem_view(problem),
        config=SolverConfig(search_limit=10),
    )
    payload = result.model_dump(mode="python")
    if field in {"selected_candidate_ids", "route_refs"}:
        payload[field] = value
    elif field in {"solver_config", "deterministic_settings"}:
        payload["certificate"][field].update(value)
    else:
        payload["certificate"][field] = value

    with pytest.raises(ValidationError, match=message):
        BackendResult(**payload)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
            ("scenario_content", "scenario fingerprint|scenarios do not match"),
            ("scenario_status", "scenario fingerprint|scenarios do not match"),
            ("scenario_fingerprint", "scenario fingerprint|scenarios do not match"),
        ("findings", "findings do not match"),
        ("explanations", "infeasibility_explanations do not match"),
        ("missing_set", "scenario_set"),
    ],
)
def test_backend_result_requires_complete_canonical_scenario_set_projection(
    mutation,
    message,
):
    problem = _problem()
    result = DeterministicChoiceBackend().solve(
        problem,
        build_solver_problem_view(problem),
        config=SolverConfig(search_limit=10),
    )
    payload = result.model_dump(mode="python")
    if mutation == "scenario_content":
        payload["scenarios"][0]["metrics"] = {"forged": 1.0}
    elif mutation == "scenario_status":
        payload["scenarios"][0]["status"] = "partial"
    elif mutation == "scenario_fingerprint":
        payload["scenarios"][0]["fingerprint"] = "forged:fingerprint"
    elif mutation == "findings":
        payload["findings"] = [{
            "code": "FORGED",
            "message": "forged",
        }]
    elif mutation == "explanations":
        payload["infeasibility_explanations"] = ["forged explanation"]
    else:
        payload["scenario_set"] = None

    with pytest.raises(ValidationError, match=message):
        BackendResult(**payload)


def _shared_parcel_problem(*, planning_area_ha: float) -> GroundedPlanningProblem:
    candidates = []
    domains = []
    targets = []
    for index, target_id in enumerate(("target-a", "target-b")):
        candidate_id = f"parcel-{index}"
        x = index * 2
        candidates.append(CandidateGeometry(
            candidate_id=candidate_id,
            target_id=target_id,
            kind="polygon",
            role="execution_geometry",
            materialization_role="land_use_assignment",
            wkt=f"POLYGON (({x} 0, {x + 1} 0, {x + 1} 1, {x} 1, {x} 0))",
            crs="EPSG:3857",
            source_area_ha=1.0,
            planning_area_ha=planning_area_ha,
            availability_status="fully_available",
            eligible_area_ha=1.0,
            excluded_area_ha=0.0,
            source_bsms=["P-SHARED"],
            source_ref=f"parcel:P-SHARED:{index}",
            evidence_refs=[f"evidence:parcel:{index}"],
            hard_constraint_status="passed",
            suitability_components={"suitability": 0.8 - index * 0.1},
        ))
        domains.append(GroundedCandidateDomain(
            target_id=target_id,
            candidate_ids=[candidate_id],
            candidate_geometry_refs=[candidate_id],
            selection_mode="choose_one",
            status="resolved",
        ))
        targets.append(GroundedTargetDomain(
            target_id=target_id,
            target_kind="site_area",
            expected_output_kind="polygon",
            candidate_site_refs=[candidate_id],
            geometry_roles=["execution_geometry"],
            status="resolved",
        ))
    return GroundedPlanningProblem(
        shared_resource_refs=["parcel-pool:test"],
        target_domains=targets,
        candidate_domains=domains,
        candidate_geometries=candidates,
    )


def test_parcel_assignment_backend_enforces_shared_bsm_capacity():
    problem = _shared_parcel_problem(planning_area_ha=0.6)
    view = build_solver_problem_view(problem)

    assert view.problem_kind == "parcel_assignment"
    assert view.input_complete is True
    assert any(ref.startswith("parcel-resource:P-SHARED") for ref in view.resource_refs)

    result = optimize_scenarios(
        problem,
        set_id="parcel-capacity-conflict",
        evaluator_context=RelationEvaluationContext(scenario_id="parcel-capacity-conflict"),
    )

    assert result.solver_certificate.backend_id == "parcel_assignment_bounded"
    assert result.solver_certificate.status == "infeasible"
    assert result.feasible_scenario_ids == []
    assert any("PARCEL_CAPACITY_EXCEEDED:P-SHARED" in item for item in result.infeasibility_explanations)


def test_parcel_assignment_backend_returns_both_non_overlapping_members_when_capacity_allows():
    problem = _shared_parcel_problem(planning_area_ha=0.4)
    result = optimize_scenarios(
        problem,
        set_id="parcel-capacity-feasible",
        evaluator_context=RelationEvaluationContext(scenario_id="parcel-capacity-feasible"),
    )

    assert result.solver_certificate.backend_id == "parcel_assignment_bounded"
    assert result.solver_certificate.status == "feasible"
    assert len(result.feasible_scenario_ids) == 1
    selected = {
        item.target_id: item.candidate_ids
        for item in result.recommended.target_selections
    }
    assert selected == {"target-a": ["parcel-0"], "target-b": ["parcel-1"]}


def test_parcel_assignment_unknown_availability_fails_closed_even_with_area():
    problem = _shared_parcel_problem(planning_area_ha=0.4)
    for candidate in problem.candidate_geometries:
        candidate.availability_status = "unknown"
    # Re-run the model's derived pool after the intentional status mutation.
    problem.parcel_resource_pool = None
    problem = GroundedPlanningProblem.model_validate(problem.model_dump(mode="python"))

    view = build_solver_problem_view(problem)
    assert view.problem_kind == "parcel_assignment"
    assert view.input_complete is False
    assert "missing:parcel_resource:P-SHARED:availability_status" in view.missing_input_refs

    result = optimize_scenarios(
        problem,
        set_id="parcel-unknown-availability",
        evaluator_context=RelationEvaluationContext(scenario_id="parcel-unknown-availability"),
    )
    assert result.solver_certificate.status == "unknown"
    assert result.feasible_scenario_ids == []


def test_mixed_candidate_availability_does_not_collapse_to_whole_parcel_status():
    problem = _shared_parcel_problem(planning_area_ha=0.4)
    problem.candidate_geometries[0].availability_status = "fully_available"
    problem.candidate_geometries[1].availability_status = "partially_available"
    problem.candidate_geometries[1].eligible_area_ha = 0.4
    problem.candidate_geometries[1].excluded_area_ha = 0.6
    problem.parcel_resource_pool = None
    problem = GroundedPlanningProblem.model_validate(problem.model_dump(mode="python"))

    resource = problem.parcel_resource_pool.resources[0]
    assert resource.availability_status == "unknown"
    result = optimize_scenarios(
        problem,
        set_id="parcel-mixed-availability",
        evaluator_context=RelationEvaluationContext(scenario_id="parcel-mixed-availability"),
    )
    assert result.solver_certificate.status == "unknown"
    assert result.feasible_scenario_ids == []


def test_shared_parcel_partition_makes_identical_target_extents_disjoint():
    problem = _shared_parcel_problem(planning_area_ha=0.2)
    first, second = problem.candidate_geometries
    second.wkt = first.wkt
    catalog = {item.candidate_id: item for item in problem.candidate_geometries}
    partitioned = _partition_shared_parcel_candidates(
        catalog,
        set(catalog),
    )

    from shapely import wkt

    left = wkt.loads(partitioned[first.candidate_id].wkt)
    right = wkt.loads(partitioned[second.candidate_id].wkt)
    assert left.intersection(right).area <= 1e-12
    assert partitioned[first.candidate_id].subgeometry_operation == "shared_parcel_capacity_partition"
    assert partitioned[second.candidate_id].subgeometry_operation == "shared_parcel_capacity_partition"


def test_shared_parcel_partition_uses_eligible_parent_not_sized_footprint():
    parent = "POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0))"
    candidates = []
    for index, target_id in enumerate(("target-a", "target-b")):
        candidates.append(CandidateGeometry(
            candidate_id=f"eligible-parent-{index}",
            target_id=target_id,
            kind="polygon",
            role="execution_geometry",
            materialization_role="site_footprint",
            # Both members came back with the same target-sized footprint.
            wkt="POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))",
            eligible_geometry_wkt=parent,
            crs="EPSG:3857",
            source_area_ha=1.0,
            planning_area_ha=0.1,
            availability_status="partially_available",
            eligible_area_ha=0.5,
            excluded_area_ha=0.5,
            source_bsms=["P-ELIGIBLE"],
            hard_constraint_status="passed",
        ))
    catalog = {item.candidate_id: item for item in candidates}

    partitioned = _partition_shared_parcel_candidates(catalog, set(catalog))
    from shapely import wkt

    left = wkt.loads(partitioned[candidates[0].candidate_id].wkt)
    right = wkt.loads(partitioned[candidates[1].candidate_id].wkt)
    assert left.intersection(right).area <= 1e-12
    # 0.1 / 0.5 of the eligible parent is allocated to each target; the
    # result must not be 0.1 / 1.0 of an already-sized footprint.
    assert abs(float(left.area + right.area) - 40.0) <= 1e-6
    assert "partitioned_from_eligible_parent_extent" in (
        partitioned[candidates[0].candidate_id].subgeometry_diagnostics
    )


def test_resource_pool_ignores_coarse_unknown_when_exact_bsm_member_is_proven():
    exact = CandidateGeometry(
        candidate_id="exact-bsm-member",
        target_id="target-a",
        kind="polygon",
        role="execution_geometry",
        materialization_role="site_footprint",
        spatial_domain_kind="parcel_extent",
        subgeometry_operation="obb_subdivide",
        wkt="POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))",
        source_bsms=["P-COARSE-MIXED"],
        source_area_ha=1.0,
        planning_area_ha=0.2,
        availability_status="fully_available",
        eligible_area_ha=1.0,
        hard_constraint_status="passed",
    )
    coarse = exact.model_copy(update={
        "candidate_id": "coarse-bsm-member",
        "role": "parcel_candidate",
        "subgeometry_operation": "bundle_extent",
        "wkt": "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))",
        "planning_area_ha": 1.0,
        "availability_status": "unknown",
        "eligible_area_ha": None,
    })

    pool = derive_parcel_resource_pool([exact, coarse])

    assert pool is not None
    resource = pool.resources[0]
    assert resource.bsm == "P-COARSE-MIXED"
    assert resource.availability_status == "fully_available"
    assert resource.eligible_area_ha == 1.0
