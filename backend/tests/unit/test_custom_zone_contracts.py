from app.modules.schema.contracts.custom_zone_contracts import (
    Vocabulary,
    CustomZoneTarget,
    TypingRule,
)


def test_vocabulary_parses_minimal_yaml():
    v = Vocabulary(
        name="jintian_industry",
        categories=[
            {
                "code": "IND_LEAD",
                "name_zh": "主导产业区",
                "color": "#CC5500",
                "typing_rules": [{"kind": "dlbm_in", "value": ["2124", "2125"]}],
            }
        ],
    )
    assert v.name == "jintian_industry"
    assert v.categories[0].code == "IND_LEAD"
    assert isinstance(v.categories[0].typing_rules[0], TypingRule)


def test_custom_zone_target_default_decided_by_is_llm():
    t = CustomZoneTarget(
        vocabulary_name="jintian_industry",
        category_code="IND_LEAD",
        target_bsms=["X1"],
    )
    assert t.decided_by == "llm"
    assert t.confidence == 0.85


def test_vocabulary_accepts_empty_categories():
    v = Vocabulary(name="empty")
    assert v.categories == []
    assert v.incompatibilities == []