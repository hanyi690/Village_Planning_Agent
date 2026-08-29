"""Public L1 application facade.

The facade is the only new entry point for L1.  It accepts workflow control
state, delegates one real aggregate implementation, reloads the committed
typed artifact, and returns a typed result to the orchestrator.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.l1.l1_contracts import L1Snapshot

from .aggregation import l1_aggregate


class L1RunRequest(BaseModel):
    """Typed identity required to start an L1 aggregation."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    branch_id: str = Field(default="main", min_length=1)
    context_version: str = Field(min_length=1)
    context_ref: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> "L1RunRequest":
        return cls(
            run_id=str(state.get("run_id") or state.get("session_id") or ""),
            session_id=str(state.get("session_id") or ""),
            branch_id=str(state.get("branch_id") or "main"),
            context_version=str(state.get("context_version") or ""),
            context_ref=dict(state.get("context_ref") or {}),
        )


class L1RunResult(BaseModel):
    """Typed result returned by the L1 facade after CAS commit and reload."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    request: L1RunRequest
    snapshot: L1Snapshot
    snapshot_ref: ArtifactRef
    gate_ref: ArtifactRef
    review_id: str = ""
    projection_digest: str = ""
    input_snapshot_ref: ArtifactRef | None = None
    iteration: int = 0

    def to_state_patch(self) -> dict[str, Any]:
        """Convert the typed result to the workflow's control-plane patch."""

        return {
            "artifact_refs": {
                "l1_snapshot": self.snapshot_ref.model_dump(mode="json"),
                "l1_gate": self.gate_ref.model_dump(mode="json"),
            },
            "l1_review_id": self.review_id,
        }


class L1Application:
    """Application boundary for L1 OBSERVE."""

    @staticmethod
    def _validate_snapshot(
        snapshot: L1Snapshot,
        request: L1RunRequest,
    ) -> L1Snapshot:
        if snapshot.context_version != request.context_version:
            raise RuntimeError("L1Snapshot context version does not match the run")
        if not snapshot.context_fingerprint:
            raise RuntimeError("L1Snapshot has no frozen context fingerprint")
        if not snapshot.sources and snapshot.fact_records:
            raise RuntimeError("L1Snapshot facts have no source catalog")
        source_refs = {
            source.reference
            for source in snapshot.sources
            if source.reference
        }
        for fact in snapshot.fact_records:
            if not fact.source_refs:
                raise RuntimeError(f"L1 fact has no provenance: {fact.fact_id}")
            if not any(
                ref in source_refs
                or any(ref.startswith(f"{source_ref}#") for source_ref in source_refs)
                for ref in fact.source_refs
            ):
                raise RuntimeError(
                    "L1 fact provenance is not represented by sources: "
                    f"fact={fact.fact_id} refs={fact.source_refs}"
                )
            expected_level = {
                "derived_metric": "derived",
                "kg_canonical_fact": "inferred",
            }.get(fact.fact_kind)
            allowed_levels = (
                {expected_level}
                if expected_level is not None
                else {
                    "observed",
                    "inferred",
                    "pending",
                    "conflicted",
                }
            )
            if fact.inference_level not in allowed_levels:
                raise RuntimeError(
                    f"L1 fact inference level mismatch: {fact.fact_id}"
                )
            if fact.status != fact.inference_level:
                raise RuntimeError(f"L1 fact status mismatch: {fact.fact_id}")
        return snapshot

    async def run(self, state: Mapping[str, Any]) -> L1RunResult:
        request = L1RunRequest.from_state(state)
        patch = dict(await l1_aggregate(dict(state)))
        refs = dict(state.get("artifact_refs") or {})
        refs.update(dict(patch.get("artifact_refs") or {}))
        replay_state = {**dict(state), **patch, "artifact_refs": refs}
        snapshot = self.load(replay_state)
        if snapshot is None:
            raise RuntimeError("L1 aggregate did not commit an L1Snapshot artifact")
        self._validate_snapshot(snapshot, request)
        snapshot_ref = ArtifactRef.model_validate(refs.get("l1_snapshot"))
        gate_ref = ArtifactRef.model_validate(refs.get("l1_gate"))
        return L1RunResult(
            request=request,
            snapshot=snapshot,
            snapshot_ref=snapshot_ref,
            gate_ref=gate_ref,
            review_id=str(patch.get("l1_review_id") or ""),
            projection_digest=str(patch.get("l1_projection_digest") or ""),
            input_snapshot_ref=(
                ArtifactRef.model_validate(patch["l1_input_snapshot_ref"])
                if patch.get("l1_input_snapshot_ref")
                else None
            ),
            iteration=int(patch.get("l1_iteration") or 0),
        )

    @staticmethod
    def load(state: Mapping[str, Any]) -> L1Snapshot | None:
        from app.infrastructure.artifacts.runtime import load_artifact

        return load_artifact(dict(state), "l1_snapshot", L1Snapshot)


async def analyze_dimension(state: Mapping[str, Any]) -> dict[str, Any]:
    """Run one bounded L1 dimension through the stage-owned facade."""

    from .reasoning import analyze_dimension as run_dimension

    return await run_dimension(dict(state))


async def run_l1(state: Mapping[str, Any]) -> L1RunResult:
    """Run L1 through the canonical facade."""

    return await L1Application().run(state)


__all__ = [
    "L1Application",
    "L1RunRequest",
    "L1RunResult",
    "analyze_dimension",
    "run_l1",
]
