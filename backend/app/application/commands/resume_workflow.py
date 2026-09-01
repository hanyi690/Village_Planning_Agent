"""Application command for resuming a persisted planning workflow.

The API owns only transport validation and projection.  This module owns the
resume use case: reading the requested checkpoint, applying the persisted
checkpoint policy, and handing an approved cursor to the runtime port.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.workflow.resume_contracts import (
    ResumeCommand,
    ResumeMode,
    ResumePlan,
)
from app.application.recovery.resume_service import ResumeConflictError, ResumeService


class ResumeRequestError(ValueError):
    """The command is not a valid interrupt or checkpoint request."""


class ResumeNotFoundError(LookupError):
    """The session or requested historical checkpoint does not exist."""


class ResumeRuntimePort(Protocol):
    """Runtime operations required by the resume use case."""

    async def current_snapshot(self, session_id: str) -> Any | None: ...

    async def checkpoint_snapshot(self, session_id: str, checkpoint_id: str) -> Any | None: ...

    async def resume_interrupt(
        self,
        session_id: str,
        resume_data: dict[str, Any],
        *,
        expected_event_id: str,
    ) -> None: ...

    async def fork_checkpoint(
        self,
        session_id: str,
        *,
        checkpoint_id: str,
        state_values: dict[str, Any],
        replay_from_stage: str | None,
        branch_id: str,
    ) -> None: ...


class PlanningRuntimeResumePort:
    """Adapter that keeps LangGraph/task-supervisor details out of the API."""

    async def current_snapshot(self, session_id: str) -> Any | None:
        from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

        return await PlanningRuntimeService.aget_state(session_id)

    async def checkpoint_snapshot(self, session_id: str, checkpoint_id: str) -> Any | None:
        from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

        await PlanningRuntimeService.ensure_initialized()
        graph = PlanningRuntimeService.get_graph()
        if graph is None:
            raise RuntimeError("planning runtime graph is not initialized")
        return await graph.aget_state(
            PlanningRuntimeService.get_thread_config(
                session_id,
                checkpoint_id=checkpoint_id,
            )
        )

    async def resume_interrupt(
        self,
        session_id: str,
        resume_data: dict[str, Any],
        *,
        expected_event_id: str,
    ) -> None:
        from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

        await PlanningRuntimeService.resume_from_interrupt(
            session_id,
            resume_data,
            expected_event_id=expected_event_id,
        )

    async def fork_checkpoint(
        self,
        session_id: str,
        *,
        checkpoint_id: str,
        state_values: dict[str, Any],
        replay_from_stage: str | None,
        branch_id: str,
    ) -> None:
        from app.bootstrap.composition import CompositionRoot
        from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

        await PlanningRuntimeService.ensure_initialized()
        CompositionRoot.get_task_supervisor().create_task(
            session_id,
            PlanningRuntimeService.trigger_planning_execution(
                session_id,
                checkpoint_id=checkpoint_id,
                state_values=state_values,
                replay_from_stage=replay_from_stage,
                branch_id=branch_id,
            ),
        )


class ResumeWorkflowCommand(BaseModel):
    """Transport-independent command for the two supported resume modes."""

    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(default_factory=lambda: f"resume-{uuid4().hex}", min_length=1)
    session_id: str = Field(min_length=1)
    mode: Literal["interrupt", "checkpoint"]
    event_id: str | None = None
    action: Literal["retry", "approve", "reject"] | None = None
    feedback: str = ""
    checkpoint_id: str | None = None
    replay_from_stage: str | None = None

    def as_policy_command(self) -> ResumeCommand:
        """Expose the canonical resume contract to policy/audit code."""

        return ResumeCommand(
            command_id=self.command_id,
            session_id=self.session_id,
            mode=(
                ResumeMode.INTERRUPT
                if self.mode == "interrupt"
                else ResumeMode.CHECKPOINT
            ),
            checkpoint_id=self.checkpoint_id,
            event_id=self.event_id,
            payload={
                "action": self.action,
                "feedback": self.feedback,
                "replay_from_stage": self.replay_from_stage,
            },
        )


class ResumeWorkflowResult(BaseModel):
    """Application result later projected into the public API DTO."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    mode: Literal["interrupt", "checkpoint"]
    status: Literal["resumed", "accepted"]
    checkpoint_id: str = ""
    branch_id: str = ""
    event_id: str | None = None
    resume_plan: ResumePlan


def _snapshot_checkpoint_id(snapshot: Any) -> str:
    config = getattr(snapshot, "config", {}) or {}
    configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
    return str(configurable.get("checkpoint_id") or "")


