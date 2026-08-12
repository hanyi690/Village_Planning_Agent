"""Facility execution worker (blueprint M6): explicit-input wrapper."""

from __future__ import annotations

from app.domain.materialization.worker_contract import (
    WorkerInput,
    WorkerResult,
    _state_from_deps,
    adapt_legacy_result,
    gate_explicit_inputs,
)


async def run_worker(task: WorkerInput, *, deps: dict | None = None) -> WorkerResult:
    """Place facility footprints from decision-driven targets.

    The legacy node still performs facility re-siting (anchor lookup and
    footprint placement), so it is invoked only under explicit opt-in.
    """
    gate = gate_explicit_inputs(
        task,
        "facility",
        "facility re-siting (anchor lookup + design_facility_parcel)",
        deps=deps,
    )
    if gate is not None:
        return gate
    from app.agent.execute.nodes.facility_worker import _facility_worker

    return adapt_legacy_result(task, _facility_worker(_state_from_deps(deps)))
