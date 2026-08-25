"""GROUND gate evaluator - 3-route decision over a GroundingResult.

Pure function: GroundingResult -> GateDecision. No I/O. Mirrors the gate
convention in app.domain.{assessment,objectives,program} gates with
stage="ground".

Routes (precedence high -> low):
  EXPLORE -> no candidates were produced and there is no target-specific
             unresolved reference (request evidence exploration)
  HUMAN   -> target-specific unresolved references or ambiguous candidates
             require an explicit human decision
  PASS    -> all specs resolved, candidates non-empty, no ambiguity

Determinism: routing is a pure function of the result fields, no RNG, no LLM.
"""
from __future__ import annotations

from app.contracts.spatial.grounding_contracts import CandidateSite, GroundingResult
from app.contracts.planning.p1_closure import build_decision_fingerprint
from app.contracts.workflow.workflow_contracts import GateDecision, PendingRequest

STAGE = "ground"


def _confidence_fields(candidate: CandidateSite) -> tuple[float, float, list[str], bool]:
    geometry = getattr(candidate, "geometry", None)
    if geometry is not None:
        return (
            float(getattr(geometry, "identity_confidence", 0.0) or 0.0),
            float(getattr(geometry, "geometry_confidence", 0.0) or 0.0),
            list(getattr(geometry, "schema_diagnostics", None) or []),
            bool(getattr(geometry, "grounding_confidence_trusted", False)),
        )
    return (
        float(getattr(candidate, "identity_confidence", 0.0) or 0.0),
        float(getattr(candidate, "geometry_confidence", 0.0) or 0.0),
        list(getattr(candidate, "schema_diagnostics", None) or []),
        False,
    )


def _is_ambiguous(candidate: CandidateSite, ambiguity_threshold: float) -> bool:
    geometry = getattr(candidate, "geometry", None)
    identity_confidence, geometry_confidence, diagnostics, trusted = _confidence_fields(candidate)
    if geometry is None:
        return True
    if not trusted:
        return True
    if diagnostics:
        return True
    return (
        len(candidate.source_parcels) > 1
        and min(identity_confidence, geometry_confidence) < ambiguity_threshold
    )


def _problem_readiness_issues(result: GroundingResult) -> list[dict[str, object]]:
    """Project typed problem incompleteness into GROUND gate evidence.

    GROUND may still contain candidate-dependent relation satisfaction, but it
    must not pass a problem whose target/candidate domains are unresolved or
    whose hard relation inputs are not computable.  Solver-specific readiness
    remains a SELECT concern; this small projection only prevents the old
    false PASS after unresolved targets were manually deferred.
    """

    problem = getattr(result, "problem", None)
    if problem is None:
        return []

    issues: list[dict[str, object]] = []
    completeness = getattr(problem, "candidate_completeness", None)
    completeness_status = str(getattr(completeness, "status", "") or "")
    if completeness is not None and completeness_status != "candidate_complete":
        issues.append({
            "code": f"candidate_completeness:{completeness_status or 'missing'}",
            "message": "; ".join(getattr(completeness, "reasons", ()) or ())
            or "candidate completeness is not closed",
            "ref": f"candidate_completeness:{completeness_status or 'missing'}",
        })

    for domain in list(getattr(problem, "target_domains", None) or ()):
        status = str(getattr(domain, "status", "unresolved") or "unresolved")
        if status != "resolved":
            target_id = str(getattr(domain, "target_id", "") or "")
            issues.append({
                "code": f"target_domain:{status}",
                "message": f"target {target_id or 'unknown'} is {status}",
                "ref": f"target:{target_id or 'unknown'}",
            })

    for domain in list(getattr(problem, "candidate_domains", None) or ()):
        status = str(getattr(domain, "status", "unresolved") or "unresolved")
        if status != "resolved":
            target_id = str(getattr(domain, "target_id", "") or "")
            issues.append({
                "code": f"candidate_domain:{status}",
                "message": f"candidate domain for {target_id or 'unknown'} is {status}",
                "ref": f"target:{target_id or 'unknown'}",
            })

    factors = list(getattr(problem, "constraint_factors", None) or ())
    for factor in factors:
        if not bool(getattr(factor, "hard", False)):
            continue
        factor_id = str(getattr(factor, "factor_id", "") or "unknown")
        if str(getattr(factor, "semantic_status", "valid")) != "valid":
            issues.append({
                "code": "relation_semantic_invalid",
                "message": f"hard relation {factor_id} has invalid semantics",
                "ref": f"relation:{factor_id}",
            })
        if str(getattr(factor, "input_status", "ready")) != "ready":
            issues.append({
                "code": "relation_input_not_ready",
                "message": f"hard relation {factor_id} input is {getattr(factor, 'input_status', '')}",
                "ref": f"relation:{factor_id}",
            })
        if getattr(factor, "solver_supported", True) is False:
            issues.append({
                "code": "relation_solver_unsupported",
                "message": f"hard relation {factor_id} has no supported solver backend",
                "ref": f"relation:{factor_id}",
            })

    for satisfaction in list(getattr(problem, "relation_satisfaction", None) or ()):
        if str(getattr(satisfaction, "input_status", "ready")) != "ready":
            relation_id = str(getattr(satisfaction, "relation_id", "") or "unknown")
            issues.append({
                "code": "relation_satisfaction_input_not_ready",
                "message": f"relation {relation_id} input is not ready",
                "ref": f"relation:{relation_id}",
            })
    return issues


