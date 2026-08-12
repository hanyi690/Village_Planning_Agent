"""Application command for building a ResumePlan from a checkpoint cursor.

The command only plans recovery; it never invokes LangGraph directly.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.workflow.resume_contracts import (
    ResumeMode,
    ResumePlan,
    build_resume_plan as _build_contract_plan,
)
from app.infrastructure.checkpoint.checkpoint_policy import classify_checkpoint, first_pending_interrupt_payload
from app.application.recovery.resume_service import fork_branch_from_plan, mark_plan_fork, plan_blocked


class CheckpointCursor(BaseModel):
    """Transport-independent cursor describing one persisted checkpoint."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)
    checkpoint_kind: str = "intermediate"
    values: dict[str, object] = Field(default_factory=dict)
    next_nodes: list[str] = Field(default_factory=list)
    pending_interrupt: dict[str, object] | None = None


def _snapshot_values(snapshot: Any) -> dict[str, Any]:
    if isinstance(snapshot, dict):
        values = snapshot.get("values")
        return dict(values) if isinstance(values, dict) else {}
    return dict(getattr(snapshot, "values", None) or {})


def _pending_interrupt_payload(snapshot: Any) -> dict[str, Any] | None:
    if isinstance(snapshot, dict):
        tasks = snapshot.get("tasks") or []
        for task in tasks:
            if not isinstance(task, dict):
                continue
            for interrupt in task.get("interrupts") or ():
                value = (
                    interrupt.get("value")
                    if isinstance(interrupt, dict)
                    else getattr(interrupt, "value", None)
                )
                if isinstance(value, dict):
                    return value
        return None
    return first_pending_interrupt_payload(snapshot)


def _snapshot_next_nodes(snapshot: Any) -> list[str]:
    if isinstance(snapshot, dict):
        next_nodes = snapshot.get("next") or ()
    else:
        next_nodes = getattr(snapshot, "next", None) or ()
    return [str(node) for node in next_nodes]


def _snapshot_checkpoint_id(snapshot: Any) -> str:
    if isinstance(snapshot, dict):
        config = snapshot.get("config") or {}
    else:
        config = getattr(snapshot, "config", None) or {}
    configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
    return str(configurable.get("checkpoint_id") or "")


def _snapshot_kind(
    snapshot: Any,
    values: dict[str, Any],
    pending: dict[str, Any] | None,
) -> str:
    if isinstance(snapshot, dict):
        kind = str(snapshot.get("checkpoint_kind") or "")
    else:
        kind = str(getattr(snapshot, "checkpoint_kind", "") or "")
    if kind:
        return kind
    _, kind = classify_checkpoint(values, pending_interrupt=bool(pending))
    return kind


def _coerce_requested_mode(requested_mode: ResumeMode | str | None) -> ResumeMode | None:
    if requested_mode is None:
        return None
    if isinstance(requested_mode, ResumeMode):
        return requested_mode
    text = str(requested_mode).strip().lower()
    for mode in ResumeMode:
        if mode.value == text:
            return mode
    return None


