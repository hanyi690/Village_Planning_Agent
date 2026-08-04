def test_merge_sourced_constraints_tags_and_dedupes():
    from app.agent.execute.execute_constraints import merge_sourced_constraints

    kg = [{"id": "eco", "operator": ">=", "value": 330.0}, {"id": "eco", "operator": ">=", "value": 330.0}]
    parse = [{"type": "farmland_protection", "value": 85.2, "source_text": "农田保护区 85.20公顷"}]
    out = merge_sourced_constraints(kg, parse)
    assert len(out) == 2
    assert out[0]["source_type"] == "kg:layer2"
    assert out[1]["source_type"] == "parse"
