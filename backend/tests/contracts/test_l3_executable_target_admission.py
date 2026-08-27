from app.contracts.domain.l3_contracts import L3ProgramFragment, PlanningIntervention, PlanningProgram
from app.contracts.domain.l3_contracts import PlanningProgram
from app.contracts.domain.planning_semantics import FacilityPlanningParameters
from app.contracts.program import PlanningClaim, PlanningRelationRequirement, PlanningSpatialRequirements
from app.domain.program.claim_draft import PlanningClaimDraft, PlanningClaimDraftSet, normalize_claim_draft_set
from app.domain.program.aggregate import merge_program_fragments
from app.domain.program.claim_adapter import classify_claims, interventions_from_claims
from app.evidence.retrieval.requirements import requirements_from_l3
from app.domain.program.target_projection.compile import compile_program_deterministic


def _claim(**overrides):
    values = {
        "claim_id": "c-1",
        "dimension_key": "public_service",
        "statement": "维护社前村文化设施",
        "suggested_category": "facility",
        "suggested_output_kind": "point",
        "asset_kind": "facility",
        "planning_role": "evidence_statement",
    }
    values.update(overrides)
    return PlanningClaim(**values)


def test_legacy_and_non_spatial_roles_remain_claims_without_targets():
    claims = [
        _claim(claim_id="evidence", planning_role="evidence_statement"),
        _claim(claim_id="indicator", planning_role="indicator"),
        _claim(claim_id="constraint", planning_role="constraint"),
        _claim(claim_id="objective", planning_role="objective"),
        _claim(claim_id="package", planning_role="project_package"),
        _claim(claim_id="action", planning_role="non_spatial_action"),
    ]
    issues = []
    assert interventions_from_claims(claims, dimension_key="public_service", issues=issues) == []
    assert {issue.claim_id for issue in issues} == {claim.claim_id for claim in claims}

    program = merge_program_fragments(
        [L3ProgramFragment(dimension_key="public_service", claims=claims)],
        run_id="run-1",
    )
    assert {claim.claim_id for claim in program.claims} == {claim.claim_id for claim in claims}
    assert program.interventions == []


def test_incomplete_spatial_claim_is_rejected_with_typed_issue():
    claim = _claim(
        planning_role="spatial_intervention",
        project_package_ref="pkg-facility",
        facility_parameters=None,
        location_hints=["社前村"],
        evidence_refs=["fact-1"],
    )
    issues = []
    assert interventions_from_claims([claim], issues=issues) == []
    assert issues[0].code == "claim_admission_incomplete"
    assert issues[0].claim_id == claim.claim_id
    assert issues[0].dimension_key == claim.dimension_key


def test_spatial_intent_missing_locator_and_evidence_is_pending_grounding():
    claim = _claim(
        planning_role="spatial_intervention",
        project_package_ref="pkg-facility",
        facility_parameters=FacilityPlanningParameters(
            facility_type="文化设施",
            action="new",
        ),
    )

    interventions, pending_claims, dispositions, issues = classify_claims([claim])

    assert interventions == []
    assert pending_claims == [claim]
    assert dispositions[0].status == "pending_grounding"
    assert dispositions[0].missing_requirements == [
        "locator_or_candidate_or_source_feature_reference",
        "evidence_or_source_lineage",
    ]
    assert issues[0].code == "claim_grounding_pending"
    assert issues[0].severity == "warning"
    assert "locator_or_candidate_or_source_feature_reference" in issues[0].detail

    program = merge_program_fragments(
        [L3ProgramFragment(dimension_key=claim.dimension_key, claims=[claim])],
        run_id="pending-claim",
    )
    assert program.claims == [claim]
    assert program.pending_grounding_claims == [claim]
    assert program.claim_dispositions[0].claim_id == claim.claim_id


