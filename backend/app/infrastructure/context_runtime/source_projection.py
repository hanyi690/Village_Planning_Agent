"""Deterministic source projections shared by stage context builders.

The projection selects existing source segments by an explicit stage-owned
section contract.  It never extracts facts, changes source text, or invents a
fallback segment when the contract has no match.  The full source index remains
the parent artifact; this value is only the bounded input view for one call.
"""

from __future__ import annotations

import unicodedata
import re
from collections.abc import Iterable

from app.contracts.l1.l1_contracts import L1SourceIndex


def _token(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = "".join(text.split()).strip("#【】[]()（）:：")
    return re.sub(r"^[一二三四五六七八九十百千万0-9]+[、.．]", "", text)


def project_source_index(
    source_index: L1SourceIndex | None,
    section_hints: Iterable[str] = (),
) -> L1SourceIndex | None:
    """Return only source sections explicitly admitted for the current call.

    Section matching is literal against the source's structural
    ``section_path``.  A missing match is represented as an empty projection,
    which is an auditable evidence gap rather than permission to expose all
    unrelated source material.
    """

    if source_index is None:
        return None
    hints = tuple(dict.fromkeys(_token(value) for value in section_hints if _token(value)))
    if not hints:
        return source_index
    selected = [
        segment
        for segment in source_index.source_segments
        if any(
            hint == _token(section)
            for hint in hints
            for section in (segment.section_path or [])
        )
    ]
    diagnostics = [
        diagnostic
        for diagnostic in source_index.diagnostics
        if not str(diagnostic).startswith("source_projection:")
    ]
    diagnostics.append(
        "source_projection:sections="
        + ",".join(hints)
        + f";segments={len(selected)}"
    )
    if not selected:
        diagnostics.append("source_projection_no_matching_sections")
    return source_index.model_copy(
        update={"source_segments": selected, "diagnostics": diagnostics}
    )


__all__ = ["project_source_index"]
