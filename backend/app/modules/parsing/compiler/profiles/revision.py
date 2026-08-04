"""REVISION compilation profile.

Wave F Task 1 lands only the stub: the full REVISION profile implementation
arrives in Wave F Task 5. The stub keeps the function signature fixed so the
top-level agent/parse stage can wire against it without surprises.
"""
from __future__ import annotations

from typing import Any


def compile_revision(
    *,
    revision_request: Any,
    base_result: Any,
    dimension_key: str,
    content: str,
    instruction: str,
    summary: str = "",
    report_id: str = "",
    run_id: str = "",
) -> None:
    raise NotImplementedError("REVISION profile implementation lands in Wave F Task 5.")


__all__ = ["compile_revision"]
