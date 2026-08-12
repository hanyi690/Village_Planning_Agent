"""Application policy for all persisted execution recovery paths.

This module deliberately does not invoke LangGraph.  It owns the decision
about whether a cursor is resumable and which artifacts may be reused; the
runtime owns execution and locking.
"""

from __future__ import annotations

from typing import Any, Dict
from uuid import uuid4

from app.modules.schema.contracts.resume_contracts import (
    ARTIFACT_STAGE_ORDER,
    ResumeMode,
    ResumePlan,
    build_resume_plan,
    repair_plan_for_integrity,
)
from app.services.checkpoint_policy import (
    classify_checkpoint,
    first_pending_interrupt_payload,
    has_pending_interrupt,
)

FORK_BRANCH_MARKER = "fork branch="


def mark_plan_fork(plan: ResumePlan, branch_id: str | None = None) -> ResumePlan:
    """Return a copy of the plan annotated with the required fork branch.

    A plain checkpoint resume must fork the artifact refs into a new branch
    (``fork_artifact_refs``) and must never carry ``Command(resume=...)``.
    The caller reads the branch back with ``fork_branch_from_plan`` and passes
    it to the runtime's fork path.
    """

    branch = branch_id or f"fork-{uuid4().hex[:16]}"
    marker = f"{FORK_BRANCH_MARKER}{branch}"
    reason = f"{plan.reason}; {marker}" if plan.reason else marker
    return plan.model_copy(update={"reason": reason})


def fork_branch_from_plan(plan: ResumePlan) -> str | None:
    """Return the branch_id a plan requires, or None when no fork is marked."""

    idx = plan.reason.find(FORK_BRANCH_MARKER)
    if idx < 0:
        return None
    tail = plan.reason[idx + len(FORK_BRANCH_MARKER):].strip()
    return tail.split(";")[0].strip().split(" ")[0] or None


def plan_blocked(plan: ResumePlan, reason: str) -> ResumePlan:
    """Rebuild the plan as a typed BLOCKED decision with a specific reason."""

    return plan.model_copy(update={"mode": ResumeMode.BLOCKED, "resume_from": "", "reason": reason})


class ResumeConflictError(RuntimeError):
    """The caller supplied a stale or already-consumed resume token."""


class ResumeService:
    """Pure application-level recovery policy shared by API and runtime."""

    @staticmethod
    def plan_for_snapshot(session_id: str, snapshot: Any) -> tuple[bool, str, ResumePlan]:
        values = dict(snapshot.values) if getattr(snapshot, "values", None) else {}
        pending = has_pending_interrupt(snapshot)
        stable, kind = classify_checkpoint(values, pending_interrupt=pending)
        checkpoint_id = (
            getattr(snapshot, "config", {})
            .get("configurable", {})
            .get("checkpoint_id", "")
        )
        plan = build_resume_plan(
            values,
            session_id=session_id,
            checkpoint_id=checkpoint_id,
            checkpoint_kind=kind,
            next_nodes=getattr(snapshot, "next", ()) or (),
            pending_interrupt=first_pending_interrupt_payload(snapshot),
        )
        plan = ResumeService.verify_reusable_artifacts(values, plan)
        return stable, kind, plan

    @staticmethod
    def fork_required(plan: ResumePlan) -> bool:
        """True when a recovery must fork a new artifact branch."""

        return plan.mode in {ResumeMode.CHECKPOINT, ResumeMode.RERUN}

    @staticmethod
    def validate_interrupt(state: Dict[str, Any], expected_event_id: str) -> None:
        interrupt = state.get("human_interrupt") or {}
        if state.get("human_review_resume_consumed"):
            raise ResumeConflictError(
                "human review checkpoint was already resumed; wait for a new HUMAN pause"
            )
        if interrupt.get("event_id") != expected_event_id:
            raise ResumeConflictError(
                "human review event_id does not match the active checkpoint"
            )

    @staticmethod
    def verify_reusable_artifacts(state: Dict[str, Any], plan: ResumePlan) -> ResumePlan:
        """Verify refs before a recovery is allowed to produce output.

        A checkpoint can outlive a local artifact directory or contain a
        corrupted payload.  Treat that as an explicit recovery conflict,
        rather than letting a later node silently rebuild partial state.
        The caller may then choose a deliberate upstream rerun policy.
        """

        from app.infrastructure.artifacts.runtime import load_artifact

        integrity: dict[str, str] = {}
        for key in plan.reuse:
            try:
                payload = load_artifact(state, key)
            except Exception as exc:  # noqa: BLE001 - normalize storage errors
                integrity[key] = f"invalid:{type(exc).__name__}"
                continue
            integrity[key] = "valid" if payload is not None else "missing"

        checked = plan.model_copy(update={"artifact_integrity": integrity})
        invalid = [key for key, status in integrity.items() if status != "valid"]
        return repair_plan_for_integrity(checked, invalid)

    @staticmethod
    def select_replay_snapshot(snapshots: list[Any], plan: ResumePlan) -> Any | None:
        """Select the newest historical cursor at a safe replay boundary."""

        required = set(plan.reuse)
        rerun_keys = {
            key
            for key, stage in ARTIFACT_STAGE_ORDER
            if stage in set(plan.rerun)
        }
        for snapshot in snapshots:
            values = dict(getattr(snapshot, "values", {}) or {})
            refs = dict(values.get("artifact_refs") or {})
            if not required.issubset(refs):
                continue
            stable, kind = classify_checkpoint(
                values,
                pending_interrupt=bool(
                    getattr(snapshot, "tasks", None)
                    and any(getattr(task, "interrupts", None) for task in snapshot.tasks or ())
                ),
            )
            if not stable or kind in {"human", "completed"}:
                continue
            if any(key in refs for key in rerun_keys):
                continue
            if getattr(snapshot, "tasks", None) and any(
                getattr(task, "interrupts", None) for task in snapshot.tasks or ()
            ):
                continue
            return snapshot
        return None


__all__ = [
    "FORK_BRANCH_MARKER",
    "ResumeConflictError",
    "ResumeService",
    "fork_branch_from_plan",
    "mark_plan_fork",
    "plan_blocked",
]