def test_pending_spatial_claim_emits_exact_grounding_requirements():
    claim = _claim(
        planning_role="spatial_intervention",
        project_package_ref="pkg-facility",
        facility_parameters=FacilityPlanningParameters(
            facility_type="文化设施",
            action="new",
        ),
        location_hints=["社前村"],
        spatial_requirements=PlanningSpatialRequirements(
            grounding_requirements=[
                "place_binding",
                "candidate_geometry",
                "parcel_membership",
                "network_snapshot",
                "topology",
                "demand_points",
            ],
            relations=[
                PlanningRelationRequirement(
                    relation_template="connect_network",
                    relation_id="connect-1",
                    parameters={"network_ref": "network:roads"},
                ),
                PlanningRelationRequirement(
                    relation_template="part_of",
                    relation_id="topology-1",
                ),
            ],
        ),
    )
    _, pending, dispositions, _ = classify_claims([claim])
    program = PlanningProgram(
        artifact_id="l3-pending",
        claims=[claim],
        pending_grounding_claims=pending,
        claim_dispositions=dispositions,
    )

    requirements = requirements_from_l3(program)
    pending_requirements = [
        item for item in requirements if item.metadata.get("pending_grounding")
    ]

    assert pending_requirements
    assert all(
        item.kind in {"spatial", "metric", "source"}
        for item in pending_requirements
    )
    assert all(item.allowed_inference == "exact" for item in pending_requirements)
    assert all(item.metadata["claim_id"] == claim.claim_id for item in pending_requirements)
    assert all("evidence_or_source_lineage" in item.metadata["missing_requirements"] for item in pending_requirements)
    assert {item.evidence_role for item in pending_requirements} >= {
        "l3_claim",
        "l3_place_binding",
        "l3_candidate_geometry",
        "l3_parcel_membership",
        "l3_network_snapshot",
        "l3_topology",
        "l3_demand_points",
        "l3_relation_network",
        "l3_relation_topology",
        "l3_pending_source_lineage",
    }
    assert all(set(item.source_families) >= {"artifact", "report", "bundle", "kg"} for item in pending_requirements if item.evidence_role in {"l3_claim", "l3_pending_source_lineage"})
    place_requirements = [
        item
        for item in pending_requirements
        if item.evidence_role in {"l3_place_binding", "l3_candidate_geometry"}
    ]
    assert all(item.scope == (claim.claim_id, "社前村") for item in place_requirements)
    assert all(item.metadata["place_hints"] == ["社前村"] for item in place_requirements)
    assert all(item.metadata["relation_context"] == "pending_grounding_claim" for item in place_requirements)


def test_pending_claim_missing_package_has_auditable_source_requirement():
    claim = _claim(
        planning_role="spatial_intervention",
        facility_parameters=FacilityPlanningParameters(facility_type="文化设施", action="new"),
    )
    _, pending, dispositions, _ = classify_claims([claim])
    requirements = requirements_from_l3(
        PlanningProgram(
            claims=[claim],
            pending_grounding_claims=pending,
            claim_dispositions=dispositions,
        )
    )

    package_requirement = next(
        item for item in requirements if item.evidence_role == "l3_pending_package_identity"
    )
    assert package_requirement.metadata["pending_grounding"] is True
    assert package_requirement.metadata["missing_requirement"] == "project_package_ref"


def test_pending_claim_is_audited_on_projection_without_target_specs():
    claim = _claim(
        planning_role="spatial_intervention",
        project_package_ref="pkg-facility",
        facility_parameters=FacilityPlanningParameters(facility_type="文化设施", action="new"),
        location_hints=["社前村"],
        spatial_requirements=PlanningSpatialRequirements(
            grounding_requirements=["place_binding", "candidate_geometry"],
            relations=[
                PlanningRelationRequirement(
                    relation_template="connect_network",
                    relation_id="pending-connect",
                    parameters={"network_ref": "network:pending"},
                )
            ],
        ),
    )
    _, pending, dispositions, _ = classify_claims([claim])
    program = PlanningProgram(
        artifact_id="l3-pending-projection",
        claims=[claim],
        pending_grounding_claims=pending,
        claim_dispositions=dispositions,
    )

    result, specs, diagnostics = compile_program_deterministic(program)

    assert specs == []
    assert result.spatial_reference_specs == []
    assert result.pending_grounding_claims == [claim]
    assert result.claim_dispositions[0].model_dump() == dispositions[0].model_dump()
    assert not [item for item in diagnostics if item.code == "INTERVENTION_ADMISSION_RECOMPUTE_FAILED"]
    pending_requirements = [
        item for item in result.evidence_requirements if item.metadata.get("pending_grounding")
    ]
    assert pending_requirements
    assert all(item.producer_stage == "L3" for item in pending_requirements)
    assert all(item.metadata["missing_requirements"] == ["evidence_or_source_lineage"] for item in pending_requirements)
    assert {item.evidence_role for item in pending_requirements} >= {
        "l3_place_binding",
        "l3_candidate_geometry",
        "l3_relation_network",
    }
    assert len([
        item for item in result.evidence_requirements
        if item.evidence_role == "l3_place_binding"
    ]) == 1
    assert not [
        item for item in result.evidence_requirements
        if item.producer_stage == "TARGET_PROJECTION"
        and item.metadata.get("target_id") == claim.claim_id
    ]


def test_classifier_marks_missing_typed_parameter_pending():
    claim = _claim(
        planning_role="spatial_intervention",
        project_package_ref="pkg-facility",
        location_hints=["社前村"],
        evidence_refs=["fact-1"],
        facility_parameters=None,
    )

    interventions, pending_claims, dispositions, issues = classify_claims([claim])

    assert interventions == []
    assert pending_claims == [claim]
    assert dispositions[0].status == "pending_grounding"
    assert issues[0].code == "claim_grounding_pending"
    assert issues[0].severity == "warning"


