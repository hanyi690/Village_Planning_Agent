from __future__ import annotations

from app.contracts.domain.l3_contracts import PlanningIntervention, PlanningProgram
from app.contracts.program import PlanningClaim
from app.contracts.domain.planning_semantics import FacilityPlanningParameters, LinearAssetPlanningParameters
from app.contracts.evidence.identity_contracts import EvidenceObservation, GroundedEntityBinding
from app.contracts.planning.relation_parameters import ConnectParameters, ServiceParameters
from app.domain.program.target_projection.compile import compile_program_deterministic
from app.domain.program.target_projection.intent_graph_compiler import compile_intent_graph_v2


def _facility(target_id: str = "clinic-1") -> PlanningIntervention:
    return PlanningIntervention(
        intervention_id=target_id,
        target_id=target_id,
        name="卫生室",
        planning_role="spatial_intervention",
        project_package_ref=f"pkg-{target_id}",
        admission_reason="typed_spatial_claim_ready",
        category="facility",
        asset_kind="facility",
        execution_mode="spatial",
        expected_output_kind="point",
        claim_refs=[f"claim-{target_id}"],
        evidence_refs=[f"fact-{target_id}"],
        facility_parameters=FacilityPlanningParameters(facility_type="clinic"),
    )


def _road(target_id: str = "road-1") -> PlanningIntervention:
    return PlanningIntervention(
        intervention_id=target_id,
        target_id=target_id,
        name="连接道路",
        planning_role="spatial_intervention",
        project_package_ref=f"pkg-{target_id}",
        admission_reason="typed_spatial_claim_ready",
        category="road",
        asset_kind="road",
        execution_mode="spatial",
        expected_output_kind="line",
        claim_refs=[f"claim-{target_id}"],
        evidence_refs=[f"fact-{target_id}"],
        road_parameters={"action": "new", "length_m": 800, "pavement_width_m": 5},
    )


def _program(*interventions: PlanningIntervention) -> PlanningProgram:
    claims = []
    for intervention in interventions:
        claims.append(
            PlanningClaim(
                claim_id=intervention.claim_refs[0],
                statement=intervention.name,
                suggested_category=intervention.category,
                suggested_output_kind=intervention.expected_output_kind,
                asset_kind=intervention.asset_kind,
                planning_role="spatial_intervention",
                project_package_ref=intervention.project_package_ref,
                location_hints=["社前村"],
                evidence_refs=list(intervention.evidence_refs),
                facility_parameters=intervention.facility_parameters,
                road_parameters=intervention.road_parameters,
                linear_parameters=intervention.linear_parameters,
            )
        )
    return PlanningProgram(interventions=list(interventions), claims=claims)


def test_compile_parameterized_serve_and_connect_relations() -> None:
    clinic = _facility()
    clinic.spatial_requirements = {
        "relations": [{
            "relation_id": "serve-settlement",
            "relation_template": "serve",
            "object_ref": "settlement:社前村",
            "object_ref_kind": "entity",
            "criticality": "hard",
            "parameters": ServiceParameters(
                demand_ref="demand:sheqian",
                facility_type="clinic",
                max_travel_time_min=20,
                min_coverage_ratio=0.8,
                capacity=100,
                capacity_unit="person/day",
                network_ref="network:road:1",
            ).model_dump(mode="json"),
        }]
    }
    road = _road()
    road.spatial_requirements = {
        "relations": [{
            "relation_id": "connect-clinic",
            "relation_template": "connect_network",
            "object_ref": "clinic-1",
            "object_ref_kind": "target",
            "criticality": "hard",
            "parameters": ConnectParameters(
                network_kind="road", endpoint_tolerance_m=15, network_ref="network:road:1"
            ).model_dump(mode="json"),
        }]
    }

    graph = compile_intent_graph_v2(
        _program(clinic, road),
        observations=[EvidenceObservation(
            observation_id="obs:settlement", mention="社前村", normalized_name="社前村",
            evidence_refs=["e:report:1"],
        )],
        bindings=[GroundedEntityBinding(
            binding_id="binding:settlement", mention_ref="obs:settlement",
            canonical_entity_ref="settlement:社前村", status="resolved",
            evidence_refs=["e:binding:1"],
        )],
    )

    serve = next(item for item in graph.relations if item.relation_id == "serve-settlement")
    connect = next(item for item in graph.relations if item.relation_id == "connect-clinic")
    assert serve.parameter_status == "provided"
    assert serve.parameters is not None and serve.parameters.parameter_type == "service"
    assert serve.source_binding_refs == ["binding:settlement"]
    assert "e:binding:1" in serve.evidence_refs
    assert connect.parameter_status == "provided"
    assert not any("relation_parameters_missing" in item for item in graph.diagnostics)
    assert graph.solver_kind == "coverage"
    assert graph.solver_kind_reasons == ["typed_service_coverage_relation"]


def test_missing_parameters_are_retained_as_deferred_diagnostic() -> None:
    clinic = _facility()
    clinic.spatial_requirements = {
        "relations": [{
            "relation_id": "serve-without-threshold",
            "relation_template": "serve",
            "object_ref": "settlement:社前村",
            "object_ref_kind": "entity",
            "criticality": "hard",
        }]
    }
    graph = compile_intent_graph_v2(PlanningProgram(interventions=[clinic]))
    relation = graph.relations[0]
    assert relation.parameter_status == "missing"
    assert relation.parameters is None
    assert any("relation_parameters_missing:serve-without-threshold" in item for item in graph.diagnostics)


def test_empty_parameter_object_is_the_same_pending_boundary_as_omission() -> None:
    clinic = _facility()
    clinic.spatial_requirements = {
        "relations": [{
            "relation_id": "serve-empty-parameters",
            "relation_template": "serve",
            "object_ref": "settlement:社前村",
            "object_ref_kind": "entity",
            "criticality": "hard",
            "parameters": {},
        }]
    }

    graph = compile_intent_graph_v2(PlanningProgram(interventions=[clinic]))

    relation = graph.relations[0]
    assert relation.parameter_status == "missing"
    assert relation.parameters is None
    assert any("relation_parameters_missing:serve-empty-parameters" in item for item in graph.diagnostics)


def test_dependency_keeps_explicit_source_and_is_not_inferred_from_list_order() -> None:
    clinic = _facility()
    road = _road()
    graph = compile_intent_graph_v2(
        PlanningProgram(
            interventions=[clinic, road],
            dependencies=[{
                "from_intervention_id": "road-1",
                "to_intervention_id": "clinic-1",
                "dependency_type": "utility_before_facility",
            }],
        )
    )
    relation = graph.relations[0]
    assert relation.relation_template == "precedes"
    assert relation.source == "utility_before_facility"
    assert relation.parameter_status == "missing"
    assert any("relation_parameters_missing" in item for item in graph.diagnostics)


def test_compile_result_surfaces_graph_diagnostics() -> None:
    clinic = _facility()
    clinic.spatial_requirements = {
        "relations": [{
            "relation_template": "serve",
            "object_ref": "settlement:社前村",
            "criticality": "hard",
        }]
    }
    result, _, diagnostics = compile_program_deterministic(_program(clinic))
    assert result.intent_graph is not None
    assert any(item.code == "relation_parameters_missing" for item in diagnostics)
