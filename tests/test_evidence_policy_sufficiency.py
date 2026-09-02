from datetime import datetime, timezone

import pytest

from app.contracts.evidence.acquisition_contracts import (
    EvidenceAcquisitionReceipt,
    EvidenceObservationSnapshot,
)
from app.contracts.evidence.evidence_contracts import (
    EvidenceBundle,
    EvidenceFact,
    EvidenceSource,
    ExplorationRequest,
    ExplorationResult,
)
from app.contracts.evidence.provider_attempt import EvidenceObservationRecord, ProviderAttempt
from app.contracts.evidence.requirement_contracts import EvidenceRequirement
from app.modules.evidence.sufficiency import SufficiencyStatus, evaluate_sufficiency
from app.modules.evidence.coverage import build_evidence_coverage
from app.modules.evidence.application import _coverage_and_outcome


def _requirement(
    *,
    policy_ref: str = "road_identity.v1",
    statement: str = "road R1 exists",
    allowed_inference: str = "exact",
    source_families: tuple[str, ...] = (),
) -> EvidenceRequirement:
    return EvidenceRequirement(
        requirement_id="req-1",
        statement=statement,
        kind="identity",
        policy_ref=policy_ref,
        allowed_inference=allowed_inference,
        source_families=source_families,
    )


def _receipt(
    *,
    completion: str = "complete",
    origin_completeness: str = "not_applicable",
    termination_reasons: tuple[str, ...] = (),
    attempts: tuple[ProviderAttempt, ...] = (),
) -> EvidenceAcquisitionReceipt:
    return EvidenceAcquisitionReceipt(
        receipt_ref="receipt-1",
        query_plan_ref="plan-1",
        query_plan_fingerprint="a" * 64,
        attempt_refs=tuple(item.attempt_ref for item in attempts),
        required_route_refs=("route-1",),
        completed_required_routes=("route-1",) if completion == "complete" else (),
        incomplete_required_routes=("route-1",) if completion != "complete" else (),
        completion_basis=(
            "required_routes_complete" if completion == "complete" else "required_route_incomplete"
        ),
        origin_completeness=origin_completeness,
        completion=completion,
        termination_reasons=termination_reasons,
    )


def _result(
    requirement: EvidenceRequirement,
    *,
    facts: tuple[EvidenceFact, ...] = (),
    sources: tuple[EvidenceSource, ...] = (),
    receipt: EvidenceAcquisitionReceipt | None = None,
    attempts: tuple[ProviderAttempt, ...] = (),
) -> ExplorationResult:
    records = tuple(
        EvidenceObservationRecord(
            observation_ref=f"observation-{fact.fact_id}",
            attempt_ref="attempt-1",
            route_ref="route-1",
            provider="data_catalog",
            source_family="gis",
            source_ref=fact.source_refs[0] if fact.source_refs else "",
            source_refs=tuple(fact.source_refs),
            statement=fact.statement,
            valid_time=str(fact.fields.get("valid_time") or ""),
        )
        for fact in facts
    )
    snapshot = EvidenceObservationSnapshot(
        snapshot_ref="snapshot-1",
        query_plan_ref="plan-1",
        query_plan_fingerprint="a" * 64,
        observation_refs=tuple(item.observation_ref for item in records),
        source_refs=tuple(
            dict.fromkeys(
                source_ref
                for item in records
                for source_ref in item.source_refs
            )
        ),
        records=records,
        complete=True,
    )
    return ExplorationResult(
        evidence_bundle=EvidenceBundle(
            request=requirement.statement,
            facts=list(facts),
            sources=list(sources),
        ),
        acquisition_receipt=receipt or _receipt(attempts=attempts),
        provider_attempts=attempts,
        observation_snapshot=snapshot,
    )


