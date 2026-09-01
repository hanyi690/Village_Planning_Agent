"""Single application boundary for typed LLM calls.

Domain code owns the meaning of a prompt and its response model.  This module
owns the mechanics that must be identical for every call: input admission,
stage budgets, protocol fallback, provider concurrency, bounded retries and
safe call auditing.  Prompt contents and provider responses are deliberately
not retained by the manager.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import BaseModel

from app.core.llm_config import get_llm_settings


LLMCallType = Literal["semantic", "report", "retrieval", "closed_set"]
AuditSink = Callable[["LLMCallRecord"], Any]


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _safe_scalar(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, str):
            return value[:160]
        return value
    return str(value)[:160]


def _safe_context(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        str(key)[:80]: _safe_scalar(child)
        for key, child in list(value.items())[:32]
    }


def _normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not isinstance(messages, list) or not messages:
        raise TypeError("LLM messages must be a non-empty list")
    normalized: list[dict[str, str]] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise TypeError(f"LLM message {index} must be an object")
        role = str(message.get("role") or "").strip()
        content = message.get("content")
        if role not in {"system", "user", "assistant", "tool"}:
            raise ValueError(f"LLM message {index} has an unsupported role")
        if not isinstance(content, str):
            raise TypeError(f"LLM message {index} content must be text")
        normalized.append({"role": role, "content": content})
    return normalized


def _chat_message_content(message: Any) -> str:
    """Return text used for admission accounting without changing the call."""

    content = message.get("content") if isinstance(message, dict) else getattr(
        message, "content", ""
    )
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(content)


def _normalize_chat_messages(messages: list[Any]) -> list[dict[str, str]]:
    """Normalize LangChain chat messages for budget accounting and auditing."""

    if not isinstance(messages, list) or not messages:
        raise TypeError("LLM chat messages must be a non-empty list")
    normalized: list[dict[str, str]] = []
    for index, message in enumerate(messages):
        if isinstance(message, dict):
            role = str(message.get("role") or "").strip()
        else:
            message_type = str(getattr(message, "type", "")).strip().lower()
            role = {
                "human": "user",
                "ai": "assistant",
                "function": "tool",
            }.get(message_type, message_type)
        if role not in {"system", "user", "assistant", "tool"}:
            raise ValueError(f"LLM chat message {index} has an unsupported role")
        normalized.append({"role": role, "content": _chat_message_content(message)})
    return normalized


def _tool_context_shape(tools: list[Any]) -> list[dict[str, int | str]]:
    """Measure tool definitions without retaining their descriptions or schema."""

    if not isinstance(tools, list) or not tools:
        raise ValueError("tool-calling requires at least one tool")
    shape: list[dict[str, int | str]] = []
    for tool in tools:
        name = str(getattr(tool, "name", tool.__class__.__name__))
        description = str(getattr(tool, "description", "") or "")
        schema = getattr(tool, "args_schema", None)
        if isinstance(schema, type) and hasattr(schema, "model_json_schema"):
            schema = schema.model_json_schema()
        elif schema is None:
            schema = getattr(tool, "args", {}) or {}
        schema_text = json.dumps(schema, ensure_ascii=False, sort_keys=True, default=str)
        shape.append(
            {
                "name": name,
                "name_chars": len(name),
                "description_chars": len(description),
                "schema_chars": len(schema_text),
            }
        )
    return shape


class LLMContextOverflow(ValueError):
    """Raised before transport when the caller assembled an oversized prompt."""

    def __init__(self, *, stage: str, contract_key: str, chars: int, limit: int) -> None:
        self.stage = stage
        self.contract_key = contract_key
        self.input_chars = chars
        self.input_char_limit = limit
        super().__init__(
            f"LLM input context exceeds the {stage} budget "
            f"({chars}>{limit} chars; contract={contract_key})"
        )


@dataclass(frozen=True)
class LLMCallSpec:
    """The complete policy for one provider call.

    A spec is intentionally small.  It describes a call boundary, not a
    second domain payload contract.  ``response_model`` remains the one typed
    output contract and ``messages`` remain the one input projection.
    """

    stage: str
    contract_key: str
    response_model: type[BaseModel]
    call_type: LLMCallType = "semantic"
    model: str | None = None
    timeout_s: float | None = None
    max_tokens: int | None = None
    max_retries: int | None = None
    incomplete_output_max_tokens: int | None = None
    max_concurrent: int | None = None
    semaphore_scope: str | None = None
    transient_retries: int | None = None
    transient_retry_backoff_s: float | None = None
    temperature: float = 0.1
    allow_content_json: bool = False
    input_char_limit: int = 120_000
    timeout_includes_queue: bool = True

    def __post_init__(self) -> None:
        stage = str(self.stage or "").strip().lower()
        if not stage:
            raise ValueError("LLM call stage is required")
        if not str(self.contract_key or "").strip():
            raise ValueError("LLM call contract_key is required")
        if self.call_type not in {"semantic", "report", "retrieval", "closed_set"}:
            raise ValueError(f"unsupported LLM call type: {self.call_type!r}")
        if not isinstance(self.response_model, type) or not issubclass(
            self.response_model, BaseModel
        ):
            raise TypeError("LLM response_model must be a Pydantic model class")
        if self.input_char_limit <= 0:
            raise ValueError("LLM input_char_limit must be positive")
        if self.timeout_s is not None and self.timeout_s <= 0:
            raise ValueError("LLM timeout_s must be positive")
        if self.max_tokens is not None and self.max_tokens <= 0:
            raise ValueError("LLM max_tokens must be positive")


@dataclass(frozen=True)
class LLMCallRecord:
    """Safe audit metadata for one call; no prompt or response text is stored."""

    call_id: str
    stage: str
    contract_key: str
    call_type: str
    input_digest: str
    input_chars: int
    input_message_count: int
    response_model: str
    status: Literal["succeeded", "failed"]
    elapsed_ms: float
    failure_code: str = ""


def _stage_defaults(stage: str, call_type: LLMCallType) -> dict[str, Any]:
    settings = get_llm_settings()
    normalized = str(stage or "").strip().lower()
    if normalized in {"l1", "l2", "l3"}:
        policy = settings.stage_policy(normalized)
        return {
            "timeout_s": policy.timeout_s,
            "max_tokens": policy.report_max_tokens
            if call_type == "report"
            else policy.max_tokens,
            "max_retries": policy.parse_retries,
            "incomplete_output_max_tokens": policy.incomplete_output_max_tokens,
            "max_concurrent": policy.max_concurrent,
            "transient_retries": policy.transient_retries,
            "transient_retry_backoff_s": policy.transient_retry_backoff_s,
            "semaphore_scope": normalized,
        }
    if normalized == "ground":
        return {
            "timeout_s": float(settings.ground_call_timeout_s),
            "max_tokens": int(settings.ground_max_tokens),
            "max_retries": int(settings.ground_parse_retries),
            "incomplete_output_max_tokens": int(settings.incomplete_output_max_tokens),
            "max_concurrent": settings.stage_concurrency("ground"),
            "transient_retries": 0,
            "transient_retry_backoff_s": 0.0,
            "semaphore_scope": "ground",
        }
    if normalized in {
        "cognition",
        "evidence",
        "select",
        "execute",
        "rag",
        "summary",
        "conversation",
    }:
        return {
            "timeout_s": settings.request_timeout_seconds(),
            "max_tokens": 800 if call_type == "report" else 2048,
            "max_retries": 0 if call_type in {"retrieval", "closed_set"} else 1,
            "incomplete_output_max_tokens": max(2048, int(settings.incomplete_output_max_tokens)),
            "max_concurrent": settings.provider_concurrency(),
            "transient_retries": 0,
            "transient_retry_backoff_s": 0.0,
            "semaphore_scope": normalized,
        }
    raise ValueError(f"unknown LLM stage: {stage!r}")


class LLMManager:
    """Execute all application typed calls through one policy boundary."""

    def __init__(self, *, audit_sink: AuditSink | None = None) -> None:
        self._audit_sink = audit_sink
        self._tool_models: dict[tuple[str, float, int, str], Any] = {}

    async def _emit(self, record: LLMCallRecord) -> None:
        if self._audit_sink is None:
            return
        result = self._audit_sink(record)
        if inspect.isawaitable(result):
            await result

    async def run_structured(
        self,
        spec: LLMCallSpec,
        messages: list[dict[str, Any]],
        *,
        context: dict[str, Any] | None = None,
        llm: Any | None = None,
    ) -> BaseModel:
        """Admit, execute and audit one bounded typed call.

        Context overflow is a hard admission failure.  The manager never
        truncates a report, source artifact or reasoning input because doing so
        would silently change the evidence boundary.  Callers must build a
        smaller typed projection and retry with a new digest.
        """

        normalized = _normalize_messages(messages)
        serialized = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        input_chars = sum(len(item["content"]) for item in normalized)
        input_digest = _canonical_digest(normalized)
        if input_chars > spec.input_char_limit:
            overflow = LLMContextOverflow(
                stage=str(spec.stage).strip().upper(),
                contract_key=spec.contract_key,
                chars=input_chars,
                limit=spec.input_char_limit,
            )
            setattr(overflow, "structured_failure_code", "CONTEXT_OVERFLOW")
            await self._emit(
                LLMCallRecord(
                    call_id=f"llm:{input_digest[:16]}",
                    stage=str(spec.stage).strip().upper(),
                    contract_key=spec.contract_key,
                    call_type=spec.call_type,
                    input_digest=input_digest,
                    input_chars=input_chars,
                    input_message_count=len(normalized),
                    response_model=spec.response_model.__name__,
                    status="failed",
                    elapsed_ms=0.0,
                    failure_code="CONTEXT_OVERFLOW",
                )
            )
            raise overflow

        defaults = _stage_defaults(spec.stage, spec.call_type)
        resolved = {
            key: value if value is not None else defaults[key]
            for key, value in (
                ("timeout_s", spec.timeout_s),
                ("max_tokens", spec.max_tokens),
                # The caller/configuration owns schema retry policy.  A zero
                # value is intentional for probes and item-level recovery.
                ("max_retries", spec.max_retries),
                ("incomplete_output_max_tokens", spec.incomplete_output_max_tokens),
                ("max_concurrent", spec.max_concurrent),
                ("transient_retries", spec.transient_retries),
                ("transient_retry_backoff_s", spec.transient_retry_backoff_s),
                ("semaphore_scope", spec.semaphore_scope),
            )
        }
        call_id = f"llm:{input_digest[:16]}"
        started = time.perf_counter()
        try:
            from app.infrastructure.structured_runtime import parser as structured_output

            result = await structured_output.run_structured_output(
                spec.response_model,
                normalized,
                model=spec.model,
                max_retries=int(resolved["max_retries"]),
                timeout=float(resolved["timeout_s"]),
                context={
                    **(_safe_context(context) or {}),
                    "stage": str(spec.stage).strip().upper(),
                    "call_type": spec.call_type,
                    "input_digest": input_digest,
                    "input_chars": input_chars,
                    "serialized_chars": len(serialized),
                },
                llm=llm,
                incomplete_output_max_tokens=int(
                    resolved["incomplete_output_max_tokens"]
                ),
                max_concurrent=int(resolved["max_concurrent"]),
                semaphore_scope=str(resolved["semaphore_scope"]),
                transient_retries=int(resolved["transient_retries"]),
                transient_retry_backoff_s=float(
                    resolved["transient_retry_backoff_s"]
                ),
                contract_key=spec.contract_key,
                timeout_includes_queue=spec.timeout_includes_queue,
                allow_content_json=spec.allow_content_json,
                temperature=float(spec.temperature),
                max_tokens=int(resolved["max_tokens"]),
            )
            if not isinstance(result, spec.response_model):
                result = spec.response_model.model_validate(result)
            from app.infrastructure.structured_runtime.validator import (
                validate_provider_page,
            )

            result = validate_provider_page(spec.contract_key, result)
        except Exception as exc:
            from app.infrastructure.structured_runtime.parser import structured_failure_code

            await self._emit(
                LLMCallRecord(
                    call_id=call_id,
                    stage=str(spec.stage).strip().upper(),
                    contract_key=spec.contract_key,
                    call_type=spec.call_type,
                    input_digest=input_digest,
                    input_chars=input_chars,
                    input_message_count=len(normalized),
                    response_model=spec.response_model.__name__,
                    status="failed",
                    elapsed_ms=(time.perf_counter() - started) * 1000.0,
                    failure_code=structured_failure_code(exc) or type(exc).__name__,
                )
            )
            raise

        await self._emit(
            LLMCallRecord(
                call_id=call_id,
                stage=str(spec.stage).strip().upper(),
                contract_key=spec.contract_key,
                call_type=spec.call_type,
                input_digest=input_digest,
                input_chars=input_chars,
                input_message_count=len(normalized),
                response_model=spec.response_model.__name__,
                status="succeeded",
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
            )
        )
        return result

    async def run_tool_calling(
        self,
        *,
        stage: str,
        contract_key: str,
        messages: list[Any],
        tools: list[Any],
        context: dict[str, Any] | None = None,
        llm: Any | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        timeout_s: float | None = None,
        max_concurrent: int | None = None,
        input_char_limit: int = 120_000,
    ) -> Any:
        """Run the conversation tool router through the same call boundary.

        Tool calling returns the provider's chat message because the workflow
        must preserve native ``tool_calls`` for the tool executor.  The
        manager still owns context admission, model construction, provider
        and stage gates, timeout, and safe audit metadata.  It deliberately
        does not convert a tool-call response into a second output contract.
        """

        normalized = _normalize_chat_messages(messages)
        tool_shape = _tool_context_shape(tools)
        input_chars = sum(len(item["content"]) for item in normalized)
        input_chars += sum(
            int(item["name_chars"])
            + int(item["description_chars"])
            + int(item["schema_chars"])
            for item in tool_shape
        )
        input_digest = _canonical_digest(
            {"messages": normalized, "tools": tool_shape}
        )
        stage_name = str(stage).strip().upper()
        if input_char_limit <= 0:
            raise ValueError("LLM input_char_limit must be positive")
        if input_chars > input_char_limit:
            overflow = LLMContextOverflow(
                stage=stage_name,
                contract_key=contract_key,
                chars=input_chars,
                limit=input_char_limit,
            )
            setattr(overflow, "structured_failure_code", "CONTEXT_OVERFLOW")
            await self._emit(
                LLMCallRecord(
                    call_id=f"llm:{input_digest[:16]}",
                    stage=stage_name,
                    contract_key=contract_key,
                    call_type="semantic",
                    input_digest=input_digest,
                    input_chars=input_chars,
                    input_message_count=len(normalized),
                    response_model="AIMessage",
                    status="failed",
                    elapsed_ms=0.0,
                    failure_code="CONTEXT_OVERFLOW",
                )
            )
            raise overflow

        defaults = _stage_defaults(stage, "semantic")
        resolved_timeout = float(
            timeout_s if timeout_s is not None else defaults["timeout_s"]
        )
        resolved_tokens = int(
            max_tokens if max_tokens is not None else defaults["max_tokens"]
        )
        resolved_concurrency = int(
            max_concurrent
            if max_concurrent is not None
            else defaults["max_concurrent"]
        )
        if resolved_timeout <= 0 or resolved_tokens <= 0:
            raise ValueError("conversation LLM budgets must be positive")

        if llm is None:
            tool_key = (
                str(model or ""),
                float(temperature),
                resolved_tokens,
                _canonical_digest(tool_shape),
            )
            bound_llm = self._tool_models.get(tool_key)
            if bound_llm is None:
                from app.infrastructure.llm.factory import create_llm

                base_llm = create_llm(
                    model=model,
                    temperature=float(temperature),
                    max_tokens=resolved_tokens,
                )
                bound_llm = base_llm.bind_tools(tools)
                self._tool_models[tool_key] = bound_llm
        else:
            bound_llm = llm.bind_tools(tools)

        from app.infrastructure.llm.factory import get_llm_semaphore

        provider_semaphore = await get_llm_semaphore()
        stage_semaphore = await get_llm_semaphore(
            resolved_concurrency,
            scope=str(stage).strip().lower(),
        )
        started = time.perf_counter()
        call_id = f"llm:{input_digest[:16]}"
        try:
            async def _invoke() -> Any:
                return await bound_llm.ainvoke(messages)

            async def _admitted() -> Any:
                async with provider_semaphore:
                    async with stage_semaphore:
                        return await _invoke()

            result = await asyncio.wait_for(_admitted(), timeout=resolved_timeout)
            if result is None:
                raise ValueError("conversation provider returned no message")
        except Exception as exc:
            await self._emit(
                LLMCallRecord(
                    call_id=call_id,
                    stage=stage_name,
                    contract_key=contract_key,
                    call_type="semantic",
                    input_digest=input_digest,
                    input_chars=input_chars,
                    input_message_count=len(normalized),
                    response_model="AIMessage",
                    status="failed",
                    elapsed_ms=(time.perf_counter() - started) * 1000.0,
                    failure_code=type(exc).__name__,
                )
            )
            raise

        await self._emit(
            LLMCallRecord(
                call_id=call_id,
                stage=stage_name,
                contract_key=contract_key,
                call_type="semantic",
                input_digest=input_digest,
                input_chars=input_chars,
                input_message_count=len(normalized),
                response_model="AIMessage",
                status="succeeded",
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
            )
        )
        return result

    def run_structured_sync(
        self,
        spec: LLMCallSpec,
        messages: list[dict[str, Any]],
        *,
        context: dict[str, Any] | None = None,
        llm: Any | None = None,
    ) -> BaseModel:
        """Run the same manager boundary from a synchronous worker thread.

        Synchronous spatial adapters are executed in a short-lived worker and
        therefore do not own the application event loop.  Keeping this bridge
        here prevents them from selecting a second structured-output policy.
        """

        return asyncio.run(
            self.run_structured(
                spec,
                messages,
                context=context,
                llm=llm,
            )
        )


_DEFAULT_MANAGER = LLMManager()


def get_llm_manager() -> LLMManager:
    """Return the process-local manager used by application call sites."""

    return _DEFAULT_MANAGER


__all__ = [
    "LLMCallRecord",
    "LLMCallSpec",
    "LLMContextOverflow",
    "LLMManager",
    "get_llm_manager",
]
