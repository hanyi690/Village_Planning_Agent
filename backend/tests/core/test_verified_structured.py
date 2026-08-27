"""Focused tests for the generic verified structured-decision kernel."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel, ValidationError

from app.contracts.llm.decision_contracts import (
    ClosedSetRef,
    DecisionCertificate,
    DecisionContext,
    PendingDecision,
    QuarantinedRecord,
    RepairOperation,
    RetryState,
    SemanticIssue,
    SemanticValidationOutcome,
    SourceSpanRef,
    VerifiedDecisionResult,
    stable_digest,
)
from app.domain.validation.repair_operations import evaluate_repair_policy
from app.infrastructure.llm.verified_structured import run_verified_structured_decision


class _Proposal(BaseModel):
    record_id: str
    value: int


class _StructuredResult:
    async def ainvoke(self, _messages):
        return _Proposal(record_id="proposal:1", value=7)


class _Llm:
    def with_structured_output(self, _response_model, *, method):
        assert method == "function_calling"
        return _StructuredResult()


def _context() -> DecisionContext:
    return DecisionContext(stage="unit", object_type="proposal", input_digest="input-digest")


def _issue() -> SemanticIssue:
    return SemanticIssue(
        stage="unit",
        code="semantic_problem",
        object_ref="proposal:1",
        field_path="value",
        dependency_refs=["claim:b", "claim:a"],
    )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ClosedSetRef(namespace="claim", ref_id="claim-1"),
        lambda: SourceSpanRef(segment_id="segment-1", start=0, end=1, quote_hash="hash"),
        _context,
        _issue,
        lambda: QuarantinedRecord(record_ref="proposal:1", payload_digest="payload", reason_code="bad"),
        lambda: PendingDecision(decision_ref="proposal:1", reason_code="evidence_missing"),
        lambda: RepairOperation(
            object_ref="proposal:1",
            field_path="value",
            reason_code="shape",
            repair_kind="shape_only",
        ),
        lambda: DecisionCertificate(input_digest="input"),
        RetryState,
        lambda: VerifiedDecisionResult(
            certificate=DecisionCertificate(input_digest="input"),
            retry_state=RetryState(),
        ),
    ],
)
def test_decision_contracts_forbid_extra_fields(factory):
    instance = factory()
    with pytest.raises(ValidationError):
        type(instance).model_validate({**instance.model_dump(mode="json"), "unexpected": True})


def test_issue_fingerprint_is_stable_across_reference_order_and_message_changes():
    first = _issue()
    second = SemanticIssue(
        stage="unit",
        code="semantic_problem",
        object_ref="proposal:1",
        field_path="value",
        dependency_refs=["claim:a", "claim:b"],
        message="provider wording is not part of decision identity",
    )

    assert first.fingerprint == second.fingerprint
    assert first.issue_id == second.issue_id
    assert stable_digest({"b": 2, "a": 1}) == stable_digest({"a": 1, "b": 2})


@pytest.mark.asyncio
async def test_verified_runner_routes_semantic_validator_result_and_records_digests():
    issue = _issue()

    async def validator(_context, proposal):
        return SemanticValidationOutcome[_Proposal](
            accepted=[proposal],
            quarantined=[
                QuarantinedRecord(
                    record_ref="proposal:2",
                    payload_digest="quarantined-payload",
                    issue_fingerprints=[issue.fingerprint],
                    reason_code="semantic_problem",
                )
            ],
            pending=[PendingDecision(decision_ref="proposal:3", reason_code="needs_evidence")],
            issues=[issue],
        )

    result = await run_verified_structured_decision(
        decision_context=_context(),
        proposal_model_factory=lambda _context: _Proposal,
        messages=[{"role": "user", "content": "proposal"}],
        semantic_validator=validator,
        llm=_Llm(),
    )

    assert [item.record_id for item in result.accepted] == ["proposal:1"]
    assert [item.record_ref for item in result.quarantined] == ["proposal:2"]
    assert [item.decision_ref for item in result.pending] == ["proposal:3"]
    assert result.issues == [issue]
    assert result.certificate.input_digest == "input-digest"
    assert result.certificate.schema_digest
    assert result.certificate.prompt_digest
    assert result.certificate.output_digest
    assert result.retry_state.progress_made is True


@pytest.mark.asyncio
async def test_verified_runner_preserves_transport_failure_code_as_pending(monkeypatch):
    from app.infrastructure.llm import verified_structured

    async def failing_runner(*_args, **_kwargs):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(verified_structured, "run_structured_output", failing_runner)

    result = await run_verified_structured_decision(
        decision_context=_context(),
        proposal_model_factory=lambda _context: _Proposal,
        messages=[{"role": "user", "content": "proposal"}],
        semantic_validator=lambda _context, proposal: SemanticValidationOutcome[_Proposal](accepted=[proposal]),
    )

    assert result.accepted == []
    assert result.pending[0].reason_code == "TIMEOUT"
    assert result.retry_state.transport_failure_code == "TIMEOUT"


def test_repair_policy_requires_evidence_for_semantic_change_and_never_silently_removes_hard_relation():
    missing_evidence = RepairOperation(
        object_ref="claim:1",
        field_path="action",
        reason_code="default_action",
        repair_kind="semantic_change",
    )
    hard_relation_removal = RepairOperation(
        object_ref="claim:1",
        field_path="relations.0",
        reason_code="incompatible_relation",
        repair_kind="semantic_change",
        operation="remove",
        hard_relation=True,
        evidence_refs=[ClosedSetRef(namespace="source_segment", ref_id="segment-1")],
    )
    identity_resolution = RepairOperation(
        object_ref="claim:1",
        field_path="source_ref",
        reason_code="closed_set_match",
        repair_kind="identity_resolution",
    )

    assert evaluate_repair_policy(missing_evidence).reason_code == "semantic_change_requires_evidence"
    assert evaluate_repair_policy(hard_relation_removal).reason_code == "hard_relation_removal_requires_review"
    assert evaluate_repair_policy(identity_resolution).status == "auto_apply"


@pytest.mark.asyncio
async def test_same_input_same_issue_and_same_accepted_set_stops_retry_loop():
    async def validator(_context, proposal):
        return SemanticValidationOutcome[_Proposal](accepted=[proposal], issues=[_issue()])

    first = await run_verified_structured_decision(
        decision_context=_context(),
        proposal_model_factory=lambda _context: _Proposal,
        messages=[{"role": "user", "content": "proposal"}],
        semantic_validator=validator,
        llm=_Llm(),
    )
    second = await run_verified_structured_decision(
        decision_context=_context(),
        proposal_model_factory=lambda _context: _Proposal,
        messages=[{"role": "user", "content": "proposal"}],
        semantic_validator=validator,
        previous_retry_state=first.retry_state,
        llm=_Llm(),
    )

    assert second.retry_state.no_progress is True
    assert second.retry_state.should_stop is True
    assert second.retry_state.progress_made is False
