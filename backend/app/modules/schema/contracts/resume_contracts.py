"""Contracts for deterministic checkpoint recovery planning.

LangGraph tells us where execution can continue (``next`` and pending
interrupts).  This module records the application-level decision about which
versioned artifacts are reusable and which stages must be rerun.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Dict, Iterable, Optional

from pydantic import BaseModel, ConfigDict, Field


class ResumeMode(StrEnum):
    INTERRUPT = "resume_interrupt"
    CHECKPOINT = "resume_checkpoint"
    RERUN = "rerun_from_stage"
    COMPLETED = "completed"
    BLOCKED = "blocked"


class ResumePlan(BaseModel):
    """Auditable application decision for a checkpoint operation."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    checkpoint_id: str = ""
    mode: ResumeMode
    resume_from: str
    checkpoint_kind: str
    reuse: list[str] = Field(default_factory=list)
    rerun: list[str] = Field(default_factory=list)
    reason: str
    context_version: str = ""
    context_fingerprint: str = ""
    input_checksums: Dict[str, str] = Field(default_factory=dict)
    output_checksums: Dict[str, str] = Field(default_factory=dict)
    graph_next: list[str] = Field(default_factory=list)
    interrupt_id: Optional[str] = None


ARTIFACT_STAGE_ORDER: tuple[tuple[str, str], ...] = (
    ("l1_snapshot", "L1"),
    ("l2_strategy", "L2"),
    ("planning_program", "L3"),
    ("intent_compilation", "PARSE"),
    ("grounding_result", "GROUND"),
    ("site_selection", "SELECT"),
    ("execution_plan", "EXECUTE"),
    ("execution_outcome", "EXECUTE"),
    ("parcel_changeset", "EXECUTE"),
    ("planned_state", "EXECUTE"),
    ("validation_report", "VALIDATE"),
    ("reconciliation_report", "RECONCILE"),
    ("delivery_manifest", "DELIVER"),
)


def _ref_checksum(ref: Any) -> str:
    if isinstance(ref, dict):
        return str(ref.get("checksum") or ref.get("semantic_checksum") or "")
    return str(getattr(ref, "checksum", "") or getattr(ref, "semantic_checksum", "") or "")


def _ref_revision(ref: Any) -> str:
    if isinstance(ref, dict):
        return str(ref.get("revision") or "v1")
    return str(getattr(ref, "revision", "v1") or "v1")


def _ref_context_value(ref: Any, field: str) -> str:
    if isinstance(ref, dict):
        return str(ref.get(field) or "")
    return str(getattr(ref, field, "") or "")


def _ref_parent_checksums(ref: Any) -> Dict[str, str]:
    if isinstance(ref, dict):
        parent_checksums = ref.get("parent_checksums") or {}
    else:
        parent_checksums = getattr(ref, "parent_checksums", {}) or {}
    return {
        str(parent_key): str(parent_identity)
        for parent_key, parent_identity in parent_checksums.items()
        if str(parent_key)
    }


def _artifact_checksums(refs: Dict[str, Any]) -> Dict[str, str]:
    return {
        key: checksum
        for key, ref in refs.items()
        if (checksum := _ref_checksum(ref))
    }


def _stage_for_node(node: str) -> str:
    normalized = node.lower()
    for token, stage in (
        ("l1", "L1"), ("l2", "L2"), ("l3", "L3"),
        ("parse", "PARSE"), ("ground", "GROUND"), ("select", "SELECT"),
        ("execute", "EXECUTE"), ("validate", "VALIDATE"),
        ("reconcile", "RECONCILE"), ("deliver", "DELIVER"),
    ):
        if token in normalized:
            return stage
    return node or "unknown"


def _rerun_from_stage(stage: str) -> list[str]:
    stages = [stage_name for _, stage_name in ARTIFACT_STAGE_ORDER]
    unique_stages = list(dict.fromkeys(stages))
    try:
        start = unique_stages.index(stage)
    except ValueError:
        return []
    return unique_stages[start:]


def _artifact_context_changed(ref: Any, state: Dict[str, Any]) -> bool:
    state_version = str(state.get("context_version") or "")
    ref_version = _ref_context_value(ref, "context_version")
    if state_version and ref_version and state_version != ref_version:
        return True

    state_fingerprint = str(state.get("context_fingerprint") or "")
    ref_fingerprint = _ref_context_value(ref, "context_fingerprint")
    return bool(
        state_fingerprint
        and ref_fingerprint
        and state_fingerprint != ref_fingerprint
    )


def _parent_identity_status(
    artifact_key: str,
    ref: Any,
    refs: Dict[str, Any],
    valid_upstream: list[str],
) -> str | None:
    parent_checksums = _ref_parent_checksums(ref)
    parent_checksums.pop(artifact_key, None)

    if valid_upstream and not parent_checksums:
        return "missing"

    for parent_key, encoded_identity in parent_checksums.items():
        expected_revision, separator, expected_checksum = encoded_identity.partition(":")
        if not separator or not expected_revision or not expected_checksum:
            return "missing"
        current_parent = refs.get(parent_key)
        if current_parent is None:
            return "changed"
        if _ref_revision(current_parent) != expected_revision:
            return "changed"
        if _ref_checksum(current_parent) != expected_checksum:
            return "changed"

    for parent_key in valid_upstream:
        if parent_key not in parent_checksums:
            return "missing"

    return None