def _fact(
    source_ref: str = "source-1",
    *,
    value: str = "present",
    inference_level: str = "exact",
    geometry_authority: str = "none",
    legal_authority: str = "none",
    valid_time: str = "2026-09-01T00:00:00+00:00",
) -> EvidenceFact:
    return EvidenceFact(
        fact_id=f"fact-{source_ref}-{value}",
        statement="road R1 exists",
        source_refs=[source_ref],
        spatial_refs=["road:R1"] if geometry_authority != "none" else [],
        fields={
            "value": value,
            "inference_level": inference_level,
            "geometry_authority": geometry_authority,
            "legal_authority": legal_authority,
            "valid_time": valid_time,
        },
        source_locator=f"data://roads/{source_ref}",
    )


def _source(
    reference: str = "source-1",
    *,
    source_type: str = "gis_layer",
    authority: str = "authoritative",
    retrieved_at: str = "2026-09-01T00:00:00+00:00",
) -> EvidenceSource:
    return EvidenceSource(
        source_type=source_type,
        reference=reference,
        authority=authority,
        retrieved_at=retrieved_at,
    )


def test_policy_gates_reject_wrong_family_authority_and_inference():
    requirement = _requirement(allowed_inference="exact", source_families=("data",))
    result = _result(
        requirement,
        facts=(_fact(inference_level="derived"),),
        sources=(_source(source_type="report", authority="advisory"),),
    )

    decision = evaluate_sufficiency(
        ExplorationRequest(
            run_id="run-1",
            request_type="fact_check",
            query=requirement.statement,
            requirements=[requirement],
        ),
        result,
    )

    requirement_decision = decision.policy_result.requirement_decisions[0]
    assert decision.status == SufficiencyStatus.INSUFFICIENT
    assert [item.gate for item in requirement_decision.checks] == [
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
    assert requirement_decision.checks[0].status == "fail"
    assert requirement_decision.checks[1].status == "fail"
    assert requirement_decision.checks[6].status == "fail"


def test_authoritative_exact_evidence_with_complete_receipt_is_sufficient():
    requirement = _requirement()
    result = _result(
        requirement,
        facts=(_fact(),),
        sources=(_source(),),
    )
    request = ExplorationRequest(
        run_id="run-1",
        request_type="fact_check",
        query=requirement.statement,
        requirements=[requirement],
    )

    decision = evaluate_sufficiency(request, result)

    assert decision.status == SufficiencyStatus.SUFFICIENT
    assert decision.policy_result.requirement_decisions[0].conclusion_kind == "presence"
    assert all(
        item.status == "pass"
        for item in decision.policy_result.requirement_decisions[0].checks
        if item.gate != "absence_policy"
    )


def test_fact_without_typed_observation_cannot_become_candidate_evidence():
    requirement = _requirement()
    result = _result(
        requirement,
        facts=(_fact(),),
        sources=(_source(),),
    ).model_copy(update={"observation_snapshot": None})
    request = ExplorationRequest(
        run_id="run-observation-boundary",
        request_type="fact_check",
        query=requirement.statement,
        requirements=[requirement],
    )

    decision = evaluate_sufficiency(request, result)

    assert decision.candidate_evidence == ()
    assert decision.status == SufficiencyStatus.INSUFFICIENT


def test_policy_gates_reject_stale_evidence_and_wrong_geometry_or_legal_authority():
    requirement = _requirement(
        policy_ref="legal_extent_support.v1",
    ).model_copy(update={"valid_time": "2026-09-01T00:00:00+00:00"})
    result = _result(
        requirement,
        facts=(_fact(
            geometry_authority="none",
            legal_authority="advisory",
            valid_time="2020-01-01T00:00:00+00:00",
        ),),
        sources=(_source(),),
    )

    decision = evaluate_sufficiency(
        ExplorationRequest(
            run_id="run-1",
            request_type="fact_check",
            query=requirement.statement,
            requirements=[requirement],
        ),
        result,
    )

    checks = decision.policy_result.requirement_decisions[0].checks
    assert checks[3].status == "fail"
    assert checks[4].status == "fail"
    assert decision.status == SufficiencyStatus.INSUFFICIENT


def test_independent_source_and_conflict_policy_are_requirement_specific():
    requirement = _requirement(policy_ref="absence_claim.v1")
    facts = (
        _fact("source-1", value="present"),
        _fact("source-2", value="absent"),
    )
    result = _result(
        requirement,
        facts=facts,
        sources=(_source("source-1"), _source("source-2")),
    )

    decision = evaluate_sufficiency(
        ExplorationRequest(
            run_id="run-1",
            request_type="fact_check",
            query=requirement.statement,
            requirements=[requirement],
        ),
        result,
    )

    requirement_decision = decision.policy_result.requirement_decisions[0]
    assert len(decision.candidate_evidence) == 2
    assert len(decision.conflict_sets) == 1
    assert requirement_decision.checks[2].status == "pass"
    assert requirement_decision.checks[5].status == "fail"
    assert decision.status == SufficiencyStatus.HUMAN_REQUIRED


def test_incomplete_acquisition_and_provider_origin_cannot_be_sufficient():
    requirement = _requirement(policy_ref="source_semantic_support.v1")
    attempt = ProviderAttempt(
        attempt_ref="attempt-1",
        route_ref="route-1",
        provider="frozen_cache",
        stage="EVIDENCE",
        status="SUCCESS_NONEMPTY",
        metadata={"completion": "bounded_query_complete"},
    )
    result = _result(
        requirement,
        facts=(_fact("source-1"),),
        sources=(_source(source_type="external", authority="advisory"),),
        receipt=_receipt(
            completion="partial",
            origin_completeness="incomplete",
            attempts=(attempt,),
        ),
        attempts=(attempt,),
    )

    decision = evaluate_sufficiency(
        ExplorationRequest(
            run_id="run-1",
            request_type="fact_check",
            query=requirement.statement,
            requirements=[requirement],
        ),
        result,
    )

    checks = decision.policy_result.requirement_decisions[0].checks
    assert checks[7].status == "fail"
    assert checks[8].status == "fail"
    assert decision.status == SufficiencyStatus.INSUFFICIENT


def test_absence_is_last_and_requires_provider_exhaustion_and_two_sources():
    requirement = EvidenceRequirement(
        requirement_id="req-absence",
        statement="no road R1 exists",
        kind="claim",
        policy_ref="absence_claim.v1",
    )
    attempt = ProviderAttempt(
        attempt_ref="attempt-absence",
        route_ref="route-1",
        provider="data_catalog",
        stage="EVIDENCE",
        status="SUCCESS_EMPTY",
        reason_code="bounded_query_complete",
        metadata={"completion": "bounded_query_complete"},
    )
    result = _result(
        requirement,
        sources=(_source("source-1", source_type="data"), _source("source-2", source_type="kg")),
        receipt=_receipt(
            termination_reasons=("provider_exhausted",),
            attempts=(attempt,),
        ),
        attempts=(attempt,),
    )
    request = ExplorationRequest(
        run_id="run-absence",
        request_type="fact_check",
        query=requirement.statement,
        requirements=[requirement],
    )

    decision = evaluate_sufficiency(request, result)

    requirement_decision = decision.policy_result.requirement_decisions[0]
    assert decision.status == SufficiencyStatus.SUFFICIENT
    assert requirement_decision.conclusion_kind == "absence"
    assert requirement_decision.absence_authorized is True
    assert requirement_decision.checks[-1].gate == "absence_policy"
    assert requirement_decision.checks[-1].status == "pass"

    coverage = build_evidence_coverage(
        request,
        result,
        decision,
        requirements=(requirement,),
    )
    assert coverage.sufficient is True
    assert coverage.requirement_coverage[0].conclusion_kind == "absence"


def test_success_empty_without_complete_exhaustion_never_means_absence():
    requirement = EvidenceRequirement(
        requirement_id="req-absence",
        statement="no road R1 exists",
        kind="claim",
        policy_ref="absence_claim.v1",
    )
    attempt = ProviderAttempt(
        attempt_ref="attempt-empty",
        route_ref="route-1",
        provider="data_catalog",
        stage="EVIDENCE",
        status="SUCCESS_EMPTY",
        reason_code="bounded_query_complete",
        metadata={"completion": "bounded_query_complete"},
    )
    result = _result(
        requirement,
        sources=(_source("source-1", source_type="data"),),
        receipt=_receipt(attempts=(attempt,)),
        attempts=(attempt,),
    )

    decision = evaluate_sufficiency(
        ExplorationRequest(
            run_id="run-absence",
            request_type="fact_check",
            query=requirement.statement,
            requirements=[requirement],
        ),
        result,
    )

    requirement_decision = decision.policy_result.requirement_decisions[0]
    assert requirement_decision.conclusion_kind == "none"
    assert requirement_decision.absence_authorized is False
    assert requirement_decision.checks[-1].status == "fail"
    assert decision.status in {SufficiencyStatus.INSUFFICIENT, SufficiencyStatus.NOT_AVAILABLE}


@pytest.mark.parametrize("attempt_status", ["NOT_ATTEMPTED", "MISSING_CAPABILITY", "PARTIAL", "QUOTA_EXHAUSTED"])
def test_non_success_attempt_status_cannot_satisfy_complete_acquisition(attempt_status: str):
    requirement = _requirement()
    attempt = ProviderAttempt(
        attempt_ref=f"attempt-{attempt_status.lower()}",
        route_ref="route-1",
        provider="data_catalog",
        stage="EVIDENCE",
        status=attempt_status,
    )
    result = _result(
        requirement,
        facts=(_fact(),),
        sources=(_source(),),
        receipt=_receipt(attempts=(attempt,)),
        attempts=(attempt,),
    )

    decision = evaluate_sufficiency(
        ExplorationRequest(
            run_id="run-attempt-status",
            request_type="fact_check",
            query=requirement.statement,
            requirements=[requirement],
        ),
        result,
    )

    assert decision.status == SufficiencyStatus.INSUFFICIENT
    assert decision.policy_result.requirement_decisions[0].checks[7].status == "fail"


def test_coverage_persists_candidates_conflicts_and_requirement_gate_results():
    requirement = _requirement()
    result = _result(
        requirement,
        facts=(_fact(),),
        sources=(_source(),),
    )
    request = ExplorationRequest(
        run_id="run-coverage",
        request_type="fact_check",
        query=requirement.statement,
        requirements=[requirement],
    )
    decision = evaluate_sufficiency(request, result)

    coverage = build_evidence_coverage(
        request,
        result,
        decision,
        requirements=(requirement,),
    )

    assert coverage.sufficiency_decision == decision.policy_result
    assert len(coverage.candidate_evidence) == 1
    assert coverage.requirement_coverage[0].candidate_refs == (
        coverage.candidate_evidence[0].candidate_ref,
    )
    assert len(coverage.requirement_coverage[0].sufficiency_checks) == 10
    reloaded = type(coverage).model_validate(coverage.model_dump(mode="json"))
    assert reloaded.sufficiency_decision == coverage.sufficiency_decision


def test_application_normalization_uses_ev02_as_packet_and_outcome_source():
    requirement = _requirement()
    request = ExplorationRequest(
        run_id="run-application",
        request_type="fact_check",
        query=requirement.statement,
        requirements=[requirement],
    )
    result = _result(
        requirement,
        facts=(_fact(),),
        sources=(_source(),),
    )

    normalized = _coverage_and_outcome(request, (requirement,), result)

    assert normalized.outcome is not None
    assert normalized.outcome.status == "sufficient"
    assert normalized.evidence_packet is not None
    assert normalized.evidence_packet.sufficiency == "sufficient"
    assert normalized.coverage is not None
    assert normalized.coverage.sufficiency_decision is not None
