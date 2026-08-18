from app.contracts.domain.l3_contracts import PlanningIntervention
from app.contracts.evidence.identity_contracts import (
    EvidenceObservation,
    GroundedEntityBinding,
)
from app.contracts.domain.planning_semantics import FacilityPlanningParameters
from app.domain.program.assembler import assemble_planning_program
from app.domain.program.target_projection.aggregate import project_program


def test_existing_feature_binding_becomes_kg_revalidated_exact_reference():
    intervention = PlanningIntervention(
        intervention_id="facility-existing-1",
        name="公交站维护",
        category="facility",
        execution_mode="spatial",
        expected_output_kind="point",
        intervention_action="preserve",
        spatial_requirements={"location": "现状公交站"},
        facility_parameters=FacilityPlanningParameters(
            facility_type="公交站",
            action="preserve",
        ),
    )
    observation = EvidenceObservation(
        observation_id="obs-bus-stop",
        mention="公交站",
        normalized_name="公交站",
        observed_type="facility",
    )
    binding = GroundedEntityBinding(
        binding_id="binding-bus-stop",
        mention_ref=observation.observation_id,
        canonical_entity_ref="poi:公交站",
        status="resolved",
        geometry_granularity="exact_feature",
        geometry_ref="POINT(1 2)",
    )
    program = assemble_planning_program([intervention], [], claims=[])
    _, specs, gate = project_program(
        program,
        observations=[observation],
        bindings=[binding],
    )

    assert gate.passed
    assert specs[0].type == "directional"
    assert specs[0].reference.filter == {
        "rdf_type": "Facility",
        "label_contains": "公交站",
    }


def test_existing_binding_without_audited_geometry_stays_coarse():
    intervention = PlanningIntervention(
        intervention_id="facility-existing-2",
        name="公交站维护",
        category="facility",
        execution_mode="spatial",
        expected_output_kind="point",
        intervention_action="preserve",
        spatial_requirements={"location": "现状公交站"},
        facility_parameters=FacilityPlanningParameters(
            facility_type="公交站",
            action="preserve",
        ),
    )
    observation = EvidenceObservation(
        observation_id="obs-bus-stop-2",
        mention="公交站",
        normalized_name="公交站",
        observed_type="facility",
    )
    binding = GroundedEntityBinding(
        binding_id="binding-bus-stop-2",
        mention_ref=observation.observation_id,
        canonical_entity_ref="poi:公交站",
        status="resolved",
        geometry_granularity="exact_feature",
    )
    program = assemble_planning_program([intervention], [], claims=[])
    _, specs, gate = project_program(
        program,
        observations=[observation],
        bindings=[binding],
    )

    assert gate.passed
    assert specs[0].type != "directional"
