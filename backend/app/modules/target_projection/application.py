"""Public TARGET_PROJECTION facade."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.l3.l3_contracts import PlanningProgram
from app.contracts.target_projection.parse_result_contracts import IntentCompilationResult


class TargetProjectionRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    context_version: str = Field(min_length=1)
    planning_program_ref: ArtifactRef

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> "TargetProjectionRunRequest":
        ref = (state.get("artifact_refs") or {}).get("planning_program")
        if not ref:
            raise RuntimeError(
                "TARGET_PROJECTION requires the canonical planning_program artifact ref"
            )
        return cls(
            run_id=str(state.get("run_id") or state.get("session_id") or ""),
            session_id=str(state.get("session_id") or ""),
            context_version=str(state.get("context_version") or ""),
            planning_program_ref=ArtifactRef.model_validate(ref),
        )


class TargetProjectionRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    request: TargetProjectionRunRequest
    compilation: IntentCompilationResult
    artifact_ref: ArtifactRef
    gate_ref: ArtifactRef

    def to_state_patch(self) -> dict[str, Any]:
        return {
            "artifact_refs": {
                "target_projection": self.artifact_ref.model_dump(mode="json"),
                "target_projection_gate": self.gate_ref.model_dump(mode="json"),
            }
        }


class TargetProjectionApplication:
    """Execute the stage adapter, then reload the immutable projection."""

    @staticmethod
    def load_program(state: Mapping[str, Any]) -> PlanningProgram:
        from app.infrastructure.artifacts.runtime import load_artifact

        program = load_artifact(dict(state), "planning_program", PlanningProgram)
        if program is None:
            raise RuntimeError("TARGET_PROJECTION cannot proceed without PlanningProgram")
        return program

    @staticmethod
    def load(state: Mapping[str, Any]) -> IntentCompilationResult:
        from app.infrastructure.artifacts.runtime import load_artifact

        result = load_artifact(dict(state), "target_projection", IntentCompilationResult)
        if result is None:
            raise RuntimeError("TARGET_PROJECTION did not commit IntentCompilationResult")
        return result

    async def run(self, state: Mapping[str, Any]) -> TargetProjectionRunResult:
        request = TargetProjectionRunRequest.from_state(state)
        program = self.load_program(state)
        if program.context_version != request.context_version:
            raise RuntimeError("TARGET_PROJECTION input PlanningProgram context mismatch")
        from .stage import target_projection_node

        patch = dict(await target_projection_node(dict(state)))
        refs = {**dict(state.get("artifact_refs") or {}), **dict(patch.get("artifact_refs") or {})}
        result = self.load({**dict(state), **patch, "artifact_refs": refs})
        return TargetProjectionRunResult(
            request=request,
            compilation=result,
            artifact_ref=ArtifactRef.model_validate(refs["target_projection"]),
            gate_ref=ArtifactRef.model_validate(refs["target_projection_gate"]),
        )


async def run_target_projection(state: Mapping[str, Any]) -> TargetProjectionRunResult:
    return await TargetProjectionApplication().run(state)


async def run_target_projection_stage(state: Mapping[str, Any]) -> dict[str, Any]:
    """Workflow adapter that keeps stage orchestration behind this facade."""

    from .stage import target_projection_node

    return dict(await target_projection_node(dict(state)))


__all__ = [
    "TargetProjectionApplication",
    "TargetProjectionRunRequest",
    "TargetProjectionRunResult",
    "run_target_projection",
    "run_target_projection_stage",
]
