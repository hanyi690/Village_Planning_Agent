"""GROUND gate evaluator - 3-route decision over a GroundingResult.

Pure function: GroundingResult -> GateDecision. No I/O. Mirrors the gate
convention in app.agent.{l1_observe,l2_strategize,l3_plan,parse} with
stage="ground".

Routes (precedence high -> low):
  EXPLORE -> unresolved specs remain, or no candidates were produced
             (nothing resolved -> request exploration)
  HUMAN   -> some candidate is ambiguous: multiple source parcels with
             confidence below ``ambiguity_threshold`` (needs human review)
  PASS    -> all specs resolved, candidates non-empty, no ambiguity

Determinism: routing is a pure function of the result fields, no RNG, no LLM.
"""
from __future__ import annotations

from app.modules.schema.contracts.grounding_contracts import CandidateSite, GroundingResult
from app.modules.schema.contracts.workflow_contracts import GateDecision, PendingRequest

STAGE = "ground"


def _is_ambiguous(candidate: CandidateSite, ambiguity_threshold: float) -> bool:
    return (
        len(candidate.source_parcels) > 1
        and candidate.metrics.get("confidence", 0.0) < ambiguity_threshold
    )


def ground_gate_route(
    result: GroundingResult,
    *,
    ambiguity_threshold: float = 0.6,
    expected_spec_count: int | None = None,
) -> str:
    """Return the deterministic route for ``result``: "PASS"|"EXPLORE"|"HUMAN"."""
    if expected_spec_count == 0 and not result.unresolved:
        return "PASS"
    if result.unresolved or not result.candidates:
        return "EXPLORE"
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
        return GateDecision(
            stage=stage,
            passed=False,
            feedback_route="HUMAN",
            context_version=cv,
            artifact_id=gate_artifact_id,
        )

    return GateDecision(
        stage=stage,
        passed=True,
        feedback_route=None,
        context_version=cv,
        artifact_id=gate_artifact_id,
    )


__all__ = ["evaluate_ground_gate", "ground_gate_route"]
