from types import SimpleNamespace

import pytest
from pydantic import BaseModel


class _Result(BaseModel):
    value: int


class _NestedResult(BaseModel):
    model_config = {"extra": "forbid"}
    items: list[dict[str, int]]


def test_provider_normalizer_is_schema_aware_for_container_strings():
    from app.infrastructure.llm.structured import _normalize_provider_payload

    payload = _normalize_provider_payload(
        _NestedResult,
        {"items": '[{"value": 7}]', "provider_placeholder": None},
    )

    assert payload == {"items": [{"value": 7}]}


def test_provider_normalizer_preserves_non_null_schema_drift():
    from app.infrastructure.llm.structured import _normalize_provider_payload

    payload = _normalize_provider_payload(
        _NestedResult,
        {"items": [{"value": 7, "unexpected": "keep"}]},
    )

    assert payload["items"][0]["unexpected"] == "keep"


def _missing_tool(content: str):
    from instructor.core import InstructorRetryException

    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=None),
                finish_reason="stop",
            )
        ]
    )
    return InstructorRetryException(
        "No tool calls or function call found in response",
        last_completion=completion,
        n_attempts=1,
        total_usage=0,
    )


@pytest.mark.asyncio
async def test_content_json_fallback_accepts_valid_object(monkeypatch):
    from app.infrastructure.llm import structured

    calls = []

    class _Completions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise _missing_tool('{"value": 7}')
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"value": 7}'),
                        finish_reason="stop",
                    )
                ]
            )

    class _Client:
        chat = SimpleNamespace(completions=_Completions())

    modes = []
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "test-model")
    monkeypatch.setattr(
        structured,
        "get_async_instructor_client",
        lambda mode_override=None: (modes.append(mode_override) or _Client()),
    )

    result = await structured.run_structured_output(
        _Result,
        [{"role": "user", "content": "return seven"}],
        max_retries=0,
        allow_content_json=True,
    )

    assert result == _Result(value=7)
    assert len(calls) == 2
    assert modes[1].value == "json_mode"
    assert calls[1]["max_retries"] == 0


@pytest.mark.asyncio
async def test_content_json_fallback_rejects_schema_validation_failure(monkeypatch):
    from app.infrastructure.llm import structured

    class _Completions:
        calls = 0

        async def create(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise _missing_tool('{"value": 7}')
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"other": 7}'),
                        finish_reason="stop",
                    )
                ]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "test-model")
    monkeypatch.setattr(
        structured,
        "get_async_instructor_client",
        lambda mode_override=None: client,
    )

    with pytest.raises(Exception) as raised:
        await structured.run_structured_output(
            _Result,
            [{"role": "user", "content": "return seven"}],
            max_retries=0,
            allow_content_json=True,
        )

    summary = structured.structured_failure_summary(raised.value)
    assert "json_fallback" in summary
    assert '"other": 7' not in summary
    assert "return seven" not in summary


@pytest.mark.asyncio
async def test_content_json_fallback_is_strict_by_default(monkeypatch):
    from app.infrastructure.llm import structured

    class _Completions:
        async def create(self, **_kwargs):
            raise _missing_tool('{"value": 7}')

    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "test-model")
    monkeypatch.setattr(
        structured,
        "get_async_instructor_client",
        lambda mode_override=None: SimpleNamespace(
            chat=SimpleNamespace(completions=_Completions())
        ),
    )

    with pytest.raises(Exception):
        await structured.run_structured_output(
            _Result,
            [{"role": "user", "content": "return seven"}],
            max_retries=0,
        )
