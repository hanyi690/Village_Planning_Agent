from datetime import datetime, timezone

import pytest

from app.contracts.cognition_round import CognitionRound, requirement_set_digest
from app.contracts.evidence.acquisition_contracts import EvidenceObservationSnapshot
from app.contracts.evidence.evidence_contracts import (
    EvidenceBundle,
    EvidenceFact,
    EvidenceSource,
    ExplorationResult,
)
from app.contracts.evidence.evidence_packet_contracts import EvidencePacket, SpatialRelationEvidence
from app.contracts.evidence.feature_identity_contracts import FeatureEvidenceRef, SourceFeatureIdentity
from app.contracts.evidence.provider_attempt import EvidenceObservationRecord
from app.contracts.evidence.reasoning_contracts import (
    CandidateEvidence,
    EvidenceSufficiencyResult,
    RequirementSufficiencyDecision,
    SufficiencyCheck,
)
from app.contracts.evidence.requirement_contracts import EvidenceClaim, EvidenceCoverage, EvidenceRequirement
from app.modules.evidence.proposals import build_evidence_proposals, to_cognition_assertion_proposals


_GATES = (
    "source_family",
    "source_authority",
    "independent_sources",
    "temporal_fit",
    "geometry_legal_authority",
    "conflict_policy",
    "allowed_inference",
    "acquisition_completeness",
    "provider_origin_completeness",
    "absence_policy",
)


def _candidate(ref: str, *, geometry: str = "none", claim: str = "claim-1") -> CandidateEvidence:
    return CandidateEvidence(
        candidate_ref=ref,
        requirement_ref="req-1",
        claim_refs=(claim,),
        observation_refs=("observation-1",),
        source_refs=("source-1",),
        source_families=("data",),
        source_authorities=("authoritative",),
        geometry_authorities=(geometry,),
        independent_source_refs=("source-1",),
        valid_times=("2026-09-01T00:00:00+00:00",),
        inference_levels=("exact",),
        statement="candidate R1",
        value_digest="value-1",
        locator_refs=("data://R1",),
        confidence=0.9,
    )


def _requirement(kind: str = "claim", *, metadata: dict | None = None) -> EvidenceRequirement:
    return EvidenceRequirement(
        requirement_id="req-1",
        statement="road R1 exists",
        kind=kind,
        subject_refs=("road:R1",),
        policy_ref="road_identity.v1",
        metadata=metadata or {},
    )


def _round(requirements: tuple[EvidenceRequirement, ...], *, round_id: str = "round-1") -> CognitionRound:
    return CognitionRound(
        round_id=round_id,
        round_number=0,
        wm_epoch="wm-7",
        parent_world_model_snapshot_ref="world-model://session-1/7/wm-7",
        parent_world_model_snapshot_digest="wm-7",
        requirement_set_digest=requirement_set_digest(requirements),
        requirement_refs=tuple(item.requirement_id for item in requirements),
    )


