"""Bounded, typed structured-output execution for application contracts."""

from __future__ import annotations

import asyncio
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

from pydantic import BaseModel

from app.infrastructure.logging import get_logger
from app.infrastructure.llm.instructor_client import (
    get_async_instructor_client,
    get_instructor_client,
    get_structured_model,
)

ModelT = TypeVar("ModelT", bound=BaseModel)
logger = get_logger(__name__)

_CONTEXT_OVERFLOW_RE = re.compile(
    r"(?:\bcontext_length_exceeded\b|"
    r"\bmaximum context (?:length|window)\b|"
    r"\bcontext window (?:was )?exceeded\b|"
    r"\bprompt (?:is )?too long\b|"
    r"\brequest too large\b|"
    r"\btoo many tokens\b|"
    r"\binput tokens? (?:count )?exceed(?:s|ed)? (?:the )?"
    r"(?:model(?:'s)? )?(?:context )?limit\b)",
    re.IGNORECASE,
)

STRUCTURED_FAILURE_CODES = frozenset(
    {
        "CONTEXT_OVERFLOW",
        "OUTPUT_TRUNCATED",
        "TOOL_CALL_MISSING",
        "SCHEMA_INVALID",
        "TIMEOUT",
    }
)


def _set_failure_code(exc: BaseException, code: str) -> None:
    """Attach a bounded classification without changing provider exception text."""
    try:
        setattr(exc, "structured_failure_code", code)
    except Exception:
        pass


def _completion_finish_reason(completion: Any) -> str:
    choices = _read_field(completion, "choices")
    if not isinstance(choices, (list, tuple)) or not choices:
        return ""
    return str(_read_field(choices[0], "finish_reason") or "").strip().lower()


