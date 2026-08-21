"""SemanticMemoryStore — 实体和关系的语义注解存储。

v4.6 新增：替代旧的 _semantic_store（Dict[str, Dict[str, str]]）。
注解不存储在 RDF 图中，通过此模块管理。

实体注解 (EntityAnnotation): 附着于空间实体的语义说明
关系注解 (RelationAnnotation): 附着于空间关系的语义说明
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class EntityAnnotation:
    """实体注解 — 附着于空间实体的语义说明"""
    entity_uri: str
    entity_type: str
    description: str = ""
    source_text_refs: List[str] = field(default_factory=list)
    intent_refs: List[str] = field(default_factory=list)
    round_added: int = 1
    valid_from_round: int = 1
    valid_until_round: Optional[int] = None
    confidence: float = 1.0


@dataclass
class RelationAnnotation:
    """关系注解 — 附着于空间关系的语义说明"""
    subject_uri: str
    predicate: str
    object_uri: str
    description: str = ""
    derived_from: str = ""  # "spatial_ops_computed" | "llm_inferred" | "rule_derived"
    quantitative_detail: Dict[str, Any] = field(default_factory=dict)


class SemanticMemoryStore:
    """语义注解存储 — 管理实体和关系的语义注解。

    与 RDF 图协同工作：
      - RDF 图存储结构化数据（三元组）
      - SemanticMemoryStore 存储语义注解（人类可读描述）
    """

    def __init__(self):
        self.entity_annotations: Dict[str, EntityAnnotation] = {}
        self.relation_annotations: Dict[str, RelationAnnotation] = {}

    # ── Entity annotations ──

    def add_entity_annotation(self, annotation: EntityAnnotation) -> None:
        self.entity_annotations[annotation.entity_uri] = annotation

    def get_entity_semantics(self, uri: str) -> Optional[Dict[str, Any]]:
        ann = self.entity_annotations.get(uri)
        if ann is None:
            return None
        return {
            "uri": ann.entity_uri,
            "type": ann.entity_type,
            "description": ann.description,
            "source_text_refs": ann.source_text_refs,
            "intent_refs": ann.intent_refs,
        }

    # ── Relation annotations ──

    def _relation_key(self, subject: str, predicate: str, object: str) -> str:
        return f"{subject}|{predicate}|{object}"

    def add_relation_annotation(self, annotation: RelationAnnotation) -> None:
        key = self._relation_key(annotation.subject_uri, annotation.predicate, annotation.object_uri)
        self.relation_annotations[key] = annotation

    def get_relation_semantics(self, subject: str, predicate: str, object: str) -> Optional[Dict[str, Any]]:
        key = self._relation_key(subject, predicate, object)
        ann = self.relation_annotations.get(key)
        if ann is None:
            return None
        return {
            "subject": ann.subject_uri,
            "predicate": ann.predicate,
            "object": ann.object_uri,
            "description": ann.description,
            "derived_from": ann.derived_from,
            "quantitative_detail": ann.quantitative_detail,
        }

    # ── Bulk ──

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_annotations": {
                uri: {
                    "entity_type": ann.entity_type,
                    "description": ann.description,
                    "source_text_refs": ann.source_text_refs,
                    "intent_refs": ann.intent_refs,
                    "round_added": ann.round_added,
                    "valid_from_round": ann.valid_from_round,
                    "valid_until_round": ann.valid_until_round,
                    "confidence": ann.confidence,
                }
                for uri, ann in self.entity_annotations.items()
            },
            "relation_annotations": {
                key: {
                    "subject": ann.subject_uri,
                    "predicate": ann.predicate,
                    "object": ann.object_uri,
                    "description": ann.description,
                    "derived_from": ann.derived_from,
                    "quantitative_detail": ann.quantitative_detail,
                }
                for key, ann in self.relation_annotations.items()
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SemanticMemoryStore":
        """Restore a store from ``to_dict()`` output (old format tolerated)."""
        store = cls()
        for uri, raw in (data.get("entity_annotations") or {}).items():
            store.entity_annotations[uri] = EntityAnnotation(
                entity_uri=uri,
                entity_type=raw.get("entity_type", ""),
                description=raw.get("description", ""),
                source_text_refs=list(raw.get("source_text_refs") or []),
                intent_refs=list(raw.get("intent_refs") or []),
                round_added=int(raw.get("round_added", 1)),
                valid_from_round=int(raw.get("valid_from_round", 1)),
                valid_until_round=int(raw["valid_until_round"]) if raw.get("valid_until_round") else None,
                confidence=float(raw.get("confidence", 1.0)),
            )
        for key, raw in (data.get("relation_annotations") or {}).items():
            store.relation_annotations[key] = RelationAnnotation(
                subject_uri=raw.get("subject", ""),
                predicate=raw.get("predicate", ""),
                object_uri=raw.get("object", ""),
                description=raw.get("description", ""),
                derived_from=raw.get("derived_from", ""),
                quantitative_detail=dict(raw.get("quantitative_detail") or {}),
            )
        return store

    def supersede(self, annotation: EntityAnnotation) -> bool:
        """Replace an annotation only when the new confidence is higher."""
        existing = self.entity_annotations.get(annotation.entity_uri)
        if existing is None or existing.confidence >= annotation.confidence:
            return False
        existing.valid_until_round = annotation.round_added
        self.entity_annotations[annotation.entity_uri] = annotation
        return True


# ── Singleton access ──

_SEMANTIC_MEMORY: Optional[SemanticMemoryStore] = None


def get_semantic_memory() -> SemanticMemoryStore:
    global _SEMANTIC_MEMORY
    if _SEMANTIC_MEMORY is None:
        _SEMANTIC_MEMORY = SemanticMemoryStore()
    return _SEMANTIC_MEMORY


def reset_semantic_memory() -> None:
    """Release the process singleton between isolated pipeline lifecycles."""
    global _SEMANTIC_MEMORY
    _SEMANTIC_MEMORY = None


# ── Round persistence (data/kg_memory/{session_id}_round_{N}.json) ──


def get_memory_dir() -> Path:
    from app.core.settings import DATA_DIR

    d = DATA_DIR / "kg_memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


def memory_state_path(session_id: str, round_num: int) -> Path:
    return get_memory_dir() / f"{session_id}_round_{round_num}.json"


def save_memory_state(
    session_id: str,
    round_num: int,
    store: Optional[SemanticMemoryStore] = None,
) -> Path:
    store = store if store is not None else get_semantic_memory()
    path = memory_state_path(session_id, round_num)
    path.write_text(json.dumps(store.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_memory_state(session_id: str, round_num: int) -> SemanticMemoryStore:
    path = memory_state_path(session_id, round_num)
    if not path.exists():
        return SemanticMemoryStore()
    data = json.loads(path.read_text(encoding="utf-8"))
    return SemanticMemoryStore.from_dict(data)


def diff_round(
    previous: Optional[SemanticMemoryStore],
    current: SemanticMemoryStore,
) -> Dict[str, Any]:
    if previous is None:
        return {
            "added": list(current.entity_annotations.keys()),
            "superseded": [],
            "unchanged": 0,
        }
    added, superseded, unchanged = [], [], 0
    for uri, ann in current.entity_annotations.items():
        old = previous.entity_annotations.get(uri)
        if old is None:
            added.append(uri)
        elif old.valid_until_round is not None:
            superseded.append(uri)
        else:
            unchanged += 1
    return {"added": added, "superseded": superseded, "unchanged": unchanged}


__all__ = [
    "EntityAnnotation", "RelationAnnotation", "SemanticMemoryStore",
    "get_semantic_memory", "reset_semantic_memory",
    "get_memory_dir", "memory_state_path", "save_memory_state", "load_memory_state", "diff_round",
]