class ResumeWorkflowService:
    """Execute resume policy against a runtime port."""

    def __init__(self, runtime: ResumeRuntimePort | None = None) -> None:
        self._runtime = runtime or PlanningRuntimeResumePort()

    async def execute(self, command: ResumeWorkflowCommand) -> ResumeWorkflowResult:
        # Materialize the canonical command before touching the runtime.  This
        # keeps the persisted ResumePlan/CAS semantics in one application use
        # case rather than allowing each transport to reinterpret the fields.
        command.as_policy_command()
        if command.mode == "interrupt":
            return await self._resume_interrupt(command)
        return await self._fork_checkpoint(command)

    async def _resume_interrupt(
        self,
        command: ResumeWorkflowCommand,
    ) -> ResumeWorkflowResult:
        if not command.event_id or not command.action:
            raise ResumeRequestError(
                "interrupt resume requires event_id and action"
            )
        snapshot = await self._runtime.current_snapshot(command.session_id)
        if not snapshot:
            raise ResumeNotFoundError("session not found")
        stable, kind, plan = ResumeService.plan_for_snapshot(
            command.session_id,
            snapshot,
        )
        if not stable or kind != "human":
            raise ResumeConflictError("session has no active HUMAN checkpoint")
        await self._runtime.resume_interrupt(
            command.session_id,
            {"action": command.action, "feedback": command.feedback},
            expected_event_id=command.event_id,
        )
        return ResumeWorkflowResult(
            session_id=command.session_id,
            mode="interrupt",
            status="resumed",
            checkpoint_id=_snapshot_checkpoint_id(snapshot),
            event_id=command.event_id,
            resume_plan=plan,
        )

    async def _fork_checkpoint(
        self,
        command: ResumeWorkflowCommand,
    ) -> ResumeWorkflowResult:
        if not command.checkpoint_id:
            raise ResumeRequestError("checkpoint resume requires checkpoint_id")
        snapshot = await self._runtime.checkpoint_snapshot(
            command.session_id,
            command.checkpoint_id,
        )
        if not snapshot or not getattr(snapshot, "values", None):
            raise ResumeNotFoundError("checkpoint not found")
        stable, kind, plan = ResumeService.plan_for_snapshot(
            command.session_id,
            snapshot,
        )
        requested_stage = str(command.replay_from_stage or "").strip().lower()
        if requested_stage and requested_stage != "data" and requested_stage not in {
            "target_projection",
            "ground",
            "select",
            "execute",
            "validate",
            "reconcile",
            "deliver",
        }:
            raise ResumeConflictError(
                f"unsupported replay stage: {command.replay_from_stage!r}"
            )
        diagnostic_code = None
        if isinstance(snapshot.values, dict):
            diagnostic = snapshot.values.get("diagnostic_terminal") or {}
            terminal_ref = snapshot.values.get("terminal_ref") or {}
            if isinstance(diagnostic, dict):
                diagnostic_code = diagnostic.get("code")
            if not diagnostic_code and isinstance(terminal_ref, dict):
                nested = terminal_ref.get("diagnostic") or {}
                diagnostic_code = (
                    nested.get("code") if isinstance(nested, dict) else None
                ) or terminal_ref.get("code")
        replayable_diagnostic = diagnostic_code in {
            "STALE_CHECKPOINT_NO_EXECUTABLE_CURSOR",
            # Older runtime versions persisted an unauthorized transition as
            # a terminal.  It has no executable cursor, but its upstream
            # artifacts remain a valid explicit replay prefix.
            "UNAUTHORIZED_STAGE",
        }
        data_replay = requested_stage == "data"
        if data_replay:
            plan = ResumeService.explicit_data_replay_plan(
                dict(snapshot.values),
                plan,
            )
        stale_replay = (
            bool(command.replay_from_stage)
            and not data_replay
            and replayable_diagnostic
        )
        if stale_replay:
            plan = ResumeService.explicit_spatial_replay_plan(
                dict(snapshot.values),
                plan,
                command.replay_from_stage or "",
            )
        if (
            (not stable and not stale_replay and not data_replay)
            or kind == "human"
            or plan.mode is ResumeMode.BLOCKED
        ):
            raise ResumeConflictError(
                f"checkpoint cannot be forked: {plan.reason}"
            )
        branch_id = f"fork-{uuid4().hex[:16]}"
        await self._runtime.fork_checkpoint(
            command.session_id,
            checkpoint_id=command.checkpoint_id,
            state_values=dict(snapshot.values),
            replay_from_stage=("data" if data_replay else command.replay_from_stage),
            branch_id=branch_id,
        )
        return ResumeWorkflowResult(
            session_id=command.session_id,
            mode="checkpoint",
            status="accepted",
            checkpoint_id=command.checkpoint_id,
            branch_id=branch_id,
            resume_plan=plan,
        )


resume_workflow_service = ResumeWorkflowService()


__all__ = [
    "PlanningRuntimeResumePort",
    "ResumeConflictError",
    "ResumeNotFoundError",
    "ResumeRequestError",
    "ResumeRuntimePort",
    "ResumeWorkflowCommand",
    "ResumeWorkflowResult",
    "ResumeWorkflowService",
    "resume_workflow_service",
]