def _validated_reuse(refs: Dict[str, Any], state: Dict[str, Any]) -> tuple[list[str], str | None]:
    reuse: list[str] = []
    for artifact_key, stage in ARTIFACT_STAGE_ORDER:
        ref = refs.get(artifact_key)
        if ref is None:
            continue
        if _artifact_context_changed(ref, state):
            return reuse, f"context identity changed at {stage}"
        parent_status = _parent_identity_status(artifact_key, ref, refs, reuse)
        if parent_status == "missing":
            return reuse, f"parent identity missing at {stage}"
        if parent_status == "changed":
            return reuse, f"parent identity changed at {stage}"
        reuse.append(artifact_key)
    return reuse, None


def build_resume_plan(
    state: Dict[str, Any],
    *,
    session_id: str,
    checkpoint_id: str = "",
    checkpoint_kind: str = "intermediate",
    next_nodes: Iterable[str] = (),
    pending_interrupt: Optional[Dict[str, Any]] = None,
) -> ResumePlan:
    """Build a conservative, deterministic plan from checkpoint metadata.

    This planner never guesses that an artifact is reusable when its ref is
    absent.  Stage-specific invalidation can later add a stronger reason and
    rerun boundary without changing the transport contract.
    """

    graph_next = [str(node) for node in next_nodes]
    refs = dict(state.get("artifact_refs") or {})
    reuse = [key for key, _ in ARTIFACT_STAGE_ORDER if key in refs]
    checksums = _artifact_checksums(refs)
    interrupt = pending_interrupt or state.get("human_interrupt")

    if interrupt:
        payload = interrupt if isinstance(interrupt, dict) else {}
        channel = str(payload.get("channel") or "human")
        return ResumePlan(
            session_id=session_id,
            checkpoint_id=checkpoint_id,
            mode=ResumeMode.INTERRUPT,
            resume_from=graph_next[0] if graph_next else channel,
            checkpoint_kind="human",
            reuse=reuse,
            reason=f"pending HUMAN interrupt ({channel})",
            context_version=str(state.get("context_version") or ""),
            context_fingerprint=str(state.get("context_fingerprint") or ""),
            input_checksums=checksums,
            output_checksums=checksums,
            graph_next=graph_next,
            interrupt_id=str(payload.get("event_id") or "") or None,
        )

    if state.get("diagnostic_terminal"):
        return ResumePlan(
            session_id=session_id,
            checkpoint_id=checkpoint_id,
            mode=ResumeMode.BLOCKED,
            resume_from="",
            checkpoint_kind=checkpoint_kind,
            reuse=reuse,
            reason="diagnostic terminal requires an explicit new input or revision",
            context_version=str(state.get("context_version") or ""),
            context_fingerprint=str(state.get("context_fingerprint") or ""),
            input_checksums=checksums,
            output_checksums=checksums,
            graph_next=graph_next,
        )

    if state.get("phase") == "completed":
        mode = ResumeMode.COMPLETED
        resume_from = ""
        rerun: list[str] = []
        reason = "checkpoint already has a terminal delivery state"
    else:
        validated_reuse, validation_reason = _validated_reuse(refs, state)
        if validation_reason:
            invalid_stage = validation_reason.rsplit(" ", 1)[-1]
            return ResumePlan(
                session_id=session_id,
                checkpoint_id=checkpoint_id,
                mode=ResumeMode.RERUN,
                resume_from=invalid_stage,
                checkpoint_kind=checkpoint_kind,
                reuse=validated_reuse,
                rerun=_rerun_from_stage(invalid_stage),
                reason=validation_reason,
                context_version=str(state.get("context_version") or ""),
                context_fingerprint=str(state.get("context_fingerprint") or ""),
                input_checksums=checksums,
                output_checksums=checksums,
                graph_next=graph_next,
            )
        resume_from = graph_next[0] if graph_next else str(state.get("phase") or "init")
        stage = _stage_for_node(resume_from)
        mode = ResumeMode.RERUN if checkpoint_kind in {"revision", "layer"} else ResumeMode.CHECKPOINT
        rerun = _rerun_from_stage(stage) if mode == ResumeMode.RERUN else []
        reuse = validated_reuse
        reason = "continue from the persisted graph cursor" if mode == ResumeMode.CHECKPOINT else f"rerun downstream stages from {stage}"

    return ResumePlan(
        session_id=session_id,
        checkpoint_id=checkpoint_id,
        mode=mode,
        resume_from=resume_from,
        checkpoint_kind=checkpoint_kind,
        reuse=reuse,
        rerun=rerun,
        reason=reason,
        context_version=str(state.get("context_version") or ""),
        context_fingerprint=str(state.get("context_fingerprint") or ""),
        input_checksums=checksums,
        output_checksums=checksums,
        graph_next=graph_next,
    )


__all__ = [
    "ARTIFACT_STAGE_ORDER",
    "ResumeMode",
    "ResumePlan",
    "build_resume_plan",
]
