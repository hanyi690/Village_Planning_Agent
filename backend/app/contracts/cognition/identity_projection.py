"""Typed transition contracts for the L1 identity assertion plane."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.cognition.snapshot import SessionWorldModelSnapshot
from app.contracts.evidence.identity_contracts import (
    EvidenceObservationSnapshot,
    GroundedEntityBindingSnapshot,
)


class IdentityBindingCommitEnvelope(BaseModel):
    """Exact, replayable inputs for one atomic identity-plane commit."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    branch_id: str
    l1_snapshot_artifact_ref: ArtifactRef
    source_world_model_artifact_ref: ArtifactRef
    source_world_model_snapshot: SessionWorldModelSnapshot
    observation_artifact_ref: ArtifactRef
    observation_snapshot: EvidenceObservationSnapshot
    binding_artifact_ref: ArtifactRef
    binding_snapshot: GroundedEntityBindingSnapshot

    @model_validator(mode="after")
    def validate_exact_lineage(self) -> "IdentityBindingCommitEnvelope":
        refs = (
            self.l1_snapshot_artifact_ref,
            self.source_world_model_artifact_ref,
            self.observation_artifact_ref,
            self.binding_artifact_ref,
        )
        if any(ref.run_id != self.run_id for ref in refs):
            raise ValueError("identity commit artifacts belong to another run")
        if any(ref.branch_id != self.branch_id for ref in refs):
            raise ValueError("identity commit artifacts belong to another branch")
        if (
            self.observation_artifact_ref.digest
            != self.binding_snapshot.observation_snapshot_ref
        ):
            raise ValueError("binding snapshot does not reference exact observations")
        if (
            self.source_world_model_snapshot.graph_digest
            != self.binding_snapshot.source_world_model_snapshot_digest
        ):
            raise ValueError("binding snapshot World Model digest mismatch")
        if (
            self.source_world_model_snapshot.snapshot_ref
            != self.binding_snapshot.source_world_model_snapshot_ref
        ):
            raise ValueError("binding snapshot World Model ref mismatch")
        return self


class IdentityBindingCommitResult(BaseModel):
    """Result returned by a WorldModel identity-plane commit."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["committed", "noop", "aborted", "unsupported"]
    committed: bool
    written: int = 0
    error_type: str = ""
    projection_fingerprint: str = ""
    parent_world_model_snapshot_ref: str = ""
    parent_world_model_snapshot_digest: str = ""
    world_model_version: int = 0
    world_model_snapshot_ref: str = ""
    world_model_snapshot_digest: str = ""
    internal_cas_descriptor_digest: str = ""
    world_model_snapshot: SessionWorldModelSnapshot | None = None


__all__ = [
    "IdentityBindingCommitEnvelope",
    "IdentityBindingCommitResult",
]
