import pytest

from app.contracts.program import PlanningSpatialRequirements
from app.domain.program.claim_draft import (
    PlanningClaimDraft,
    PlanningClaimDraftSet,
    normalize_claim_draft_set,
)


def test_l3_claim_preserves_relation_and_grounding_requirements_for_target() -> None:
    draft = PlanningClaimDraft(
        claim_id="ROAD-CONNECT-1",
        dimension_key="traffic_planning",
        statement="提升现状村道并接入村委会。",
        planning_role="spatial_intervention",
        project_package_ref="pkg-road-1",
        suggested_category="road",
        suggested_output_kind="line",
        asset_kind="road",
        location_hints=["现状村道"],
        source_fact_refs=["l1:fact:road"],
        road_parameters={
            "action": "upgrade",
            "alignment_refs": ["现状村道"],
            "connects": ["村委会"],
        },
        spatial_requirements={
            "relations": [
                {
                    "relation_template": "connect_network",
                    "object_ref": "村委会",
                    "object_ref_kind": "place_hint",
                    "criticality": "hard",
                    "geometry_scope": "network",
                    "parameters": {"network_ref": "network:road:current"},
                }
            ],
            "network_refs": ["network:road:current"],
            "required_input_refs": ["network:road:current"],
            "grounding_requirements": ["network_snapshot", "place_binding"],
        },
    )
    claim_set = normalize_claim_draft_set(
        PlanningClaimDraftSet(claims=[draft]),
        dimension_key="traffic_planning",
    )

    claim = claim_set.claims[0]
    assert isinstance(claim.spatial_requirements, PlanningSpatialRequirements)
    assert claim.spatial_requirements.network_refs == ["network:road:current"]
    assert claim.spatial_requirements.relations[0].relation_template == "connect_network"
    assert claim.spatial_requirements.grounding_requirements == [
        "network_snapshot", "place_binding"
    ]


def test_l3_relation_requirement_rejects_geometry_payload() -> None:
    with pytest.raises(ValueError):
        PlanningSpatialRequirements(
            relations=[
                {
                    "relation_template": "near",
                    "object_ref": "湖边",
                    "parameters": {"geometry": "POLYGON (...)"},
                }
            ]
        )
