"""Road execution worker (blueprint M6): explicit-input wrapper."""

from __future__ import annotations

from app.domain.materialization.worker_contract import (
    WorkerInput,
    WorkerResult,
    _state_from_deps,
    adapt_legacy_result,
    gate_explicit_inputs,
)


async def run_worker(task: WorkerInput, *, deps: dict | None = None) -> WorkerResult:
    """Generate the planned road network.

    The legacy node still performs network re-siting via the RoadPlannerPort /
    stage generator over the spatial workspace, so it is invoked only under
    explicit opt-in.
    """
    gate = gate_explicit_inputs(
        task,
        "road",
        "road network re-siting via RoadPlannerPort / stage generator over the "
        "spatial workspace",
        deps=deps,
    )
    if gate is not None:
        return gate
    from app.agent.execute.nodes.road_worker import _road_worker

    return adapt_legacy_result(task, _road_worker(_state_from_deps(deps)))
