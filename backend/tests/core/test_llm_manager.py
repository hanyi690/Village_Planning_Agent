"""Tests for the single typed LLM admission boundary."""

from __future__ import annotations

import pytest
from pydantic import BaseModel


class _Result(BaseModel):
    value: int


@pytest.mark.asyncio
async def test_manager_resolves_stage_policy_and_audits_without_prompt_content(
    monkeypatch,
):
    from app.infrastructure.llm.manager import LLMCallSpec, LLMManager

    calls: list[dict] = []
    records = []

    async def fake_runner(response_model, messages, **kwargs):
        calls.append({"response_model": response_model, "messages": messages, **kwargs})
        return _Result(value=7)

    monkeypatch.setattr(
        "app.infrastructure.llm.structured.run_structured_output",
        fake_runner,
    )
    manager = LLMManager(audit_sink=records.append)
    result = await manager.run_structured(
        LLMCallSpec(
            stage="L2",
            contract_key="l2.decision",
            response_model=_Result,
            call_type="semantic",
            allow_content_json=True,
        ),
        [
            {"role": "system", "content": "domain rules"},
            {"role": "user", "content": "facts"},
        ],
        context={"session_id": "session-1", "raw": "must not become prompt"},
    )

    assert result == _Result(value=7)
    assert calls[0]["contract_key"] == "l2.decision"
    assert calls[0]["max_retries"] == 1
    assert calls[0]["max_tokens"] > 0
    assert calls[0]["allow_content_json"] is True
    assert calls[0]["context"]["session_id"] == "session-1"
    assert calls[0]["context"]["raw"] == "must not become prompt"
    assert records[0].status == "succeeded"
    assert records[0].input_chars == len("domain rules") + len("facts")
    assert "domain rules" not in records[0].input_digest


@pytest.mark.asyncio
async def test_manager_rejects_oversized_input_without_truncating_or_calling_provider(
    monkeypatch,
):
    from app.infrastructure.llm.manager import (
        LLMCallSpec,
        LLMContextOverflow,
        LLMManager,
    )

    called = False

    async def fake_runner(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider must not be called")

    monkeypatch.setattr(
        "app.infrastructure.llm.structured.run_structured_output",
        fake_runner,
    )
    with pytest.raises(LLMContextOverflow, match="exceeds") as raised:
        await LLMManager().run_structured(
            LLMCallSpec(
                stage="GROUND",
                contract_key="ground.candidate_selection",
                response_model=_Result,
                call_type="closed_set",
                input_char_limit=10,
            ),
            [{"role": "user", "content": "01234567890"}],
        )

    assert called is False
    assert raised.value.input_chars == 11
    assert raised.value.input_char_limit == 10


@pytest.mark.asyncio
async def test_manager_preserves_explicit_zero_schema_retries(monkeypatch):
    from app.infrastructure.llm.manager import LLMCallSpec, LLMManager

    calls: list[dict] = []

    async def fake_runner(response_model, messages, **kwargs):
        calls.append(kwargs)
        return _Result(value=1)

    monkeypatch.setattr(
        "app.infrastructure.llm.structured.run_structured_output",
        fake_runner,
    )
    await LLMManager().run_structured(
        LLMCallSpec(
            stage="L3",
            contract_key="l3.claims",
            response_model=_Result,
            max_retries=0,
        ),
        [{"role": "user", "content": "rough intent"}],
    )

    assert calls[0]["max_retries"] == 0


@pytest.mark.asyncio
async def test_manager_rejects_non_text_message_content_before_transport(monkeypatch):
    from app.infrastructure.llm.manager import LLMCallSpec, LLMManager

    async def fake_runner(*_args, **_kwargs):
        raise AssertionError("provider must not be called")

    monkeypatch.setattr(
        "app.infrastructure.llm.structured.run_structured_output",
        fake_runner,
    )
    with pytest.raises(TypeError, match="content must be text"):
        await LLMManager().run_structured(
            LLMCallSpec(
                stage="SELECT",
                contract_key="llm.closed_set",
                response_model=_Result,
                call_type="closed_set",
            ),
            [{"role": "user", "content": {"raw": "artifact"}}],
        )


@pytest.mark.asyncio
async def test_manager_routes_native_tool_calls_through_one_admission_boundary(
    monkeypatch,
):
    from app.infrastructure.llm.manager import LLMManager

    calls: list[dict] = []
    records = []

    class _Message:
        type = "human"
        content = "继续规划"

    class _Tool:
        name = "advance_planning_intent"
        description = "推进规划流程"
        args = {"type": "object", "properties": {}}

    class _LLM:
        def bind_tools(self, tools):
            calls.append({"tools": tools})
            return self

        async def ainvoke(self, messages):
            calls.append({"messages": messages})
            return type("_AIMessage", (), {"content": "已收到", "tool_calls": []})()

    fake_llm = _LLM()
    monkeypatch.setattr(
        "app.infrastructure.llm.factory.create_llm",
        lambda **kwargs: (calls.append({"factory": kwargs}) or fake_llm),
    )

    result = await LLMManager(audit_sink=records.append).run_tool_calling(
        stage="conversation",
        contract_key="conversation.tool_routing",
        messages=[_Message()],
        tools=[_Tool()],
        context={"session_id": "session-1", "raw": "not a prompt"},
        timeout_s=2,
    )

    assert result.content == "已收到"
    assert calls[0]["factory"]["max_tokens"] == 2048
    assert calls[1]["tools"][0].name == "advance_planning_intent"
    assert calls[2]["messages"][0].content == "继续规划"
    assert records[0].stage == "CONVERSATION"
    assert records[0].response_model == "AIMessage"
    assert records[0].status == "succeeded"
