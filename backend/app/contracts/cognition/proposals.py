"""Immutable Cognition proposals and World Model commit receipts.

Evidence and L1-GROUND may construct these value objects, but only the
``WorldModelCommitPort`` can turn a proposal into an accepted current-world
assertion.  The separate batch contract makes the parent snapshot and the
all-or-nothing commit boundary explicit at the application edge.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field, model_validator

from app.contracts.base import StrictContractModel
from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.cognition.snapshot import SessionWorldModelSnapshot


ProposalStatus = Literal[
    "PROPOSED",
    "ACCEPTED",
    "AMBIGUOUS",
    "REJECTED",
    "SUPERSEDED",
]

WorldModelCommitStatus = Literal[
    "committed",
    "noop",
    "stale_parent",
    "ambiguous",
    "rejected",
    "aborted",
    "unsupported",
]


class WorldModelProposal(StrictContractModel):
    """One source/evidence-backed assertion proposal.

    ``status`` must be ``PROPOSED`` at the Cognition input boundary.  A
    proposal carrying ``ACCEPTED`` is treated as an attempted authority
    escalation and rejected by the commit port; callers never manufacture a
    current-world decision by setting a field in this object.
    """

    proposal_ref: str = Field(min_length=1)
    assertion_ref: str = ""
    assertion_kind: str = "semantic"
    subject_ref: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object_ref: str = ""
    value: Any = None
    valid_time: str = ""
    source_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    confidence_components: dict[str, float] = Field(default_factory=dict)
    authority: dict[str, str] = Field(default_factory=dict)
    parent_world_model_snapshot_ref: str = ""
    parent_world_model_snapshot_digest: str = ""
    supersedes: tuple[str, ...] = ()
    decision_ref: str = ""
    status: ProposalStatus = "PROPOSED"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_evidence_and_confidence(self) -> "WorldModelProposal":
        if not self.source_refs and not self.evidence_refs:
            raise ValueError("World Model proposal requires source or evidence refs")
        if any(
            not 0.0 <= float(value) <= 1.0
            for value in self.confidence_components.values()
        ):
            raise ValueError("proposal confidence components must be between 0 and 1")
        return self


class WorldModelProposalBatch(StrictContractModel):
    """Atomic set of proposals evaluated against one World Model parent."""

    batch_ref: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    branch_id: str = Field(default="main", min_length=1)
    parent_world_model_snapshot_ref: str = Field(min_length=1)
    parent_world_model_snapshot_digest: str = Field(min_length=1)
    proposals: tuple[WorldModelProposal, ...] = ()
    input_artifact_refs: tuple[str, ...] = ()
    policy_ref: str = ""

    @model_validator(mode="after")
    def validate_batch(self) -> "WorldModelProposalBatch":
        refs = tuple(item.proposal_ref for item in self.proposals)
        if len(refs) != len(set(refs)):
            raise ValueError("World Model proposal refs must be unique")
        for proposal in self.proposals:
            if proposal.parent_world_model_snapshot_ref and (
                proposal.parent_world_model_snapshot_ref
                != self.parent_world_model_snapshot_ref
            ):
                raise ValueError("proposal parent ref differs from batch parent")
            if proposal.parent_world_model_snapshot_digest and (
                proposal.parent_world_model_snapshot_digest
                != self.parent_world_model_snapshot_digest
            ):
                raise ValueError("proposal parent digest differs from batch parent")
        return self


class WorldModelCommitResult(StrictContractModel):
    """Typed outcome of one atomic Cognition commit attempt."""

    status: WorldModelCommitStatus
    committed: bool = False
    batch_ref: str = ""
    proposal_fingerprint: str = ""
    written: int = 0
    accepted: int = 0
    rejected: int = 0
    error_type: str = ""
    parent_world_model_snapshot_ref: str = ""
    parent_world_model_snapshot_digest: str = ""
    world_model_snapshot_ref: str = ""
    world_model_snapshot_digest: str = ""
    world_model_version: int = 0
    world_model_artifact_ref: ArtifactRef | None = None
    world_model_snapshot: SessionWorldModelSnapshot | None = None


__all__ = [
    "ProposalStatus",
    "WorldModelCommitResult",
    "WorldModelCommitStatus",
    "WorldModelProposal",
    "WorldModelProposalBatch",
]