def test_classifier_assigns_a_disposition_to_every_claim():
    ready = _claim(
        claim_id="ready",
        planning_role="spatial_intervention",
        project_package_ref="pkg-ready",
        location_hints=["社前村"],
        evidence_refs=["fact-ready"],
        facility_parameters=FacilityPlanningParameters(
            facility_type="文化设施",
            action="new",
        ),
    )
    pending = ready.model_copy(
        update={"claim_id": "pending", "location_hints": [], "evidence_refs": []}
    )
    invalid = ready.model_copy(
        update={"claim_id": "invalid", "facility_parameters": None}
    )
    deferred = _claim(claim_id="deferred")

    _, _, dispositions, _ = classify_claims([ready, pending, invalid, deferred])

    assert {item.claim_id for item in dispositions} == {
        "ready",
        "pending",
        "invalid",
        "deferred",
    }
    assert {item.status for item in dispositions} == {
        "admitted",
        "pending_grounding",
        "deferred",
    }


def test_ready_spatial_claim_carries_admission_lineage():
    claim = _claim(
        planning_role="spatial_intervention",
        project_package_ref="pkg-facility",
        location_hints=["社前村"],
        evidence_refs=["fact-1"],
        facility_parameters=FacilityPlanningParameters(
            facility_type="文化设施",
            action="preserve",
        ),
    )
    interventions = interventions_from_claims([claim])
    assert len(interventions) == 1
    intervention = interventions[0]
    assert intervention.planning_role == "spatial_intervention"
    assert intervention.project_package_ref == "pkg-facility"
    assert intervention.admission_reason == "typed_spatial_claim_ready"
    assert intervention.claim_refs == [claim.claim_id]
    assert intervention.evidence_refs == ["fact-1"]


def test_provider_role_and_package_survive_strict_normalization():
    draft = PlanningClaimDraft(
        claim_id="draft-1",
        statement="新增卫生站",
        planning_role="spatial_intervention",
        project_package_ref="pkg-health",
        suggested_category="facility",
        suggested_output_kind="point",
        asset_kind="facility",
        location_hints=["社前村"],
        evidence_refs=["fact-health"],
        facility_parameters={"facility_type": "卫生站", "action": "new"},
    )
    claim_set = normalize_claim_draft_set(PlanningClaimDraftSet(claims=[draft]))
    assert claim_set.claims[0].planning_role == "spatial_intervention"
    assert claim_set.claims[0].project_package_ref == "pkg-health"


def test_rejected_spatial_claim_has_document_not_spatial_requirement():
    claim = _claim(
        planning_role="spatial_intervention",
        project_package_ref="pkg-rejected",
        location_hints=["社前村"],
        evidence_refs=["fact-rejected"],
    )
    requirements = requirements_from_l3(PlanningProgram(claims=[claim]))
    assert len(requirements) == 1
    assert requirements[0].spatial_granularity == "document"
    assert requirements[0].allowed_inference == "text_only"


def test_forged_intervention_without_matching_claim_projects_nothing():
    intervention = PlanningIntervention(
        intervention_id="forged",
        name="forged",
        planning_role="spatial_intervention",
        project_package_ref="pkg-forged",
        admission_reason="typed_spatial_claim_ready",
        execution_mode="spatial",
        expected_output_kind="point",
        category="facility",
        asset_kind="facility",
        claim_refs=["missing-claim"],
        evidence_refs=["fact-forged"],
        facility_parameters=FacilityPlanningParameters(facility_type="clinic"),
    )
    result, _, diagnostics = compile_program_deterministic(
        PlanningProgram(interventions=[intervention])
    )
    assert result.typed_intent.facilities == []
    assert any(item.code == "INTERVENTION_ADMISSION_RECOMPUTE_FAILED" for item in diagnostics)


def test_forged_intervention_missing_typed_readiness_is_not_spatial_evidence():
    claim = _claim(
        claim_id="matching-claim",
        planning_role="spatial_intervention",
        project_package_ref="pkg-forged",
        location_hints=["社前村"],
        evidence_refs=["fact-matching"],
        facility_parameters=FacilityPlanningParameters(
            facility_type="clinic",
            action="new",
        ),
    )
    forged = PlanningIntervention(
        intervention_id="forged-missing-params",
        name="forged",
        planning_role="spatial_intervention",
        project_package_ref="pkg-forged",
        admission_reason="typed_spatial_claim_ready",
        execution_mode="spatial",
        expected_output_kind="point",
        category="facility",
        asset_kind="facility",
        claim_refs=["matching-claim"],
        evidence_refs=["fact-matching"],
        facility_parameters=None,
    )
    program = PlanningProgram(interventions=[forged], claims=[claim])
    result, _, diagnostics = compile_program_deterministic(program)
    requirements = requirements_from_l3(program)
    assert result.typed_intent.facilities == []
    assert any(item.code == "INTERVENTION_ADMISSION_RECOMPUTE_FAILED" for item in diagnostics)
    assert requirements[0].spatial_granularity == "document"
    assert requirements[0].allowed_inference == "text_only"
