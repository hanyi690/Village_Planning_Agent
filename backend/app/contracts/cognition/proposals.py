"""Cognition-owned World Model assertion transaction contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field, model_validator

from app.contracts.base import StrictContractModel
from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.cognition.snapshot import SessionWorldModelSnapshot


AssertionDecision = Literal["ACCEPT", "AMBIGUOUS", "REJECT"]
WorldModelCommitStatus = Literal[
    "committed",
    "noop",
    "invalid_request",
    "stale_parent",
    "aborted",
]


def _fingerprint_payload(data: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in data.items()
        if key not in {
            "proposal_fingerprint",
            "schema_version",
            "digest",
            "parent_digests",
            "provenance",
            "created_at",
        }
    }


def _proposal_fingerprint(data: dict[str, Any]) -> str:
    raw = json.dumps(
        _fingerprint_payload(data),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AssertionProposal(StrictContractModel):
    """Evidence-backed assertion candidate; never a current-world fact."""

    proposal_ref: str = Field(min_length=1)
    proposal_kind: str = Field(min_length=1)
    subject_ref: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object_ref: str = ""
    value: Any = None
    source_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    requirement_refs: tuple[str, ...] = ()
    authority: dict[str, str] = Field(default_factory=dict)
    valid_time: str = ""
    parent_current_world_digest: str = Field(min_length=1)
    proposal_fingerprint: str = ""
    supersedes: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="before")
    @classmethod
    def populate_and_validate_fingerprint(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        fingerprint = str(data.get("proposal_fingerprint") or "")
        expected = _proposal_fingerprint(data)
        if fingerprint and fingerprint != expected:
            raise ValueError("proposal_fingerprint does not match proposal content")
        data["proposal_fingerprint"] = expected
        return data

    @model_validator(mode="after")
    def validate_lineage(self) -> "AssertionProposal":
        if not self.source_refs and not self.evidence_refs:
            raise ValueError("AssertionProposal requires source_refs or evidence_refs")
        if not self.authority:
            raise ValueError("AssertionProposal requires authority")
        if not self.object_ref and self.value is None:
            raise ValueError("AssertionProposal requires object_ref or value")
        return self


class AssertionDecisionArtifact(StrictContractModel):
    """Deterministic Cognition decision attached to exactly one proposal."""

    decision_ref: str = Field(min_length=1)
    proposal_ref: str = Field(min_length=1)
    decision: AssertionDecision
    reason_code: str = Field(min_length=1)
    validator_ref: str = Field(min_length=1)
    policy_ref: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    parent_current_world_digest: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AssertionCommitRequest(StrictContractModel):
    """Closed reference set for one atomic Cognition commit group."""

    proposal_refs: tuple[str, ...] = Field(min_length=1)
    decision_refs: tuple[str, ...] = Field(min_length=1)
    expected_parent_snapshot: str = Field(min_length=1)
    expected_current_world_digest: str = Field(min_length=1)
    evidence_artifact_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_refs(self) -> "AssertionCommitRequest":
        if len(self.proposal_refs) != len(set(self.proposal_refs)):
            raise ValueError("proposal_refs must be unique")
        if len(self.decision_refs) != len(set(self.decision_refs)):
            raise ValueError("decision_refs must be unique")
        if len(self.proposal_refs) != len(self.decision_refs):
            raise ValueError("proposal_refs and decision_refs must have equal length")
        return self


class WorldModelCommitReceipt(StrictContractModel):
    """Auditable result of one immutable World Model transaction."""

    status: WorldModelCommitStatus
    parent: str = ""
    child: str = ""
    accepted_assertion_refs: tuple[str, ...] = ()
    ambiguous_assertion_refs: tuple[str, ...] = ()
    rejected_assertion_refs: tuple[str, ...] = ()
    affected_entity_refs: tuple[str, ...] = ()
    affected_relation_refs: tuple[str, ...] = ()
    affected_representation_refs: tuple[str, ...] = ()
    old_current_world_digest: str = ""
    new_current_world_digest: str = ""
    old_world_model_snapshot_digest: str = ""
    new_world_model_snapshot_digest: str = ""
    transaction_fingerprint: str = ""
    error_type: str = ""
    committed: bool = False
    world_model_version: int = 0
    receipt_artifact_ref: ArtifactRef | None = None
    world_model_snapshot: SessionWorldModelSnapshot | None = None


__all__ = [
    "AssertionDecision",
    "AssertionDecisionArtifact",
    "AssertionCommitRequest",
    "AssertionProposal",
    "WorldModelCommitReceipt",
    "WorldModelCommitStatus",
]
