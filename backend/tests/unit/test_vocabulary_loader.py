from app.modules.schema.encodings.dicts.vocabularies.loader import (
    list_vocabularies,
    load_vocabulary,
)


def test_load_jintian_industry_returns_vocabulary():
    v = load_vocabulary("jintian_industry")
    assert v.name == "jintian_industry"
    assert len(v.categories) >= 1
    codes = [c.code for c in v.categories]
    assert "IND_LEAD" in codes


def test_list_vocabularies_includes_jintian():
    names = list_vocabularies()
    assert "jintian_industry" in names


def test_load_unknown_raises():
    import pytest

    with pytest.raises(FileNotFoundError):
        load_vocabulary("nonexistent_vocabulary")