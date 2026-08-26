import pytest

from app.domain.program.claim_draft import (
    PlanningClaimDraft,
    PlanningClaimDraftSet,
    normalize_claim_draft_set,
)
from app.contracts.domain.l3_contracts import PlanningIntervention, PlanningProgram
from app.contracts.domain.planning_semantics import FacilityPlanningParameters
from app.contracts.program import PlanningClaim
from app.domain.program.target_projection.compile import compile_program_deterministic
from app.infrastructure.llm.prompts.detailed import get_dimension_prompt


def _invalid_sewer_claim() -> PlanningClaimDraft:
    return PlanningClaimDraft(
        claim_id="lup-lin-001",
        dimension_key="land_use_planning",
        statement="推进污水管道建设，覆盖多个自然村。",
        planning_role="spatial_intervention",
        project_package_ref="pkg-lup-sewage-network",
        suggested_category="action",
        suggested_output_kind="line",
        asset_kind="sewer",
        intervention_action="new",
        linear_parameters={
            "action": "new",
            "length": {"value": 2000, "unit": "m"},
            "alignment_refs": ["village_road_network"],
        },
        location_hints=["黄竹村"],
    )


def test_strict_normalizer_reports_linear_asset_category_mismatch() -> None:
    claim_set = normalize_claim_draft_set(
        PlanningClaimDraftSet(claims=[_invalid_sewer_claim()]),
        dimension_key="land_use_planning",
    )

    assert claim_set.claims == []
    assert any("lup-lin-001" in item for item in claim_set.diagnostics)
    assert any("suggested_category=road" in item for item in claim_set.diagnostics)
    assert any("linear_parameters" in item for item in claim_set.diagnostics)


def test_normalization_does_not_lossily_turn_invalid_spatial_claim_into_action() -> None:
    claim_set = normalize_claim_draft_set(
        PlanningClaimDraftSet(claims=[_invalid_sewer_claim()]),
        dimension_key="land_use_planning",
    )

    assert claim_set.claims == []
    assert any("draft_contract_invalid" in item for item in claim_set.diagnostics)
    assert not any(
        claim.claim_id == "lup-lin-001" and claim.suggested_category == "action"
        for claim in claim_set.claims
    )


def test_l3_prompt_delegates_shape_and_relation_rules_to_compiler_contracts() -> None:
    prompt = get_dimension_prompt("land_use_planning")

    assert "结构化 schema 是字段、组件类型和参数块的唯一约束来源" in prompt
    assert "candidate_context" in prompt
    assert "以下输出非法" not in prompt
    assert "serve 的 subject 只能是 facility" not in prompt


def test_target_compile_marks_missing_relation_inputs_as_ground_deferrable() -> None:
    clinic = PlanningIntervention(
        intervention_id="clinic-1",
        target_id="clinic-1",
        name="卫生室",
        planning_role="spatial_intervention",
        project_package_ref="pkg-clinic-1",
        admission_reason="typed_spatial_claim_ready",
        category="facility",
        asset_kind="facility",
        execution_mode="spatial",
        expected_output_kind="point",
        facility_parameters=FacilityPlanningParameters(facility_type="clinic"),
        spatial_requirements={
            "relations": [{
                "relation_id": "serve-pending",
                "relation_template": "serve",
                "object_ref": "settlement:甲村",
                "object_ref_kind": "entity",
                "criticality": "hard",
                "parameters": {},
            }],
        },
    )
    claim = PlanningClaim(
        claim_id="claim-clinic-1",
        statement="建设卫生室",
        planning_role="spatial_intervention",
        project_package_ref="pkg-clinic-1",
        suggested_category="facility",
        suggested_output_kind="point",
        asset_kind="facility",
        facility_parameters=FacilityPlanningParameters(facility_type="clinic"),
        evidence_refs=["evidence:clinic-1"],
        location_hints=["甲村"],
    )
    clinic.claim_refs = [claim.claim_id]
    clinic.evidence_refs = list(claim.evidence_refs)

    result, _, diagnostics = compile_program_deterministic(
        PlanningProgram(interventions=[clinic], claims=[claim])
    )

    pending = [item for item in diagnostics if item.code == "relation_parameters_missing"]
    assert pending
    assert all(item.severity == "warning" for item in pending)
    assert all("source_claim_id=claim-clinic-1" in item.message for item in pending)
    assert all("relation_ordinal=" in item.message for item in pending)
    assert all("compiled_relation=" in item.message for item in pending)


def test_provider_blank_action_is_left_unresolved_for_schema_or_grounding() -> None:
    with pytest.raises(ValueError):
        PlanningClaimDraft(
            claim_id="linear-blank-001",
            statement="完善污水管线。",
            planning_role="spatial_intervention",
            project_package_ref="pkg-linear-blank-001",
            suggested_category="road",
            suggested_output_kind="line",
            asset_kind="sewer",
            intervention_action="",
            linear_parameters={"action": "", "alignment_refs": ["村道"]},
        )
