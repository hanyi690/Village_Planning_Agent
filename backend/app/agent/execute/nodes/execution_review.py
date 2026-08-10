"""Execution review node: execution-checks only (no full VALIDATE aggregate)."""

from __future__ import annotations

from typing import Any, Dict, List

from app.agent.execute.execute_state import ExecuteAgentState
from app.agent.execute.nodes.worker_common import _worker_result_get, _worker_type
from app.utils.logger import get_logger

logger = get_logger(__name__)

_TASK_WORKER_TYPE: Dict[str, str] = {
    "layout": "zone",
    "project": "project",
    "facility": "facility",
    "axis": "axis",
    "road": "road",
}


async def _execution_review_node(state: ExecuteAgentState) -> dict:
    """Execution review: execution-checks only (no full VALIDATE aggregate).

    Checks: input completeness / worker-output completeness / change lineage /
    geometry validity / worker conflicts. Produces ``execution_review_report``
    diagnostics and ``validation_result`` for the outer post-L3 VALIDATE stage.
    """
    checks: List[Dict[str, Any]] = []
    violations: List[Dict[str, Any]] = []

    plan_tasks = list(getattr(state.execution_plan, "worker_tasks", None) or [])
    action_only = bool(plan_tasks) and all(
        str(getattr(task, "expected_output_kind", "")) == "action"
        for task in plan_tasks
    )
    input_ok = bool(state.parcel_by_bsm) or action_only
    if not input_ok:
        violations.append({
            "check": "missing_parcel_input",
            "message": "No parcel_by_bsm prepared for spatial execution (landuse input missing).",
        })
    checks.append({"check": "input_completeness", "passed": input_ok})

    routed = set(state.tasks_to_run or [])
    expected_worker_types = {_TASK_WORKER_TYPE.get(task, task) for task in routed}
    worker_types = {_worker_type(result) for result in state.worker_results}
    missing = sorted(expected_worker_types - worker_types)
    workers_ok = not missing
    for worker_type in missing:
        violations.append({
            "check": "missing_worker_output",
            "worker_type": worker_type,
            "message": f"No result produced for routed worker: {worker_type}",
        })
    checks.append({"check": "worker_output_completeness", "passed": workers_ok, "missing": missing})

    lineage_ok = True
    for change in (state.parcel_changeset.changes if state.parcel_changeset is not None else []):
        # Created parcels (e.g. facility buffers) legitimately have no source
        # parcel; lineage is required only for transformations of existing parcels.
        if getattr(change, "action", "") == "create":
            continue
        if not (getattr(change, "derived_from_bsms", None) or []):
            lineage_ok = False
            violations.append({
                "check": "missing_lineage",
                "bsm": getattr(change, "bsm", ""),
                "message": "Change has no derived_from_bsms.",
            })
    checks.append({"check": "change_lineage", "passed": lineage_ok})

    geom_report = state.geometry_materialize_report or {}
    geometry_ok = bool(geom_report.get("geometry_valid", True))
    if not geometry_ok:
        for diag in geom_report.get("diagnostics") or []:
            violations.append({
                "check": diag.get("code", "geometry_invalid"),
                "message": diag.get("message") or f"geometry invalid on {diag.get('bsm')}",
            })
    checks.append({"check": "geometry_validity", "passed": geometry_ok})

    conflicts = list(state.worker_conflict_diagnostics or [])
    conflicts_ok = not conflicts
    for conflict in conflicts:
        violations.append({
            "check": "worker_conflict",
            "message": f"BSM conflict on {conflict.get('bsm')}: {conflict.get('workers')}",
        })
    checks.append({"check": "worker_conflicts", "passed": conflicts_ok, "conflicts": len(conflicts)})

    for issue in state.execution_errors or []:
        violations.append({
            "check": issue.get("code", "execution_error"),
            "message": issue.get("message", "Execution failed"),
        })
    checks.append({"check": "execution_errors", "passed": not state.execution_errors})

    passed = all(check.get("passed", False) for check in checks)
    report = {"passed": passed, "checks": checks, "violations": violations}
    validation_result = {
        "passed": passed,
        "status": "pass" if passed else "fail",
        "violations": violations,
        "reason": "" if passed else "execution_review_failed",
    }
    logger.info(
        "[EXECUTE:review] round %d: %s (%d violations)",
        state.validation_round + 1, "PASS" if passed else "FAIL", len(violations),
    )
    return {
        "execution_review_report": report,
        "validation_result": validation_result,
        "validation_round": state.validation_round + 1,
    }
