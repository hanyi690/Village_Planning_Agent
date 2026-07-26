"""SemanticMemoryStore — 实体和关系的语义注解存储。

v4.6 新增：替代旧的 _semantic_store（Dict[str, Dict[str, str]]）。
注解不存储在 RDF 图中，通过此模块管理。

实体注解 (EntityAnnotation): 附着于空间实体的语义说明
关系注解 (RelationAnnotation): 附着于空间关系的语义说明
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EntityAnnotation:
    """实体注解 — 附着于空间实体的语义说明"""
    entity_uri: str
    entity_type: str
    description: str = ""
    source_text_refs: List[str] = field(default_factory=list)
    intent_refs: List[str] = field(default_factory=list)


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


# ── Singleton access ──

_SEMANTIC_MEMORY: Optional[SemanticMemoryStore] = None


def get_semantic_memory() -> SemanticMemoryStore:
    global _SEMANTIC_MEMORY
    if _SEMANTIC_MEMORY is None:
        _SEMANTIC_MEMORY = SemanticMemoryStore()
    return _SEMANTIC_MEMORY


__all__ = [
    "EntityAnnotation", "RelationAnnotation", "SemanticMemoryStore",
    "get_semantic_memory",
]