"""Verified semantic-decision layer built on the typed output transport."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from pydantic import BaseModel

from app.contracts.llm.decision_contracts import (
    DecisionCertificate,
    DecisionContext,
    PendingDecision,
    RetryState,
    SemanticIssue,
    SemanticValidationOutcome,
    VerifiedDecisionResult,
    schema_digest,
    stable_digest,
)
from app.domain.validation.repair_operations import pending_repair_decisions
from app.infrastructure.llm.structured import run_structured_output, structured_failure_code


ProposalT = TypeVar("ProposalT", bound=BaseModel)
ProposalModelFactory = Callable[[DecisionContext], type[ProposalT]]
SemanticValidator = Callable[
    [DecisionContext, ProposalT],
    SemanticValidationOutcome[ProposalT] | Awaitable[SemanticValidationOutcome[ProposalT]],
]


def issue_fingerprint(issues: list[SemanticIssue]) -> str:
    """Return a stable summary fingerprint independent of issue ordering."""
    return stable_digest(sorted(issue.fingerprint for issue in issues)) if issues else ""


def same_input_no_progress(
    *,
    decision_context: DecisionContext,
    current_issue_fingerprint: str,
    accepted_digest: str,
    previous_retry_state: RetryState | None,
) -> bool:
    """Detect an unchanged input replay with unchanged findings and output."""
    if previous_retry_state is None:
        return False
    return bool(current_issue_fingerprint) and (
        previous_retry_state.input_digest == decision_context.input_digest
        and previous_retry_state.issue_fingerprint == current_issue_fingerprint
        and previous_retry_state.accepted_digest == accepted_digest
    )


def _record_ref(record: Any, index: int) -> str:
    for name in ("record_ref", "decision_ref", "id", "ref_id"):
        value = getattr(record, name, "")
        if str(value).strip():
            return str(value).strip()
    return f"accepted:{index}"


def _certificate(
    *,
    context: DecisionContext,
    outcome: SemanticValidationOutcome[ProposalT],
    accepted_digest: str,
) -> DecisionCertificate:
    accepted_refs = [_record_ref(record, index) for index, record in enumerate(outcome.accepted)]
    output = {
        "accepted": outcome.accepted,
        "quarantined": outcome.quarantined,
        "pending": outcome.pending,
        "issues": outcome.issues,
        "repair_operations": outcome.repair_operations,
    }
    return DecisionCertificate(
        input_digest=context.input_digest,
        schema_digest=context.schema_digest,
        prompt_digest=context.prompt_digest,
        candidate_set_digest=context.candidate_set_digest,
        output_digest=stable_digest(output),
        accepted_digest=accepted_digest,
        prompt_version=context.prompt_version,
        provider=context.provider,
        model=context.model,
        validator_version=context.validator_version,
        accepted_refs=accepted_refs,
        quarantined_refs=[record.record_ref for record in outcome.quarantined],
        pending_refs=[record.decision_ref for record in outcome.pending],
        issue_fingerprints=[issue.fingerprint for issue in outcome.issues],
        repair_operations=outcome.repair_operations,
    )


def _retry_state(
    *,
    context: DecisionContext,
    certificate: DecisionCertificate,
    issues: list[SemanticIssue],
    previous_retry_state: RetryState | None,
    transport_failure_code: str = "",
) -> RetryState:
    current_fingerprint = issue_fingerprint(issues)
    no_progress = same_input_no_progress(
        decision_context=context,
        current_issue_fingerprint=current_fingerprint,
        accepted_digest=certificate.accepted_digest,
        previous_retry_state=previous_retry_state,
    )
    return RetryState(
        attempt=(previous_retry_state.attempt + 1) if previous_retry_state else 1,
        input_digest=context.input_digest,
        issue_fingerprint=current_fingerprint,
        previous_issue_fingerprint=(previous_retry_state.issue_fingerprint if previous_retry_state else ""),
        accepted_digest=certificate.accepted_digest,
        output_digest=certificate.output_digest,
        transport_failure_code=transport_failure_code,
        inputs_changed=(
            previous_retry_state is None
            or previous_retry_state.input_digest != context.input_digest
        ),
        progress_made=not no_progress,
        no_progress=no_progress,
        should_stop=no_progress,
    )


async def _validate(
    semantic_validator: SemanticValidator[ProposalT],
    decision_context: DecisionContext,
    proposal: ProposalT,
) -> SemanticValidationOutcome[ProposalT]:
    outcome = semantic_validator(decision_context, proposal)
    if inspect.isawaitable(outcome):
        outcome = await outcome
    if not isinstance(outcome, SemanticValidationOutcome):
        raise TypeError("semantic_validator must return SemanticValidationOutcome")
    return outcome


def _merge_pending(
    pending: list[PendingDecision],
    additional: list[PendingDecision],
) -> list[PendingDecision]:
    unique: dict[tuple[str, str], PendingDecision] = {}
    for item in [*pending, *additional]:
        unique[(item.decision_ref, item.reason_code)] = item
    return [unique[key] for key in sorted(unique)]


async def run_verified_structured_decision(
    *,
    decision_context: DecisionContext,
    proposal_model_factory: ProposalModelFactory[ProposalT],
    messages: list[dict[str, Any]],
    semantic_validator: SemanticValidator[ProposalT],
    previous_retry_state: RetryState | None = None,
    model: str | None = None,
    max_retries: int = 2,
    timeout: float | None = None,
    llm: Any | None = None,
    **kwargs: Any,
) -> VerifiedDecisionResult[ProposalT]:
    """Generate one proposal then route it through deterministic semantics.

    Transport and schema failures remain distinguishable through the existing
    structured-output failure code.  Semantic failures are never folded into
    that code: validators route their records explicitly to accepted,
    quarantined, or pending collections.
    """
    proposal_model = proposal_model_factory(decision_context)
    context = decision_context.model_copy(
        update={
            "schema_digest": decision_context.schema_digest or schema_digest(proposal_model),
            "prompt_digest": decision_context.prompt_digest or stable_digest(messages),
        }
    )
    try:
        proposal = await run_structured_output(
            proposal_model,
            messages,
            model=model,
            max_retries=max_retries,
            timeout=timeout,
            llm=llm,
            **kwargs,
        )
    except Exception as exc:
        failure_code = structured_failure_code(exc) or "STRUCTURED_OUTPUT_ERROR"
        issue = SemanticIssue(
            stage=context.stage,
            code=failure_code,
            severity="error",
            fatal_scope="stage",
            object_ref=context.object_type,
            retryable=failure_code != "SCHEMA_INVALID",
            repair_kind="transport_or_schema",
            message="verified structured transport or schema execution failed",
        )
        outcome = SemanticValidationOutcome[ProposalT](
            pending=[
                PendingDecision(
                    decision_ref=context.object_type,
                    reason_code=failure_code,
                    issue_fingerprints=[issue.fingerprint],
                    requires_human_review=False,
                )
            ],
            issues=[issue],
        )
        accepted_digest = stable_digest([])
        certificate = _certificate(context=context, outcome=outcome, accepted_digest=accepted_digest)
        retry_state = _retry_state(
            context=context,
            certificate=certificate,
            issues=outcome.issues,
            previous_retry_state=previous_retry_state,
            transport_failure_code=failure_code,
        )
        return VerifiedDecisionResult[ProposalT](
            accepted=outcome.accepted,
            quarantined=outcome.quarantined,
            pending=outcome.pending,
            issues=outcome.issues,
            certificate=certificate,
            retry_state=retry_state,
        )

    try:
        outcome = await _validate(semantic_validator, context, proposal)
    except Exception as exc:
        issue = SemanticIssue(
            stage=context.stage,
            code="SEMANTIC_VALIDATOR_ERROR",
            severity="error",
            fatal_scope="stage",
            object_ref=context.object_type,
            retryable=False,
            repair_kind="semantic_validation",
            message="verified structured semantic validation failed unexpectedly",
        )
        outcome = SemanticValidationOutcome[ProposalT](
            pending=[
                PendingDecision(
                    decision_ref=context.object_type,
                    reason_code="semantic_validator_error",
                    issue_fingerprints=[issue.fingerprint],
                    requires_human_review=True,
                )
            ],
            issues=[issue],
        )

    pending_from_policy = pending_repair_decisions(outcome.repair_operations)
    outcome = outcome.model_copy(
        update={"pending": _merge_pending(outcome.pending, pending_from_policy)}
    )
    accepted_digest = stable_digest(outcome.accepted)
    certificate = _certificate(context=context, outcome=outcome, accepted_digest=accepted_digest)
    retry_state = _retry_state(
        context=context,
        certificate=certificate,
        issues=outcome.issues,
        previous_retry_state=previous_retry_state,
    )
    return VerifiedDecisionResult[ProposalT](
        accepted=outcome.accepted,
        quarantined=outcome.quarantined,
        pending=outcome.pending,
        issues=outcome.issues,
        certificate=certificate,
        retry_state=retry_state,
    )


__all__ = [
    "ProposalModelFactory",
    "SemanticValidator",
    "issue_fingerprint",
    "run_verified_structured_decision",
    "same_input_no_progress",
]
