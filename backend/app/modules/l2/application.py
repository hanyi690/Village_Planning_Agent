"""Public L2 STRATEGIZE facade."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.l1.l1_contracts import L1ObservationSnapshot
from app.contracts.l2.l2_contracts import L2Strategy


class L2RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    context_version: str = Field(min_length=1)
    l1_snapshot_ref: ArtifactRef

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> "L2RunRequest":
        ref = (state.get("artifact_refs") or {}).get("l1_snapshot")
        if not ref:
            raise RuntimeError("L2 requires the canonical l1_snapshot artifact ref")
        return cls(
            run_id=str(state.get("run_id") or state.get("session_id") or ""),
            session_id=str(state.get("session_id") or ""),
            context_version=str(state.get("context_version") or ""),
            l1_snapshot_ref=ArtifactRef.model_validate(ref),
        )


class L2RunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    request: L2RunRequest
    decision_set: L2Strategy
    artifact_ref: ArtifactRef
    gate_ref: ArtifactRef
    review_id: str = ""
    state_patch: dict[str, Any] = Field(default_factory=dict)

    def to_state_patch(self) -> dict[str, Any]:
        patch = dict(self.state_patch)
        patch["artifact_refs"] = {
            **dict(patch.get("artifact_refs") or {}),
            "l2_strategy": self.artifact_ref.model_dump(mode="json"),
            "l2_gate": self.gate_ref.model_dump(mode="json"),
        }
        patch["l2_review_id"] = self.review_id
        return patch


def _reject_executable_fields(decision: L2Strategy) -> None:
    payload = decision.model_dump(mode="json")
    forbidden = {
        "candidate_id", "candidate_ids", "geometry", "scenario_set",
        "approved_execution_input", "execution_plan", "planned_state",
    }

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).casefold() in forbidden:
                    raise RuntimeError(f"L2 decision contains forbidden field: {key}")
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    if decision.development_goals:
        raise RuntimeError("L2 decision contains planning goals")
    if any(item.kind == "goal" or item.target_year for item in decision.objectives):
        raise RuntimeError("L2 decision contains target-like objective content")
    if any(item.value is not None or item.target_year for item in decision.metrics):
        raise RuntimeError("L2 decision contains target metric values")
    if any(item.target_refs for item in decision.strategy_rules):
        raise RuntimeError("L2 decision contains planning target refs")


class L2Application:
    """Load L1 by ref, run the real L2 aggregate, then reload its artifact."""

    @staticmethod
    def load_l1(state: Mapping[str, Any]) -> L1ObservationSnapshot:
        from app.infrastructure.artifacts.runtime import load_artifact

        snapshot = load_artifact(dict(state), "l1_snapshot", L1ObservationSnapshot)
        if snapshot is None:
            raise RuntimeError("L2 cannot proceed without a reloaded L1ObservationSnapshot")
        return snapshot

    @staticmethod
    def load(state: Mapping[str, Any]) -> L2Strategy | None:
        from app.infrastructure.artifacts.runtime import load_artifact

        return load_artifact(dict(state), "l2_strategy", L2Strategy)

    async def run(self, state: Mapping[str, Any]) -> L2RunResult:
        request = L2RunRequest.from_state(state)
        from app.workflow.stages.support import require_upstream_gates

        require_upstream_gates(dict(state), ("data", "kg", "evidence", "l1"))
        from app.infrastructure.artifacts.runtime import (
            validate_l1_world_projection_transition,
        )

        projection = validate_l1_world_projection_transition(dict(state))
        if projection.status != "ready":
            raise RuntimeError(
                "L2 cannot consume a partial L1 World projection"
            )
        snapshot = self.load_l1(state)
        from app.infrastructure.artifacts.runtime import (
            validate_artifact_context_with_l1_transition,
        )

        validate_artifact_context_with_l1_transition(
            dict(state),
            "l1_snapshot",
            request.l1_snapshot_ref,
        )
        if snapshot.context_version != request.context_version:
            raise RuntimeError("L2 input L1ObservationSnapshot context version mismatch")
        from .aggregation import l2_aggregate

        patch = dict(await l2_aggregate(dict(state)))
        refs = {
            **dict(state.get("artifact_refs") or {}),
            **dict(patch.get("artifact_refs") or {}),
        }
        replay_state = {**dict(state), **patch, "artifact_refs": refs}
        decision = self.load(replay_state)
        if decision is None:
            raise RuntimeError("L2 aggregate did not commit l2_strategy")
        validate_artifact_context(
            replay_state,
            "l2_strategy",
            refs.get("l2_strategy"),
        )
        _reject_executable_fields(decision)
        return L2RunResult(
            request=request,
            decision_set=decision,
            artifact_ref=ArtifactRef.model_validate(refs["l2_strategy"]),
            gate_ref=ArtifactRef.model_validate(refs["l2_gate"]),
            review_id=str(patch.get("l2_review_id") or ""),
            state_patch=patch,
        )


async def run_l2(state: Mapping[str, Any]) -> L2RunResult:
    return await L2Application().run(state)


async def analyze_l2_dimension(state: Mapping[str, Any]) -> dict[str, Any]:
    from app.workflow.stages.support import require_upstream_gates

    require_upstream_gates(dict(state), ("data", "kg", "evidence", "l1"))
    from app.infrastructure.artifacts.runtime import (
        validate_l1_world_projection_transition,
    )

    projection = validate_l1_world_projection_transition(dict(state))
    if projection.status != "ready":
        raise RuntimeError(
            "L2 dimension cannot consume a partial L1 World projection"
        )
    from .reasoning import analyze_l2_dimension as run_dimension

    result = await run_dimension(dict(state))
    from app.infrastructure.artifacts.dimension_runtime import (
        ensure_dimension_product_patch,
    )

    return ensure_dimension_product_patch(state, result, layer=2)


__all__ = [
    "L2Application",
    "L2RunRequest",
    "L2RunResult",
    "analyze_l2_dimension",
    "run_l2",
]
