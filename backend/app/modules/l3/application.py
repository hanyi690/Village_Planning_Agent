"""Public L3 PLAN facade.

L3 owns claim meaning and program assembly.  Retrieval, context construction,
and structured-output execution are supplied by shared runtimes; this facade
only validates the upstream artifact boundary and reloads the committed
PlanningProgram before returning it to the workflow.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.l1.l1_contracts import L1Snapshot
from app.contracts.l2.l2_contracts import L2Strategy
from app.contracts.l3.l3_contracts import PlanningProgram


class L3RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    context_version: str = Field(min_length=1)
    l1_snapshot_ref: ArtifactRef
    l2_strategy_ref: ArtifactRef

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> "L3RunRequest":
        refs = state.get("artifact_refs") or {}
        if not refs.get("l1_snapshot"):
            raise RuntimeError("L3 requires the canonical l1_snapshot artifact ref")
        if not refs.get("l2_strategy"):
            raise RuntimeError("L3 requires the canonical l2_strategy artifact ref")
        return cls(
            run_id=str(state.get("run_id") or state.get("session_id") or ""),
            session_id=str(state.get("session_id") or ""),
            context_version=str(state.get("context_version") or ""),
            l1_snapshot_ref=ArtifactRef.model_validate(refs["l1_snapshot"]),
            l2_strategy_ref=ArtifactRef.model_validate(refs["l2_strategy"]),
        )


class L3RunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    request: L3RunRequest
    program: PlanningProgram
    artifact_ref: ArtifactRef
    gate_ref: ArtifactRef
    review_id: str = ""

    def to_state_patch(self) -> dict[str, Any]:
        return {
            "artifact_refs": {
                "planning_program": self.artifact_ref.model_dump(mode="json"),
                "l3_gate": self.gate_ref.model_dump(mode="json"),
            },
            "l3_review_id": self.review_id,
        }


class L3Application:
    """Run the production L3 aggregate and reload its immutable artifact."""

    @staticmethod
    def _load(state: Mapping[str, Any], key: str, model: type[BaseModel]) -> Any:
        from app.infrastructure.artifacts.runtime import load_artifact

        value = load_artifact(dict(state), key, model)
        if value is None:
            raise RuntimeError(f"L3 cannot proceed without a reloaded {key} artifact")
        return value

    def load_l1(self, state: Mapping[str, Any]) -> L1Snapshot:
        return self._load(state, "l1_snapshot", L1Snapshot)

    def load_l2(self, state: Mapping[str, Any]) -> L2Strategy:
        return self._load(state, "l2_strategy", L2Strategy)

    @staticmethod
    def require_l2_pass(state: Mapping[str, Any]) -> None:
        """Fail closed when the upstream L2 gate is not a persisted PASS."""

        from app.workflow.state import load_root_gate

        gate = load_root_gate(dict(state), "l2")
        if gate.passed:
            return
        pending = list(gate.pending_requests or [])
        request_ids = ", ".join(
            str(item.request_id)
            for item in pending[:8]
            if str(getattr(item, "request_id", "") or "").strip()
        )
        suffix = f" pending={request_ids}" if request_ids else ""
        raise RuntimeError(
            "L3 requires a persisted L2 PASS gate; "
            f"current route={gate.feedback_route or 'BLOCK'}.{suffix}"
        )

    def load(self, state: Mapping[str, Any]) -> PlanningProgram:
        return self._load(state, "planning_program", PlanningProgram)

    async def run(self, state: Mapping[str, Any]) -> L3RunResult:
        request = L3RunRequest.from_state(state)
        self.require_l2_pass(state)
        l1 = self.load_l1(state)
        l2 = self.load_l2(state)
        if l1.context_version != request.context_version:
            raise RuntimeError("L3 input L1Snapshot context version mismatch")
        if l2.context_version != request.context_version:
            raise RuntimeError("L3 input L2Strategy context version mismatch")

        from .aggregation import l3_aggregate

        patch = dict(await l3_aggregate(dict(state)))
        refs = {
            **dict(state.get("artifact_refs") or {}),
            **dict(patch.get("artifact_refs") or {}),
        }
        replay_state = {**dict(state), **patch, "artifact_refs": refs}
        program = self.load(replay_state)
        return L3RunResult(
            request=request,
            program=program,
            artifact_ref=ArtifactRef.model_validate(refs["planning_program"]),
            gate_ref=ArtifactRef.model_validate(refs["l3_gate"]),
            review_id=str(patch.get("l3_review_id") or ""),
        )


async def run_l3(state: Mapping[str, Any]) -> L3RunResult:
    return await L3Application().run(state)


async def analyze_l3_dimension(state: Mapping[str, Any]) -> dict[str, Any]:
    from .reasoning import analyze_l3_dimension as run_dimension

    return await run_dimension(dict(state))


__all__ = [
    "L3Application",
    "L3RunRequest",
    "L3RunResult",
    "analyze_l3_dimension",
    "run_l3",
]
