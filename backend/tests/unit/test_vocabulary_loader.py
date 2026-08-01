"""词汇表 loader 单测 — v4 后词汇表来自 LLM/报告动态提取（内存注册），无固定 YAML。"""

from app.modules.schema.contracts.custom_zone_contracts import (
    Vocabulary,
    VocabularyCategory,
)
from app.modules.schema.encodings.dicts.vocabularies.loader import (
    get_vocabulary,
    list_vocabularies,
    register_vocabulary,
)


def _sample_vocab() -> Vocabulary:
    return Vocabulary(
        name="sess_v1",
        categories=[
            VocabularyCategory(code="FZ01", name_zh="生态保护区", color="#2d6a4f"),
        ],
    )


def test_register_and_get_memory_vocabulary():
    vocab = _sample_vocab()
    register_vocabulary("sess_v1", vocab)
    v = get_vocabulary("sess_v1")
    assert v.name == "sess_v1"
    assert len(v.categories) == 1
    assert v.categories[0].code == "FZ01"


def test_list_vocabularies_includes_registered():
    register_vocabulary("sess_v1", _sample_vocab())
    names = list_vocabularies()
    assert "sess_v1" in names


def test_get_unknown_raises():
    import pytest

    with pytest.raises(FileNotFoundError):
        get_vocabulary("nonexistent_vocabulary")
