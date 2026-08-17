"""Deterministic source-integrity facts for gate diagnostics."""
from __future__ import annotations

from typing import Iterable

from app.contracts.evidence.evidence_contracts import EvidenceFact, EvidenceSource
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)
RETRIEVER_VERSION = "integrity-v1"


async def retrieve_from_integrity(
    session_id: str,
    query: str = "",
    source_refs: Iterable[str] = (),
    required_facts: Iterable[str] = (),
) -> tuple[list[EvidenceFact], list[EvidenceSource]]:
    """Report checks that can be proven from checkpoint metadata.

    Geometry-level CRS/coverage validation remains the responsibility of the
    GIS validators.  This retriever only emits facts about source presence,
    descriptor identity and missing metadata, so it cannot overclaim spatial
    quality from a checkpoint alone.
    """
    try:
        from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

        state = await PlanningRuntimeService.aget_state_values(session_id)
    except Exception as exc:
        logger.warning("[integrity_retriever] state unavailable: %s", exc)
        return [], []
    refs = dict((state or {}).get("artifact_refs") or {})
    if not refs:
        return [], []
    facts: list[EvidenceFact] = []
    sources: list[EvidenceSource] = []
    for key, ref in sorted(refs.items()):
        digest = str((ref or {}).get("descriptor_digest") or (ref or {}).get("digest") or "") if isinstance(ref, dict) else ""
        reference = f"integrity:{key}:{digest or 'missing-digest'}"
        sources.append(EvidenceSource(source_type="integrity", reference=reference, confidence=1.0 if digest else 0.0))
        if digest:
            statement = f"产物 {key} 具有可验证 descriptor digest"
            status = "verified"
        else:
            statement = f"产物 {key} 缺少 descriptor digest，无法证明版本完整性"
            status = "unresolved"
        facts.append(EvidenceFact(
            statement=statement,
            confidence=1.0 if digest else 0.0,
            source_refs=[reference],
            fact_type="source_integrity",
            fields={"artifact_key": key, "descriptor_digest": digest},
            support_relation="identity",
            status=status,
        ))
    return facts, sources


__all__ = ["RETRIEVER_VERSION", "retrieve_from_integrity"]
