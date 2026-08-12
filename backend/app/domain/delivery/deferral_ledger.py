"""DeferralLedger construction helpers for the HUMAN deferral boundary.

Pure functions: build immutable ``TargetDeferral`` entries and merge them into
an immutable ``DeferralLedger`` revision. No state, no persistence — CAS writes
are owned exclusively by the workflow layer via ``persist_stage_artifact``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from app.contracts.artifacts.deferral_contracts import (
    DeferralLedger,
    HumanDeferralDecision,
    TargetDeferral,
)


def build_target_deferrals(
    target_ids: Sequence[str],
    *,
    reason: str,
    source_refs: Sequence[str] | Callable[[str], Sequence[str]],
    decision: HumanDeferralDecision | None = None,
    review_id: str = "",
    decided_by: str = "",
    rationale: str = "",
) -> list[TargetDeferral]:
    """Construct one auditable ``TargetDeferral`` entry per target id.

    ``source_refs`` may be a shared tuple applied to every entry or a callable
    ``(target_id) -> refs`` for per-target provenance (GROUND spec links,
    SELECT artifact digests). When ``decision`` is omitted one is built from
    ``review_id``/``decided_by``/``rationale`` mirroring the HUMAN boundary.
    """
    if decision is None:
        decision = HumanDeferralDecision(
            decision_id=review_id or "human-review",
            decided_by=decided_by,
            rationale=rationale,
        )
    entries: list[TargetDeferral] = []
    for target_id in dict.fromkeys(target_ids):
        refs = source_refs(target_id) if callable(source_refs) else tuple(source_refs)
        entries.append(
            TargetDeferral(
                target_id=str(target_id),
                reason=reason,
                source_refs=tuple(refs),
                decision=decision,
            )
        )
    return entries


def append_ledger(
    existing: DeferralLedger | None,
    new_entries: Sequence[TargetDeferral],
) -> DeferralLedger:
    """Append new entries to an existing immutable ledger, preserving prior entries.

    A target is deferred once: repeated HUMAN deferral revisions (GROUND,
    SELECT, VALIDATE) must not stack duplicate ledger rows for the same
    target - that inflates the deferral summary and re-marks already-deferred
    targets as structurally blocked.
    """
    existing_entries = tuple(getattr(existing, "entries", None) or ())
    seen = {str(entry.target_id) for entry in existing_entries}
    unique_new = tuple(
        entry for entry in new_entries if str(getattr(entry, "target_id", "")) not in seen
    )
    return DeferralLedger(entries=existing_entries + unique_new)


__all__ = ["append_ledger", "build_target_deferrals"]
