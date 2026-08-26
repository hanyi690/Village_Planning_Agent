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


@pytest.mark.asyncio
async def test_injected_minimax_llm_uses_function_calling(monkeypatch):
    from app.infrastructure.llm import structured

    calls: list[dict] = []

    class _Runner:
        async def ainvoke(self, _input):
            return _Result(value=7)

    class _LLM:
        def with_structured_output(self, response_model, **kwargs):
            calls.append({"response_model": response_model, **kwargs})
            return _Runner()

    monkeypatch.setenv("LLM_PROVIDER", "minimax")
    result = await structured.run_structured_output(
        _Result,
        [{"role": "user", "content": "return seven"}],
        llm=_LLM(),
        max_retries=0,
        timeout=2,
    )

    assert result == _Result(value=7)
    assert calls[0]["method"] == "function_calling"


@pytest.mark.asyncio
async def test_runner_classifies_none_as_missing_typed_output_without_reask():
    from app.infrastructure.llm import structured

    calls = 0

    class _Runner:
        async def ainvoke(self, _input):
            nonlocal calls
            calls += 1
            return None

    class _LLM:
        def with_structured_output(self, *_args, **_kwargs):
            return _Runner()

    with pytest.raises(ValueError, match="no typed output") as raised:
        await structured.run_structured_output(
            _Result,
            [{"role": "user", "content": "return seven"}],
            llm=_LLM(),
            max_retries=0,
            timeout=2,
        )

    assert calls == 1
    assert structured.structured_failure_code(raised.value) == "TOOL_CALL_MISSING"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (asyncio.TimeoutError(), "TIMEOUT"),
        (ValueError("context_length_exceeded"), "CONTEXT_OVERFLOW"),
        (ValueError("maximum context length exceeded"), "CONTEXT_OVERFLOW"),
        (ValueError("input tokens exceed the context limit"), "CONTEXT_OVERFLOW"),
        (ValueError("schema validation failed for input token field"), "SCHEMA_INVALID"),
        (ValueError("provider token mismatch"), None),
    ],
)
def test_structured_failure_code_classifies_timeout_and_context_overflow(error, expected):
    from app.infrastructure.llm.structured import structured_failure_code

    assert structured_failure_code(error) == expected


def _retry_exception_with_content(content: str, *, finish_reason: str | None = None, message: str = "No tool calls or function call found in response (mode: TOOLS)"):
    from instructor.core import InstructorRetryException

    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=None),
                finish_reason=finish_reason,
            )
        ]
    )
    return InstructorRetryException(
        message,
        last_completion=completion,
        n_attempts=1,
        total_usage=0,
    )


def _retry_exception_with_provider_503():
    import httpx
    from instructor.core import FailedAttempt, InstructorRetryException

    request = httpx.Request("POST", "https://provider.invalid/v1/chat/completions")
    response = httpx.Response(
        503,
        request=request,
        text="503 Service Temporarily Unavailable",
    )
    error = httpx.HTTPStatusError(
        "provider returned HTTP 503",
        request=request,
        response=response,
    )
    return InstructorRetryException(
        "provider request failed",
        n_attempts=1,
        total_usage=0,
        failed_attempts=[FailedAttempt(1, error)],
    )


def test_wrapped_provider_503_is_not_classified_as_schema_invalid():
    from app.infrastructure.llm import structured
    from app.infrastructure.llm.dimension_runtime import is_provider_failure

    error = _retry_exception_with_provider_503()

    assert structured.provider_http_status(error) == 503
    assert structured.structured_failure_code(error) == "PROVIDER_HTTP_5XX"
    assert "http_status=503" in structured.structured_failure_summary(error)
    assert "SCHEMA_INVALID" not in structured.structured_failure_summary(error)
    assert is_provider_failure(error) is True


@pytest.mark.asyncio
async def test_transient_retry_unwraps_provider_503_from_instructor(monkeypatch):
    from app.infrastructure.llm import structured

    calls = 0

    class _Completions:
        async def create(self, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise _retry_exception_with_provider_503()
            return _Result(value=7)

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "test-model")

    result = await structured.run_structured_output(
        _Result,
        [{"role": "user", "content": "return seven"}],
        max_retries=0,
        transient_retries=1,
        transient_retry_backoff_s=0,
        timeout=2,
    )

    assert result == _Result(value=7)
    assert calls == 2


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
async def test_runner_rejects_complete_content_json_after_instructor_retry(
    monkeypatch, content
):
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
async def test_runner_rejects_untyped_l1_observation_json(monkeypatch):
    from instructor.core import InstructorRetryException
    from app.domain.assessment.observation_draft import L1ObservationPassOutput
    from app.infrastructure.llm import structured

    content = (
        '{"observations":[{"fact_type":"spatial_entity",'
        '"entity_type":"道路","name":"村道",'
        '"locator":{"place_names":["沿村"],"relation":"贯穿村庄"},'
        '"description":"现状道路","scale":"1条"}]}'
    )

    class _Completions:
        async def create(self, **_kwargs):
            raise _retry_exception_with_content(content)

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "MiniMax-M2.7-highspeed")

    with pytest.raises(InstructorRetryException):
        await structured.run_structured_output(
            L1ObservationPassOutput,
            [{"role": "user", "content": "return the typed L1 output"}],
            max_retries=1,
            timeout=2,
        )


