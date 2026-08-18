"""Canonical execution worker contract (blueprint M6).

Each execution worker is an independent ``WorkerInput -> WorkerResult``
function.  ``run_workers`` fans out independent workers and collects results
into the authoritative ``ExecutionResult`` root artifact (single owner:
``app.contracts.workflow.execution_plan_contracts``).
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from app.contracts.workflow.execution_plan_contracts import (
    ExecutionResult,
    TaskExecutionResult,
)

WorkerStatus = Literal["succeeded", "failed", "unresolved", "blocked", "deferred"]

STATUS_TO_TASK_STATUS: dict[str, str] = {
    "succeeded": "succeeded",
    "failed": "failed",
    "unresolved": "deferred",
    "blocked": "deferred",
    "deferred": "deferred",
}

WORKER_MODULES: dict[str, str] = {
    "site_area": "app.domain.materialization.project_worker",
    "zone": "app.domain.materialization.zone_worker",
    "facility": "app.domain.materialization.facility_worker",
    "road": "app.domain.materialization.road_worker",
    "axis": "app.domain.materialization.axis_worker",
}

REQUIRED_ARTIFACT_REFS: tuple[str, ...] = (
    "parcel_changeset_ref",
    "planned_state_ref",
    "layout_configs_ref",
)

DiagnosticCode = Literal[
    "input_requirements_unmet",
    "worker_needs_explicit_input",
    "delegated_ok",
    "algorithm_unavailable",
    "unknown_worker",
    "worker_raised",
    "unexpected_payload",
]

DIAGNOSTIC_TAXONOMY: dict[str, str] = {
    "input_requirements_unmet": "task spec lacks a required ExecutionPlan task ref or artifact ref; inputs are never fabricated",
    "worker_needs_explicit_input": "legacy node still performs re-siting / reclassification / direct KG query; explicit inputs required before delegation",
    "delegated_ok": "delegated to a clean execution worker and produced typed output",
    "algorithm_unavailable": "the algorithm / port required to execute is unavailable",
    "unknown_worker": "no worker registered for this worker name",
    "worker_raised": "worker raised while executing",
    "unexpected_payload": "worker returned an untyped payload",
}


class WorkerInput(BaseModel):
    """Typed inputs for a single execution worker."""

    worker: str
    target_ref: str
    task_ref: str = ""
    input_refs: dict[str, str] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    scenario_id: str = ""
    candidate_id: str = ""
    relation_ids: list[str] = Field(default_factory=list)
    target_binding: dict[str, Any] = Field(default_factory=dict)


class WorkerResult(BaseModel):
    """Typed outcome produced by an execution worker.

    ``code`` is a stable diagnostic key distinct from ``status`` so
    downstream can branch on the reason (see ``DIAGNOSTIC_TAXONOMY``).
    """

    worker: str
    target_ref: str
    task_ref: str = ""
    status: WorkerStatus = "unresolved"
    code: str = ""
    change_refs: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, str] = Field(default_factory=dict)
    scenario_features: list[dict[str, Any]] = Field(default_factory=list)
    execution_events: list[dict[str, Any]] = Field(default_factory=list)


def blocked_result(
    task: WorkerInput,
    worker: str,
    reason: str,
    *,
    code: str = "input_requirements_unmet",
) -> WorkerResult:
    """Typed blocked outcome when the task cannot be executed as specified."""
    return WorkerResult(
        worker=worker,
        target_ref=task.target_ref,
        task_ref=task.task_ref,
        status="blocked",
        code=code,
        diagnostics={"code": code, "message": reason},
        provenance={
            "blocked": (
                "needs_explicit_input"
                if code == "worker_needs_explicit_input"
                else "missing_dependency"
            )
        },
    )


def _state_from_deps(deps: dict | None) -> Any:
    if not deps:
        return None
    return deps.get("state")


def _legacy_value(item: Any, key: str, default: Any) -> Any:
    if item is None:
        return default
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _as_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return {"message": str(item)}


def gate_explicit_inputs(
    task: WorkerInput,
    worker: str,
    legacy_operations: str,
    *,
    deps: dict | None = None,
) -> WorkerResult | None:
    """Block unless the task ref is real and legacy delegation is explicit.

    Returns ``None`` when delegation may proceed, otherwise a typed blocked
    result.  The legacy nodes still perform re-siting / reclassification /
    direct KG reads, so they are never invoked silently; callers must opt in
    with ``input_refs['legacy_opt_in']='true'`` after migration.
    """
    if not task.task_ref:
        return blocked_result(
            task,
            worker,
            "%s worker requires a real ExecutionPlan task ref (task_ref); "
            "inputs were not fabricated." % worker,
            code="input_requirements_unmet",
        )
    if task.input_refs.get("legacy_opt_in") != "true":
        return blocked_result(
            task,
            worker,
            "legacy %s node still performs %s; explicit inputs required. "
            "Set input_refs['legacy_opt_in']='true' only after the node consumes "
            "ExecutionPlan task inputs." % (worker, legacy_operations),
            code="worker_needs_explicit_input",
        )
    if deps is not None and _state_from_deps(deps) is None:
        return blocked_result(
            task,
            worker,
            "legacy delegation opted in but the execution state is absent; "
            "explicit inputs are incomplete.",
            code="worker_needs_explicit_input",
        )
    return None


def adapt_legacy_result(task: WorkerInput, legacy: Any) -> WorkerResult:
    """Fold a legacy node ``WorkerResult`` into the canonical envelope.

    Only reached through the explicit opt-in delegation path; the worker
    executed cleanly against the legacy body, so the code is ``delegated_ok``.
    """
    worker = str(_legacy_value(legacy, "worker_type", "") or task.worker)
    task_results = list(_legacy_value(legacy, "task_results", None) or [])
    parcel_changes = list(_legacy_value(legacy, "parcel_changes", None) or [])
    layers = list(_legacy_value(legacy, "layers", None) or [])
    unresolved = list(_legacy_value(legacy, "unresolved_items", None) or [])
    action_results = list(_legacy_value(legacy, "action_results", None) or [])
    diagnostics = list(_legacy_value(legacy, "diagnostics", None) or [])
    scenario_features = list(_legacy_value(legacy, "scenario_features", None) or [])
    execution_events = list(_legacy_value(legacy, "execution_events", None) or [])

    statuses = [str(_legacy_value(tr, "status", "")) for tr in task_results]
    if unresolved:
        status: str = "unresolved"
    elif not task_results and not layers and not parcel_changes and not action_results:
        status = "deferred"
    elif "failed" in statuses:
        status = "failed"
    elif "succeeded" in statuses or layers or parcel_changes or action_results:
        status = "succeeded"
    else:
        status = "unresolved"

    change_refs = [
        str(_legacy_value(change, "bsm", ""))
        for change in parcel_changes
        if _legacy_value(change, "bsm", "")
    ]
    change_refs.extend(
        str(layer.get("layerType") or layer.get("layer_type") or "")
        for layer in layers
        if isinstance(layer, dict) and (layer.get("layerType") or layer.get("layer_type"))
    )

    return WorkerResult(
        worker=worker,
        target_ref=task.target_ref,
        task_ref=task.task_ref,
        status=status,
        code="delegated_ok",
        change_refs=[ref for ref in change_refs if ref],
        diagnostics={
            "task_results": len(task_results),
            "layers": len(layers),
            "parcel_changes": len(parcel_changes),
            "action_results": len(action_results),
            "legacy_diagnostics": [_as_dict(item) for item in diagnostics],
            "unresolved_items": [_as_dict(item) for item in unresolved],
        },
        provenance={"source": "app.domain.materialization.nodes", "ref_kind": "bsm_and_layer_type"},
        scenario_features=[
            item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
            for item in scenario_features
        ],
        execution_events=execution_events,
    )


def to_task_result(result: WorkerResult) -> TaskExecutionResult:
    """Map one canonical WorkerResult into plan-level task evidence."""
    return TaskExecutionResult(
        task_id=result.task_ref,
        target_id=result.target_ref,
        status=STATUS_TO_TASK_STATUS[result.status],
        output_artifacts=list(result.change_refs) if result.status == "succeeded" else [],
        errors=[] if result.status != "failed" else [result.code or "worker_failed"],
        diagnostics=[dict(result.diagnostics)] if result.diagnostics else [],
        scenario_id=str(result.diagnostics.get("scenario_id", "") or "") if isinstance(result.diagnostics, dict) else "",
        feature_ids=[
            str(item.get("feature_id", ""))
            for item in result.scenario_features
            if isinstance(item, dict) and str(item.get("feature_id", ""))
        ],
        execution_trace_refs=[
            str(item.get("trace_ref", ""))
            for item in result.execution_events
            if isinstance(item, dict) and str(item.get("trace_ref", ""))
        ],
    )


async def _unknown_worker(task: WorkerInput) -> WorkerResult:
    return blocked_result(
        task, task.worker, "unknown worker name", code="unknown_worker"
    )


async def _invoke(runner: Callable[..., Any], task: WorkerInput, deps: dict) -> WorkerResult:
    return await runner(task, deps=deps)


def _load_runner(worker: str) -> Callable[..., Any] | None:
    import importlib

    module_name = WORKER_MODULES.get(worker)
    if module_name is None:
        return None
    module = importlib.import_module(module_name)
    return module.run_worker


def _require_refs(deps: dict[str, Any]) -> None:
    missing = [name for name in REQUIRED_ARTIFACT_REFS if not deps.get(name)]
    if missing:
        raise ValueError(
            "ExecutionResult requires parent artifact refs %s; run_workers does "
            "not fabricate ExecutionResult / ParcelChangeSet / PlannedState refs "
            "(missing: %s)" % (", ".join(REQUIRED_ARTIFACT_REFS), ", ".join(missing))
        )


async def run_workers(
    inputs: list[WorkerInput], deps: dict | None = None
) -> ExecutionResult:
    """Fan out independent workers and collect results into an ExecutionResult.

    The root requires the child artifact refs (parcel_changeset / planned_state
    / layout_configs) to be supplied via ``deps``; they are the workflow's
    existing artifact identities and are never fabricated here.  Missing parent
    refs raise rather than silently producing an empty result.
    """
    deps = deps or {}
    _require_refs(deps)
    results: list[WorkerResult] = []
    from app.domain.materialization.task_scheduler import schedule_tasks

    schedule = schedule_tasks(inputs)
    by_id = {task.task_ref: task for task in inputs if task.task_ref}
    if schedule.fail_closed:
        for task in inputs:
            results.append(blocked_result(
                task,
                task.worker,
                "ExecutionDAG rejected: "
                + "; ".join(
                    str(item.get("code", "invalid_graph"))
                    for item in schedule.diagnostics
                ),
                code="input_requirements_unmet",
            ))
    else:
        sequence = 0
        for batch in schedule.batches:
            pending: list[Any] = []
            batch_tasks = [by_id[task_id] for task_id in batch.task_ids if task_id in by_id]
            for task in batch_tasks:
                runner = _load_runner(task.worker)
                if runner is None:
                    pending.append(_unknown_worker(task))
                else:
                    pending.append(_invoke(runner, task, deps))
            outcomes = await asyncio.gather(*pending, return_exceptions=True)
            for task, outcome in zip(batch_tasks, outcomes):
                sequence += 1
                if isinstance(outcome, BaseException):
                    result = blocked_result(
                        task,
                        task.worker,
                        "worker raised: %s" % outcome,
                        code="worker_raised",
                    )
                elif isinstance(outcome, WorkerResult):
                    result = outcome
                else:
                    result = blocked_result(
                        task,
                        task.worker,
                        "worker returned unexpected payload",
                        code="unexpected_payload",
                    )
                result.execution_events.extend([
                    {"task_id": task.task_ref, "event": "start", "sequence": sequence},
                    {"task_id": task.task_ref, "event": "complete", "sequence": sequence},
                ])
                results.append(result)
        for task in inputs:
            if task.task_ref in schedule.deferred_task_ids:
                results.append(blocked_result(
                    task,
                    task.worker,
                    "task or dependency is durably deferred",
                    code="input_requirements_unmet",
                ))

    trace_refs = [
        f"trace:{event['task_id']}:{event['event']}"
        for result in results
        for event in result.execution_events
        if event.get("task_id") and event.get("event")
    ]

    return ExecutionResult(
        execution_plan_ref=deps.get("execution_plan_ref"),
        parcel_changeset_ref=deps["parcel_changeset_ref"],
        planned_state_ref=deps["planned_state_ref"],
        deferral_ledger_ref=deps.get("deferral_ledger_ref"),
        layout_configs_ref=deps["layout_configs_ref"],
        task_results=[to_task_result(result) for result in results],
        execution_trace_refs=trace_refs,
        diagnostics=[
            {
                "worker": result.worker,
                "target_ref": result.target_ref,
                "status": result.status,
                "code": result.code or "delegated_ok",
                "change_count": len(result.change_refs),
            }
            for result in results
        ],
    )
