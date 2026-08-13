"""Provider-boundary recovery tests for structured L3 claim responses."""

from __future__ import annotations

import asyncio

from app.infrastructure.llm.planning_claims import PlanningClaimGenerator


class _StructuredInvoker:
    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, _messages):
        self.calls += 1
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
