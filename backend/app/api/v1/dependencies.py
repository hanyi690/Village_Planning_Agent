"""FastAPI dependency stubs for the stable v1 routers (blueprint M9)."""

from __future__ import annotations

from typing import Annotated, Any, Protocol

from fastapi import Depends


class PlanningRuntime(Protocol):
    """Application-facing runtime boundary used by v1 routers."""

    async def current_values(self, session_id: str) -> dict[str, object] | None: ...

    async def aget_state(self, session_id: str) -> Any | None: ...

    async def resume_interrupt(
        self,
        session_id: str,
        resume_data: dict[str, object],
        *,
        expected_event_id: str,
    ) -> None: ...


class _PlanningRuntimeDefault:
    async def current_values(self, session_id: str) -> dict[str, object] | None:
        from app.services.runtime import PlanningRuntimeService

        return await PlanningRuntimeService.aget_state_values(session_id)

    async def aget_state(self, session_id: str) -> Any | None:
        from app.services.runtime import PlanningRuntimeService

        return await PlanningRuntimeService.aget_state(session_id)

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


def get_planning_runtime() -> PlanningRuntime:
    """Return the lazily-initialized planning runtime adapter."""

    return _PlanningRuntimeDefault()


RuntimeDependency = Annotated[PlanningRuntime, Depends(get_planning_runtime)]


__all__ = ["PlanningRuntime", "RuntimeDependency", "get_planning_runtime"]
