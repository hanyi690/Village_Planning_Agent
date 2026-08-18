from __future__ import annotations

from app.contracts.domain.l3_contracts import PlanningIntervention, PlanningProgram
from app.contracts.domain.planning_semantics import FacilityPlanningParameters, RoadPlanningParameters
from app.domain.program.target_projection.intent_graph_compiler import compile_intent_graph_v2


def _facility() -> PlanningIntervention:
    return PlanningIntervention(
        intervention_id="clinic-1",
        target_id="clinic-1",
        name="卫生室",
        category="facility",
        asset_kind="facility",
        execution_mode="spatial",
        expected_output_kind="point",
        facility_parameters=FacilityPlanningParameters(facility_type="clinic"),
    )


def _road() -> PlanningIntervention:
    return PlanningIntervention(
        intervention_id="road-1",
        target_id="road-1",
        name="道路",
        category="road",
        asset_kind="road",
        execution_mode="spatial",
        expected_output_kind="line",
        road_parameters=RoadPlanningParameters(length_m=800, pavement_width_m=5),
    )


def test_connect_network_rejects_facility_subject_but_retains_relation() -> None:
    clinic = _facility()
    clinic.spatial_requirements = {
        "relations": [{
            "relation_id": "facility-connect-invalid",
            "relation_template": "connect_network",
            "subject_ref": "clinic-1",
            "object_ref": "road-1",
            "object_ref_kind": "target",
            "criticality": "hard",
            "parameters": {
                "network_kind": "road",
                "endpoint_tolerance_m": 10,
                "network_ref": "network:road:1",
            },
        }]
    }
    graph = compile_intent_graph_v2(PlanningProgram(interventions=[clinic, _road()]))
    assert len(graph.relations) == 1
    assert any("relation_subject_type_mismatch:facility-connect-invalid" in item for item in graph.diagnostics)


def test_serve_requires_facility_subject_and_rejects_road_target() -> None:
    road = _road()
    road.spatial_requirements = {
        "relations": [{
            "relation_id": "road-serve-invalid",
            "relation_template": "serve",
            "subject_ref": "road-1",
            "object_ref": "road-1",
            "object_ref_kind": "target",
            "criticality": "hard",
            "parameters": {
                "demand_ref": "demand:1",
                "facility_type": "clinic",
                "max_travel_time_min": 20,
                "min_coverage_ratio": 0.8,
                "capacity": 100,
                "capacity_unit": "person/day",
                "network_ref": "network:road:1",
            },
        }]
    }
    graph = compile_intent_graph_v2(PlanningProgram(interventions=[road]))
    assert any("relation_subject_type_mismatch:road-serve-invalid" in item for item in graph.diagnostics)
    assert any("relation_object_type_mismatch:road-serve-invalid" in item for item in graph.diagnostics)


def test_multiple_prose_village_names_are_preserved_as_explicit_alternatives() -> None:
    from app.data.ingestion.compiler.spec_mapper import map_intervention_to_spec

    intervention = _facility()
    intervention.problem_addressed = "服务甲村和乙村居民"
    spec = map_intervention_to_spec(intervention)
    assert spec is not None
    assert spec.type == "composed"
    assert spec.op == "or"
    assert [child.reference.filter["label_contains"] for child in spec.children] == ["甲村", "乙村"]
