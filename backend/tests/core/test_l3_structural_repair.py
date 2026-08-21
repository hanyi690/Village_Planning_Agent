"""Bounded structural repair for L3 claim sets that fail schema validation."""

import asyncio
from types import SimpleNamespace

import pytest

from app.domain.program import worker
from app.domain.program.claim_draft import L3DimensionOutput


class _SequentialOutput:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0
        self.feedbacks = []

    async def __call__(
        self,
        _generator,
        *,
        session_id,
        dimension_key,
        prompt,
        validation_feedback=None,
        require_report_body=True,
    ):
        self.feedbacks.append(list(validation_feedback or []))
        out = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        return out


def _bad_output():
    # suggested_category is not in the closed-set literal, so building the
    # PlanningClaimDraftSet fails schema validation.
    return SimpleNamespace(report_body="正文", claims=[
        {
            "claim_id": "C-1",
            "statement": "新建设施",
            "suggested_category": "bogus_category",
            "suggested_output_kind": "point",
        }
    ])


def _good_output():
    return L3DimensionOutput(report_body="正文", claims=[
        {
            "claim_id": "C-1",
            "statement": "新建设施",
            "suggested_category": "facility",
            "suggested_output_kind": "point",
            "facility_parameters": {"facility_type": "卫生室", "action": "new"},
        }
    ])


def test_structural_repair_retries_with_validation_feedback(monkeypatch):
    seq = _SequentialOutput([_bad_output(), _good_output()])
    monkeypatch.setattr(worker, "_cached_claim_generation", seq)
    monkeypatch.setenv("L3_STRUCTURAL_COMPILE_RETRIES", "2")

    draft_set, claim_set = asyncio.run(worker._normalize_with_structural_repair(
        object(),
        session_id="s1",
        dimension_key="infrastructure_planning",
        output=seq.outputs[0],
    ))

    assert seq.calls == 2
    assert seq.feedbacks[1], "second call must carry the validation error as feedback"
    assert draft_set is not None
    assert claim_set.claims
    assert claim_set.claims[0].suggested_category == "facility"


def test_structural_repair_exhausts_budget_and_raises(monkeypatch):
    seq = _SequentialOutput([_bad_output()])
    monkeypatch.setattr(worker, "_cached_claim_generation", seq)
    monkeypatch.setenv("L3_STRUCTURAL_COMPILE_RETRIES", "1")

    with pytest.raises(Exception):
        asyncio.run(worker._normalize_with_structural_repair(
            object(),
            session_id="s1",
            dimension_key="infrastructure_planning",
            output=seq.outputs[0],
        ))
    assert seq.calls == 1  # one repair round before the budget is exhausted


def test_valid_output_returns_without_extra_call(monkeypatch):
    seq = _SequentialOutput([_good_output()])
    monkeypatch.setattr(worker, "_cached_claim_generation", seq)

    draft_set, claim_set = asyncio.run(worker._normalize_with_structural_repair(
        object(),
        session_id="s1",
        dimension_key="infrastructure_planning",
        output=seq.outputs[0],
    ))

    assert seq.calls == 0  # a valid output needs no repair call
    assert claim_set.claims
