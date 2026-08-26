"""Bounded structural repair for L3 claim sets that fail schema validation."""

import pytest

from app.domain.program import worker
from app.domain.program.claim_draft import L3ClaimOutput


def _good_output():
    return L3ClaimOutput(claims=[
        {
            "component_kind": "facility",
            "claim_id": "C-1",
            "statement": "新建设施",
            "intervention_action": "new",
            "facility_parameters": {"facility_type": "卫生室", "action": "new"},
        }
    ])


def test_component_conversion_is_single_pass():
    draft_set, claim_set = worker._normalize_claim_components(
        dimension_key="infrastructure_planning",
        output=_good_output(),
    )

    assert draft_set is not None
    assert claim_set.claims
    assert claim_set.claims[0].suggested_category == "facility"


def test_missing_component_parameters_are_rejected_at_provider_boundary():
    with pytest.raises(ValueError):
        L3ClaimOutput(claims=[
            {
                "component_kind": "facility",
                "claim_id": "C-1",
                "statement": "新建设施",
            }
        ])
