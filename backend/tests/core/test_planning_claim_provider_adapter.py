"""Provider-boundary recovery tests for structured L3 claim responses."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.infrastructure.llm.planning_claims import PlanningClaimGenerator


class _StructuredInvoker:
    def __init__(self) -> None:
        self.calls = 0
        self.messages = []

    async def ainvoke(self, _messages):
        self.calls += 1
        self.messages.append(_messages)
        if self.calls == 1:
            return {"claims": "[{claim_id: broken}]"}
        return {
            "report_body": "Provide a small agricultural service point.",
            "claims": [
                {
                    "claim_id": "industry-1",
                    "statement": "Provide a small agricultural service point.",
                    "suggested_category": "facility",
                    "suggested_output_kind": "point",
                }
            ],
        }


class _FakeLLM:
    def __init__(self, invoker: _StructuredInvoker) -> None:
        self.invoker = invoker

    def with_structured_output(self, *_args, **_kwargs):
        return self.invoker


def test_provider_adapter_retries_malformed_nested_json(monkeypatch):
    invoker = _StructuredInvoker()
    generator = PlanningClaimGenerator()
    generator._llm = _FakeLLM(invoker)
    monkeypatch.setenv("L3_PROVIDER_PARSE_RETRIES", "1")

    result = asyncio.run(generator.generate("Generate one planning claim."))

    assert invoker.calls == 2
    assert result.report_body == "Provide a small agricultural service point."
    assert result.claims[0].claim_id == "industry-1"
    assert "Return both" in invoker.messages[0][1]["content"]
    assert "PlanningClaimSet only" not in invoker.messages[0][1]["content"]


def test_provider_adapter_queue_wait_is_bounded(monkeypatch):
    import app.infrastructure.llm.planning_claims as planning_claims

    generator = PlanningClaimGenerator()
    generator._slots = asyncio.Semaphore(1)
    monkeypatch.setattr(planning_claims, "LLM_STREAM_TIMEOUT", 0.01)

    async def scenario():
        await generator._slots.acquire()
        try:
            with pytest.raises(asyncio.TimeoutError):
                await generator.generate("Generate one planning claim.")
        finally:
            generator._slots.release()

    asyncio.run(scenario())


def test_l3_worker_rejects_empty_human_report_body() -> None:
    from app.domain.program.worker import L3ReportBodyEmptyError, _require_l3_report_body

    with pytest.raises(L3ReportBodyEmptyError, match="L3_REPORT_BODY_EMPTY"):
        _require_l3_report_body("  ")
    assert _require_l3_report_body("【规划】正文") == "【规划】正文"


def test_l3_prompt_exposes_dual_output_and_typed_fact_ids(monkeypatch) -> None:
    from app.contracts.domain.l1_contracts import L1Fact
    from app.domain.program.worker import _build_prompt

    context = SimpleNamespace(
        l1_fact_records=[L1Fact(
            fact_id="l1:road:one",
            statement="现状村道需要提升",
            fact_kind="document_observation",
            dimension_key="traffic",
            semantic_type="road",
            attributes={"normalized_name": "村道"},
            source_refs=["report:traffic"],
            source_feature_ids=["feature:road:one"],
        )],
        input_text=lambda _key, default: default,
    )
    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda _session_id: context,
    )

    prompt = _build_prompt(
        SimpleNamespace(key="traffic"),
        {"session_id": "prompt-test", "dimension_key": "traffic"},
        l1_deps="现状道路分布于村庄主要居民点。",
        l2_deps="完善道路连接。",
    )

    assert "report_body" in prompt
    assert "不能只返回 claims" in prompt
    assert "l1:road:one" in prompt
    assert "feature:road:one" in prompt
    assert "source_fact_refs" in prompt
    assert "现状道路分布于村庄主要居民点。" in prompt
    assert "当前模板中的项目数量" in prompt
