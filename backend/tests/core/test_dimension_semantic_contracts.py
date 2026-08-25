from app.domain.assessment.dimension_contracts import (
    get_dimension_semantic_contract,
    render_dimension_semantic_contract,
)


def test_l1_dimensions_do_not_share_one_spatial_target_contract() -> None:
    traffic = get_dimension_semantic_contract("traffic", 1)
    wishes = get_dimension_semantic_contract("villager_wishes", 1)

    assert "spatial_relation" in traffic["l1_fact_types"]
    assert "demand" in wishes["l1_fact_types"]
    assert "network_snapshot" in traffic["l3_grounding_requirements"]
    assert "demand_points" in wishes["l3_grounding_requirements"]
    assert traffic["focus"] != wishes["focus"]


def test_l3_contract_names_grounding_inputs_and_keeps_report_scope() -> None:
    rendered = render_dimension_semantic_contract("public_service", 3)

    assert "facility" in rendered
    assert "demand_points" in rendered
    assert "GROUND" in rendered
