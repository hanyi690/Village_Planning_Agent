"""Checkpoint replay must restore the persisted semantic context inputs."""

from pathlib import Path

from app.infrastructure.kg.memory import EntityAnnotation, SemanticMemoryStore, save_memory_state
from app.infrastructure.context import planning_context_factory as planning_context


def test_latest_session_semantic_memory_is_restored(monkeypatch, tmp_path: Path):
    import app.core.settings as settings

    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    session_id = "checkpoint-context-test"

    older = SemanticMemoryStore()
    older.add_entity_annotation(EntityAnnotation("urn:old", "Village", "old"))
    save_memory_state(session_id, 1, older)

    latest = SemanticMemoryStore()
    latest.add_entity_annotation(EntityAnnotation("urn:latest", "Village", "latest"))
    save_memory_state(session_id, 2, latest)

    restored = planning_context._load_session_semantic_memory(session_id)

    assert "urn:latest" in restored.entity_annotations
    assert "urn:old" not in restored.entity_annotations


def test_persisted_gis_village_binding_restores_bsms():
    from app.infrastructure.kg.gazetteer.gazetteer import _annotation_entries_from_memory

    memory = SemanticMemoryStore()
    memory.add_entity_annotation(EntityAnnotation(
        "pln:gis_village_binding:营仔",
        "GISVillageBinding",
        "营仔村（GIS 属性名绑定）",
        intent_refs=["441426211000049192"],
    ))

    entries = _annotation_entries_from_memory(memory, bundle=None)

    assert entries[0].name == "营仔村"
    assert entries[0].bsms == ["441426211000049192"]


def test_persisted_facility_anchor_restores_exact_target_binding():
    from app.infrastructure.kg.gazetteer.gazetteer import _annotation_entries_from_memory

    memory = SemanticMemoryStore()
    memory.add_entity_annotation(EntityAnnotation(
        "pln:anchor_facility:活动场地:营仔",
        "LocationAnchor",
        "活动场地@营仔（L1 instruction；位于营仔）",
        intent_refs=["441426211000049192"],
    ))

    entries = _annotation_entries_from_memory(memory, bundle=None)

    assert entries[0].name == "活动场地@营仔"
    assert entries[0].bsms == ["441426211000049192"]
