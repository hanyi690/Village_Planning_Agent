"""H 子任务：SemanticMemoryStore 轮次持久化单测。"""
from pathlib import Path

import pytest

from app.modules.kg.memory import (
    EntityAnnotation,
    SemanticMemoryStore,
    diff_round,
    load_memory_state,
    save_memory_state,
)


@pytest.fixture
def tmp_memory_dir(monkeypatch, tmp_path: Path):
    import app.modules.kg.memory as mem
    monkeypatch.setattr(mem, "get_memory_dir", lambda: tmp_path)
    return tmp_path


def test_entity_annotation_round_defaults():
    ann = EntityAnnotation(entity_uri="pln:parcel_1", entity_type="Parcel")
    assert ann.round_added == 1
    assert ann.valid_from_round == 1
    assert ann.valid_until_round is None
    assert ann.confidence == 1.0


def test_from_dict_round_trip_all_fields():
    data = {
        "entity_annotations": {
            "pln:parcel_1": {
                "entity_type": "Parcel",
                "description": "田坑自然村耕地",
                "source_text_refs": ["land_use"],
                "intent_refs": [],
                "round_added": 2,
                "valid_from_round": 2,
                "valid_until_round": None,
                "confidence": 0.9,
            }
        },
        "relation_annotations": {},
    }
    store = SemanticMemoryStore.from_dict(data)
    ann = store.entity_annotations["pln:parcel_1"]
    assert ann.round_added == 2
    assert ann.valid_from_round == 2
    assert ann.confidence == 0.9


def test_from_dict_backward_compat_old_format():
    # 旧 to_dict 输出没有 round/confidence 字段 → 默认值补齐
    old = {
        "entity_annotations": {
            "pln:parcel_1": {
                "entity_type": "Parcel",
                "description": "旧注解",
                "source_text_refs": [],
                "intent_refs": [],
            }
        },
        "relation_annotations": {},
    }
    store = SemanticMemoryStore.from_dict(old)
    ann = store.entity_annotations["pln:parcel_1"]
    assert ann.round_added == 1
    assert ann.valid_until_round is None
    assert ann.confidence == 1.0


def test_supersede_marks_old_valid_until():
    store = SemanticMemoryStore()
    old = EntityAnnotation(entity_uri="pln:parcel_1", entity_type="Parcel", description="旧", confidence=0.5, round_added=1)
    store.add_entity_annotation(old)
    new = EntityAnnotation(entity_uri="pln:parcel_1", entity_type="Parcel", description="新", confidence=0.9, round_added=2)
    assert store.supersede(new) is True
    ann = store.entity_annotations["pln:parcel_1"]
    assert ann.description == "新"
    assert old.valid_until_round == 2


def test_supersede_rejects_lower_or_equal_confidence():
    store = SemanticMemoryStore()
    old = EntityAnnotation(entity_uri="pln:parcel_1", entity_type="Parcel", description="旧", confidence=0.9, round_added=1)
    store.add_entity_annotation(old)
    new = EntityAnnotation(entity_uri="pln:parcel_1", entity_type="Parcel", description="低置信", confidence=0.5, round_added=2)
    assert store.supersede(new) is False
    assert store.entity_annotations["pln:parcel_1"].description == "旧"


def test_diff_round_counts():
    prev = SemanticMemoryStore()
    prev.add_entity_annotation(EntityAnnotation(entity_uri="pln:a", entity_type="Parcel", round_added=1))
    cur = SemanticMemoryStore()
    cur.add_entity_annotation(EntityAnnotation(entity_uri="pln:a", entity_type="Parcel", round_added=2, confidence=0.9))
    cur.add_entity_annotation(EntityAnnotation(entity_uri="pln:b", entity_type="Parcel", round_added=2))
    diff = diff_round(prev, cur)
    assert "pln:b" in diff["added"]
    assert isinstance(diff["unchanged"], int)


def test_save_load_round_trip(tmp_memory_dir):
    store = SemanticMemoryStore()
    store.add_entity_annotation(
        EntityAnnotation(entity_uri="pln:parcel_1", entity_type="Parcel", description="田坑", round_added=3, confidence=0.8)
    )
    path = save_memory_state("sess_x", 3, store)
    assert path.name == "sess_x_round_3.json"
    assert path.exists()

    loaded = load_memory_state("sess_x", 3)
    ann = loaded.entity_annotations["pln:parcel_1"]
    assert ann.description == "田坑"
    assert ann.round_added == 3
    assert ann.confidence == 0.8


def test_load_missing_round_returns_empty_store(tmp_memory_dir):
    store = load_memory_state("sess_missing", 9)
    assert isinstance(store, SemanticMemoryStore)
    assert store.entity_annotations == {}
