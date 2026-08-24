from app.contracts.evidence import (
    EvidenceClaim,
    EvidenceCoverage,
    EvidenceRequirement,
    RequirementCoverage,
)
from app.contracts.evidence.evidence_contracts import (
    EvidenceBundle,
    EvidenceFact,
    EvidenceSource,
    ExplorationRequest,
    ExplorationResult,
)
from app.evidence.retrieval.coverage import build_evidence_coverage
from app.evidence.retrieval.requirements import compile_requirements
from app.evidence.retrieval.sufficiency import evaluate_sufficiency


def test_compile_requirements_is_stable_and_keeps_scope() -> None:
    request = ExplorationRequest(
        run_id="run-1",
        request_type="evidence_gap",
        query="公共服务设施覆盖",
        questions=["主要居民点"],
        required_facts=["服务半径"],
        entity_scope=["facilities", "settlements"],
    )

    first = compile_requirements(request)
    second = compile_requirements(request)

    assert first == second
    assert [item.requirement_id for item in first]
    assert all(item.required for item in first)
    assert all(item.scope == ("facilities", "settlements") for item in first)
    assert all(item.source_families for item in first)


def test_coverage_records_supported_claims_and_stop_reason() -> None:
    request = ExplorationRequest(
        run_id="run-1",
        request_type="fact_check",
        query="服务半径",
        required_facts=["服务半径"],
    )
    result = ExplorationResult(
        evidence_bundle=EvidenceBundle(
            request=request.query,
            facts=[
                EvidenceFact(
                    statement="服务半径为 15 分钟",
                    source_refs=["report-1"],
                    source_locator="report-1:p3",
                    evidence_span="服务半径为 15 分钟",
                )
            ],
            sources=[
                EvidenceSource(
                    source_type="report",
                    reference="report-1",
                    evidence_role="planning_background",
                    authority="project_report",
                )
            ],
        )
    )
    decision = evaluate_sufficiency(request, result)

    coverage = build_evidence_coverage(request, result, decision)

    assert isinstance(coverage, EvidenceCoverage)
    assert coverage.stop_reason == "sufficient"
    assert coverage.sufficient is True
    assert coverage.requirement_coverage[0].status == "supported"
    assert coverage.claims[0].status == "supported"
    assert coverage.claims[0].locators == ("report-1:p3", "服务半径为 15 分钟")


def test_coverage_fails_closed_when_sources_are_unavailable() -> None:
    request = ExplorationRequest(
        run_id="run-1",
        request_type="spatial_lookup",
        query="道路位置",
        required_facts=["道路位置"],
        entity_scope=["roads"],
    )
    result = ExplorationResult(evidence_bundle=EvidenceBundle(request=request.query))
    decision = evaluate_sufficiency(request, result)

    coverage = build_evidence_coverage(request, result, decision)

    assert coverage.stop_reason == "source_exhausted"
    assert coverage.sufficient is False
    assert coverage.requirement_coverage[0].status == "unavailable"
    assert coverage.unresolved_requirements == (coverage.requirement_coverage[0].requirement_id,)


def test_claim_and_requirement_contracts_reject_empty_identity() -> None:
    try:
        EvidenceClaim(claim_id="", statement="x")
    except ValueError:
        pass
    else:
        raise AssertionError("empty claim identity must be rejected")

    try:
        EvidenceRequirement(requirement_id="", statement="x")
    except ValueError:
        pass
    else:
        raise AssertionError("empty requirement identity must be rejected")

    try:
        RequirementCoverage(requirement_id="", status="supported")
    except ValueError:
        pass
    else:
        raise AssertionError("empty coverage identity must be rejected")