def _classify_structured_failure(exc: BaseException, completion: Any = None) -> str | None:
    """Classify a typed-output failure using provider metadata and safe markers."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "TIMEOUT"
    finish_reason = _completion_finish_reason(completion)
    if finish_reason == "length":
        return "OUTPUT_TRUNCATED"
    message = str(exc or "").lower()
    if _CONTEXT_OVERFLOW_RE.search(message):
        return "CONTEXT_OVERFLOW"
    if "no tool calls" in message or "function call found" in message:
        return "TOOL_CALL_MISSING"
    if "validation" in message or "schema" in message or "parse" in message:
        return "SCHEMA_INVALID"
    return None


def structured_failure_code(exc: BaseException) -> str | None:
    """Return the bounded typed-output code attached by this module."""
    code = str(getattr(exc, "structured_failure_code", "") or "").strip()
    return code if code in STRUCTURED_FAILURE_CODES else _classify_structured_failure(exc)


def structured_failure_summary(exc: BaseException) -> str:
    """Return a stable diagnostic that never embeds provider response text."""
    code = structured_failure_code(exc) or "STRUCTURED_OUTPUT_ERROR"
    return f"{code} ({type(exc).__name__})"


def _read_field(value: Any, field: str) -> Any:
    if isinstance(value, dict):
        return value.get(field)
    return getattr(value, field, None)


async def run_structured_output(
    response_model: type[ModelT],
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    max_retries: int = 2,
    timeout: float | None = None,
    context: dict[str, Any] | None = None,
    llm: Any | None = None,
    incomplete_output_max_tokens: int | None = None,
    max_concurrent: int | None = None,
    semaphore_scope: str = "default",
    transient_retries: int = 0,
    transient_retry_backoff_s: float = 2.0,
    **kwargs: Any,
) -> ModelT:
    """Generate a Pydantic result through Instructor with bounded reasks.

    Production calls use Instructor's async OpenAI-compatible client so the
    LangGraph event loop remains responsive.  The dependency-injection path
    keeps a synchronous fallback for deterministic test doubles.  ``timeout``
    bounds the caller's wait, while ``max_retries`` bounds schema-validation
    reasks.  Transport retries remain controlled by the provider client itself.
    """
    retry_budget = max(0, int(max_retries))
    request: dict[str, Any] = {
        "model": get_structured_model(model),
        "response_model": response_model,
        "messages": messages,
        "max_retries": retry_budget,
        **kwargs,
    }
    provider_name = os.getenv("LLM_PROVIDER", "").strip().lower()
    if provider_name in {"minimax", "minimaxai", "mini-max"}:
        # MiniMax M2.x may expose reasoning and final content separately when
        # requested.  Keep this provider hint scoped to typed calls; free-form
        # L3 generation remains responsible for its own reasoning policy.
        extra_body = dict(request.get("extra_body") or {})
        extra_body.setdefault("reasoning_split", True)
        request["extra_body"] = extra_body
    if provider_name in {"opencode-go", "opencode_go", "opencodego"}:
        # Console Go currently rejects tool_choice when DeepSeek V4 is in
        # thinking mode.  Instructor's TOOLS mode necessarily sends
        # tool_choice, so structured contracts use non-thinking mode.  This
        # keeps the typed contract reliable; free-form L2 calls remain
        # independent of this compatibility setting.
        extra_body = dict(request.get("extra_body") or {})
        extra_body.setdefault("thinking", {"type": "disabled"})
        request["extra_body"] = extra_body
    if context is not None:
        request["context"] = context

    async def _call_once(call_request: dict[str, Any]) -> ModelT:
        if llm is not None:
            # Dependency-injection seam for existing deterministic tests and
            # controlled adapters. Production calls leave this unset and use
            # the Instructor client below.
            structured = llm.with_structured_output(
                response_model,
                method="function_calling",
            )
            invoke_input: Any = messages
            if len(messages) == 1 and messages[0].get("role") == "user":
                invoke_input = messages[0].get("content", "")
            invoke = getattr(structured, "ainvoke", None)
            if callable(invoke):
                result = await invoke(invoke_input)
            else:
                result = await asyncio.to_thread(structured.invoke, invoke_input)
            if isinstance(result, response_model):
                return result
            return response_model.model_validate(result)

        client = get_async_instructor_client()
        result = await client.chat.completions.create(**call_request)
        if not isinstance(result, response_model):
            return response_model.model_validate(result)
        return result

    async def _call() -> ModelT:
        from instructor.core import IncompleteOutputException, InstructorRetryException

        async def _retry_after_truncation(exc: BaseException) -> ModelT:
            current_tokens = request.get("max_tokens")
            try:
                current_tokens = int(current_tokens)
            except (TypeError, ValueError):
                current_tokens = 0
            configured_ceiling = (
                incomplete_output_max_tokens
                if incomplete_output_max_tokens is not None
                else int(os.getenv("LLM_INCOMPLETE_OUTPUT_MAX_TOKENS", "0"))
            )
            ceiling = max(current_tokens, int(configured_ceiling))
            if current_tokens <= 0 or ceiling <= current_tokens:
                raise exc
            retry_request = dict(request)
            retry_request["max_tokens"] = min(ceiling, current_tokens * 2)
            logger.warning(
                "[structured] incomplete output; retrying with max_tokens=%d",
                retry_request["max_tokens"],
            )
            return await _call_once(retry_request)

        try:
            return await _call_once(request)
        except InstructorRetryException as exc:
            completion = exc.last_completion
            failure_code = _classify_structured_failure(exc, completion)
            if failure_code == "OUTPUT_TRUNCATED":
                try:
                    return await _retry_after_truncation(exc)
                except BaseException as retry_exc:
                    retry_code = _classify_structured_failure(
                        retry_exc, getattr(retry_exc, "last_completion", None)
                    )
                    _set_failure_code(retry_exc, retry_code or "OUTPUT_TRUNCATED")
                    raise
            _set_failure_code(exc, failure_code or "SCHEMA_INVALID")
            logger.warning(
                "[structured] typed output failed; untyped content is not accepted"
            )
            raise
        except IncompleteOutputException as exc:
            # Instructor raises this specific exception when the provider
            # reaches max_tokens before completing the declared tool call.
            # Retry only that condition, with an explicit ceiling; provider
            # 5xx/timeout retries remain owned by the OpenAI transport.
            if _classify_structured_failure(
                exc, getattr(exc, "last_completion", None)
            ) != "OUTPUT_TRUNCATED":
                _set_failure_code(exc, "SCHEMA_INVALID")
                raise
            try:
                return await _retry_after_truncation(exc)
            except BaseException as retry_exc:
                retry_code = _classify_structured_failure(
                    retry_exc, getattr(retry_exc, "last_completion", None)
                )
                _set_failure_code(retry_exc, retry_code or "OUTPUT_TRUNCATED")
                raise

    # LangGraph's graph-level max_concurrency is a scheduling hint and does
    # not reliably bound every Send/resume fan-out at the provider boundary.
    # Acquire one shared, loop-local gate immediately around the actual LLM
    # call so all Instructor contracts share one enforceable budget.
    from app.infrastructure.llm.factory import get_llm_semaphore

    if max_concurrent is None and semaphore_scope == "default":
        # Keep the zero-argument compatibility seam used by deterministic
        # tests and older callers that replace the factory gate.
        semaphore = await get_llm_semaphore()
    else:
        semaphore = await get_llm_semaphore(max_concurrent, scope=semaphore_scope)

    transient_budget = max(0, int(transient_retries))
    backoff = max(0.0, float(transient_retry_backoff_s))

    def _is_transient_provider_error(exc: BaseException) -> bool:
        from app.infrastructure.llm.dimension_runtime import is_provider_quota_exhausted

        if is_provider_quota_exhausted(exc):
            return False
        status = getattr(exc, "status_code", None)
        if status is None:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
        try:
            return int(status) in {429, 500, 502, 503, 504, 529}
        except (TypeError, ValueError):
            return False

    async def _call_with_gate() -> ModelT:
        attempt = 0
        while True:
            try:
                async with semaphore:
                    return await _call()
            except Exception as exc:
                if attempt >= transient_budget or not _is_transient_provider_error(exc):
                    raise
                attempt += 1
                delay = backoff * (2 ** (attempt - 1))
                logger.warning(
                    "[structured] transient provider status=%s; retrying within the bounded call budget (attempt=%d/%d, backoff=%.1fs)",
                    getattr(exc, "status_code", None),
                    attempt,
                    transient_budget,
                    delay,
                )
                if delay:
                    await asyncio.sleep(delay)

    # The timeout starts before semaphore acquisition.  A queued request is
    # still consuming the caller's budget; otherwise provider saturation can
    # leave a task waiting indefinitely and only start the HTTP request after
    # its advertised timeout has already elapsed.
    if timeout is None:
        return await _call_with_gate()
    return await asyncio.wait_for(_call_with_gate(), timeout=float(timeout))


def run_structured_output_sync(
    response_model: type[ModelT],
    messages: list[dict[str, Any]],
    *,
    timeout: float | None = None,
    **kwargs: Any,
) -> ModelT:
    """Synchronous bridge for legacy synchronous pipeline boundaries.

    The bridge still executes the same typed runner, including the shared
    semaphore, bounded retries, and fail-closed handling.  A worker thread is
    used when the caller already owns an event loop, which keeps synchronous
    document/spatial adapters from creating nested loops.
    """

    async def _run() -> ModelT:
        return await run_structured_output(
            response_model,
            messages,
            timeout=timeout,
            **kwargs,
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_run())

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(lambda: asyncio.run(_run()))
    try:
        return future.result(timeout=timeout)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


__all__ = [
    "run_structured_output",
    "run_structured_output_sync",
    "structured_failure_code",
    "structured_failure_summary",
    "STRUCTURED_FAILURE_CODES",
]
