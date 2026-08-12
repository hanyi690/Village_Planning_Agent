"""Bounded projections used when a planning stage consumes prior claims."""

from __future__ import annotations

import json
import re
from typing import Any


_REPORT_MARKER = re.compile(r"(?=【[^】]+】分析结果：)")


def compact_claim_context(
    reports: str,
    *,
    max_claims_per_report: int = 20,
    max_chars: int = 24000,
) -> str:
    """Project claim identity/evidence into a bounded synthesis context.

    ``project_bank`` needs cross-dimension coverage, not another copy of all
    report prose.  This projection keeps the causal references and proposed
    output kind while preventing prompt growth from being proportional to the
    full L3 report corpus.
    """

    parts: list[str] = []
    for block in _REPORT_MARKER.split(reports or ""):
        block = block.strip()
        if not block:
            continue
        marker, _, body = block.partition("\n")
        if not body:
            parts.append(block[:800])
            continue
        try:
            payload: Any = json.loads(body.strip())
        except (TypeError, ValueError):
            parts.append(f"{marker}\n{body[:800]}")
            continue
        claims = payload.get("claims") if isinstance(payload, dict) else None
        if not isinstance(claims, list):
            parts.append(f"{marker}\n{body[:800]}")
            continue
        rows = [marker]
        for claim in claims[:max_claims_per_report]:
            if not isinstance(claim, dict):
                continue
            claim_id = str(claim.get("claim_id") or "").strip()
            statement = str(claim.get("statement") or "").strip()
            if not claim_id or not statement:
                continue
            category = str(claim.get("suggested_category") or "action")
            output = str(claim.get("suggested_output_kind") or "action")
            evidence = ",".join(str(item) for item in claim.get("evidence_refs") or [])
            locations = ",".join(str(item) for item in claim.get("location_hints") or [])
            rows.append(
                f"- {claim_id}: {statement[:240]} | category={category}; "
                f"output={output}; locations={locations or 'unresolved'}; "
                f"evidence={evidence or 'none'}"
            )
        parts.append("\n".join(rows))
    result = "\n\n".join(parts)
    return result[:max_chars]


__all__ = ["compact_claim_context"]
