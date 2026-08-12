"""Project execution worker (blueprint M6): explicit-input wrapper."""

from __future__ import annotations

from app.domain.materialization.worker_contract import (
    WorkerInput,
    WorkerResult,
    _state_from_deps,
    adapt_legacy_result,
    gate_explicit_inputs,
)


async def run_worker(task: WorkerInput, *, deps: dict | None = None) -> WorkerResult:
    """Place each L3 project on its SSD-selected parcel.

    The legacy node still performs parcel re-siting (selected-BSM join and
    site-selection fallback), so it is invoked only under explicit opt-in.
    """
    gate = gate_explicit_inputs(
        task,
        "project",
        "parcel re-siting (selected_bsm join / full_ranking fallback)",
        deps=deps,
    )
    if gate is not None:
        return gate
    from app.agent.execute.nodes.project_worker import _project_worker

    return adapt_legacy_result(task, _project_worker(_state_from_deps(deps)))
