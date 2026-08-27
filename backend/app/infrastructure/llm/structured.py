"""Bounded, typed structured-output execution for application contracts."""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from queue import Empty, Queue
from typing import Any, TypeVar

from pydantic import BaseModel

from app.infrastructure.logging import get_logger
from app.infrastructure.llm.instructor_client import (
    get_async_instructor_client,
    get_structured_model,
)

ModelT = TypeVar("ModelT", bound=BaseModel)
logger = get_logger(__name__)


def _assistant_content(completion: Any) -> str | None:
    choices = _read_field(completion, "choices")
    if not isinstance(choices, (list, tuple)) or not choices:
        return None
    message = _read_field(choices[0], "message")
    content = _read_field(message, "content")
    return content if isinstance(content, str) else None


def _decode_content_json(response_model: type[ModelT], completion: Any) -> ModelT:
    content = _assistant_content(completion)
    if content is None:
        raise ValueError("structured assistant content is missing")
    from app.contracts.json_container import decode_json_container

    decoded = decode_json_container(content)
    if not isinstance(decoded, dict):
        raise ValueError("structured assistant content must be a JSON object")
    return response_model.model_validate(decoded)

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
        "PROVIDER_HTTP_4XX",
        "PROVIDER_HTTP_5XX",
        "PROVIDER_TRANSPORT",
    }
)

_PROVIDER_STATUS_TEXT_RE = re.compile(
    r"\b(429|4\d{2}|5\d{2})\b\s+"
    r"(?:service temporarily unavailable|bad gateway|gateway timeout|too many requests)",
    re.IGNORECASE,
)


def _iter_nested_exceptions(exc: BaseException):
    """Yield wrapper and provider exceptions without exposing response bodies."""

    pending = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop(0)
        if not isinstance(current, BaseException) or id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        for attempt in getattr(current, "failed_attempts", ()) or ():
            nested = getattr(attempt, "exception", None)
            if isinstance(nested, BaseException):
                pending.append(nested)
        for attribute in ("__cause__", "__context__", "last_exception", "original_exception"):
            nested = getattr(current, attribute, None)
            if isinstance(nested, BaseException):
                pending.append(nested)


def _exception_status_code(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    try:
        status_int = int(status)
    except (TypeError, ValueError):
        status_int = 0
    if 400 <= status_int <= 599:
        return status_int
    match = _PROVIDER_STATUS_TEXT_RE.search(str(exc or ""))
    return int(match.group(1)) if match else None


def provider_http_status(exc: BaseException) -> int | None:
    """Return an HTTP status from a wrapped provider exception, if present."""

    for nested in _iter_nested_exceptions(exc):
        status = _exception_status_code(nested)
        if status is not None:
            return status
    return None


def provider_failure_code(exc: BaseException) -> str | None:
    """Classify wrapped HTTP/transport failures before schema text matching."""

    try:
        import httpx
        from openai import APIError

        provider_error_types = (APIError, httpx.HTTPError)
    except ImportError:
        provider_error_types = ()
    for nested in _iter_nested_exceptions(exc):
        status = _exception_status_code(nested)
        if status is not None:
            if 500 <= status <= 599:
                return "PROVIDER_HTTP_5XX"
            return "PROVIDER_HTTP_4XX"
        if isinstance(nested, provider_error_types) or (
            isinstance(nested, (ConnectionError, OSError))
            and not isinstance(nested, (asyncio.TimeoutError, TimeoutError))
        ):
            return "PROVIDER_TRANSPORT"
    return None


def _set_failure_code(exc: BaseException, code: str) -> None:
    """Attach a bounded classification without changing provider exception text."""
    try:
        setattr(exc, "structured_failure_code", code)
    except Exception:
        pass


def _set_contract_metadata(exc: BaseException, metadata: dict[str, Any]) -> None:
    if not metadata:
        return
    try:
        setattr(exc, "structured_contract", metadata)
    except Exception:
        pass


def _completion_finish_reason(completion: Any) -> str:
    choices = _read_field(completion, "choices")
    if not isinstance(choices, (list, tuple)) or not choices:
        return ""
    return str(_read_field(choices[0], "finish_reason") or "").strip().lower()


def _value_length(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes, list, tuple, dict)):
        return len(value)
    return None


