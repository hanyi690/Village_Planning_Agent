"""Typed compare-and-set command for HUMAN review decisions."""

from __future__ import annotations

import logging

from typing import Literal, Mapping, Protocol

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.application.recovery.resume_service import ResumeConflictError
from app.application.unit_of_work import RuntimePort

logger = logging.getLogger(__name__)


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
        from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

        return await PlanningRuntimeService.aget_state_values(session_id)

    async def resume_interrupt(
        self,
        session_id: str,
        resume_data: dict[str, object],
        *,
        expected_event_id: str,
    ) -> None:
        from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

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
        if current.get("human_review_resume_consumed") and not interrupt:
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


class ResolveRequest(BaseModel):
    """Canonical decision submitted for the active HUMAN checkpoint."""

    decisions: dict[str, object] = Field(..., min_length=1)
    action: str | None = Field(
        None,
        pattern="^(retry|accept|reject|approve)$",
        description="审查动作: retry/accept(approve)/reject",
    )
    event_id: str | None = Field(None, description="HUMAN checkpoint 幂等键")

    @model_validator(mode="after")
    def populate_action(self) -> ResolveRequest:
        if self.action is None:
            self.action = self.decisions.get("action")
        if self.action is None:
            raise ValueError("action is required")
        if self.action not in {"retry", "accept", "reject", "approve"}:
            raise ValueError(f"unsupported action: {self.action!r}")
        if self.action == "accept":
            self.action = "approve"
        self.decisions.setdefault("action", self.action)
        if self.decisions.get("action") == "accept":
            self.decisions["action"] = "approve"
        return self


async def resolve_human_review(
    session_id: str,
    request: ResolveRequest,
) -> dict[str, object]:
    """Submit the decision and resume the exact active checkpoint."""
    try:
        from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

        current = await PlanningRuntimeService.aget_state_values(session_id) or {}
        current_interrupt = current.get("human_interrupt") or {}
        if request.event_id and request.event_id != current_interrupt.get("event_id"):
            raise HTTPException(status_code=409, detail="event_id does not match active checkpoint")
        if current.get("human_review_resume_consumed") and not current_interrupt:
            raise HTTPException(status_code=409, detail="checkpoint was already resumed")
        await PlanningRuntimeService.resume_from_interrupt(
            session_id,
            request.decisions,
            expected_event_id=request.event_id,
        )
        resumed = await PlanningRuntimeService.aget_state_values(session_id) or {}
        result = {
            "phase": resumed.get("phase"),
            "paused_stage": resumed.get("paused_stage"),
            "delivery_status": resumed.get("delivery_status"),
            "human_review_event_id": resumed.get("human_review_event_id"),
        }
    except ResumeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[human-review] resolve failed for %s (exception_type=%s)",
            session_id,
            type(exc).__name__,
        )
        raise HTTPException(status_code=500, detail="Resume failed") from exc
    return {"session_id": session_id, "resolved": True, "result": result}


__all__ = [
    "HumanDecisionConflictError",
    "HumanDecisionNotFoundError",
    "ResolveRequest",
    "SubmitHumanDecisionCommand",
    "SubmitHumanDecisionResult",
    "SubmitHumanDecisionService",
    "resolve_human_review",
    "submit_human_decision_service",
]
