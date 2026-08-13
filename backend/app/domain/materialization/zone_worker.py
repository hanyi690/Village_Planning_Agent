"""Zone execution worker (blueprint M6): explicit-input wrapper."""

from __future__ import annotations

from app.domain.materialization.worker_contract import (
    WorkerInput,
    WorkerResult,
    _state_from_deps,
    adapt_legacy_result,
    blocked_result,
)


async def run_worker(task: WorkerInput, *, deps: dict | None = None) -> WorkerResult:
    """Run assignment-only zone materialization from an explicit artifact."""
    deps = deps or {}
    if not task.task_ref:
        return blocked_result(
            task,
            "zone",
            "zone worker requires a real ExecutionPlan task ref",
        )
    if not task.input_refs.get("global_zone_allocation_ref"):
        return blocked_result(
            task,
            "zone",
            "zone worker requires global_zone_allocation_ref",
            code="worker_needs_explicit_input",
        )
    state = _state_from_deps(deps)
    allocation = deps.get("global_zone_allocation_result")
    if state is None or allocation is None:
        return blocked_result(
            task,
            "zone",
            "global zone allocation artifact or execution state is absent",
            code="worker_needs_explicit_input",
        )
    from app.domain.materialization.nodes.zone_worker import _zone_worker

    return adapt_legacy_result(
        task,
        _zone_worker(state, allocation_result=allocation),
    )
