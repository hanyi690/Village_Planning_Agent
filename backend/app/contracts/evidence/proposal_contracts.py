"""Immutable Evidence-to-Cognition proposal contracts."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.evidence.provider_attempt import EvidenceAuthority, EvidenceConfidence

if TYPE_CHECKING:
    from app.contracts.cognition.proposals import AssertionProposal


EvidenceProposalKind = Literal[
    "entity_support",
    "relation_support",
    "property_assertion",
    "representation_support",
]
ConclusionKind = Literal["presence", "absence", "none"]


class EvidenceProposalBase(BaseModel):
    """One Evidence conclusion candidate, never a current-world assertion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_ref: str = Field(min_length=1)
    proposal_kind: EvidenceProposalKind
    requirement_ref: str = Field(min_length=1)
    policy_ref: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    subject_ref: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object_ref: str = ""
    value: Any = None
    candidate_refs: tuple[str, ...] = ()
    claim_refs: tuple[str, ...] = ()
    observation_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    supporting_evidence_refs: tuple[str, ...] = ()
    opposing_evidence_refs: tuple[str, ...] = ()
    confidence: EvidenceConfidence = Field(default_factory=EvidenceConfidence)
    authority: EvidenceAuthority = Field(default_factory=EvidenceAuthority)
    valid_time: str = ""
    parent_world_model_digest: str = Field(min_length=1)
    evidence_packet_digest: str = Field(min_length=1)
    evidence_artifact_ref: str = ""
    conclusion_kind: ConclusionKind = "presence"
    absence_authorized: bool = False

    @model_validator(mode="after")
    def _validate_lineage(self) -> "EvidenceProposalBase":
        if not self.candidate_refs and self.conclusion_kind != "absence":
            raise ValueError("Evidence proposal requires candidate_refs")
        if (
            not self.observation_refs
            and not self.claim_refs
            and self.conclusion_kind != "absence"
        ):
            raise ValueError("Evidence proposal requires observation_refs or claim_refs")
        if not self.source_refs:
            raise ValueError("Evidence proposal requires source_refs")
        if not self.evidence_refs:
            raise ValueError("Evidence proposal requires evidence_refs")
        if not self.object_ref and self.value is None and self.conclusion_kind != "absence":
            raise ValueError("presence proposal requires object_ref or value")
        if self.conclusion_kind == "absence" and not self.absence_authorized:
            raise ValueError("absence proposal requires absence authorization")
        if self.absence_authorized and self.conclusion_kind != "absence":
            raise ValueError("absence authorization requires an absence conclusion")
        return self

    def to_assertion_proposal(self) -> "AssertionProposal":
        """Convert to Cognition's generic input contract without committing it."""

        from app.contracts.cognition.proposals import AssertionProposal

        return AssertionProposal(
            proposal_ref=self.proposal_ref,
            proposal_kind=self.proposal_kind,
            subject_ref=self.subject_ref,
            predicate=self.predicate,
            object_ref=self.object_ref,
            value=self.value,
            source_refs=self.source_refs,
            evidence_refs=self.evidence_refs,
            requirement_refs=(self.requirement_ref,),
            authority={
                "source_authority": self.authority.source_authority,
                "geometry_authority": self.authority.geometry_authority,
                "legal_authority": self.authority.legal_authority,
                "policy_ref": self.policy_ref,
                "policy_version": self.policy_version,
            },
            valid_time=self.valid_time,
            parent_current_world_digest=self.parent_world_model_digest,
        )


class EntitySupportProposal(EvidenceProposalBase):
    proposal_kind: Literal["entity_support"] = "entity_support"
    predicate: str = "supports_entity"


class RelationSupportProposal(EvidenceProposalBase):
    proposal_kind: Literal["relation_support"] = "relation_support"

    @model_validator(mode="after")
    def _require_object(self) -> "RelationSupportProposal":
        if not self.object_ref:
            raise ValueError("relation proposal requires object_ref")
        return self


class PropertyAssertionProposal(EvidenceProposalBase):
    proposal_kind: Literal["property_assertion"] = "property_assertion"
    predicate: str = "asserts_property"


class RepresentationSupportProposal(EvidenceProposalBase):
    proposal_kind: Literal["representation_support"] = "representation_support"
    predicate: str = "has_representation"
    representation_ref: str = Field(min_length=1)
    geometry_authority: Literal["data_resource_catalog"]

    @model_validator(mode="after")
    def _representation_object(self) -> "RepresentationSupportProposal":
        if self.object_ref != self.representation_ref:
            raise ValueError("representation proposal object_ref must match representation_ref")
        return self


EvidenceProposal = Annotated[
    EntitySupportProposal
    | RelationSupportProposal
    | PropertyAssertionProposal
    | RepresentationSupportProposal,
    Field(discriminator="proposal_kind"),
]


class EvidenceProposalBatch(BaseModel):
    """Frozen EV-03 output for one Evidence/Cognition round."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    round_id: str = Field(min_length=1)
    wm_epoch: str = Field(min_length=1)
    parent_world_model_digest: str = Field(min_length=1)
    requirement_set_digest: str = Field(min_length=1)
    evidence_packet_digest: str = Field(min_length=1)
    proposals: tuple[EvidenceProposal, ...] = ()
    proposal_fingerprint: str = ""

    @model_validator(mode="after")
    def _validate_and_freeze_fingerprint(self) -> "EvidenceProposalBatch":
        for proposal in self.proposals:
            if proposal.parent_world_model_digest != self.parent_world_model_digest:
                raise ValueError("proposal parent digest does not match batch")
            if proposal.evidence_packet_digest != self.evidence_packet_digest:
                raise ValueError("proposal packet digest does not match batch")
        payload = self.model_dump(mode="json", exclude={"proposal_fingerprint"})
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        expected = "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if self.proposal_fingerprint and self.proposal_fingerprint != expected:
            raise ValueError("proposal_fingerprint does not match proposal content")
        object.__setattr__(self, "proposal_fingerprint", expected)
        return self

    def to_assertion_proposals(self) -> tuple[AssertionProposal, ...]:
        return tuple(proposal.to_assertion_proposal() for proposal in self.proposals)


__all__ = [
    "ConclusionKind",
    "EntitySupportProposal",
    "EvidenceProposal",
    "EvidenceProposalBase",
    "EvidenceProposalBatch",
    "EvidenceProposalKind",
    "PropertyAssertionProposal",
    "RelationSupportProposal",
    "RepresentationSupportProposal",
]
