from __future__ import annotations

from app.modules.kg.adapters.gazetteer_adapter import KGGazetteerAdapter
from app.modules.schema.contracts.gazetteer_contracts import GazetteerEntryLike


def test_resolve_known_name(gazetteer):
    adapter = KGGazetteerAdapter(gazetteer)
    entry = adapter.resolve("run-1", "园寨")
    assert isinstance(entry, GazetteerEntryLike)
    assert entry.bsms == ["P001"]


def test_resolve_exact_and_unknown(gazetteer):
    adapter = KGGazetteerAdapter(gazetteer)
    assert adapter.resolve("run-1", "园寨", fuzzy=False) is not None
    assert adapter.resolve("run-1", "nonexistent_xyz", fuzzy=False) is None


def test_resolve_place_name(gazetteer):
    adapter = KGGazetteerAdapter(gazetteer)
    d = adapter.resolve_place_name("run-1", "园寨")
    assert isinstance(d, dict)
    assert "bsms" in d
    assert adapter.resolve_place_name("run-1", "nonexistent_xyz") is None


def test_get_cluster_by_name_non_cluster(gazetteer):
    adapter = KGGazetteerAdapter(gazetteer)
    assert adapter.get_cluster_by_name("run-1", "田垄") is None


def test_get_cluster_by_name_kg_cluster(gazetteer):
    adapter = KGGazetteerAdapter(gazetteer)
    d = adapter.get_cluster_by_name("run-1", "园寨")
    assert d is not None
    assert d["source"] == "kg_cluster"
