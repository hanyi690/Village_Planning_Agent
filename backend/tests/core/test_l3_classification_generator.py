from __future__ import annotations

import asyncio

import pytest

from app.domain.program import classification_generator as generator


class _FakeStructuredLlm:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.messages: list[list[dict]] = []

    def with_structured_output(self, _schema, method: str):
        assert method == "function_calling"
        return self

    async def ainvoke(self, _messages):
        self.messages.append(_messages)
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


def _targets(count: int = 2) -> list[dict]:
    return [
        {
            "target_id": f"target-{index}",
            "name": "公共服务设施",
            "category": "facility",
            "expected_output_kind": "polygon",
            "evidence_refs": [f"claim:{index}"],
        }
        for index in range(1, count + 1)
    ]


def _response(count: int) -> dict:
    return {
        "results": [
            {
                "index": index,
                "selected_code": "1500",
                "rationale": "规划设施依据",
            }
            for index in range(1, count + 1)
        ]
    }


def test_classification_generator_uses_validation_feedback_retry(monkeypatch) -> None:
    monkeypatch.setattr(generator, "_targets_with_evidence", lambda _program: _targets())
    llm = _FakeStructuredLlm(
        [
            {
                "results": [
                    {
                        "index": 1,
                        "selected_code": "1500",
                        "rationale": "first only",
                    }
                ]
            },
            {
                "results": [
                    {
                        "index": 1,
                        "selected_code": "1500",
                        "rationale": "facility evidence",
                    },
                    {
                        "index": 2,
                        "selected_code": "1500",
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


def test_classification_generator_splits_targets_into_small_batches(monkeypatch) -> None:
    targets = _targets(13)
    monkeypatch.setattr(generator, "_targets_with_evidence", lambda _program: targets)
    llm = _FakeStructuredLlm([_response(6), _response(6), _response(1)])

    decisions = asyncio.run(generator.generate_classification_decisions(object(), llm=llm))

    assert llm.calls == 3
    assert len(decisions) == 13
    assert [message[0]["content"].count("target=") for message in llm.messages] == [
        6,
        6,
        1,
    ]


@pytest.mark.parametrize("invalid_index", ["1", True], ids=["string", "boolean"])
def test_classification_generator_rejects_non_strict_indices(
    monkeypatch,
    invalid_index,
) -> None:
    monkeypatch.setattr(generator, "_targets_with_evidence", lambda _program: _targets())
    invalid_response = {
        "results": [
            {"index": invalid_index, "selected_code": "1500"},
            {"index": 2, "selected_code": "1500"},
        ]
    }
    llm = _FakeStructuredLlm([invalid_response, _response(2)])

    decisions = asyncio.run(generator.generate_classification_decisions(object(), llm=llm))

    assert llm.calls == 2
    assert [decision.target_id for decision in decisions] == ["target-1", "target-2"]


def test_classification_generator_continues_after_middle_batch_failure(monkeypatch) -> None:
    targets = _targets(13)
    monkeypatch.setattr(generator, "_targets_with_evidence", lambda _program: targets)
    llm = _FakeStructuredLlm(
        [
            _response(6),
            {"results": []},
            {"results": []},
            {"results": []},
            _response(1),
        ]
    )

    decisions = asyncio.run(generator.generate_classification_decisions(object(), llm=llm))

    assert llm.calls == 5
    assert [decision.target_id for decision in decisions] == [
        *[f"target-{index}" for index in range(1, 7)],
        "target-13",
    ]


def test_classification_generator_rejects_trailing_characters_and_retries(
    monkeypatch,
) -> None:
    monkeypatch.setattr(generator, "_targets_with_evidence", lambda _program: _targets())
    llm = _FakeStructuredLlm(
        [
            '{"results":[{"index":1,"selected_code":"1500"},{"index":2,"selected_code":"1500"}]} trailing',
            _response(2),
        ]
    )

    decisions = asyncio.run(generator.generate_classification_decisions(object(), llm=llm))

    assert llm.calls == 2
    assert [decision.selected_code for decision in decisions] == ["1500", "1500"]


def test_classification_generator_rejects_nested_string_response(monkeypatch) -> None:
    monkeypatch.setattr(generator, "_targets_with_evidence", lambda _program: _targets())
    llm = _FakeStructuredLlm(
        [
            {
                "results": '[{"index":1,"selected_code":"1500"},{"index":2,"selected_code":"1500"}]'
            },
            _response(2),
        ]
    )

    decisions = asyncio.run(generator.generate_classification_decisions(object(), llm=llm))

    assert llm.calls == 2
    assert len(decisions) == 2


def test_classification_generator_fails_closed_without_category_fallback(
    monkeypatch,
) -> None:
    monkeypatch.setattr(generator, "_targets_with_evidence", lambda _program: _targets())
    llm = _FakeStructuredLlm([{"results": []} for _ in range(3)])

    decisions = asyncio.run(generator.generate_classification_decisions(object(), llm=llm))

    assert llm.calls == 3
    assert decisions == []


def test_classification_generator_keeps_appendix5_closed_set_validation(
    monkeypatch,
) -> None:
    monkeypatch.setattr(generator, "_targets_with_evidence", lambda _program: _targets())
    llm = _FakeStructuredLlm(
        [
            {
                "results": [
                    {"index": 1, "selected_code": "not-an-appendix5-code"},
                    {"index": 2, "selected_code": "1500"},
                ]
            },
            _response(2),
        ]
    )

    decisions = asyncio.run(generator.generate_classification_decisions(object(), llm=llm))

    assert llm.calls == 2
    assert all(decision.code_system.value == "appendix5" for decision in decisions)
    assert all(decision.selected_code == "1500" for decision in decisions)
    assert all(decision.candidate_codes == ["1500"] for decision in decisions)
