"""Read-only retrieval of typed artifact references from the active run."""
from __future__ import annotations

from typing import Iterable

from app.contracts.evidence.evidence_contracts import EvidenceFact, EvidenceSource
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)
RETRIEVER_VERSION = "artifact-v1"


def _ref_value(ref: object, key: str) -> str:
    if isinstance(ref, dict):
        return str(ref.get(key) or "")
    return str(getattr(ref, key, "") or "")


async def retrieve_from_artifacts(
    session_id: str,
    query: str = "",
    source_refs: Iterable[str] = (),
    required_facts: Iterable[str] = (),
) -> tuple[list[EvidenceFact], list[EvidenceSource]]:
    """Return only artifact identity facts; never infer artifact payload facts."""
    try:
        from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

        state = await PlanningRuntimeService.aget_state_values(session_id)
    except Exception as exc:
        logger.warning("[artifact_retriever] state unavailable: %s", exc)
        return [], []
    refs = dict((state or {}).get("artifact_refs") or {})
    if not refs:
        return [], []
    requested = {
        ref.split(":", 1)[1]
        for ref in source_refs
        if isinstance(ref, str) and ref.startswith("artifact:")
    }
    terms = " ".join([query, *required_facts]).lower()
    if requested:
        keys = [key for key in refs if key in requested]
    elif terms:
        keys = [key for key in refs if key.lower() in terms or not required_facts]
    else:
        keys = list(refs)
    facts: list[EvidenceFact] = []
    sources: list[EvidenceSource] = []
    for key in sorted(keys):
        digest = _ref_value(refs[key], "descriptor_digest") or _ref_value(refs[key], "digest")
        if not digest:
            continue
        reference = f"artifact:{key}:{digest}"
        sources.append(EvidenceSource(source_type="artifact", reference=reference, confidence=1.0))
        facts.append(EvidenceFact(
            statement=f"运行产物 {key} 已存在，descriptor={digest}",
            confidence=1.0,
            source_refs=[reference],
            fact_type="artifact_presence",
            fields={"artifact_key": key, "descriptor_digest": digest},
            support_relation="identity",
        ))
    return facts, sources


__all__ = ["RETRIEVER_VERSION", "retrieve_from_artifacts"]
