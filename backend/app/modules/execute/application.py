"""Public EXECUTE facade around the approval-bound materialization stage."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.execute.execution_plan_contracts import ExecutionResult


class ExecuteRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    context_version: str = Field(min_length=1)
    approved_execution_input_ref: ArtifactRef
    execution_plan_ref: ArtifactRef

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> "ExecuteRunRequest":
        refs = state.get("artifact_refs") or {}
        if not refs.get("approved_execution_input"):
            raise RuntimeError("EXECUTE requires approved_execution_input")
        if not refs.get("execution_plan"):
            raise RuntimeError("EXECUTE requires execution_plan")
        return cls(
            run_id=str(state.get("run_id") or state.get("session_id") or ""),
            session_id=str(state.get("session_id") or ""),
            context_version=str(state.get("context_version") or ""),
            approved_execution_input_ref=ArtifactRef.model_validate(refs["approved_execution_input"]),
            execution_plan_ref=ArtifactRef.model_validate(refs["execution_plan"]),
        )


class ExecuteRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    request: ExecuteRunRequest
    execution_result: ExecutionResult | None = None
    artifact_refs: dict[str, ArtifactRef] = Field(default_factory=dict)

    def to_state_patch(self) -> dict[str, Any]:
        return {"artifact_refs": {key: value.model_dump(mode="json") for key, value in self.artifact_refs.items()}}


class ExecuteApplication:
    """Run EXECUTE and reload its immutable result when committed."""

    @staticmethod
    def load(state: Mapping[str, Any]) -> ExecutionResult | None:
        from app.infrastructure.artifacts.runtime import load_artifact

        return load_artifact(dict(state), "execution_result", ExecutionResult)

    async def run(self, state: Mapping[str, Any]) -> ExecuteRunResult:
        request = ExecuteRunRequest.from_state(state)
        from .stage import execute_node

        patch = dict(await execute_node(dict(state)))
        refs = {**dict(state.get("artifact_refs") or {}), **dict(patch.get("artifact_refs") or {})}
        return ExecuteRunResult(
            request=request,
            execution_result=self.load({**dict(state), **patch, "artifact_refs": refs}),
            artifact_refs={key: ArtifactRef.model_validate(value) for key, value in refs.items() if value},
        )


async def run_execute(state: Mapping[str, Any]) -> ExecuteRunResult:
    return await ExecuteApplication().run(state)


async def run_execute_stage(state: Mapping[str, Any]) -> dict[str, Any]:
    """Workflow adapter that keeps EXECUTE orchestration behind its facade."""

    from .stage import execute_node

    return dict(await execute_node(dict(state)))


__all__ = [
    "ExecuteApplication",
    "ExecuteRunRequest",
    "ExecuteRunResult",
    "run_execute",
    "run_execute_stage",
]
