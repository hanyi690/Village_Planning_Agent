"""Execution result reconciliation entry point."""

from __future__ import annotations

from typing import Any


def execution_result_diagnostics(result: Any) -> list[Any]:
    return list(getattr(result, "diagnostics", []) or [])


__all__ = ["execution_result_diagnostics"]
