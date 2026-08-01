"""P5 单测：L3 报告 → session 功能区词汇表提取器。"""

import asyncio

from app.agent.gis.vocab_extractor import (
    extract_vocabulary_deterministic,
    extract_vocabulary_from_reports,
    register_session_vocabulary,
)
from app.modules.schema.encodings.dicts.vocabularies.loader import get_vocabulary

ZONE_REPORT = """【功能分区表】
| 分区名称 | 面积(公顷) | 占比(%) | 管控要求 |
| :--- | :--- | :--- | :--- |
| 生态保护区 | 362.02 | 15.39 | 严格保护 |
| 农田保护区 | 78.83 | 3.35 | 严禁占用 |
"""


def test_deterministic_extraction_4_zones_with_hex_colors():
    vocab = extract_vocabulary_deterministic({"spatial_structure": ZONE_REPORT})
    assert len(vocab.categories) == 2
    names = {c.name_zh: c for c in vocab.categories}
    assert "生态保护区" in names
    assert names["生态保护区"].color.startswith("#")
    assert len(names["生态保护区"].color) == 7
    # 语义推断：生态→现状林地 codes（1340 商品林/1350 生态林）
    assert any("1340" in r.value for r in names["生态保护区"].typing_rules)


class _FakeLLM:
    def __init__(self, content: str):
        self._content = content

    async def ainvoke(self, prompt: str):
        class _Resp:
            content = ""
        r = _Resp()
        r.content = self._content
        return r


def test_llm_enhances_table_categories_with_free_color():
    """v5 表格闭集：LLM 只增强表格里已有的类别（自由色生效），编造类别被丢弃。"""
    report = """【土地用途分区表】
| 分区名称 | 面积(公顷) | 占比(%) | 管控要求 |
| :--- | :--- | :--- | :--- |
| 生态保护区 | 362.02 | 15.39 | 严格保护 |
"""
    vocab = asyncio.run(
        extract_vocabulary_from_reports(
            {"land_use_planning": report},
            llm=_FakeLLM(
                '{"categories": [{"name_zh": "生态保护区", "color": "#ff8800", "dlbm_hints": ["1340"], "is_protection": true, "evidence": "表"}]}'
            ),
        )
    )
    assert len(vocab.categories) == 1
    cat = vocab.categories[0]
    assert cat.name_zh == "生态保护区"
    assert cat.color == "#ff8800"  # LLM 自由色生效
    assert cat.is_protection is True


def test_llm_fabricated_category_dropped():
    """v5：LLM 编造的类别（不在报告表格）必须被丢弃。"""
    report = """【土地用途分区表】
| 分区名称 | 占比(%) |
| :--- | :--- |
| 农田保护区 | 3.35 |
"""
    vocab = asyncio.run(
        extract_vocabulary_from_reports(
            {"land_use_planning": report},
            llm=_FakeLLM(
                '{"categories": [{"name_zh": "防灾减灾区", "color": "#b84e4e", "dlbm_hints": [], "evidence": "编造"}]}'
            ),
        )
    )
    names = [c.name_zh for c in vocab.categories]
    assert "防灾减灾区" not in names
    assert "农田保护区" in names  # 表格闭集兜底


def test_llm_failure_falls_back_to_deterministic():
    vocab = asyncio.run(
        extract_vocabulary_from_reports(
            {"spatial_structure": ZONE_REPORT},
            llm=_FakeLLM("not json at all"),
        )
    )
    assert len(vocab.categories) == 2


def test_register_session_vocabulary():
    vocab = extract_vocabulary_deterministic({"spatial_structure": ZONE_REPORT})
    name = register_session_vocabulary("sess_v1", vocab)
    assert name == "sess_v1_vocab"
    loaded = get_vocabulary(name)
    assert loaded.categories[0].name_zh == "生态保护区"
