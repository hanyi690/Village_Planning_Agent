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

    async def ainvoke(self, messages):
        self.messages.append(messages)
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


def _targets(count: int = 2, *, candidate_codes: list[str] | None = None) -> list[dict]:
    codes = ["1500"] if candidate_codes is None else candidate_codes
    return [
        {
            "target_id": f"target-{index}",
            "claim_refs": [f"claim-{index}"],
            "name": "公共服务设施",
            "category": "facility",
            "expected_output_kind": "polygon",
            "evidence_refs": [f"claim-{index}"],
            "candidate_codes": list(codes),
        }
        for index in range(1, count + 1)
    ]


def _item(target_id: str, *, code: str = "1500", claim_id: str | None = None) -> dict:
    return {
        "target_id": target_id,
        "claim_id": claim_id or target_id.replace("target", "claim"),
        "selected_code": code,
        "rationale": "typed evidence",
    }


def _response(target_ids: list[str], *, code: str = "1500") -> dict:
    return {"results": [_item(target_id, code=code) for target_id in target_ids]}


def test_classification_schema_keeps_runtime_candidates_out_of_provider_schema() -> None:
    model = generator._dynamic_proposal_model(["1510"])
    schema = model.model_json_schema()
    assert "index" not in str(schema)
    assert "target_id" in schema["$defs"][next(iter(schema["$defs"]))]["properties"]
    selected_schema = next(
        value
        for value in schema["$defs"].values()
        if "selected_code" in value.get("properties", {})
    )["properties"]["selected_code"]
    assert selected_schema["anyOf"][0]["type"] == "string"
    assert "1510" not in str(selected_schema)
    assert "1500" not in str(selected_schema)


def test_empty_input_candidate_set_is_pending_without_provider_call(monkeypatch) -> None:
    monkeypatch.setattr(
        generator,
        "_targets_with_evidence",
        lambda _program: _targets(candidate_codes=[]),
    )
    llm = _FakeStructuredLlm([])

    result = asyncio.run(generator.generate_classification_decisions(object(), llm=llm))

    assert result == []
    assert llm.calls == 0
    assert result.pending[0].reason_code == "candidate_set_empty"
    assert result.pending[0].candidate_set_digest


def test_accepted_target_is_frozen_and_only_failed_target_is_retried(monkeypatch) -> None:
    monkeypatch.setattr(generator, "_targets_with_evidence", lambda _program: _targets())
    monkeypatch.setenv("L3_CLASSIFICATION_RETRIES", "1")
    llm = _FakeStructuredLlm(
        [
            {
                "results": [
                    _item("target-1"),
                    {
                        "target_id": "target-2",
                        "claim_id": "claim-2",
                        "status": "ambiguous",
                    },
                ]
            },
            _response(["target-2"]),
        ]
    )

    result = asyncio.run(generator.generate_classification_decisions(object(), llm=llm))

    assert llm.calls == 2
    assert [decision.target_id for decision in result] == ["target-1", "target-2"]
    first_prompt = "\n".join(str(item.get("content", "")) for item in llm.messages[0])
    second_prompt = "\n".join(str(item.get("content", "")) for item in llm.messages[1])
    assert "target-1" in first_prompt
    assert "target-1" not in second_prompt
    assert result.pending == []


def test_batches_use_stable_ids_without_positional_indexes(monkeypatch) -> None:
    targets = _targets(13, candidate_codes=["1500", "1510"])
    monkeypatch.setattr(generator, "_targets_with_evidence", lambda _program: targets)
    llm = _FakeStructuredLlm(
        [
            _response([f"target-{index}" for index in range(1, 7)]),
            _response([f"target-{index}" for index in range(7, 13)]),
            _response(["target-13"]),
        ]
    )

    result = asyncio.run(generator.generate_classification_decisions(object(), llm=llm))

    assert llm.calls == 3
    assert len(result) == 13
    assert all("index" not in message[1]["content"] for message in llm.messages)


def test_unknown_or_ambiguous_proposal_becomes_pending_without_implicit_retries(monkeypatch) -> None:
    monkeypatch.setattr(generator, "_targets_with_evidence", lambda _program: _targets())
    llm = _FakeStructuredLlm(
        [
            {
                "results": [
                    _item("target-1"),
                    {
                        "target_id": "target-2",
                        "claim_id": "claim-2",
                        "status": "ambiguous",
                    },
                ]
            },
            {
                "results": [
                    {
                        "target_id": "target-2",
                        "claim_id": "claim-2",
                        "status": "ambiguous",
                    }
                ]
            },
        ]
    )

    result = asyncio.run(generator.generate_classification_decisions(object(), llm=llm))

    assert [decision.target_id for decision in result] == ["target-1"]
    assert [item.reason_code for item in result.pending] == ["classification_ambiguous"]
    assert result.pending[0].decision_ref == "target-2"
    assert llm.calls == 1


def test_dynamic_candidate_set_rejects_code_outside_this_input_locally(monkeypatch) -> None:
    monkeypatch.setattr(
        generator,
        "_targets_with_evidence",
        lambda _program: _targets(candidate_codes=["1510"]),
    )
    llm = _FakeStructuredLlm([_response(["target-1"], code="1500")])

    result = asyncio.run(generator.generate_classification_decisions(object(), llm=llm))

    assert result == []
    assert result.pending[0].reason_code == "unknown_candidate_id"
    assert llm.calls == 1


def test_content_json_string_is_rejected_without_semantic_regex_fallback(monkeypatch) -> None:
    monkeypatch.setattr(generator, "_targets_with_evidence", lambda _program: _targets())
    llm = _FakeStructuredLlm(
        [
            '{"results": [{"target_id": "target-1", "claim_id": "claim-1", "selected_code": "1500"}]}',
            _response(["target-1", "target-2"]),
        ]
    )

    result = asyncio.run(generator.generate_classification_decisions(object(), llm=llm))

    assert result == []
    assert result.pending[0].reason_code == "SCHEMA_INVALID"
    assert llm.calls == 1


def test_candidate_set_digest_changes_with_input_candidates(monkeypatch) -> None:
    monkeypatch.setattr(
        generator,
        "_targets_with_evidence",
        lambda _program: _targets(candidate_codes=["1500"]),
    )
    first = asyncio.run(
        generator.generate_classification_decisions(
            object(), llm=_FakeStructuredLlm([_response(["target-1", "target-2"])]),
        )
    )
    monkeypatch.setattr(
        generator,
        "_targets_with_evidence",
        lambda _program: _targets(candidate_codes=["1510"]),
    )
    second = asyncio.run(
        generator.generate_classification_decisions(
            object(), llm=_FakeStructuredLlm([_response(["target-1", "target-2"], code="1510")]),
        )
    )

    assert first.candidate_set_digest != second.candidate_set_digest
