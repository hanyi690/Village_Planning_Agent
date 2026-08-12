"""Typed create-session use case for the stable API."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Mapping, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.application.unit_of_work import (
    PlanningStarterPort,
    SessionRepositoryPort,
    UploadIngestionPort,
)


class CreateSessionError(RuntimeError):
    """The session could not be created and its database row was cleaned up."""


class CreateSessionValidationError(ValueError):
    """The create command is invalid before workflow startup."""


class CreateSessionCommand:
    """All transport-independent inputs needed to create a planning run."""

    def __init__(
        self,
        *,
        project_name: str,
        village_name: str = "",
        province: str = "",
        city: str = "",
        county: str = "",
        township: str = "",
        planning_period: str = "2022-2035年",
        task_description: str = "制定村庄发展规划",
        constraints: str = "无特殊约束",
        step_mode: bool = False,
        rag_enabled: bool | None = None,
        rag_layer_config: Mapping[int, bool] | None = None,
        village_data: str = "",
        village_data_files: tuple[object, ...] = (),
        task_files: tuple[object, ...] = (),
        constraint_files: tuple[object, ...] = (),
        session_id: str | None = None,
    ) -> None:
        self.project_name = project_name
        self.village_name = village_name
        self.province = province
        self.city = city
        self.county = county
        self.township = township
        self.planning_period = planning_period
        self.task_description = task_description
        self.constraints = constraints
        self.step_mode = step_mode
        self.rag_enabled = rag_enabled
        self.rag_layer_config = dict(rag_layer_config or {})
        self.village_data = village_data
        self.village_data_files = village_data_files
        self.task_files = task_files
        self.constraint_files = constraint_files
        self.session_id = session_id or str(uuid4())

    def validate(self) -> None:
        if not self.project_name.strip():
            raise CreateSessionValidationError("项目名称不能为空")


class CreateSessionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    stream_url: str
    status: str = "running"


class _PlanningStarter(Protocol):
    async def start(self, session_id: str, initial_state: dict[str, object]) -> None: ...


class _SessionDefaults:
    async def create(self, values: Mapping[str, object]) -> str:
        from app.database.operations import create_planning_session_async

        return await create_planning_session_async(dict(values))

    async def update(self, session_id: str, values: Mapping[str, object]) -> None:
        from app.database.operations import update_planning_session_async

        await update_planning_session_async(session_id, dict(values))

    async def delete(self, session_id: str) -> None:
        from app.database.operations import delete_planning_session_async

        await delete_planning_session_async(session_id)


class _IngestionDefault:
    async def process(self, file: object, session_id: str, category: str) -> Mapping[str, object]:
        from app.data.ingestion.upload import process_uploaded_file

        return await process_uploaded_file(file, session_id, category)


class _StarterDefault:
    async def start(self, session_id: str, initial_state: Mapping[str, object]) -> None:
        from app.infrastructure.events import event_hub
        from app.bootstrap.composition import CompositionRoot
        from app.services.runtime import PlanningRuntimeService

        await PlanningRuntimeService.ensure_initialized()
        await event_hub.publish(
            session_id,
            {
                "type": "layer_started",
                "layer": 1,
                "layer_name": "现状认知",
                "dimension_count": 0,
            },
        )
        CompositionRoot.get_task_supervisor().create_task(
            session_id,
            PlanningRuntimeService._trigger_planning_execution(
                session_id,
                dict(initial_state),
            ),
        )


def _default_state(command: CreateSessionCommand) -> dict[str, object]:
    from app.workflow.plan_state.state_factory import StateFactory

    return StateFactory.create(
        project_name=command.project_name,
        village_name=command.village_name,
        province=command.province,
        city=command.city,
        county=command.county,
        township=command.township,
        planning_period=command.planning_period,
        session_id=command.session_id,
        stream_mode=True,
        step_mode=command.step_mode,
        rag_enabled=command.rag_enabled,
        rag_layer_config=dict(command.rag_layer_config) or None,
    )


class CreateSessionService:
    """Coordinate persistence, ingestion, state creation, and startup."""

    def __init__(
        self,
        *,
        sessions: SessionRepositoryPort | None = None,
        ingestion: UploadIngestionPort | None = None,
        starter: PlanningStarterPort | None = None,
        state_factory: Callable[[CreateSessionCommand], dict[str, object]] = _default_state,
    ) -> None:
        self._sessions = sessions or _SessionDefaults()
        self._ingestion = ingestion or _IngestionDefault()
        self._starter = starter or _StarterDefault()
        self._state_factory = state_factory

    async def execute(self, command: CreateSessionCommand) -> CreateSessionResult:
        command.validate()
        parsed_content = command.village_data
        task_description = command.task_description
        constraints = command.constraints
        created = False
        try:
            await self._sessions.create(
                {
                    "session_id": command.session_id,
                    "project_name": command.project_name,
                    "village_name": command.village_name,
                    "province": command.province,
                    "city": command.city,
                    "county": command.county,
                    "township": command.township,
                    "planning_period": command.planning_period,
                    "village_data": command.village_data,
                    "task_description": task_description,
                    "constraints": constraints,
                }
            )
            created = True
            for files, category in (
                (command.village_data_files, "village_data"),
                (command.task_files, "task_description"),
                (command.constraint_files, "constraint"),
            ):
                for file in files:
                    result = await self._ingestion.process(file, command.session_id, category)
                    parsed_text = str(result.get("parsed_text") or "")
                    if category == "village_data" and parsed_text:
                        parsed_content += f"\n\n--- 村庄数据: {result.get('filename', 'upload')} ---\n{parsed_text}"
                    elif category == "task_description" and parsed_text:
                        task_description = parsed_text.strip()
                    elif category == "constraint" and parsed_text:
                        constraints = parsed_text.strip()
            if len(parsed_content.strip()) < 10:
                raise CreateSessionValidationError("村庄数据不能为空或过短")
            await self._sessions.update(
                command.session_id,
                {
                    "village_data": parsed_content,
                    "task_description": task_description,
                    "constraints": constraints,
                },
            )
            await self._starter.start(command.session_id, self._state_factory(command))
            return CreateSessionResult(
                session_id=command.session_id,
                stream_url=f"/api/v1/sessions/{command.session_id}/events",
            )
        except CreateSessionValidationError:
            if created:
                await self._sessions.delete(command.session_id)
            raise
        except Exception as exc:
            if created:
                await self._sessions.delete(command.session_id)
            raise CreateSessionError(str(exc)) from exc


create_session_service = CreateSessionService()


__all__ = [
    "CreateSessionCommand",
    "CreateSessionError",
    "CreateSessionResult",
    "CreateSessionService",
    "CreateSessionValidationError",
    "create_session_service",
]
