"""Execution evidence projection helpers."""

from __future__ import annotations

from typing import Any


def execution_evidence_refs(result: Any) -> list[str]:
    return sorted({
        str(ref).strip()
        for ref in list(getattr(result, "evidence_refs", []) or [])
        if str(ref).strip()
    })


__all__ = ["execution_evidence_refs"]
