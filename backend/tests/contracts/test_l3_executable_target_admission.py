from app.contracts.domain.l3_contracts import L3ProgramFragment, PlanningIntervention, PlanningProgram
from app.contracts.domain.l3_contracts import PlanningProgram
from app.contracts.domain.planning_semantics import FacilityPlanningParameters
from app.contracts.program import PlanningClaim
from app.domain.program.claim_draft import PlanningClaimDraft, PlanningClaimDraftSet, normalize_claim_draft_set
from app.domain.program.aggregate import merge_program_fragments
from app.domain.program.claim_adapter import interventions_from_claims
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
