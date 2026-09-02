import pytest
from pydantic import ValidationError

from app.contracts.evidence.proposal_contracts import (
    EntitySupportProposal,
    EvidenceProposalBatch,
    PropertyAssertionProposal,
)


def _entity() -> EntitySupportProposal:
    return EntitySupportProposal(
        proposal_ref="evidence.proposal.entity.req-1.candidate-1",
        requirement_ref="req-1",
        policy_ref="facility_existence",
        policy_version="1",
        subject_ref="candidate-1",
        value="facility candidate",
        candidate_refs=("candidate-1",),
        claim_refs=("claim-1",),
        observation_refs=("observation-1",),
        source_refs=("source-1",),
        evidence_refs=("claim-1", "observation-1"),
        authority={
            "source_authority": "authoritative",
            "geometry_authority": "none",
            "legal_authority": "none",
        },
        parent_world_model_digest="wm-1",
        evidence_packet_digest="packet-1",
    )


def test_proposal_batch_is_immutable_and_has_all_round_lineage():
    proposal = _entity()
    batch = EvidenceProposalBatch(
        round_id="round-1",
        wm_epoch="wm-epoch-1",
        parent_world_model_digest="wm-1",
        requirement_set_digest="requirements-1",
        evidence_packet_digest="packet-1",
        proposals=(proposal,),
    )

    assert batch.proposal_fingerprint.startswith("sha256:")
    with pytest.raises((TypeError, ValidationError)):
        proposal.subject_ref = "other"


def test_absence_proposal_requires_explicit_authorization():
    with pytest.raises(ValidationError, match="absence"):
        PropertyAssertionProposal(
            proposal_ref="evidence.proposal.property.req-1.candidate-1",
            requirement_ref="req-1",
            policy_ref="absence_claim",
            policy_version="1",
            subject_ref="road:R1",
            predicate="exists",
            candidate_refs=("candidate-1",),
            observation_refs=("observation-1",),
            source_refs=("source-1",),
            evidence_refs=("observation-1",),
            conclusion_kind="absence",
            authority={"source_authority": "authoritative"},
            parent_world_model_digest="wm-1",
            evidence_packet_digest="packet-1",
        )


def test_batch_rejects_proposal_from_another_world_model_parent():
    with pytest.raises(ValidationError, match="parent digest"):
        EvidenceProposalBatch(
            round_id="round-1",
            wm_epoch="wm-epoch-1",
            parent_world_model_digest="wm-1",
            requirement_set_digest="requirements-1",
            evidence_packet_digest="packet-1",
            proposals=(_entity().model_copy(update={"parent_world_model_digest": "wm-2"}),),
        )