def _result(
    requirement: EvidenceRequirement,
    *,
    status: str = "sufficient",
    conclusion_kind: str = "presence",
    candidates: tuple[CandidateEvidence, ...] = (_candidate("candidate-1"),),
    claims: tuple[EvidenceClaim, ...] = (
        EvidenceClaim(
            claim_id="claim-1",
            statement="road R1 exists",
            source_refs=("source-1",),
            source_families=("data",),
            authority="authoritative",
            confidence=0.9,
            metadata={"predicate": "exists", "value": "true"},
        ),
    ),
    facts: tuple[EvidenceFact, ...] = (
        EvidenceFact(
            fact_id="fact-1",
            statement="road R1 exists",
            source_refs=["source-1"],
            fields={"predicate": "exists", "value": "true"},
        ),
    ),
    packet: EvidencePacket | None = None,
) -> ExplorationResult:
    decision = RequirementSufficiencyDecision(
        requirement_ref=requirement.requirement_ref,
        policy_ref=requirement.policy_ref,
        policy_version="1",
        status=status,
        candidate_refs=tuple(candidate.candidate_ref for candidate in candidates),
        conclusion_kind=conclusion_kind,
        absence_authorized=conclusion_kind == "absence",
        checks=tuple(SufficiencyCheck(gate=gate, status="pass") for gate in _GATES),
    )
    sufficiency = EvidenceSufficiencyResult(
        status=status,
        candidates=candidates,
        requirement_decisions=(decision,),
        absence_authorized=conclusion_kind == "absence",
    )
    observation = EvidenceObservationRecord(
        observation_ref="observation-1",
        attempt_ref="attempt-1",
        provider="data_catalog",
        source_family="data",
        source_ref="source-1",
        statement="road R1 exists",
        observed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    snapshot = EvidenceObservationSnapshot(
        snapshot_ref="snapshot-1",
        query_plan_ref="plan-1",
        query_plan_fingerprint="plan-fingerprint",
        attempt_refs=("attempt-1",),
        observation_refs=("observation-1",),
        source_refs=("source-1",),
        records=(observation,),
        complete=True,
    )
    coverage = EvidenceCoverage(
        requirement_set_fingerprint="requirements-1",
        requirements=(requirement,),
        requirement_coverage=(),
        claims=claims,
        stop_reason="sufficient" if status == "sufficient" else "source_exhausted",
        candidate_evidence=candidates,
        sufficiency_decision=sufficiency,
    )
    return ExplorationResult(
        evidence_bundle=EvidenceBundle(
            request=requirement.statement,
            facts=list(facts),
            sources=[EvidenceSource(
                source_type="gis_layer",
                reference="source-1",
                authority="authoritative",
            )],
        ),
        evidence_packet=packet or EvidencePacket(request=requirement.statement),
        coverage=coverage,
        observation_snapshot=snapshot,
    )


def test_sufficient_identity_requirement_produces_entity_support():
    requirement = _requirement("identity")
    result = _result(requirement)

    batch = build_evidence_proposals(
        result,
        cognition_round=_round((requirement,)),
    )

    assert [item.proposal_kind for item in batch.proposals] == ["entity_support"]
    assert batch.proposals[0].source_refs == ("source-1",)
    assert batch.proposals[0].observation_refs == ("observation-1",)
    assert batch.proposals[0].parent_world_model_digest == "wm-7"


def test_relation_property_and_local_representation_are_distinct_proposals():
    relation = SpatialRelationEvidence(
        relation_id="relation-1",
        subject=FeatureEvidenceRef(
            identity=SourceFeatureIdentity(source_feature_id="road:R1"),
            entity_refs=["road:R1"],
        ),
        predicate="connected_to",
        object=FeatureEvidenceRef(
            identity=SourceFeatureIdentity(source_feature_id="junction:J1"),
            entity_refs=["junction:J1"],
        ),
        provenance_refs=["source-1"],
    )
    candidate = _candidate("candidate-1", geometry="data_resource_catalog")
    packet = EvidencePacket(
        request="road R1 exists",
        candidate_refs=[FeatureEvidenceRef(
            identity=SourceFeatureIdentity(source_feature_id="road:R1"),
            entity_refs=["road:R1"],
            representation_refs=["representation:R1"],
        )],
        relation_evidence=[relation],
    )
    requirement = _requirement("spatial")
    result = _result(requirement, candidates=(candidate,), packet=packet)

    batch = build_evidence_proposals(
        result,
        cognition_round=_round((requirement,)).model_copy(update={
            "round_id": "r",
            "wm_epoch": "8",
            "parent_world_model_snapshot_digest": "wm-8",
        }),
    )

    assert {item.proposal_kind for item in batch.proposals} == {
        "relation_support",
        "property_assertion",
        "representation_support",
    }
    relation_proposal = next(
        item for item in batch.proposals if item.proposal_kind == "relation_support"
    )
    assert relation_proposal.object_ref == "junction:J1"

    property_requirement = _requirement("claim")
    property_result = _result(property_requirement, packet=EvidencePacket(request="road R1 exists"))
    property_batch = build_evidence_proposals(
        property_result,
        cognition_round=_round((property_requirement,)).model_copy(update={
            "round_id": "r",
            "wm_epoch": "8",
            "parent_world_model_snapshot_digest": "wm-8",
        }),
    )
    assert property_batch.proposals[0].proposal_kind == "property_assertion"


@pytest.mark.parametrize("status", ["partial", "insufficient", "human_required", "failed"])
def test_non_sufficient_decision_produces_no_wm_proposal(status: str):
    requirement = _requirement()
    result = _result(requirement, status=status)

    batch = build_evidence_proposals(
        result,
        cognition_round=_round((requirement,)).model_copy(update={
            "round_id": "r",
            "wm_epoch": "8",
            "parent_world_model_snapshot_digest": "wm-8",
        }),
    )

    assert batch.proposals == ()


def test_authorized_absence_produces_only_an_absence_property_proposal():
    requirement = _requirement("claim", metadata={"predicate": "exists"})
    result = _result(
        requirement,
        conclusion_kind="absence",
        candidates=(),
        claims=(),
        facts=(),
    )

    batch = build_evidence_proposals(
        result,
        cognition_round=_round((requirement,)).model_copy(update={
            "round_id": "r",
            "wm_epoch": "8",
            "parent_world_model_snapshot_digest": "wm-8",
        }),
    )

    assert len(batch.proposals) == 1
    assert batch.proposals[0].proposal_kind == "property_assertion"
    assert batch.proposals[0].conclusion_kind == "absence"
    assert batch.proposals[0].absence_authorized is True


def test_external_locator_cannot_become_representation_support():
    candidate = _candidate("candidate-1", geometry="none")
    packet = EvidencePacket(
        request="road R1 exists",
        candidate_refs=[FeatureEvidenceRef(
            identity=SourceFeatureIdentity(source_feature_id="road:R1"),
            entity_refs=["road:R1"],
            representation_refs=["representation:external"],
        )],
    )
    requirement = _requirement("spatial")
    result = _result(requirement, candidates=(candidate,), packet=packet)

    batch = build_evidence_proposals(
        result,
        cognition_round=_round((requirement,)).model_copy(update={
            "round_id": "r",
            "wm_epoch": "8",
            "parent_world_model_snapshot_digest": "wm-8",
        }),
    )

    assert all(item.proposal_kind != "representation_support" for item in batch.proposals)


def test_cognition_adapter_is_conversion_only_and_preserves_lineage():
    requirement = _requirement("identity")
    result = _result(requirement)
    batch = build_evidence_proposals(
        result,
        cognition_round=_round((requirement,)).model_copy(update={
            "round_id": "r",
            "wm_epoch": "8",
            "parent_world_model_snapshot_digest": "wm-8",
        }),
    )

    proposals = to_cognition_assertion_proposals(batch)

    assert len(proposals) == 1
    assert proposals[0].proposal_ref == batch.proposals[0].proposal_ref
    assert proposals[0].requirement_refs == ("req-1",)
    assert proposals[0].parent_current_world_digest == "wm-8"