def build_resume_plan(
    checkpoint_snapshot: Any,
    session_id: str,
    requested_mode: ResumeMode | str | None,
    *,
    expected_event_id: str | None = None,
) -> ResumePlan:
    """Classify a checkpoint snapshot into a pure, auditable ResumePlan.

    Mode priority: pending interrupt -> ``resume_interrupt``; context/checksum
    mismatch -> ``rerun_from_stage`` at the earliest affected stage; terminal
    state -> ``completed``/``blocked``; otherwise ``resume_checkpoint``.

    A plain checkpoint resume must fork a new branch (via ``fork_artifact_refs``
    with a fresh branch_id) and must never carry ``Command(resume=...)``.  A
    HUMAN resume requires ``expected_event_id`` to match the pending interrupt;
    any mismatch yields a typed ``blocked`` plan.  No LangGraph is invoked.
    """

    values = _snapshot_values(checkpoint_snapshot)
    pending = _pending_interrupt_payload(checkpoint_snapshot)
    next_nodes = _snapshot_next_nodes(checkpoint_snapshot)
    checkpoint_id = _snapshot_checkpoint_id(checkpoint_snapshot)
    kind = _snapshot_kind(checkpoint_snapshot, values, pending)
    requested = _coerce_requested_mode(requested_mode)

    plan = _build_contract_plan(
        values,
        session_id=session_id,
        checkpoint_id=checkpoint_id,
        checkpoint_kind=kind,
        next_nodes=next_nodes,
        pending_interrupt=pending,
    )

    if pending:
        if requested not in (None, ResumeMode.INTERRUPT):
            return plan_blocked(
                plan,
                "HUMAN checkpoint requires the interrupt channel (Command(resume=...)); "
                "plain checkpoint resume is forbidden",
            )
        event_id = str(pending.get("event_id") or "")
        if requested == ResumeMode.INTERRUPT:
            if not expected_event_id:
                return plan_blocked(plan, "interrupt resume requires the active event_id")
            if expected_event_id != event_id:
                return plan_blocked(
                    plan,
                    f"event_id mismatch: expected {expected_event_id}, "
                    f"active interrupt is {event_id}",
                )
        return plan

    if requested == ResumeMode.INTERRUPT:
        return plan_blocked(plan, "no pending HUMAN interrupt; interrupt resume is invalid")

    if plan.mode in {ResumeMode.CHECKPOINT, ResumeMode.RERUN}:
        return mark_plan_fork(plan)
    return plan


class ResumePlanBuilderPort(Protocol):
    def build(self, cursor: CheckpointCursor) -> ResumePlan: ...


class _PlanBuilderDefault:
    def build(self, cursor: CheckpointCursor) -> ResumePlan:
        snapshot = {
            "values": dict(cursor.values),
            "next": list(cursor.next_nodes),
            "checkpoint_kind": cursor.checkpoint_kind,
            "tasks": (
                [{"interrupts": [{"value": dict(cursor.pending_interrupt)}]}]
                if cursor.pending_interrupt is not None
                else []
            ),
            "config": {"configurable": {"checkpoint_id": cursor.checkpoint_id}},
        }
        return build_resume_plan(snapshot, cursor.session_id, ResumeMode.CHECKPOINT)


class ResumeCheckpointCommand(BaseModel):
    """Validate and plan a checkpoint cursor without invoking the runtime."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)
    checkpoint_kind: str = "intermediate"
    values: dict[str, object] = Field(default_factory=dict)
    next_nodes: list[str] = Field(default_factory=list)
    pending_interrupt: dict[str, object] | None = None

    def as_cursor(self) -> CheckpointCursor:
        return CheckpointCursor(
            session_id=self.session_id,
            checkpoint_id=self.checkpoint_id,
            checkpoint_kind=self.checkpoint_kind,
            values=dict(self.values),
            next_nodes=list(self.next_nodes),
            pending_interrupt=(
                dict(self.pending_interrupt)
                if self.pending_interrupt is not None
                else None
            ),
        )


class ResumeCheckpointResult(BaseModel):
    """The auditable plan produced from a checkpoint cursor."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    checkpoint_id: str
    plan: ResumePlan


class ResumeCheckpointService:
    def __init__(self, builder: ResumePlanBuilderPort | None = None) -> None:
        self._builder = builder or _PlanBuilderDefault()

    def execute(self, command: ResumeCheckpointCommand) -> ResumeCheckpointResult:
        plan = self._builder.build(command.as_cursor())
        return ResumeCheckpointResult(
            session_id=command.session_id,
            checkpoint_id=command.checkpoint_id,
            plan=plan,
        )


resume_checkpoint_service = ResumeCheckpointService()


__all__ = [
    "CheckpointCursor",
    "ResumeCheckpointCommand",
    "ResumeCheckpointResult",
    "ResumeCheckpointService",
    "ResumePlanBuilderPort",
    "build_resume_plan",
    "fork_branch_from_plan",
    "resume_checkpoint_service",
]
