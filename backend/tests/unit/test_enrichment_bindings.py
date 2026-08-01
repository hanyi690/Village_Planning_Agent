"""enrichment 单测：gazetteer 构建 + 村名绑定（Flash 判定）+ 实体注解真写入。"""

import asyncio
from pathlib import Path

from app.modules.kg.enrichment import extract_bindings
from app.modules.kg.enrichment.bindings import _extract_village_mentions, _is_village_name
from app.modules.kg.gazetteer import Gazetteer, GazetteerEntry, spatial_score


class _FakeKG:
    """最小 fake：g 属性存在但查询返回空（gazetteer 降级空）。"""

    def __init__(self):
        class _G:
            def subjects(self, *a, **k):
                return []

            def triples(self, *a, **k):
                return []

            def predicate_objects(self, *a, **k):
                return []

            def objects(self, *a, **k):
                return []

        self.g = _G()


def test_village_name_filter():
    assert _is_village_name("田坑村") is True
    assert _is_village_name("田坑自然村") is True
    assert _is_village_name("金田村") is False        # 村域
    assert _is_village_name("个自然村") is False      # 泛称
    assert _is_village_name("黄竹村和田坑村") is False  # 连写
    assert _is_village_name("八社村") is False         # 村外行政村


def test_gazetteer_fuzzy_and_score():
    g = Gazetteer([GazetteerEntry(name="居民点1", bsms=["B1"], centroid=[116.05, 24.83])])
    assert g.resolve("田坑村") is None  # 无村名条目 → None
    g2 = Gazetteer([GazetteerEntry(name="田坑自然村", bsms=["B1"], centroid=[116.05, 24.83])])
    assert g2.resolve("田坑村") is not None  # fuzzy
    assert spatial_score("山体林地", ["1340"]) > 0
    assert spatial_score("山体林地", ["1100"]) == 0


async def _fake_llm_confirm(prompt: str):
    class _R:
        content = '{"match": true}'
    return _R()


def test_extract_bindings_writes_semantic_annotations(monkeypatch, tmp_path: Path):
    import app.modules.kg.enrichment.bindings as enrich_mod
    import app.modules.kg.memory as mem_mod

    fake_store = mem_mod.SemanticMemoryStore()
    monkeypatch.setattr(mem_mod, "get_memory_dir", lambda: tmp_path)
    monkeypatch.setattr(enrich_mod, "_get_semantic_memory", lambda: fake_store)

    report = {
        "land_use_planning": (
            "【功能分区表】\n| 分区名称 | 面积(公顷) | 占比(%) | 管控要求 |\n"
            "| :--- | :--- | :--- | :--- |\n"
            "| 生态保护区 | 362.02 | 15.39 | 严格保护 |\n"
        )
    }
    stats = asyncio.run(
        extract_bindings("sess-e", wave=3, reports=report, llm=None, kg=_FakeKG(), bundle=None)
    )
    assert stats["semantic_entities"] >= 1
    uris = [a.entity_uri for a in fake_store.entity_annotations.values()]
    assert any("FunctionalZone" in u for u in uris)
    assert (tmp_path / "sess-e_round_3.json").exists()


def test_village_mentions_from_l3_text():
    text = "炉池自然村周边山体治理，田坑自然村耕地12.5公顷，全村统一规划。"
    mentions = _extract_village_mentions({"disaster_prevention": text})
    names = [m["name"] for m in mentions]
    assert "炉池自然村" in names
    assert "田坑自然村" in names
    assert "全村" not in names
