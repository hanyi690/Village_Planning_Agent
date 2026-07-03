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
from typing import Any, Dict, Optional, Type

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
) -> BaseModel:
    """Unified structured parse entry point.

    Uses Instructor + DashScope for Pydantic schema-enforced extraction.
    On schema violation, Instructor auto-retries up to max_retries times.

    Args:
        content: Input text to parse.
        output_schema: Pydantic BaseModel class defining the output structure.
        anchors: Optional metric anchors to inject into prompt as few-shot.
        dimension_key: Optional dimension identifier (for summary generation).
        max_retries: Auto-retry count on schema violation (default 3).
        max_tokens: Max output tokens (default 2000).
        temperature: Generation temperature (default 0).
        model_name: Override model name (default: uses FLASH_MODEL_NAME).

    Returns:
        Pydantic instance of output_schema.

    Raises:
        Exception: If Instructor fails after max_retries.
    """
    from app.core.instructor_client import get_instructor_client

    client = get_instructor_client()
    model = model_name or _get_model_name()

    prompt = _build_prompt(content, anchors, dimension_key, output_schema)

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
    except Exception as e:
        logger.error("[structured_parse] Instructor failed: %s", e)
        raise

    return result


async def structured_parse_with_correction(
    content: str,
    output_schema: Type[BaseModel],
    anchors: Optional[Dict[str, Any]] = None,
    dimension_key: str = "",
    validate_fn: Optional[Any] = None,
    max_retries: int = _DEFAULT_MAX_RETRIES,
) -> BaseModel:
    """Structured parse with semantic validation + single correction round.

    1. Instructor parse (max_retries=3 handles format issues)
    2. Semantic validation (area_ratio sum, anchor cross-check, required zones)
    3. If validation fails: single correction round

    Args:
        content: Input text.
        output_schema: Pydantic output schema.
        anchors: Metric anchors for few-shot injection.
        dimension_key: Dimension identifier.
        validate_fn: Callable(result, anchors) -> ValidationResult.
        max_retries: Instructor retry count.

    Returns:
        Pydantic instance, possibly corrected.
    """
    result = await structured_parse(
        content, output_schema, anchors, dimension_key, max_retries=max_retries,
    )

    if validate_fn is not None:
        validation = validate_fn(result, anchors)
        if not validation.passed:
            logger.info(
                "[structured_parse] Semantic validation failed: %s. Correcting.",
                validation.violations,
            )
            correction_prompt = _build_correction_prompt(
                content, anchors, dimension_key, output_schema, result, validation,
            )
            result = await structured_parse(
                correction_prompt, output_schema, anchors, dimension_key,
                max_retries=max_retries,
            )

    return result


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
