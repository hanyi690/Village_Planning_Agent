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


class ResumeCommand(BaseModel):
    """Application-level command for continuing a persisted execution.

    ``checkpoint_id`` is only a cursor.  The service must still build a
    ``ResumePlan`` from that cursor before invoking LangGraph.  ``event_id``
    is the compare-and-set token for HUMAN decisions; it is deliberately not
    inferred from the latest state so a stale browser cannot consume a newer
    interrupt.
    """

    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    mode: ResumeMode
    checkpoint_id: Optional[str] = None
    event_id: Optional[str] = None
    expected_last_event_seq: Optional[int] = Field(default=None, ge=0)
    payload: Dict[str, Any] = Field(default_factory=dict)


class ResumeResult(BaseModel):
    """Stable acknowledgement returned after a resume command is accepted."""

    model_config = ConfigDict(extra="forbid")

    command_id: str
    session_id: str
    status: str
    mode: ResumeMode
    checkpoint_id: Optional[str] = None
    event_id: Optional[str] = None
    resume_plan: Dict[str, Any]


class ResumePlan(BaseModel):
    """Auditable application decision for a checkpoint operation.

    A DATA-boundary replay is represented as one explicit full-chain plan.  It
    starts at the persisted ``bootstrap_context`` cursor and reruns every
    downstream product in order; it is not a shortcut into KG, Evidence, or a
    planning layer.
    """

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
    artifact_integrity: Dict[str, str] = Field(default_factory=dict)
    graph_next: list[str] = Field(default_factory=list)
    interrupt_id: Optional[str] = None


def repair_plan_for_integrity(
    plan: ResumePlan,
    invalid_artifacts: Iterable[str],
) -> ResumePlan:
    """Convert storage failures into the earliest safe downstream replay.

    This only computes the application plan.  The caller must select a
    historical checkpoint at or before ``resume_from`` before invoking the
    graph; reusing the original late checkpoint would not actually rerun the
    affected stage.
    """

    invalid = set(invalid_artifacts)
    if not invalid:
        return plan
    stage_by_key = {
        **dict(ARTIFACT_STAGE_ORDER),
        **{
            gate_key: stage
            for gate_key, (_output_key, stage) in _GATE_OUTPUT_BY_KEY.items()
        },
    }
    ordered = [
        (key, stage_by_key[key])
        for key in invalid
        if key in stage_by_key
    ]
    if not ordered:
        return plan.model_copy(update={
            "mode": ResumeMode.BLOCKED,
            "reason": "artifact integrity failed for an unknown stage",
        })
    first_key, first_stage = min(
        ordered,
        key=lambda item: [stage for _, stage in ARTIFACT_STAGE_ORDER].index(item[1]),
    )
    stages = list(dict.fromkeys(stage for _, stage in ARTIFACT_STAGE_ORDER))
    start = stages.index(first_stage)
    reusable_stages = set(stages[:start])
    reuse = [
        key
        for key, stage in stage_by_key.items()
        if stage in reusable_stages
    ]
    return plan.model_copy(update={
        "mode": ResumeMode.RERUN,
        "resume_from": first_stage,
        "reuse": [key for key in plan.reuse if key in reuse],
        "rerun": stages[start:],
        "reason": f"artifact {first_key} integrity failed; replay from {first_stage}",
    })


ARTIFACT_STAGE_ORDER: tuple[tuple[str, str], ...] = (
    ("l1_snapshot", "L1"),
    ("l2_strategy", "L2"),
    ("planning_program", "L3"),
    ("target_projection", "TARGET_PROJECTION"),
    ("grounding_result", "GROUND"),
    ("scoped_grounding_problem", "SELECT"),
    ("scenario_set", "SELECT"),
    ("planning_scenario", "SELECT"),
    ("approved_execution_input", "SELECT"),
    ("execution_plan", "EXECUTE"),
    ("execution_result", "EXECUTE"),
    ("spatial_changeset", "EXECUTE"),
    ("parcel_changeset", "EXECUTE"),
    ("planned_state", "EXECUTE"),
    ("validation_report", "VALIDATE"),
    ("final_manifest", "RECONCILE"),
    ("delivery_manifest", "DELIVER"),
)

