from app.domain.program.claim_draft import (
    PlanningClaimDraft,
    PlanningClaimDraftSet,
    claim_draft_semantic_errors,
    normalize_claim_draft_set,
)
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


def test_draft_contract_reports_linear_asset_category_mismatch() -> None:
    errors = claim_draft_semantic_errors(
        PlanningClaimDraftSet(claims=[_invalid_sewer_claim()])
    )

    assert errors
    assert any("lup-lin-001" in item for item in errors)
    assert any("suggested_category=road" in item for item in errors)
    assert any("linear_parameters" in item for item in errors)


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


def test_l3_prompt_contains_cross_field_decision_table_and_negative_example() -> None:
    prompt = get_dimension_prompt("land_use_planning")

    assert "asset_kind=sewer" in prompt
    assert "suggested_category=road" in prompt
    assert "suggested_output_kind=line" in prompt
    assert "以下输出非法" in prompt
    assert "action + line + sewer" in prompt
