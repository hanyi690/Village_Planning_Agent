"""Network-free tests for the provider-aware Instructor boundary."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

class _Result(BaseModel):
    value: int


class _TextResult(BaseModel):
    value: str


def _retry_exception_with_content(content: str):
    from instructor.core import InstructorRetryException

    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=None),
            )
        ]
    )
    return InstructorRetryException(
        "No tool calls or function call found in response (mode: TOOLS)",
        last_completion=completion,
        n_attempts=1,
        total_usage=0,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        '{"value": 7}',
        '<think>reasoning without a tool call</think>\n{"value": 7}',
        '```json\n{"value": 7}\n```',
    ],
    ids=["plain-json", "think-json", "fenced-json"],
)
async def test_runner_accepts_complete_content_json_after_instructor_retry(
    monkeypatch, content
):
    from app.infrastructure.llm import structured

    calls = 0

    class _Completions:
        async def create(self, **_kwargs):
            nonlocal calls
            calls += 1
            raise _retry_exception_with_content(content)

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "deepseek-v4-flash")

    result = await structured.run_structured_output(
        _Result,
        [{"role": "user", "content": "return seven"}],
        max_retries=1,
        timeout=2,
    )

    assert result == _Result(value=7)
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        '{"value": 7',
        '{"value": 7} trailing text',
        '[{"value": 7}]',
        '{"other": 7}',
    ],
    ids=["incomplete-json", "trailing-text", "array", "schema-invalid"],
)
async def test_runner_rejects_invalid_content_json_without_extra_call(
    monkeypatch, content
):
    from instructor.core import InstructorRetryException
    from app.infrastructure.llm import structured

    calls = 0
    warnings: list[tuple] = []

    class _Completions:
        async def create(self, **_kwargs):
            nonlocal calls
            calls += 1
            raise _retry_exception_with_content(content)

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "deepseek-v4-flash")
    monkeypatch.setattr(structured.logger, "warning", lambda *args, **_kwargs: warnings.append(args))

    with pytest.raises(InstructorRetryException):
        await structured.run_structured_output(
            _Result,
            [{"role": "user", "content": "return seven"}],
            max_retries=1,
            timeout=2,
        )

    assert calls == 1
    assert warnings
    assert content not in " ".join(str(item) for warning in warnings for item in warning)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        '{"value": 7}\n<think>late reasoning</think>',
        '<think>reasoning</think>\nprose before the object\n{"value": 7}',
        '```json\n{"value": 7}\n```\ntrailing text',
        '```json\n```json\n{"value": 7}\n```\n```',
    ],
    ids=["think-after-json", "prose-between-wrapper-and-json", "trailing-after-fence", "nested-fence"],
)
async def test_runner_rejects_non_outer_wrappers_without_extra_call(monkeypatch, content):
    from instructor.core import InstructorRetryException
    from app.infrastructure.llm import structured

    calls = 0

    class _Completions:
        async def create(self, **_kwargs):
            nonlocal calls
            calls += 1
            raise _retry_exception_with_content(content)

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "deepseek-v4-flash")

    with pytest.raises(InstructorRetryException):
        await structured.run_structured_output(
            _Result,
            [{"role": "user", "content": "return seven"}],
            max_retries=1,
            timeout=2,
        )

    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        '{"value": "<think>internal marker</think>"}',
        '{"value": "```json\\ninternal marker\\n```"}',
    ],
    ids=["think-marker", "fence-marker"],
)
async def test_runner_rejects_wrapper_markers_inside_json_string(monkeypatch, content):
    from instructor.core import InstructorRetryException
    from app.infrastructure.llm import structured

    calls = 0

    class _Completions:
        async def create(self, **_kwargs):
            nonlocal calls
            calls += 1
            raise _retry_exception_with_content(content)

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "deepseek-v4-flash")

    with pytest.raises(InstructorRetryException):
        await structured.run_structured_output(
            _TextResult,
            [{"role": "user", "content": "return text"}],
            max_retries=1,
            timeout=2,
        )

    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
async def test_runner_rejects_non_standard_json_constants_without_extra_call(monkeypatch, constant):
    from instructor.core import InstructorRetryException
    from app.infrastructure.llm import structured

    content = f'{{"value": {constant}}}'
    calls = 0

    class _Completions:
        async def create(self, **_kwargs):
            nonlocal calls
            calls += 1
            raise _retry_exception_with_content(content)

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "deepseek-v4-flash")

    with pytest.raises(InstructorRetryException):
        await structured.run_structured_output(
            _TextResult,
            [{"role": "user", "content": "return text"}],
            max_retries=1,
            timeout=2,
        )

    assert calls == 1


@pytest.mark.asyncio
async def test_runner_passes_typed_contract_and_bounded_retry(monkeypatch):
    from app.infrastructure.llm import structured

    calls: list[dict] = []

    class _Completions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return _Result(value=7)

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "deepseek-v4-flash")

    result = await structured.run_structured_output(
        _Result,
        [{"role": "user", "content": "return seven"}],
        max_retries=2,
        timeout=2,
    )

    assert result == _Result(value=7)
    assert calls[0]["response_model"] is _Result
    assert calls[0]["model"] == "deepseek-v4-flash"
    assert calls[0]["max_retries"] == 2


@pytest.mark.asyncio
async def test_runner_enforces_shared_provider_call_budget_and_console_go_tools_mode(monkeypatch):
    from app.infrastructure.llm import structured

    monkeypatch.setattr("app.core.settings.LLM_MAX_CONCURRENT", 2)
    monkeypatch.setenv("LLM_PROVIDER", "opencode-go")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "low")
    active = 0
    peak = 0
    requests: list[dict] = []

    class _Completions:
        async def create(self, **kwargs):
            nonlocal active, peak
            requests.append(kwargs)
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1
            return _Result(value=7)

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "deepseek-v4-flash")

    results = await asyncio.gather(*[
        structured.run_structured_output(
            _Result,
            [{"role": "user", "content": "return seven"}],
            timeout=2,
        )
        for _ in range(5)
    ])

    assert len(results) == 5
    assert peak == 2
    assert requests[0]["extra_body"]["thinking"]["type"] == "disabled"
    assert "reasoning_effort" not in requests[0]


@pytest.mark.asyncio
async def test_runner_adapts_only_incomplete_output(monkeypatch):
    from instructor.core import IncompleteOutputException
    from app.infrastructure.llm import structured

    monkeypatch.setattr("app.core.settings.LLM_MAX_CONCURRENT", 2)
    monkeypatch.setenv("LLM_PROVIDER", "opencode-go")
    monkeypatch.delenv("LLM_REASONING_EFFORT", raising=False)
    monkeypatch.setenv("LLM_INCOMPLETE_OUTPUT_MAX_TOKENS", "8192")
    requests: list[dict] = []

    class _Completions:
        async def create(self, **kwargs):
            requests.append(kwargs)
            if len(requests) == 1:
                raise IncompleteOutputException(last_completion=None)
            return _Result(value=7)

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "deepseek-v4-flash")

    result = await structured.run_structured_output(
        _Result,
        [{"role": "user", "content": "return seven"}],
        timeout=2,
        max_tokens=4096,
    )

    assert result == _Result(value=7)
    assert [request["max_tokens"] for request in requests] == [4096, 8192]


@pytest.mark.asyncio
async def test_runner_respects_per_call_incomplete_output_ceiling(monkeypatch):
    from instructor.core import IncompleteOutputException
    from app.infrastructure.llm import structured

    monkeypatch.setenv("LLM_PROVIDER", "opencode-go")
    requests: list[dict] = []

    class _Completions:
        async def create(self, **kwargs):
            requests.append(kwargs)
            raise IncompleteOutputException(last_completion=None)

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "deepseek-v4-flash")

    with pytest.raises(IncompleteOutputException):
        await structured.run_structured_output(
            _Result,
            [{"role": "user", "content": "return seven"}],
            timeout=2,
            max_tokens=4096,
            incomplete_output_max_tokens=4096,
        )

    assert [request["max_tokens"] for request in requests] == [4096]


@pytest.mark.asyncio
async def test_runner_does_not_retry_exhausted_provider_quota(monkeypatch):
    from app.infrastructure.llm import structured

    class _QuotaExhausted(Exception):
        status_code = 429

    calls = 0

    class _Completions:
        async def create(self, **_kwargs):
            nonlocal calls
            calls += 1
            raise _QuotaExhausted("GoUsageLimitError: weekly usage limit reached")

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setenv("LLM_PROVIDER", "opencode-go")
    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "deepseek-v4-flash")

    with pytest.raises(_QuotaExhausted):
        await structured.run_structured_output(
            _Result,
            [{"role": "user", "content": "return seven"}],
            timeout=2,
            transient_retries=3,
            transient_retry_backoff_s=0,
        )

    assert calls == 1


@pytest.mark.asyncio
async def test_runner_retries_only_bounded_transient_provider_status(monkeypatch):
    from app.infrastructure.llm import structured

    class _ProviderUnavailable(Exception):
        status_code = 503

    calls = 0

    class _Completions:
        async def create(self, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise _ProviderUnavailable("temporary upstream unavailability")
            return _Result(value=7)

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setenv("LLM_PROVIDER", "opencode-go")
    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "deepseek-v4-flash")

    result = await structured.run_structured_output(
        _Result,
        [{"role": "user", "content": "return seven"}],
        timeout=2,
        transient_retries=1,
        transient_retry_backoff_s=0,
    )

    assert result == _Result(value=7)
    assert calls == 2


@pytest.mark.asyncio
async def test_runner_retries_minimax_overload_status(monkeypatch):
    from app.infrastructure.llm import structured

    class _ProviderOverloaded(Exception):
        status_code = 529

    calls = 0

    class _Completions:
        async def create(self, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise _ProviderOverloaded("service cluster overloaded")
            return _Result(value=7)

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setenv("LLM_PROVIDER", "minimax")
    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(
        structured,
        "get_structured_model",
        lambda model=None: "MiniMax-M2.7-highspeed",
    )

    result = await structured.run_structured_output(
        _Result,
        [{"role": "user", "content": "return seven"}],
        timeout=2,
        transient_retries=1,
        transient_retry_backoff_s=0,
    )

    assert result == _Result(value=7)
    assert calls == 2


def test_instructor_client_uses_tools_mode_and_provider_scoped_cache(monkeypatch):
    from app.infrastructure.llm import instructor_client

    instructor_client._cached_clients.clear()
    created: list[dict] = []

    class _Wrapped:
        pass

    monkeypatch.setattr(
        instructor_client,
        "_provider_connection",
        lambda: ("opencode-go", "test-key", "https://opencode.ai/zen/go/v1"),
    )
    monkeypatch.setattr(instructor_client, "OpenAI", lambda **kwargs: kwargs)
    monkeypatch.setattr(
        instructor_client.instructor,
        "from_openai",
        lambda client, **kwargs: (created.append({"client": client, **kwargs}) or _Wrapped()),
    )

    first = instructor_client.get_instructor_client()
    second = instructor_client.get_instructor_client()

    assert first is second
    assert created[0]["mode"] is instructor_client.instructor.Mode.TOOLS
    assert created[0]["client"]["base_url"] == "https://opencode.ai/zen/go/v1"


def test_async_instructor_client_has_explicit_transport_budget(monkeypatch):
    from app.infrastructure.llm import instructor_client

    instructor_client._cached_async_clients.clear()
    created: list[dict] = []

    class _Wrapped:
        pass

    monkeypatch.setenv("LLM_PROVIDER_MAX_RETRIES", "1")
    monkeypatch.setattr(
        instructor_client,
        "_provider_connection",
        lambda: ("opencode-go", "test-key", "https://opencode.ai/zen/go/v1"),
    )
    monkeypatch.setattr(instructor_client, "_http_client", lambda **kwargs: "async-http")
    monkeypatch.setattr(
        instructor_client,
        "AsyncOpenAI",
        lambda **kwargs: (created.append(kwargs) or kwargs),
    )
    monkeypatch.setattr(
        instructor_client.instructor,
        "from_openai",
        lambda client, **kwargs: _Wrapped(),
    )

    first = instructor_client.get_async_instructor_client()
    second = instructor_client.get_async_instructor_client()

    assert first is second
    assert created[0]["max_retries"] == 1
    assert created[0]["http_client"] == "async-http"
    assert created[0]["base_url"] == "https://opencode.ai/zen/go/v1"
