"""Worker contract base types (blueprint M6 boundary).

Each execution worker is an independent ``WorkerInput -> WorkerResult``
function.  Results carry target refs, input refs, change refs, diagnostics
and provenance; workers never re-site, re-classify or fall back silently.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class WorkerInput(Protocol):
    """Typed inputs for a single execution worker."""

    target_ref: str
    task_ref: str
    input_refs: dict[str, str]


@runtime_checkable
class WorkerResult(Protocol):
    """Typed outcome produced by an execution worker."""

    worker: str
    target_ref: str
    status: str
    change_refs: list[str]
    diagnostics: dict[str, object]
    provenance: dict[str, str]


__all__ = ["WorkerInput", "WorkerResult"]