def _completion_shape(completion: Any) -> dict[str, Any]:
    """Describe a provider completion without recording its content."""

    choices = _read_field(completion, "choices")
    if not isinstance(choices, (list, tuple)):
        return {"choices": 0, "completion_type": type(completion).__name__}
    shape: dict[str, Any] = {
        "choices": len(choices),
        "completion_type": type(completion).__name__,
    }
    if not choices:
        return shape
    choice = choices[0]
    message = _read_field(choice, "message")
    tool_calls = _read_field(message, "tool_calls")
    function_call = _read_field(message, "function_call")
    content = _read_field(message, "content")
    reasoning_content = _read_field(message, "reasoning_content")
    shape.update({
        "finish_reason": str(_read_field(choice, "finish_reason") or ""),
        "message_type": type(message).__name__,
        "message_content_type": type(content).__name__ if content is not None else None,
        "message_content_length": _value_length(content),
        "reasoning_content_type": (
            type(reasoning_content).__name__ if reasoning_content is not None else None
        ),
        "reasoning_content_length": _value_length(reasoning_content),
        "tool_calls_type": type(tool_calls).__name__ if tool_calls is not None else None,
        "tool_calls_count": len(tool_calls) if isinstance(tool_calls, (list, tuple)) else 0,
        "function_call_present": function_call is not None,
        "refusal_present": _read_field(message, "refusal") is not None,
    })
    return shape


def _set_completion_shape(exc: BaseException, completion: Any) -> dict[str, Any]:
    shape = _completion_shape(completion)
    try:
        setattr(exc, "structured_response_shape", shape)
    except Exception:
        pass
    return shape


def _classify_structured_failure(exc: BaseException, completion: Any = None) -> str | None:
    """Classify a typed-output failure using provider metadata and safe markers."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "TIMEOUT"
    provider_code = provider_failure_code(exc)
    if provider_code is not None:
        return provider_code
    finish_reason = _completion_finish_reason(completion)
    if finish_reason == "length":
        return "OUTPUT_TRUNCATED"
    message = "\n".join(
        str(nested or "") for nested in _iter_nested_exceptions(exc)
    ).lower()
    if _CONTEXT_OVERFLOW_RE.search(message):
        return "CONTEXT_OVERFLOW"
    if "validation" in message or "schema" in message or "parse" in message:
        return "SCHEMA_INVALID"
    if "no tool calls" in message or "function call found" in message:
        return "TOOL_CALL_MISSING"
    shape = _completion_shape(completion)
    if (
        shape.get("choices", 0) > 0
        and not shape.get("tool_calls_count")
        and not shape.get("function_call_present")
    ):
        return "TOOL_CALL_MISSING"
    return None


def structured_failure_code(exc: BaseException) -> str | None:
    """Return the bounded typed-output code attached by this module."""
    provider_code = provider_failure_code(exc)
    if provider_code is not None:
        return provider_code
    code = str(getattr(exc, "structured_failure_code", "") or "").strip()
    return code if code in STRUCTURED_FAILURE_CODES else _classify_structured_failure(exc)


def structured_failure_summary(exc: BaseException) -> str:
    """Return a stable diagnostic that never embeds provider response text."""
    code = structured_failure_code(exc) or "STRUCTURED_OUTPUT_ERROR"
    status = provider_http_status(exc)
    status_suffix = f"; http_status={status}" if status is not None else ""
    shape = getattr(exc, "structured_response_shape", None)
    contract = getattr(exc, "structured_contract", None)
    shape_suffix = ""
    if isinstance(shape, dict):
        shape_suffix = "; response_shape=" + json.dumps(
            shape,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    contract_suffix = ""
    if isinstance(contract, dict) and contract.get("contract_key"):
        contract_suffix = f"; contract={contract['contract_key']}"
    request = getattr(exc, "structured_request", None)
    request_suffix = ""
    if isinstance(request, dict):
        request_suffix = "; request=" + json.dumps(
            request,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    input_suffix = ""
    input_chars = getattr(exc, "input_chars", None)
    input_limit = getattr(exc, "input_char_limit", None)
    if input_chars is not None and input_limit is not None:
        input_suffix = f"; input_chars={input_chars}; input_char_limit={input_limit}"
    return f"{code} ({type(exc).__name__}{status_suffix}{contract_suffix}{shape_suffix}{request_suffix}{input_suffix})"


def _read_field(value: Any, field: str) -> Any:
    if isinstance(value, dict):
        return value.get(field)
    return getattr(value, field, None)


_STRUCTURED_PROTOCOL_MARKER = "[structured-output-protocol:v1]"


def _message_shape(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return message metadata without persisting prompt contents."""

    shape: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        shape.append(
            {
                "role": str(message.get("role") or "") if isinstance(message, dict) else "",
                "content_type": type(content).__name__ if content is not None else None,
                "content_length": _value_length(content),
            }
        )
    return shape


