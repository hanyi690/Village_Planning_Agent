"""Compiler diagnostics - deterministic detection of parse quality issues."""
from __future__ import annotations

import re

from app.contracts.workflow.parse_result_contracts import ParseDiagnostic

_CHAPTER_RE = re.compile(r"^#{1,3}\s+(\S.+)$", re.MULTILINE)


def collect_diagnostics(
    dimension_key: str,
    content: str,
    instruction: str,
) -> list[ParseDiagnostic]:
    """Collect deterministic diagnostics for one dimension compile."""
    diags: list[ParseDiagnostic] = []

    chapters = _CHAPTER_RE.findall(content or "")
    if not chapters:
        diags.append(
            ParseDiagnostic(
                diagnostic_id=f"{dimension_key}-no-chapters",
                severity="warning",
                code="NO_CHAPTERS",
                message="report content has no markdown chapters",
                field_path="content",
            )
        )

    if not instruction:
        diags.append(
            ParseDiagnostic(
                diagnostic_id=f"{dimension_key}-no-instruction",
                severity="info",
                code="NO_INSTRUCTION",
                message="report has no INSTRUCTION segment",
                field_path="instruction",
            )
        )

    return diags


__all__ = ["collect_diagnostics"]
