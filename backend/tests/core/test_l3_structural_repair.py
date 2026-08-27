"""L3 rough-claim projection keeps one malformed item from killing peers."""

from app.domain.program import worker
from app.domain.program.claim_draft import L3RoughClaimOutput


def test_rough_spatial_claim_is_projected_once_and_remains_non_executable():
    output = L3RoughClaimOutput.model_validate({
        "claims": [{
            "claim_family": "facility",
            "statement": "完善公共服务方向",
            "planning_role": "spatial_intervention",
            "source_fact_refs": [],
            "grounding_requirements": ["candidate_geometry"],
        }]
    })

    draft_set, claim_set = worker._normalize_claim_components(
        dimension_key="infrastructure_planning",
        output=output,
    )

    assert draft_set is not None
    assert claim_set.claims
    assert claim_set.claims[0].suggested_category == "facility"
    assert claim_set.claims[0].facility_parameters is None


def test_empty_rough_claim_set_is_a_valid_evidence_state():
    draft_set, claim_set = worker._normalize_claim_components(
        dimension_key="infrastructure_planning",
        output=L3RoughClaimOutput(),
    )

    assert draft_set.claims == []
    assert claim_set.claims == []