def _structured_protocol_instruction(
    *,
    contract_key: str | None,
    response_model: type[ModelT],
    protocol_mode: str | None = None,
) -> str:
    """Build the one provider-protocol instruction for every typed call.

    Domain prompts describe *what* to extract.  This message describes only
    *how* the typed result crosses the provider boundary, so callers cannot
    accidentally mix tool arguments with JSON-in-content instructions.
    """

    identity = contract_key or response_model.__name__
    mode = protocol_mode or _langchain_structured_method()
    if mode == "json_schema":
        channel = (
            "本次调用使用 provider 原生 JSON Schema response_format。assistant message.content"
            " 必须是一个符合声明 schema 的 JSON 对象；不要输出 Markdown、解释、思考过程或额外文字。"
        )
    elif mode == "json_mode":
        channel = (
            "本次调用使用 JSON content 协议。只在 assistant message.content 中返回一个"
            "与声明 schema 完全匹配的 JSON 对象；不要输出 Markdown、解释、思考过程或额外文字。"
        )
    else:
        channel = (
            "本次调用使用 typed response tool 协议。必须调用声明的响应工具，并把完整结果"
            "放入 tool arguments；不要把结果 JSON 写入 assistant message.content，也不要输出"
            "Markdown、解释或思考过程。"
        )
    return (
        f"{_STRUCTURED_PROTOCOL_MARKER}\n"
        f"契约标识：{identity}。响应模型和字段规则只以 provider 收到的声明 schema 为准；"
        "不要改名、补充未声明根字段或把多个 envelope 拼在一起。"
        f"{channel}"
    )


def _prepare_structured_messages(
    messages: list[dict[str, Any]],
    *,
    contract_key: str | None,
    response_model: type[ModelT],
    protocol_mode: str | None = None,
) -> list[dict[str, Any]]:
    """Copy caller messages and insert the protocol instruction once.

    The instruction is inserted after caller system messages and before the
    first user message.  This keeps domain context intact while making the
    transport protocol the final system-level instruction seen before input.
    """

    if not isinstance(messages, list) or any(not isinstance(item, dict) for item in messages):
        raise TypeError("structured messages must be a list of message dictionaries")
    copied = [dict(item) for item in messages]
    protocol_message = _structured_protocol_instruction(
        contract_key=contract_key,
        response_model=response_model,
        protocol_mode=protocol_mode,
    )
    for item in copied:
        if (
            item.get("role") == "system"
            and str(item.get("content") or "").startswith(_STRUCTURED_PROTOCOL_MARKER)
        ):
            if protocol_mode:
                item["content"] = protocol_message
            return copied
    insert_at = next(
        (index for index, item in enumerate(copied) if item.get("role") != "system"),
        len(copied),
    )
    copied.insert(
        insert_at,
        {
            "role": "system",
            "content": protocol_message,
        },
    )
    return copied


def _request_shape(
    request: dict[str, Any],
    *,
    contract_key: str | None,
    structured_mode: str | None = None,
) -> dict[str, Any]:
    """Return safe pre-provider request metadata for failure diagnosis."""

    messages = request.get("messages")
    return {
        "model": str(request.get("model") or ""),
        "contract_key": contract_key,
        "structured_mode": structured_mode or _langchain_structured_method(),
        "response_model": getattr(request.get("response_model"), "__name__", ""),
        "max_retries": request.get("max_retries"),
        "max_tokens": request.get("max_tokens"),
        "message_shape": _message_shape(messages) if isinstance(messages, list) else [],
        "extra_body_keys": sorted(
            str(key) for key in (request.get("extra_body") or {}).keys()
        ),
    }