@pytest.mark.asyncio
async def test_runner_rejects_untyped_l3_claim_json(monkeypatch):
    from instructor.core import InstructorRetryException
    from app.domain.program.claim_draft import L3ClaimOutput
    from app.infrastructure.llm import structured

    content = '{"claims":[{"claim_id":"land-use-1","statement":"保留现状生态与耕地格局"}]}'

    class _Completions:
        async def create(self, **_kwargs):
            raise _retry_exception_with_content(content)

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "MiniMax-M2.7-highspeed")

    with pytest.raises(InstructorRetryException):
        await structured.run_structured_output(
            L3ClaimOutput,
            [{"role": "user", "content": "return the typed L3 output"}],
            max_retries=1,
            timeout=2,
        )


@pytest.mark.asyncio
async def test_runner_classifies_plain_markdown_as_tool_call_missing(monkeypatch):
    from instructor.core import InstructorRetryException
    from app.infrastructure.llm import structured

    class _Completions:
        async def create(self, **_kwargs):
            raise _retry_exception_with_content("这是一段没有结构化结果的普通说明。")

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "MiniMax-M2.7-highspeed")

    with pytest.raises(InstructorRetryException) as raised:
        await structured.run_structured_output(
            _Result,
            [{"role": "user", "content": "return seven"}],
            max_retries=1,
            timeout=2,
        )
    assert structured.structured_failure_code(raised.value) == "TOOL_CALL_MISSING"


@pytest.mark.asyncio
async def test_runner_rejects_untyped_plain_report(monkeypatch):
    from instructor.core import InstructorRetryException
    from app.domain.assessment.observation_draft import L1ReportOutput
    from app.infrastructure.llm import structured

    content = (
        "【空间结构】金田村现状建设主要沿村道和河谷呈组团分布，公共服务设施集中在村委会周边。"
        "现状交通联系依赖既有村道，部分自然村之间的步行和消防通行条件仍需进一步核验，"
        "本段结论仅描述现状，不直接替代后续规划目标和空间候选。"
    )

    class _Completions:
        async def create(self, **_kwargs):
            raise _retry_exception_with_content(content)

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "MiniMax-M2.7-highspeed")

    with pytest.raises(InstructorRetryException):
        await structured.run_structured_output(
            L1ReportOutput,
            [{"role": "user", "content": "return the typed report"}],
            max_retries=1,
            timeout=2,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        "这是一段过短的返回。",
        "完整正文但含有 ```json\n未闭合的结构化尾巴。" + "补充说明" * 30,
        "<think>reasoning</think>正文中途再次出现<think>" + "内容" * 30,
    ],
    ids=["short", "fence", "non-wrapper-think"],
)
async def test_runner_rejects_unsafe_plain_report_fallback(monkeypatch, content):
    from instructor.core import InstructorRetryException
    from app.domain.assessment.observation_draft import L1ReportOutput
    from app.infrastructure.llm import structured

    class _Completions:
        async def create(self, **_kwargs):
            raise _retry_exception_with_content(content)

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "MiniMax-M2.7-highspeed")

    with pytest.raises(InstructorRetryException):
        await structured.run_structured_output(
            L1ReportOutput,
            [{"role": "user", "content": "return the typed report"}],
            max_retries=1,
            timeout=2,
        )


@pytest.mark.asyncio
async def test_runner_classifies_finish_length_and_retries_once(monkeypatch):
    from instructor.core import InstructorRetryException
    from app.infrastructure.llm import structured

    requests: list[dict] = []

    class _Completions:
        async def create(self, **kwargs):
            requests.append(kwargs)
            if len(requests) == 1:
                raise _retry_exception_with_content("{\"value\":", finish_reason="length")
            return _Result(value=7)

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "MiniMax-M2.7-highspeed")

    result = await structured.run_structured_output(
        _Result,
        [{"role": "user", "content": "return seven"}],
        max_retries=1,
        timeout=2,
        max_tokens=300,
        incomplete_output_max_tokens=8192,
    )
    assert result == _Result(value=7)
    assert [request["max_tokens"] for request in requests] == [300, 600]


