"""Axis execution worker (blueprint M6): explicit-input wrapper."""

from __future__ import annotations

from app.domain.materialization.worker_contract import (
    WorkerInput,
    WorkerResult,
    _state_from_deps,
    adapt_legacy_result,
    gate_explicit_inputs,
)


async def run_worker(task: WorkerInput, *, deps: dict | None = None) -> WorkerResult:
    """Build the development-axis layer.

    The legacy node still reads the spatial workspace directly and builds axis
    geometry, so it is invoked only under explicit opt-in.
    """
    gate = gate_explicit_inputs(
        task,
        "axis",
        "direct spatial-workspace (KG) read via canonical_gis_data_from_workspace "
        "+ axis geometry building",
        deps=deps,
    )
    if gate is not None:
        return gate
    from app.agent.execute.nodes.axis_worker import _axis_worker

    return adapt_legacy_result(task, _axis_worker(_state_from_deps(deps)))