def _set_request_shape(
    exc: BaseException,
    request: dict[str, Any],
    *,
    contract_key: str | None,
    structured_mode: str | None = None,
) -> None:
    try:
        setattr(
            exc,
            "structured_request",
            _request_shape(
                request,
                contract_key=contract_key,
                structured_mode=structured_mode,
            ),
        )
    except Exception:
        pass


def _is_content_json_fallback_candidate(
    exc: BaseException,
    completion: Any = None,
) -> bool:
    """Return whether a strict protocol failure may use JSON content once."""

    if _langchain_structured_method() == "json_mode":
        return False
    failure_code = _classify_structured_failure(exc, completion)
    if failure_code in {"TOOL_CALL_MISSING", "SCHEMA_INVALID"}:
        return True
    if failure_code != "PROVIDER_HTTP_4XX":
        return False
    message = "\n".join(
        str(nested or "") for nested in _iter_nested_exceptions(exc)
    ).lower()
    protocol_marker = any(
        marker in message
        for marker in (
            "response_format",
            "json_schema",
            "tool_choice",
            "function_call",
            "tools",
        )
    )
    unsupported_marker = any(
        marker in message
        for marker in ("unsupported", "not supported", "does not support", "not allowed")
    )
    return protocol_marker and unsupported_marker


