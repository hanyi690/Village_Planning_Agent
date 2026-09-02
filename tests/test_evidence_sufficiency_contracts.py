import pytest
from pydantic import ValidationError

from app.contracts.evidence.reasoning_contracts import (
    CandidateEvidence,
    ConflictSet,
    EvidenceSufficiencyResult,
    RequirementSufficiencyDecision,
    SufficiencyCheck,
)


def test_candidate_evidence_has_stable_auditable_lineage():
    candidate = CandidateEvidence(
        candidate_ref="evidence.candidate.req-1.fact-1",
        requirement_ref="req-1",
        observation_refs=("observation-1",),
        claim_refs=("claim-1",),
        source_refs=("source-1",),
        source_families=("data",),
        source_authorities=("authoritative",),
        geometry_authorities=("data_resource_catalog",),
        legal_authorities=("none",),
        independent_source_refs=("source-1",),
        valid_times=("2026-09-01T00:00:00+00:00",),
        inference_levels=("exact",),
        statement="road R1 exists",
        value_digest="value-1",
        locator_refs=("data://roads/R1",),
        confidence=0.9,
    )

    assert candidate.requirement_ref == "req-1"
    assert candidate.independent_source_refs == ("source-1",)
    assert candidate.model_config["extra"] == "forbid"


def test_conflict_set_is_requirement_scoped_and_immutable():
    conflict = ConflictSet(
        conflict_ref="evidence.conflict.req-1.value-1-value-2",
        requirement_ref="req-1",
        candidate_refs=("candidate-1", "candidate-2"),
        conflict_kind="value",
        policy="human",
        resolution_status="unresolved",
        reason="two authoritative sources disagree",
    )

    assert conflict.resolution_status == "unresolved"
    with pytest.raises((TypeError, ValidationError)):
        conflict.resolution_status = "resolved"


def test_sufficiency_requires_ordered_ten_gate_audit():
    checks = tuple(
        SufficiencyCheck(
            gate=gate,
            status="pass",
            reason=f"{gate} satisfied",
        )
        for gate in (
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
    )
    decision = RequirementSufficiencyDecision(
        requirement_ref="req-1",
        policy_ref="road_identity.v1",
        policy_version="1",
        status="sufficient",
        candidate_refs=("candidate-1",),
        checks=checks,
        conclusion_kind="presence",
        reason="all policy gates passed",
    )
    result = EvidenceSufficiencyResult(
        status="sufficient",
        requirement_decisions=(decision,),
        candidates=(CandidateEvidence(
            candidate_ref="candidate-1",
            requirement_ref="req-1",
            source_refs=("source-1",),
            source_families=("data",),
            source_authorities=("authoritative",),
            independent_source_refs=("source-1",),
            statement="road R1 exists",
            value_digest="value-1",
        ),),
    )

    assert [item.gate for item in decision.checks] == [
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
    ]
    assert result.absence_authorized is False


def test_absence_conclusion_cannot_be_claimed_without_authorization():
    with pytest.raises(ValidationError, match="absence"):
        RequirementSufficiencyDecision(
            requirement_ref="req-1",
            policy_ref="absence_claim.v1",
            policy_version="1",
            status="sufficient",
            conclusion_kind="absence",
            absence_authorized=False,
            reason="invalid absence",
        )
