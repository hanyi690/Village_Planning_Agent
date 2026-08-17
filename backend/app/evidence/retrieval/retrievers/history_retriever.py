"""Read-only checkpoint history evidence for revisions and resume decisions."""
from __future__ import annotations

from typing import Iterable

from app.contracts.evidence.evidence_contracts import EvidenceFact, EvidenceSource
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)
RETRIEVER_VERSION = "history-v1"


async def retrieve_from_history(
    session_id: str,
    query: str = "",
    source_refs: Iterable[str] = (),
    required_facts: Iterable[str] = (),
) -> tuple[list[EvidenceFact], list[EvidenceSource]]:
    """Summarize checkpoint identity, without treating old state as current truth."""
    try:
        from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

        snapshots = []
        async for snapshot in PlanningRuntimeService.aget_state_history(session_id):
            snapshots.append(snapshot)
            if len(snapshots) >= 32:
                break
    except Exception as exc:
        logger.warning("[history_retriever] history unavailable: %s", exc)
        return [], []
    if not snapshots:
        return [], []
    facts: list[EvidenceFact] = []
    sources: list[EvidenceSource] = []
    for index, snapshot in enumerate(snapshots):
        values = getattr(snapshot, "values", None) or {}
        if not isinstance(values, dict):
            continue
        checkpoint = getattr(snapshot, "config", None) or {}
        configurable = checkpoint.get("configurable", {}) if isinstance(checkpoint, dict) else {}
        checkpoint_id = str(configurable.get("checkpoint_id") or index)
        refs = dict(values.get("artifact_refs") or {})
        reference = f"history:{session_id}:{checkpoint_id}"
        sources.append(EvidenceSource(source_type="history", reference=reference, confidence=1.0))
        facts.append(EvidenceFact(
            statement=f"运行历史检查点 {checkpoint_id}：{len(refs)} 个命名产物引用",
            confidence=1.0,
            source_refs=[reference],
            fact_type="checkpoint_summary",
            fields={"checkpoint_id": checkpoint_id, "artifact_count": str(len(refs))},
            support_relation="identity",
        ))
    return facts, sources


__all__ = ["RETRIEVER_VERSION", "retrieve_from_history"]