def _langchain_structured_method() -> str:
    """Select the provider-compatible LangChain structured-output method."""

    from app.core.llm_config import get_llm_settings

    configured = get_llm_settings().typed_mode()
    if configured.value == "tools":
        return "function_calling"
    if configured.value == "json_schema":
        return "json_schema"
    if configured.value in {"json", "md_json"}:
        return "json_mode"
    return "function_calling"


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
    contract_key: str | None = None,
    timeout_includes_queue: bool = True,
    allow_content_json: bool = False,
    **kwargs: Any,
) -> ModelT:
    """Generate a Pydantic result through Instructor with bounded reasks.

    Production calls use Instructor's async OpenAI-compatible client so the
    LangGraph event loop remains responsive.  The dependency-injection path
    keeps a synchronous fallback for deterministic test doubles.  ``timeout``
    bounds the caller's wait, while ``max_retries`` bounds schema-validation
    reasks.  Transport retries are opt-in and only apply to classified
    transient provider failures.
    """
    retry_budget = max(0, int(max_retries))
    from app.core.llm_config import get_llm_settings

    llm_config = get_llm_settings()
    contract_metadata: dict[str, Any] = {}
    if contract_key:
        from app.contracts.registry import contract_context

        contract_metadata = contract_context(contract_key, response_model)
    prepared_messages = _prepare_structured_messages(
        messages,
        contract_key=contract_key,
        response_model=response_model,
    )
    request: dict[str, Any] = {
        "model": get_structured_model(model),
        "response_model": response_model,
        "messages": prepared_messages,
        "max_retries": retry_budget,
        **kwargs,
    }
    provider_name = llm_config.provider
    if provider_name in {"minimax", "minimaxai", "mini-max"}:
        # MiniMax M2.x may expose reasoning and final content separately when
        # requested.  Keep this provider hint scoped to typed calls; free-form
        # L3 generation remains responsible for its own reasoning policy.
        extra_body = dict(request.get("extra_body") or {})
        extra_body.setdefault("reasoning_split", True)
        request["extra_body"] = extra_body
    if provider_name in {"opencode-go", "opencode_go", "opencodego"}:
        # This is model-specific on the OpenCode Go route: DeepSeek V4
        # accepts disabled thinking, while GLM-5.x rejects it and requires an
        # explicit reasoning level.  Resolve it from the same typed settings
        # snapshot used for the provider connection.
        extra_body = dict(request.get("extra_body") or {})
        extra_body.setdefault("thinking", llm_config.opencode_go_thinking_payload())
        request["extra_body"] = extra_body
        reasoning_effort = llm_config.opencode_go_reasoning_effort()
        if reasoning_effort and "reasoning_effort" not in request:
            request["reasoning_effort"] = reasoning_effort
    if context is not None:
        request["context"] = context

    async def _invoke_injected(structured: Any, message_list: list[dict[str, Any]]) -> Any:
        """Invoke the current injected runnable interface exactly once."""
        invoke = getattr(structured, "ainvoke", None)
        if callable(invoke):
            return await invoke(message_list)
        sync_invoke = getattr(structured, "invoke", None)
        if not callable(sync_invoke):
            raise TypeError("injected structured adapter has no invoke method")
        return await asyncio.to_thread(sync_invoke, message_list)

    async def _call_once(call_request: dict[str, Any]) -> ModelT:
        if llm is not None:
            # Dependency-injection seam for existing deterministic tests and
            # controlled adapters. Production calls leave this unset and use
            # the Instructor client below.  Ground/RAG callers may provide a
            # provider-specific LangChain model; keep its wire protocol aligned
            # with the direct Instructor client and provider mode selection.
            try:
                structured = llm.with_structured_output(
                    response_model,
                    method=_langchain_structured_method(),
                )
            except (NotImplementedError, TypeError, ValueError) as exc:
                _set_failure_code(exc, "SCHEMA_INVALID")
                raise
            result = await _invoke_injected(structured, call_request.get("messages", prepared_messages))
            if result is None:
                error = ValueError("structured provider returned no typed output")
                _set_contract_metadata(error, contract_metadata)
                _set_failure_code(error, "TOOL_CALL_MISSING")
                raise error
            if isinstance(result, response_model):
                return result
            return response_model.model_validate(result)

        client = get_async_instructor_client()
        result = await client.chat.completions.create(**call_request)
        if result is None:
            error = ValueError("structured provider returned no typed output")
            _set_contract_metadata(error, contract_metadata)
            _set_failure_code(error, "TOOL_CALL_MISSING")
            raise error
        if not isinstance(result, response_model):
            return response_model.model_validate(result)
        return result

    async def _content_json_fallback() -> ModelT:
        """Make one JSON-mode request and accept only assistant JSON content."""
        import instructor

        fallback_request = dict(request)
        fallback_request["max_retries"] = 0
        fallback_request["messages"] = _prepare_structured_messages(
            messages,
            contract_key=contract_key,
            response_model=response_model,
            protocol_mode="json_mode",
        )
        if llm is not None:
            try:
                structured = llm.with_structured_output(
                    response_model,
                    method="json_mode",
                )
            except (NotImplementedError, TypeError, ValueError) as exc:
                _set_failure_code(exc, "SCHEMA_INVALID")
                raise
            result = await _invoke_injected(structured, fallback_request["messages"])
            if result is None:
                error = ValueError("structured provider returned no JSON content")
                _set_failure_code(error, "TOOL_CALL_MISSING")
                raise error
            if isinstance(result, response_model):
                return result
            if isinstance(result, str):
                from app.contracts.json_container import decode_json_container

                decoded = decode_json_container(result)
                if not isinstance(decoded, dict):
                    raise ValueError("injected JSON fallback must return an object")
                return response_model.model_validate(decoded)
            if _assistant_content(result) is not None:
                return _decode_content_json(response_model, result)
            return response_model.model_validate(result)
        fallback_client = get_async_instructor_client(
            mode_override=instructor.Mode.JSON,
        )
        try:
            result = await fallback_client.chat.completions.create(**fallback_request)
        except BaseException as fallback_exc:
            completion = getattr(fallback_exc, "last_completion", None)
            if completion is None:
                raise
            try:
                return _decode_content_json(response_model, completion)
            except Exception as validation_exc:
                _set_failure_code(validation_exc, "SCHEMA_INVALID")
                raise validation_exc from fallback_exc
        if isinstance(result, response_model):
            return result
        if _assistant_content(result) is not None:
            return _decode_content_json(response_model, result)
        return response_model.model_validate(result)

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
                else int(llm_config.incomplete_output_max_tokens)
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

        async def _run_content_json_fallback() -> ModelT:
            try:
                return await _content_json_fallback()
            except BaseException as fallback_exc:
                _set_contract_metadata(fallback_exc, contract_metadata)
                _set_request_shape(
                    fallback_exc,
                    request,
                    contract_key=contract_key,
                    structured_mode="json_fallback",
                )
                raise

        try:
            return await _call_once(request)
        except InstructorRetryException as exc:
            _set_contract_metadata(exc, contract_metadata)
            _set_request_shape(exc, request, contract_key=contract_key)
            completion = exc.last_completion
            failure_code = _classify_structured_failure(exc, completion)
            if failure_code == "TOOL_CALL_MISSING":
                shape = _set_completion_shape(exc, completion)
                logger.warning(
                    "[structured] tool call missing; provider request_shape=%s completion_shape=%s contract=%s",
                    json.dumps(
                        getattr(exc, "structured_request", {}),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    json.dumps(shape, ensure_ascii=False, sort_keys=True),
                    contract_key or response_model.__name__,
                )
            if allow_content_json and _is_content_json_fallback_candidate(
                exc, completion
            ):
                return await _run_content_json_fallback()
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
            _set_contract_metadata(exc, contract_metadata)
            _set_request_shape(exc, request, contract_key=contract_key)
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

        except Exception as exc:
            _set_contract_metadata(exc, contract_metadata)
            _set_request_shape(exc, request, contract_key=contract_key)
            if allow_content_json and _is_content_json_fallback_candidate(exc):
                return await _run_content_json_fallback()
            raise

    # LangGraph's graph-level max_concurrency is a scheduling hint and does
    # not reliably bound every Send/resume fan-out at the provider boundary.
    # Acquire one shared, loop-local gate immediately around the actual LLM
    # call so all Instructor contracts share one enforceable budget.
    from app.infrastructure.llm.factory import get_llm_semaphore

    # A stage gate is not a provider-wide admission policy.  RAG and L1 can
    # overlap inside one dimension wave, so separate scope semaphores would
    # otherwise turn a configured provider budget of 12 into 12 per scope.
    # Keep the configured stage concurrency, but always acquire the one
    # provider-wide gate as well.  This bounds upstream queue pressure without
    # changing the requested stage budget or the prompt/context size.
    provider_semaphore = await get_llm_semaphore()
    if max_concurrent is None and semaphore_scope == "default":
        # The default scope uses only the provider-wide admission gate.
        stage_semaphore = None
    else:
        stage_semaphore = await get_llm_semaphore(
            max_concurrent,
            scope=semaphore_scope,
        )

    transient_budget = max(0, int(transient_retries))
    backoff = max(0.0, float(transient_retry_backoff_s))

    def _is_transient_provider_error(exc: BaseException) -> bool:
        from app.infrastructure.llm.dimension_runtime import is_provider_quota_exhausted

        if is_provider_quota_exhausted(exc):
            return False
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            return False
        status = provider_http_status(exc)
        try:
            if int(status) in {429, 500, 502, 503, 504, 529}:
                return True
        except (TypeError, ValueError):
            pass
        if provider_failure_code(exc) == "PROVIDER_TRANSPORT":
            return True

        # OpenAI-compatible providers frequently surface a socket reset or a
        # connect failure without an HTTP response/status code.  These are
        # safe for one exact-call retry; schema and semantic failures are not.
        if isinstance(exc, (ConnectionError, OSError)):
            return True
        message = str(exc or "").lower()
        return any(
            marker in message
            for marker in (
                "connection error",
                "server disconnected",
                "connection reset",
                "remote protocol error",
                "broken pipe",
                "network is unreachable",
                "temporarily unavailable",
                "timed out",
            )
        )

    async def _call_admitted(*, provider_timeout: float | None = None) -> ModelT:
        async def _invoke() -> ModelT:
            if provider_timeout is None:
                return await _call()
            return await asyncio.wait_for(_call(), timeout=float(provider_timeout))

        started = time.perf_counter()
        # The provider gate is acquired before the optional stage gate so a
        # saturated stage cannot hold a stage slot while waiting for provider
        # capacity.  With the default scope the provider gate is the only gate.
        async with provider_semaphore:
            if stage_semaphore is None:
                provider_started = time.perf_counter()
                logger.info(
                    "[structured] admitted contract=%s model=%s queue_ms=%.1f",
                    contract_key or response_model.__name__,
                    request.get("model"),
                    max(0.0, (provider_started - started) * 1000.0),
                )
                result = await _invoke()
            else:
                async with stage_semaphore:
                    provider_started = time.perf_counter()
                    logger.info(
                        "[structured] admitted contract=%s model=%s queue_ms=%.1f",
                        contract_key or response_model.__name__,
                        request.get("model"),
                        max(0.0, (provider_started - started) * 1000.0),
                    )
                    result = await _invoke()
        logger.info(
            "[structured] completed contract=%s model=%s queue_ms=%.1f provider_ms=%.1f",
            contract_key or response_model.__name__,
            request.get("model"),
            max(0.0, (provider_started - started) * 1000.0),
            max(0.0, (time.perf_counter() - provider_started) * 1000.0),
        )
        return result

    async def _call_with_gate(*, provider_timeout: float | None = None) -> ModelT:
        attempt = 0
        while True:
            admission_started = time.perf_counter()
            try:
                result = await _call_admitted(provider_timeout=provider_timeout)
                return result
            except Exception as exc:
                elapsed_ms = max(
                    0.0,
                    (time.perf_counter() - admission_started) * 1000.0,
                )
                _set_contract_metadata(exc, contract_metadata)
                if not isinstance(getattr(exc, "structured_request", None), dict):
                    _set_request_shape(exc, request, contract_key=contract_key)
                logger.warning(
                    "[structured] failed contract=%s model=%s elapsed_ms=%.1f error=%s",
                    contract_key or response_model.__name__,
                    request.get("model"),
                    elapsed_ms,
                    type(exc).__name__,
                )
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

    if timeout is None:
        return await _call_with_gate()
    if timeout_includes_queue:
        # Treat timeout as the total admission budget when explicitly
        # requested.  High-fanout stages opt out so queued work does not
        # expire before the provider request starts.
        return await asyncio.wait_for(_call_with_gate(), timeout=float(timeout))
    return await _call_with_gate(provider_timeout=float(timeout))


def run_structured_output_sync(
    response_model: type[ModelT],
    messages: list[dict[str, Any]],
    *,
    timeout: float | None = None,
    **kwargs: Any,
) -> ModelT:
    """Synchronous boundary for document and spatial adapters.

    The bridge still executes the same typed runner, including the shared
    semaphore, bounded retries, and fail-closed handling.  A worker thread is
    used when the caller already owns an event loop, which keeps synchronous
    document/spatial adapters from creating nested loops.
    """

    async def _run(call_timeout: float | None = timeout) -> ModelT:
        return await run_structured_output(
            response_model,
            messages,
            timeout=call_timeout,
            **kwargs,
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_run())

    # A synchronous caller may already own an event loop.  Use a daemon
    # bridge thread in that case; a timed-out provider coroutine must not leave
    # a non-daemon executor worker keeping the process alive.  The inner typed
    # runner receives a slightly shorter deadline so normal cancellation gets
    # a chance to finish before the bridge's outer wait expires.
    outer_timeout = None if timeout is None else max(0.001, float(timeout))
    inner_timeout = (
        None
        if outer_timeout is None
        else max(0.001, outer_timeout * 0.9)
    )
    outcome: Queue[tuple[bool, Any]] = Queue(maxsize=1)

    def _run_in_thread() -> None:
        try:
            outcome.put((True, asyncio.run(_run(inner_timeout))))
        except BaseException as exc:  # propagate the typed runner failure
            outcome.put((False, exc))

    thread = threading.Thread(
        target=_run_in_thread,
        name="structured-output-sync-bridge",
        daemon=True,
    )
    thread.start()
    try:
        succeeded, value = outcome.get(timeout=outer_timeout)
    except Empty as exc:
        raise TimeoutError("structured output sync bridge timed out") from exc
    if succeeded:
        return value
    raise value


__all__ = [
    "run_structured_output",
    "run_structured_output_sync",
    "structured_failure_code",
    "structured_failure_summary",
    "STRUCTURED_FAILURE_CODES",
]