# The only supported replay that invalidates the complete upstream product
# chain.  Keep this separate from ARTIFACT_STAGE_ORDER: DATA, KG, and EVIDENCE
# are bootstrap products and do not have the ordinary planning artifact keys.
DATA_REPLAY_CHAIN: tuple[str, ...] = (
    "DATA",
    "KG",
    "EVIDENCE",
    "L1",
    "L2",
    "L3",
    "TARGET_PROJECTION",
    "GROUND",
    "SELECT",
    "EXECUTE",
    "VALIDATE",
    "RECONCILE",
    "DELIVER",
)

_GATE_OUTPUT_BY_KEY: dict[str, tuple[str, str]] = {
    "l1_gate": ("l1_snapshot", "L1"),
    "l2_gate": ("l2_strategy", "L2"),
    "l3_gate": ("planning_program", "L3"),
    "target_projection_gate": ("target_projection", "TARGET_PROJECTION"),
}


def _ref_digest(ref: Any) -> str:
    if isinstance(ref, dict):
        return str(ref.get("digest") or "")
    return str(getattr(ref, "digest", "") or "")


def _ref_descriptor_digest(ref: Any) -> str:
    if isinstance(ref, dict):
        return str(ref.get("descriptor_digest") or "")
    return str(getattr(ref, "descriptor_digest", "") or "")


def _ref_context_value(ref: Any, field: str) -> str:
    if isinstance(ref, dict):
        provenance = ref.get("provenance") or {}
        if field == "context_version":
            return str((provenance.get("context_ref") or {}).get("version") or "")
        if field == "context_fingerprint":
            return str(provenance.get("context_fingerprint") or "")
        return str(ref.get(field) or "")
    provenance = getattr(ref, "provenance", {}) or {}
    if field == "context_version":
        return str((provenance.get("context_ref") or {}).get("version") or "")
    if field == "context_fingerprint":
        return str(provenance.get("context_fingerprint") or "")
    return str(getattr(ref, field, "") or "")


def _ref_parent_digests(ref: Any) -> Dict[str, str]:
    if isinstance(ref, dict):
        parent_digests = ref.get("parent_digests") or {}
    else:
        parent_digests = getattr(ref, "parent_digests", {}) or {}
    return {
        str(parent_key): str(parent_identity)
        for parent_key, parent_identity in parent_digests.items()
        if str(parent_key)
    }


def _artifact_checksums(refs: Dict[str, Any]) -> Dict[str, str]:
    return {
        key: checksum
        for key, ref in refs.items()
        if (checksum := _ref_descriptor_digest(ref))
    }


def _stage_for_node(node: str) -> str:
    normalized = node.lower()
    for token, stage in (
        ("l1", "L1"), ("l2", "L2"), ("l3", "L3"),
        ("target_projection", "TARGET_PROJECTION"), ("ground", "GROUND"), ("select", "SELECT"),
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
    parent_digests = _ref_parent_digests(ref)
    parent_digests.pop(artifact_key, None)

    if valid_upstream and not parent_digests:
        return "missing"

    for parent_key, expected_digest in parent_digests.items():
        if not expected_digest.startswith("sha256:"):
            return "missing"
        current_parent = refs.get(parent_key)
        if current_parent is None:
            return "changed"
        if _ref_digest(current_parent) != expected_digest:
            return "changed"

    for parent_key in valid_upstream:
        if parent_key not in parent_digests:
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
        gate_key = next(
            (
                key
                for key, (output_key, _gate_stage) in _GATE_OUTPUT_BY_KEY.items()
                if output_key == artifact_key
            ),
            "",
        )
        if gate_key:
            gate_ref = refs.get(gate_key)
            if gate_ref is None:
                return reuse, f"gate identity missing at {stage}"
            if _artifact_context_changed(gate_ref, state):
                return reuse, f"gate context identity changed at {stage}"
            bound_output_digest = _ref_parent_digests(gate_ref).get(artifact_key)
            if bound_output_digest != _ref_digest(ref):
                return reuse, f"gate output identity changed at {stage}"
        reuse.append(artifact_key)
        if gate_key:
            reuse.append(gate_key)
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
    "DATA_REPLAY_CHAIN",
    "ResumeMode",
    "ResumeCommand",
    "ResumeResult",
    "ResumePlan",
    "repair_plan_for_integrity",
    "build_resume_plan",
]
