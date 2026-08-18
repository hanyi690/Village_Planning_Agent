"""Bounded, typed structured-output execution for application contracts."""

from __future__ import annotations

import asyncio
import json
import os
import re
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

_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
_THINK_PREFIX_RE = re.compile(r"^<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
_FENCE_LINE_RE = re.compile(r"^\s*```(?:json)?\s*$", re.IGNORECASE | re.MULTILINE)
_JSON_FENCE_RE = re.compile(
    r"^```json[ \t]*\r?\n(?P<body>.*?)\r?\n```$",
    re.IGNORECASE | re.DOTALL,
)


def _read_field(value: Any, field: str) -> Any:
    if isinstance(value, dict):
        return value.get(field)
    return getattr(value, field, None)


def _completion_content(completion: Any) -> str | None:
    if isinstance(completion, str):
        return completion
    choices = _read_field(completion, "choices")
    if not isinstance(choices, (list, tuple)) or not choices:
        return None
    message = _read_field(choices[0], "message")
    content = _read_field(message, "content")
    return content if isinstance(content, str) else None


def _content_summary(content: Any) -> str:
    if content is None:
        return "content=missing"
    if not isinstance(content, str):
        return f"content_type={type(content).__name__}"
    return (
        f"content_type=str length={len(content)} "
        f"has_think={bool(_THINK_BLOCK_RE.search(content))} "
        f"has_fence={bool(_FENCE_LINE_RE.search(content))}"
    )


def _extract_content_json_object(content: Any) -> tuple[dict[str, Any] | None, str]:
    if not isinstance(content, str) or not content.strip():
        return None, "content is not a non-empty string"

    candidate = content.strip()
    think_match = _THINK_PREFIX_RE.match(candidate)
    if think_match:
        candidate = candidate[think_match.end() :].strip()
    else:
        fence_match = _JSON_FENCE_RE.fullmatch(candidate)
        if fence_match:
            candidate = fence_match.group("body").strip()

    if re.search(r"</?think\b", candidate, re.IGNORECASE):
        return None, "content contains a non-wrapper think marker"
    if "```" in candidate:
        return None, "content contains a non-wrapper fence marker"
    if not candidate.startswith("{"):
        return None, "content does not start with a JSON object"

    def _reject_json_constant(value: str) -> Any:
        raise ValueError(f"non-standard JSON constant: {value}")

    try:
        value, end = json.JSONDecoder(parse_constant=_reject_json_constant).raw_decode(candidate)
    except json.JSONDecodeError:
        return None, "content is not complete strict JSON"
    except ValueError:
        return None, "content contains a non-standard JSON constant"
    if not isinstance(value, dict):
        return None, "content JSON is not an object"
    if candidate[end:].strip():
        return None, "content has non-JSON trailing text"
    return value, "ok"


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
            invoke = getattr(structured, "ainvoke", None)
            if callable(invoke):
                result = await invoke(messages)
            else:
                result = await asyncio.to_thread(structured.invoke, messages)
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

        try:
            return await _call_once(request)
        except InstructorRetryException as exc:
            content = _completion_content(exc.last_completion)
            payload, reason = _extract_content_json_object(content)
            if payload is None:
                logger.warning(
                    "[structured] Instructor retry exhausted; content JSON fallback rejected (%s, reason=%s)",
                    _content_summary(content),
                    reason,
                )
                raise
            try:
                result = response_model.model_validate(payload)
            except Exception as validation_exc:
                logger.warning(
                    "[structured] content JSON fallback rejected by response model (%s, validation=%s)",
                    _content_summary(content),
                    type(validation_exc).__name__,
                )
                raise exc from validation_exc
            logger.warning(
                "[structured] Instructor retry exhausted; accepted content JSON fallback (%s, keys=%s)",
                _content_summary(content),
                sorted(payload)[:20],
            )
            return result
        except IncompleteOutputException as exc:
            # Instructor raises this specific exception when the provider
            # reaches max_tokens before completing the declared tool call.
            # Retry only that condition, with an explicit ceiling; provider
            # 5xx/timeout retries remain owned by the OpenAI transport.
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
                raise
            retry_request = dict(request)
            retry_request["max_tokens"] = min(ceiling, current_tokens * 2)
            logger.warning(
                "[structured] incomplete output; retrying with max_tokens=%d",
                retry_request["max_tokens"],
            )
            return await _call_once(retry_request)

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


__all__ = ["run_structured_output"]
