"""Deterministic structured summary generation for dimension reports.

Rule-based (no LLM): builds a dimension-typed summary carrying word count,
key points (populated upstream by the analysis pipeline), a truncated text
preview and a metrics dict. Lives under ``app.modules.parsing`` so
``ReportStore`` can import it through the corrected ``app.modules.parsing``
path.
"""

from __future__ import annotations


async def generate_structured_summary(
    dimension_key: str,
    layer: int,
    content: str,
) -> str:
    """Return a JSON-string summary for a dimension report.

    Uses the dimension's Pydantic schema (``get_dimension_schema``) so the
    summary carries the correct typed fields; semantic values default to
    empty here and are filled by the analysis pipeline upstream.
    """
    from .schemas import get_dimension_schema

    schema_cls = get_dimension_schema(dimension_key)
    summary = schema_cls(
        dimension_key=dimension_key,
        layer=layer,
        word_count=len(content),
        key_points=[],
        text_summary=content[:200],
        metrics={},
    )
    return summary.model_dump_json(ensure_ascii=False)


__all__ = ["generate_structured_summary"]