def ground_gate_route(
    result: GroundingResult,
    *,
    ambiguity_threshold: float = 0.6,
    expected_spec_count: int | None = None,
) -> str:
    """Return the deterministic route for ``result``: "PASS"|"EXPLORE"|"HUMAN"."""
    problem_issues = _problem_readiness_issues(result)
    if expected_spec_count == 0 and not result.unresolved and not problem_issues:
        return "PASS"
    if result.unresolved:
        return "HUMAN"
    if problem_issues and any(
        str(item.get("code", "")).startswith((
            "candidate_completeness:not_groundable",
            "target_domain:unresolved",
            "candidate_domain:unresolved",
        ))
        for item in problem_issues
    ):
        return "HUMAN"
    if not result.candidates:
        return "EXPLORE"
    if problem_issues:
        return "HUMAN"
    if any(_is_ambiguous(c, ambiguity_threshold) for c in result.candidates):
        return "HUMAN"
    return "PASS"


def evaluate_ground_gate(
    result: GroundingResult,
    *,
    ambiguity_threshold: float = 0.6,
    expected_spec_count: int | None = None,
) -> GateDecision:
    stage = STAGE
    cv = result.context_version
    gate_artifact_id = "gate-ground-" + (result.artifact_id or "0")

    route = ground_gate_route(
        result,
        ambiguity_threshold=ambiguity_threshold,
        expected_spec_count=expected_spec_count,
    )

    if route == "EXPLORE":
        pending = [
            PendingRequest(
                request_id=f"pr-ground-unresolved-{index}",
                stage="explore",
                request_type="spatial_reference_unresolved",
                context={
                    "reason": "spatial_reference_unresolved",
                    "message": issue.message,
                    "detail": issue.detail or "",
                },
            )
            for index, issue in enumerate(result.unresolved)
        ]
        return GateDecision(
            stage=stage,
            passed=False,
            feedback_route="EXPLORE",
            pending_requests=pending,
            context_version=cv,
            artifact_id=gate_artifact_id,
        )

    if route == "HUMAN":
        pending = [
            PendingRequest(
                request_id=f"pr-ground-unresolved-{index}",
                stage="ground",
                request_type="spatial_reference_unresolved",
                context={
                    "reason": "spatial_reference_unresolved",
                    "message": issue.message,
                    "detail": issue.detail or "",
                    "target_ids": [issue.related_artifact_id]
                    if issue.related_artifact_id else [],
                },
            )
            for index, issue in enumerate(result.unresolved)
        ]
        for index, issue in enumerate(_problem_readiness_issues(result)):
            issue_ref = str(issue["ref"] or "")
            target_ref = issue_ref.removeprefix("target:") or "grounded-problem"
            decision_fingerprint = build_decision_fingerprint(
                target_ref=target_ref,
                constraint_fingerprint=str(
                    getattr(getattr(result, "problem", None), "fingerprint", "")
                    or ""
                ),
                evaluator_key="ground_gate",
                evaluator_version="ground-gate-v2",
            )
            pending.append(
                PendingRequest(
                    request_id=f"pr-ground-problem-{index}",
                    stage="ground",
                    request_type="ground_problem_readiness",
                    context={
                        "reason": issue["code"],
                        "message": issue["message"],
                        "ref": issue_ref,
                        "problem_fingerprint": str(
                            getattr(getattr(result, "problem", None), "fingerprint", "")
                            or ""
                        ),
                        "decision_fingerprint": decision_fingerprint.model_dump(mode="json"),
                    },
                )
            )
        return GateDecision(
            stage=stage,
            passed=False,
            feedback_route="HUMAN",
            pending_requests=pending,
            context_version=cv,
            artifact_id=gate_artifact_id,
            route_reason=(
                "typed_grounded_problem_not_ready"
                if _problem_readiness_issues(result)
                else "unresolved_spatial_reference"
            ),
        )

    return GateDecision(
        stage=stage,
        passed=True,
        feedback_route=None,
        context_version=cv,
        artifact_id=gate_artifact_id,
    )


__all__ = ["evaluate_ground_gate", "ground_gate_route"]
