"""Typed compare-and-set command for HUMAN review decisions."""

from __future__ import annotations

from typing import Literal, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.application.unit_of_work import RuntimePort


class HumanDecisionConflictError(RuntimeError):
    """The active HUMAN checkpoint changed or was already consumed."""


class HumanDecisionNotFoundError(LookupError):
    """No checkpoint exists for the requested session."""


class SubmitHumanDecisionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    action: Literal["retry", "approve", "reject"]
    decisions: dict[str, object] = Field(default_factory=dict)


class SubmitHumanDecisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    resolved: bool = True
    result: dict[str, object] = Field(default_factory=dict)


class HumanDecisionRuntimePort(RuntimePort, Protocol):
    pass


class _RuntimeDefault:
    async def current_values(self, session_id: str) -> dict[str, object] | None:
        from app.services.runtime import PlanningRuntimeService

        return await PlanningRuntimeService.aget_state_values(session_id)

    async def resume_interrupt(
        self,
        session_id: str,
        resume_data: dict[str, object],
        *,
        expected_event_id: str,
    ) -> None:
        from app.services.runtime import PlanningRuntimeService

        await PlanningRuntimeService.resume_from_interrupt(
            session_id,
            resume_data,
            expected_event_id=expected_event_id,
        )


class SubmitHumanDecisionService:
    def __init__(self, runtime: HumanDecisionRuntimePort | None = None) -> None:
        self._runtime = runtime or _RuntimeDefault()

    async def execute(self, command: SubmitHumanDecisionCommand) -> SubmitHumanDecisionResult:
        current = await self._runtime.current_values(command.session_id)
        if not current:
            raise HumanDecisionNotFoundError("session not found")
        interrupt = current.get("human_interrupt")
        active_event_id = interrupt.get("event_id") if isinstance(interrupt, dict) else None
        if active_event_id != command.event_id:
            raise HumanDecisionConflictError("event_id does not match active checkpoint")
        if current.get("human_review_resume_consumed"):
            raise HumanDecisionConflictError("checkpoint was already resumed")
        resume_data = dict(command.decisions)
        resume_data["action"] = command.action
        await self._runtime.resume_interrupt(
            command.session_id,
            resume_data,
            expected_event_id=command.event_id,
        )
        resumed = await self._runtime.current_values(command.session_id) or {}
        return SubmitHumanDecisionResult(
            session_id=command.session_id,
            result={
                "phase": resumed.get("phase"),
                "paused_stage": resumed.get("paused_stage"),
                "delivery_status": resumed.get("delivery_status"),
                "human_review_event_id": resumed.get("human_review_event_id"),
            },
        )


submit_human_decision_service = SubmitHumanDecisionService()


__all__ = [
    "HumanDecisionConflictError",
    "HumanDecisionNotFoundError",
    "SubmitHumanDecisionCommand",
    "SubmitHumanDecisionResult",
    "SubmitHumanDecisionService",
    "submit_human_decision_service",
]
