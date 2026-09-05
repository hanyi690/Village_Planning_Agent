"""Evidence retriever backed by the current DATA-owned World Model view."""

from __future__ import annotations

from typing import Any

from app.contracts.evidence.evidence_contracts import (
    EvidenceFact,
    SpatialCognitionEvidence,
)
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)
RETRIEVER_VERSION = "world-model-current-v1"


def _source_root(session_id: str) -> str:
    return f"world_model:{str(session_id or '').strip()}"


def _current_world(session_id: str) -> Any | None:
    """Resolve the bounded current-world port without loading legacy KG state."""

    from app.infrastructure.context_runtime.manager import get_cached_context

    context = get_cached_context(session_id)
    if context is None:
        return None
    current_world = getattr(getattr(context, "ports", None), "current_world", None)
    if current_world is not None:
        return current_world
    return getattr(context, "world_model", None)


def _row_text(row: dict[str, Any]) -> str:
    values: list[str] = []
    for key in (
        "entity_ref",
        "entity_identity",
        "canonical_name",
        "aliases",
        "concept_types",
        "source_feature_ref",
    ):
        value = row.get(key)
        if isinstance(value, (list, tuple, set)):
            values.extend(str(item) for item in value)
        elif value not in (None, "", [], {}, ()):
            values.append(str(value))
    return " ".join(values).casefold()


def _source_refs(row: dict[str, Any], root: str) -> list[str]:
    refs: list[str] = []
    for part in row.get("parts") or ():
        for value in part.get("source_record_refs") or ():
            text = str(value or "").strip()
            if text:
                refs.append(text)
    if not refs:
        entity_ref = str(row.get("entity_ref") or "").strip()
        refs.append(f"{root}#entity:{entity_ref}" if entity_ref else root)
    return list(dict.fromkeys(refs))


async def retrieve_from_kg(
    session_id: str,
    village_name: str,
    dimension_key: str,
    stage: str,
    query: str = "",
    required_facts: list[str] | None = None,
    entity_scope: list[str] | None = None,
) -> tuple[list[EvidenceFact], SpatialCognitionEvidence]:
    """Return bounded facts from the immutable current-world read port.

    This retriever does not access a legacy session bundle, BSM-specific
    query, old KG manager, or RDF assertion/planned graph. Geometry authority remains
    DATA; this route only exposes WM identity and representation lineage.
    """

    del dimension_key, stage, required_facts, entity_scope
    world = _current_world(session_id)
    if world is None:
        return [], SpatialCognitionEvidence()

    root = _source_root(session_id)
    wanted = str(query or "").strip().casefold()
    try:
        rows = list(world.find_entities(limit=12, include_current_digest=False))
    except Exception as exc:
        logger.debug("[kg_retriever] current-world query unavailable: %s", type(exc).__name__)
        return [], SpatialCognitionEvidence()

    facts: list[EvidenceFact] = []
    filtered = [row for row in rows if not wanted or wanted in _row_text(row)]
    for row in filtered:
        identity = str(
            row.get("entity_identity")
            or row.get("entity_ref")
            or ""
        ).strip()
        parts = row.get("parts") or ()
        representations = row.get("representations") or ()
        statement = (
            f"当前世界模型实体 {identity} 包含 {len(parts)} 个源部件，"
            f"{len(representations)} 个 representation"
        )
        facts.append(EvidenceFact(
            statement=statement,
            confidence=0.65,
            source_refs=_source_refs(row, root),
            fact_type="world_model_entity",
            fields={
                "evidence_role": "entity_identity",
                "source_kind": "world_model",
                "entity_ref": str(row.get("entity_ref") or ""),
                "entity_identity": identity,
                "part_count": str(len(parts)),
                "representation_count": str(len(representations)),
                "snapshot_ref": str(row.get("snapshot_ref") or ""),
                "snapshot_digest": str(row.get("snapshot_digest") or ""),
                "geometry_authority": "data_resource_catalog",
            },
            support_relation="world_model_current_view",
        ))

    relation_count = 0
    find_relations = getattr(world, "find_relations", None)
    if callable(find_relations):
        try:
            relation_count = len(list(find_relations(limit=32)))
        except Exception:
            relation_count = 0

    cognition = SpatialCognitionEvidence(
        village_overview=(
            f"{village_name or '当前项目'} 的 DATA-backed current world 返回 "
            f"{len(filtered)} 个有界实体"
            if filtered
            else ""
        ),
        spatial_pattern=(
            f"当前世界模型包含 {len(filtered)} 个实体和 {relation_count} 条可读关系"
            if filtered or relation_count
            else ""
        ),
        kg_confidence=0.65 if filtered else 0.0,
    )
    return facts, cognition


__all__ = ["RETRIEVER_VERSION", "retrieve_from_kg"]
