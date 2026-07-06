"""Unified structured output — Instructor-based LLM extraction with auto-retry.

This module provides a single entry point `structured_parse()` that:
- Uses Instructor + Pydantic schema for format-guaranteed extraction
- Supports metric anchors injection as prompt few-shot
- Provides max_retries=3 auto-retry on schema violations
- Works with both summary generation and GIS intent parsing
"""

import asyncio
import json
import logging
from typing import Any, Dict, Optional, Tuple, Type

from pydantic import BaseModel

from app.utils.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_MAX_RETRIES = 3
_DEFAULT_MAX_TOKENS = 2000
_DEFAULT_TEMPERATURE = 0


async def structured_parse(
    content: str,
    output_schema: Type[BaseModel],
    anchors: Optional[Dict[str, Any]] = None,
    dimension_key: str = "",
    max_retries: int = _DEFAULT_MAX_RETRIES,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    temperature: float = _DEFAULT_TEMPERATURE,
    model_name: Optional[str] = None,
) -> Tuple[BaseModel, Dict[str, Any]]:
    """Unified structured parse entry point.

    Uses Instructor + DashScope for Pydantic schema-enforced extraction.
    On schema violation, Instructor auto-retries up to max_retries times.

    Returns:
        Tuple of (Pydantic instance, trace_info dict).
    """
    from app.core.instructor_client import get_instructor_client

    client = get_instructor_client()
    model = model_name or _get_model_name()

    prompt = _build_prompt(content, anchors, dimension_key, output_schema)

    trace_info: Dict[str, Any] = {
        "llm_model": model,
        "llm_prompt": prompt,
        "llm_retry_count": max_retries,
    }

    try:
        result = await asyncio.to_thread(
            client.chat.completions.create,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            max_retries=max_retries,
            response_model=output_schema,
            messages=[{"role": "user", "content": prompt}],
        )
        trace_info["llm_response"] = result.model_dump_json() if hasattr(result, "model_dump_json") else str(result)
    except Exception as e:
        logger.error("[structured_parse] Instructor failed: %s", e)
        raise

    return result, trace_info


async def structured_parse_with_correction(
    content: str,
    output_schema: Type[BaseModel],
    anchors: Optional[Dict[str, Any]] = None,
    dimension_key: str = "",
    validate_fn: Optional[Any] = None,
    max_retries: int = _DEFAULT_MAX_RETRIES,
) -> Tuple[BaseModel, Dict[str, Any]]:
    """Structured parse with semantic validation + single correction round.

    Returns:
        Tuple of (Pydantic instance, trace_info dict).
    """
    result, trace_info = await structured_parse(
        content, output_schema, anchors, dimension_key, max_retries=max_retries,
    )

    trace_info["semantic_validation_passed"] = True

    if validate_fn is not None:
        validation = validate_fn(result, anchors)
        if not validation.passed:
            trace_info["semantic_validation_passed"] = False
            trace_info["semantic_violations"] = validation.violations
            trace_info["correction_round"] = True

            logger.info(
                "[structured_parse] Semantic validation failed: %s. Correcting.",
                validation.violations,
            )
            correction_prompt = _build_correction_prompt(
                content, anchors, dimension_key, output_schema, result, validation,
            )
            corrected, correction_trace = await structured_parse(
                correction_prompt, output_schema, anchors, dimension_key,
                max_retries=max_retries,
            )
            trace_info["correction_prompt"] = correction_prompt
            trace_info["correction_response"] = correction_trace.get("llm_response", "")
            return corrected, trace_info

    return result, trace_info


def _get_model_name() -> str:
    """Get default model name for Instructor calls."""
    from app.core.instructor_client import get_flash_model
    return get_flash_model()


def _build_prompt(
    content: str,
    anchors: Optional[Dict[str, Any]],
    dimension_key: str,
    output_schema: Type[BaseModel],
) -> str:
    """Build prompt with optional anchor injection."""
    parts = []

    if dimension_key:
        parts.append(f"维度: {dimension_key}")

    if anchors:
        anchor_text = _format_anchors(anchors)
        parts.append(f"已知精确数值（请严格遵循）:\n{anchor_text}")

    parts.append(f"报告内容:\n{content[:3000]}")

    parts.append(f"请输出结构化数据，符合 {output_schema.__name__} schema。")

    return "\n\n".join(parts)


def _build_correction_prompt(
    content: str,
    anchors: Optional[Dict[str, Any]],
    dimension_key: str,
    output_schema: Type[BaseModel],
    previous_result: BaseModel,
    validation: Any,
) -> str:
    """Build correction prompt pointing out specific violations."""
    violations_text = "\n".join(f"- {v}" for v in validation.violations)

    parts = [
        "上次输出的语义校验发现问题，请修正后重新输出：",
        f"\n问题清单:\n{violations_text}",
    ]

    if anchors:
        anchor_text = _format_anchors(anchors)
        parts.append(f"精确数值锚定:\n{anchor_text}")

    parts.append(f"原始报告内容:\n{content[:3000]}")
    parts.append(f"请修正输出，符合 {output_schema.__name__} schema。")

    return "\n\n".join(parts)


def _format_anchors(anchors: Dict[str, Any]) -> str:
    """Format anchors dict into readable prompt text."""
    lines = []
    for key, value in anchors.items():
        if isinstance(value, dict) and "value" in value:
            source = value.get("source", "未知来源")
            lines.append(f"  {key} = {value['value']} (来源: {source})")
        else:
            lines.append(f"  {key} = {value}")
    return "\n".join(lines)
