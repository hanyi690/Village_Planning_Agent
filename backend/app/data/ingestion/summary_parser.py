"""Parse dimension report summaries back into plain dicts.

``DimensionReport.summary`` is stored as JSON text (see summary_generator).
This module reverses that for the report store's layer-summary read API and any
consumer that needs the structured form (UI preview rendering).
"""

from __future__ import annotations

import json
from typing import Any, Dict


def parse_summary(
    summary: str,
    dimension_key: str = "",
    layer: int = 1,
) -> Dict[str, Any]:
    """Parse a summary string into a dict.

    Returns the parsed JSON object when the summary is a JSON document;
    otherwise a ``{"summary": ...}`` fallback for plain-text summaries.
    Always tags the result with ``dimension_key`` / ``layer`` for downstream
    consumers (e.g. ``schema_cls.model_validate(raw)`` in the analysis node).
    """
    if not summary:
        return {}
    if summary.strip().startswith("{"):
        try:
            parsed = json.loads(summary)
        except (json.JSONDecodeError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            parsed.setdefault("dimension_key", dimension_key)
            parsed.setdefault("layer", layer)
            return parsed
    return {
        "dimension_key": dimension_key,
        "layer": layer,
        "summary": summary,
    }


__all__ = ["parse_summary"]
