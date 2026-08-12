"""Zone execution worker (blueprint M6): explicit-input wrapper."""

from __future__ import annotations

from app.domain.materialization.worker_contract import (
    WorkerInput,
    WorkerResult,
    _state_from_deps,
    adapt_legacy_result,
    gate_explicit_inputs,
)


async def run_worker(task: WorkerInput, *, deps: dict | None = None) -> WorkerResult:
    """Run deterministic zone reclassification and allocation.

    The legacy node still performs parcel reclassification, MIP re-allocation
    and a direct KG read of the three protection lines, so it is invoked only
    under explicit opt-in.
    """
    gate = gate_explicit_inputs(
        task,
        "zone",
        "parcel reclassification (design_zone_parcel), MIP re-allocation, direct "
        "KG three-lines read (state.kg_three_lines)",
        deps=deps,
    )
    if gate is not None:
        return gate
    from app.domain.materialization.nodes.zone_worker import _zone_worker

    return adapt_legacy_result(task, _zone_worker(_state_from_deps(deps)))
