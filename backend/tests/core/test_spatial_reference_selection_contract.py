from app.contracts.spatial.spatial_reference_contracts import (
    normalize_spatial_role,
    render_candidate_selection_contract,
)


def test_normalize_spatial_role_canonicalizes_live_provider_aliases() -> None:
    assert normalize_spatial_role("transportation_facility") == "facility"
    assert normalize_spatial_role("water_body") == "water"
    assert normalize_spatial_role("river") == "water"
    assert normalize_spatial_role("water-facility") == "water"
    assert normalize_spatial_role("road segment") == "road"
    assert normalize_spatial_role("geological_hazard_point") == "hazard"
    assert normalize_spatial_role("facility") == "facility"


def test_render_candidate_selection_contract_is_explicit_and_closed() -> None:
    prompt = render_candidate_selection_contract(["kg:a", "kg:b", "kg:a"])

    assert "只返回一个 JSON 对象" in prompt
    assert "候选 ID 集合是输入约束，不是输出字段" in prompt
    assert "输出 JSON 的键必须且只能是：status、selected_candidate_id、input_digest" in prompt
    assert "allowed_candidate_ids" in prompt
    assert "kg:a" in prompt and "kg:b" in prompt
    assert "status 为 abstain 或 ambiguous 时 selected_candidate_id 必须是空字符串" in prompt
    assert "input_digest 必须逐字复制" in prompt
    assert "不得创建、改写、截断或猜测候选 ID" in prompt
