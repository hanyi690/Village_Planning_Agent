"""Public SELECT facade around the production scenario solver."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.select.scenario import ScenarioSet
from app.contracts.target_projection.parse_result_contracts import IntentCompilationResult


class SelectRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    context_version: str = Field(min_length=1)
    target_projection_ref: ArtifactRef
    grounding_result_ref: ArtifactRef

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> "SelectRunRequest":
        refs = state.get("artifact_refs") or {}
        if not refs.get("target_projection"):
            raise RuntimeError("SELECT requires the canonical target_projection artifact ref")
        if not refs.get("grounding_result"):
            raise RuntimeError("SELECT requires the canonical grounding_result artifact ref")
        return cls(
            run_id=str(state.get("run_id") or state.get("session_id") or ""),
            session_id=str(state.get("session_id") or ""),
            context_version=str(state.get("context_version") or ""),
            target_projection_ref=ArtifactRef.model_validate(refs["target_projection"]),
            grounding_result_ref=ArtifactRef.model_validate(refs["grounding_result"]),
        )


class SelectRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    request: SelectRunRequest
    scenario_set: ScenarioSet | None = None
    artifact_refs: dict[str, ArtifactRef] = Field(default_factory=dict)
    gate_ref: ArtifactRef

    def to_state_patch(self) -> dict[str, Any]:
        return {"artifact_refs": {key: value.model_dump(mode="json") for key, value in self.artifact_refs.items()}}


class SelectApplication:
    """Run SELECT and reload its canonical scenario artifact when available."""

    @staticmethod
    def load_grounding(state: Mapping[str, Any]) -> Any:
        from app.infrastructure.artifacts.runtime import load_artifact
        from app.contracts.ground.grounding_contracts import GroundingResult

        return load_artifact(dict(state), "grounding_result", GroundingResult)

    @staticmethod
    def load_projection(state: Mapping[str, Any]) -> IntentCompilationResult:
        from app.infrastructure.artifacts.runtime import load_artifact

        result = load_artifact(dict(state), "target_projection", IntentCompilationResult)
        if result is None:
            raise RuntimeError("SELECT cannot proceed without target projection")
        return result

    @staticmethod
    def load_scenario_set(state: Mapping[str, Any]) -> ScenarioSet | None:
        """Reload the canonical ScenarioSet when SELECT produced one."""

        from app.infrastructure.artifacts.runtime import load_artifact

        return load_artifact(dict(state), "scenario_set", ScenarioSet)

    async def run(self, state: Mapping[str, Any]) -> SelectRunResult:
        request = SelectRunRequest.from_state(state)
        self.load_projection(state)
        self.load_grounding(state)
        from .stage import select_node

        patch = dict(await select_node(dict(state)))
        refs = {**dict(state.get("artifact_refs") or {}), **dict(patch.get("artifact_refs") or {})}
        scenario = None
        if refs.get("scenario_set"):
            scenario = self.load_scenario_set(
                {**dict(state), **patch, "artifact_refs": refs}
            )
        return SelectRunResult(
            request=request,
            scenario_set=scenario,
            artifact_refs={key: ArtifactRef.model_validate(value) for key, value in refs.items() if value},
            gate_ref=ArtifactRef.model_validate(refs["select_gate"]),
        )


async def run_select(state: Mapping[str, Any]) -> SelectRunResult:
    return await SelectApplication().run(state)


async def run_select_stage(state: Mapping[str, Any]) -> dict[str, Any]:
    """Workflow adapter that keeps SELECT orchestration behind its facade."""

    from .stage import select_node

    return dict(await select_node(dict(state)))


__all__ = [
    "SelectApplication",
    "SelectRunRequest",
    "SelectRunResult",
    "run_select",
    "run_select_stage",
]
