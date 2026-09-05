"""Bounded repeated structured calls without domain-specific adjudication."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.infrastructure.structured_runtime.contracts import (
    StructuredConsensusResult,
    StructuredPassResult,
)


def _provider_name() -> str:
    try:
        from app.core.llm_config import get_llm_settings

        return str(get_llm_settings().provider or "")
    except Exception:
        return ""


def _failure_metadata(exc: BaseException) -> dict[str, Any]:
    from app.infrastructure.structured_runtime.parser import (
        structured_failure_code,
        structured_failure_kind,
        structured_failure_observation,
    )

    observation = structured_failure_observation(exc)
    response_shape = getattr(exc, "structured_response_shape", {})
    if not isinstance(response_shape, dict):
        response_shape = {}
    return {
        "failure_code": structured_failure_code(exc) or "STRUCTURED_OUTPUT_ERROR",
        "failure_kind": structured_failure_kind(exc),
        "response_shape": dict(response_shape),
    }


async def run_structured_consensus(
    spec: Any,
    messages: list[dict[str, Any]],
    *,
    passes: int = 2,
    validator: Callable[[Any], bool] | None = None,
    context: dict[str, Any] | None = None,
    llm: Any | None = None,
) -> StructuredConsensusResult:
    """Run a bounded typed call repeatedly and return safe pass diagnostics.

    The shared runtime owns repetition, provider failure classification and
    reasoning metadata.  ``validator`` is deliberately a narrow callback:
    callers may validate their domain payload, but the runtime never decides
    what a payload means.
    """

    pass_count = int(passes)
    if not 1 <= pass_count <= 8:
        raise ValueError("structured consensus passes must be between 1 and 8")

    from app.infrastructure.structured_runtime.facade import run_structured

    provider = _provider_name()
    results: list[StructuredPassResult] = []
    for pass_number in range(1, pass_count + 1):
        pass_context = dict(context or {})
        pass_context["pass_number"] = pass_number
        try:
            typed_output = await run_structured(
                spec,
                messages,
                context=pass_context,
                llm=llm,
            )
        except Exception as exc:
            failure = _failure_metadata(exc)
            shape = failure["response_shape"]
            reasoning_length = int(shape.get("reasoning_content_length") or 0)
            failure_status = (
                "provider_failed"
                if failure["failure_kind"] == "provider_infrastructure"
                else "protocol_failed"
            )
            results.append(StructuredPassResult(
                pass_number=pass_number,
                status=failure_status,
                provider_name=provider,
                model_id=str(getattr(spec, "model", "") or ""),
                contract_key=str(getattr(spec, "contract_key", "") or ""),
                finish_reason=str(shape.get("finish_reason") or ""),
                failure_code=str(failure["failure_code"]),
                failure_kind=str(failure["failure_kind"]),
                response_shape=shape,
                reasoning_present=reasoning_length > 0,
                reasoning_channel=("provider_split" if reasoning_length else ""),
                reasoning_length=reasoning_length,
            ))
            continue

        valid = True
        if validator is not None:
            try:
                valid = bool(validator(typed_output))
            except Exception:
                valid = False
        if not valid:
            results.append(StructuredPassResult(
                pass_number=pass_number,
                status="semantic_failed",
                typed_output=typed_output,
                provider_name=provider,
                model_id=str(getattr(spec, "model", "") or ""),
                contract_key=str(getattr(spec, "contract_key", "") or ""),
                failure_code="SEMANTIC_VALIDATION_ERROR",
                failure_kind="semantic",
            ))
            continue
        results.append(StructuredPassResult(
            pass_number=pass_number,
            status="completed",
            typed_output=typed_output,
            provider_name=provider,
            model_id=str(getattr(spec, "model", "") or ""),
            contract_key=str(getattr(spec, "contract_key", "") or ""),
            reasoning_channel=("provider_split" if provider.casefold() == "minimax" else ""),
        ))

    provider_failure_count = sum(item.status == "provider_failed" for item in results)
    protocol_failure_count = sum(item.status == "protocol_failed" for item in results)
    semantic_failure_count = sum(item.status == "semantic_failed" for item in results)
    completed_pass_count = sum(item.status == "completed" for item in results)
    if provider_failure_count:
        status = "provider_failed"
    elif protocol_failure_count:
        status = "protocol_failed"
    elif semantic_failure_count:
        status = "semantic_failed"
    else:
        status = "completed"
    return StructuredConsensusResult(
        status=status,
        passes=tuple(results),
        completed_pass_count=completed_pass_count,
        provider_failure_count=provider_failure_count,
        protocol_failure_count=protocol_failure_count,
        semantic_failure_count=semantic_failure_count,
        contract_key=str(getattr(spec, "contract_key", "") or ""),
    )


__all__ = ["run_structured_consensus"]
