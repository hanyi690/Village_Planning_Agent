"""Workflow-owned CognitionRound creation and validation."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import Any

from app.contracts.cognition_round import CognitionRound, requirement_set_digest


def _value(source: Mapping[str, Any] | Any, name: str) -> str:
    if isinstance(source, Mapping):
        return str(source.get(name) or "").strip()
    return str(getattr(source, name, "") or "").strip()


def _parent_identity(
    source: Mapping[str, Any] | Any,
) -> tuple[str, str, str]:
    if isinstance(source, Mapping):
        ref = _value(source, "world_model_snapshot_ref")
        digest = _value(source, "world_model_snapshot_digest")
        epoch = _value(source, "world_model_epoch")
    else:
        world_model = getattr(source, "world_model", None)
        ref = str(
            getattr(world_model, "snapshot_ref", "")
            or getattr(source, "world_model_snapshot_ref", "")
            or ""
        ).strip()
        digest = str(
            getattr(world_model, "snapshot_digest", "")
            or getattr(source, "world_model_snapshot_digest", "")
            or ""
        ).strip()
        epoch = str(
            getattr(world_model, "version", "")
            or getattr(source, "world_model_epoch", "")
            or ""
        ).strip()
    if not ref or not digest or not epoch:
        raise ValueError("CognitionRound requires a pinned World Model parent snapshot")
    return ref, digest, epoch


def open_cognition_round(
    source: Mapping[str, Any] | Any,
    requirements: Iterable[Any],
    *,
    workflow_run_id: str = "",
    branch_id: str = "",
    round_number: int = 0,
    max_rounds: int = 8,
    previous_proposal_fingerprint: str = "",
) -> CognitionRound:
    """Open a deterministic round from workflow-owned parent state.

    This is the only production factory for Evidence/Cognition rounds.  It is
    intentionally outside Evidence so retrieval cannot invent a round from a
    request id or a snapshot label.
    """

    requirements = tuple(requirements)
    parent_ref, parent_digest, wm_epoch = _parent_identity(source)
    run_id = workflow_run_id or _value(source, "run_id") or _value(source, "session_id")
    branch = branch_id or _value(source, "branch_id") or "main"
    if not run_id:
        raise ValueError("CognitionRound requires workflow_run_id")
    if round_number < 0 or round_number >= max_rounds:
        raise ValueError("round_number must be below max_rounds")
    requirement_digest = requirement_set_digest(requirements)
    requirement_refs = tuple(
        str(getattr(item, "requirement_id", "") or "").strip()
        for item in requirements
    )
    if not requirement_refs or any(not value for value in requirement_refs):
        raise ValueError("CognitionRound requires stable requirement IDs")
    round_key = "|".join(
        (
            run_id,
            branch,
            str(round_number),
            wm_epoch,
            parent_ref,
            parent_digest,
            requirement_digest,
        )
    )
    round_id = "cognition-round:" + hashlib.sha256(round_key.encode("utf-8")).hexdigest()[:32]
    return CognitionRound(
        round_id=round_id,
        round_number=round_number,
        wm_epoch=wm_epoch,
        parent_world_model_snapshot_ref=parent_ref,
        parent_world_model_snapshot_digest=parent_digest,
        requirement_set_digest=requirement_digest,
        requirement_refs=requirement_refs,
        max_rounds=max_rounds,
        previous_proposal_fingerprint=previous_proposal_fingerprint,
    )


__all__ = [
    "open_cognition_round",
]
