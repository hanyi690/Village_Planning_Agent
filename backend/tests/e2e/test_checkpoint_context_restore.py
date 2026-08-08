"""Checkpoint replay must restore the persisted semantic context inputs."""

from pathlib import Path

from app.modules.kg.memory import EntityAnnotation, SemanticMemoryStore, save_memory_state
from app.services.context import planning_context


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

