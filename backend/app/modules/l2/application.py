"""Public L2 STRATEGIZE facade."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.l1.l1_contracts import L1Snapshot
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

    def to_state_patch(self) -> dict[str, Any]:
        return {
            "artifact_refs": {
                "l2_strategy": self.artifact_ref.model_dump(mode="json"),
                "l2_gate": self.gate_ref.model_dump(mode="json"),
            },
            "l2_review_id": self.review_id,
        }


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


class L2Application:
    """Load L1 by ref, run the real L2 aggregate, then reload its artifact."""

    @staticmethod
    def load_l1(state: Mapping[str, Any]) -> L1Snapshot:
        from app.infrastructure.artifacts.runtime import load_artifact

        snapshot = load_artifact(dict(state), "l1_snapshot", L1Snapshot)
        if snapshot is None:
            raise RuntimeError("L2 cannot proceed without a reloaded L1Snapshot")
        return snapshot

    @staticmethod
    def load(state: Mapping[str, Any]) -> L2Strategy | None:
        from app.infrastructure.artifacts.runtime import load_artifact

        return load_artifact(dict(state), "l2_strategy", L2Strategy)

    async def run(self, state: Mapping[str, Any]) -> L2RunResult:
        request = L2RunRequest.from_state(state)
        snapshot = self.load_l1(state)
        if snapshot.context_version != request.context_version:
            raise RuntimeError("L2 input L1Snapshot context version mismatch")
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
        _reject_executable_fields(decision)
        return L2RunResult(
            request=request,
            decision_set=decision,
            artifact_ref=ArtifactRef.model_validate(refs["l2_strategy"]),
            gate_ref=ArtifactRef.model_validate(refs["l2_gate"]),
            review_id=str(patch.get("l2_review_id") or ""),
        )


async def run_l2(state: Mapping[str, Any]) -> L2RunResult:
    return await L2Application().run(state)


async def analyze_l2_dimension(state: Mapping[str, Any]) -> dict[str, Any]:
    from .reasoning import analyze_l2_dimension as run_dimension

    return await run_dimension(dict(state))


__all__ = [
    "L2Application",
    "L2RunRequest",
    "L2RunResult",
    "analyze_l2_dimension",
    "run_l2",
]