@pytest.mark.asyncio
async def test_runner_classifies_schema_invalid_without_logging_model_content(monkeypatch):
    from instructor.core import InstructorRetryException
    from app.infrastructure.llm import structured

    warnings: list[tuple] = []

    class _Completions:
        async def create(self, **_kwargs):
            raise _retry_exception_with_content('{"other":7}', message="schema validation failed")

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "MiniMax-M2.7-highspeed")
    monkeypatch.setattr(structured.logger, "warning", lambda *args, **_kwargs: warnings.append(args))

    with pytest.raises(InstructorRetryException) as raised:
        await structured.run_structured_output(
            _Result,
            [{"role": "user", "content": "return seven"}],
            max_retries=1,
            timeout=2,
        )
    assert structured.structured_failure_code(raised.value) == "SCHEMA_INVALID"
    assert '"other":7' not in " ".join(str(item) for warning in warnings for item in warning)


@pytest.mark.asyncio
async def test_minimax_structured_request_enables_reasoning_split(monkeypatch):
    from app.infrastructure.llm import structured

    requests: list[dict] = []

    class _Completions:
        async def create(self, **kwargs):
            requests.append(kwargs)
            return _Result(value=7)

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setenv("LLM_PROVIDER", "minimax")
    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "MiniMax-M2.7-highspeed")

    await structured.run_structured_output(
        _Result,
        [{"role": "user", "content": "return seven"}],
        timeout=2,
    )
    assert requests[0]["extra_body"]["reasoning_split"] is True


@pytest.mark.asyncio
async def test_incomplete_exception_without_length_metadata_is_not_retried(monkeypatch):
    from instructor.core import IncompleteOutputException
    from app.infrastructure.llm import structured

    requests: list[dict] = []

    class _Completions:
        async def create(self, **kwargs):
            requests.append(kwargs)
            raise IncompleteOutputException(last_completion=None)

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(structured, "get_structured_model", lambda model=None: "MiniMax-M2.7-highspeed")

    with pytest.raises(IncompleteOutputException) as raised:
        await structured.run_structured_output(
            _Result,
            [{"role": "user", "content": "return seven"}],
            timeout=2,
            max_tokens=300,
            incomplete_output_max_tokens=8192,
        )
    assert len(requests) == 1
    assert structured.structured_failure_code(raised.value) == "SCHEMA_INVALID"


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
                raise IncompleteOutputException(
                    last_completion=SimpleNamespace(
                        choices=[SimpleNamespace(finish_reason="length")]
                    )
                )
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
            raise IncompleteOutputException(
                last_completion=SimpleNamespace(
                    choices=[SimpleNamespace(finish_reason="length")]
                )
            )

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
async def test_sync_bridge_timeout_does_not_wait_for_provider_thread():
    from app.infrastructure.llm.structured import run_structured_output_sync

    class _Runner:
        async def ainvoke(self, _input):
            await asyncio.sleep(1)
            return _Result(value=1)

    class _LLM:
        def with_structured_output(self, *_args, **_kwargs):
            return _Runner()

    with pytest.raises(TimeoutError):
        run_structured_output_sync(
            _Result,
            [{"role": "user", "content": "return one"}],
            llm=_LLM(),
            max_retries=0,
            timeout=0.03,
        )


@pytest.mark.asyncio
async def test_runner_retries_connection_error_without_http_status(monkeypatch):
    from app.infrastructure.llm import structured

    calls = 0

    class _Completions:
        async def create(self, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("Connection error")
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


def test_minimax_structured_client_defaults_to_tools_mode(monkeypatch):
    from app.infrastructure.llm import instructor_client

    instructor_client._cached_clients.clear()
    created: list[dict] = []

    class _Wrapped:
        pass

    monkeypatch.delenv("LLM_STRUCTURED_MODE", raising=False)
    monkeypatch.setattr(
        instructor_client,
        "_provider_connection",
        lambda: ("minimax", "test-key", "https://api.minimaxi.com/v1"),
    )
    monkeypatch.setattr(instructor_client, "OpenAI", lambda **kwargs: kwargs)
    monkeypatch.setattr(
        instructor_client.instructor,
        "from_openai",
        lambda client, **kwargs: (
            created.append({"client": client, **kwargs}) or _Wrapped()
        ),
    )

    instructor_client.get_instructor_client()

    assert created[0]["mode"] is instructor_client.instructor.Mode.TOOLS


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
