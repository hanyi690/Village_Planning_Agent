from __future__ import annotations

import asyncio

from app.domain.program import classification_generator as generator


class _FakeStructuredLlm:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def with_structured_output(self, _schema, method: str):
        assert method == "function_calling"
        return self

    async def ainvoke(self, _messages):
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


def _targets() -> list[dict]:
    return [
        {
            "target_id": "target-1",
            "name": "公共服务设施",
            "category": "facility",
            "expected_output_kind": "polygon",
            "evidence_refs": ["claim:1"],
        },
        {
            "target_id": "target-2",
            "name": "产业用地",
            "category": "project",
            "expected_output_kind": "parcel",
            "evidence_refs": ["claim:2"],
        },
    ]


def test_classification_generator_uses_validation_feedback_retry(monkeypatch) -> None:
    monkeypatch.setattr(generator, "_targets_with_evidence", lambda _program: _targets())
    llm = _FakeStructuredLlm(
        [
            {
                "results": [
                    {
                        "index": 1,
                        "selected_code": "1500",
                        "candidate_codes": ["1500"],
                        "rationale": "first only",
                    }
                ]
            },
            {
                "results": [
                    {
                        "index": 1,
                        "selected_code": "1500",
                        "candidate_codes": ["1500"],
                        "rationale": "facility evidence",
                    },
                    {
                        "index": 2,
                        "selected_code": "1500",
                        "candidate_codes": ["1500"],
                        "rationale": "project evidence",
                    },
                ]
            },
        ]
    )

    decisions = asyncio.run(generator.generate_classification_decisions(object(), llm=llm))

    assert llm.calls == 2
    assert [decision.target_id for decision in decisions] == ["target-1", "target-2"]
    assert all(decision.decision_mode == "llm_l3" for decision in decisions)


def test_classification_generator_fails_closed_without_category_fallback(
    monkeypatch,
) -> None:
    monkeypatch.setattr(generator, "_targets_with_evidence", lambda _program: _targets())
    llm = _FakeStructuredLlm([{"results": []} for _ in range(3)])

    decisions = asyncio.run(generator.generate_classification_decisions(object(), llm=llm))

    assert llm.calls == 3
    assert decisions == []
