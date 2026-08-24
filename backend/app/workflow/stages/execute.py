"""EXECUTE stage service and its worker-result reconciliation adapter."""

from __future__ import annotations

from typing import Any, Dict

from app.infrastructure.logging import get_logger
from app.workflow.stage_adapter import persist_stage_artifact
from app.workflow.stages.support import (
    _adopt_context,
    _context_version,
    _jsonable,
    _load_ref_artifact,
    _require_context,
    _run_id,
)

logger = get_logger(__name__)

_execute_subgraph = None


def _ref_digest(ref: Any) -> str:
    if isinstance(ref, dict):
        return str(ref.get("descriptor_digest") or ref.get("digest") or "")
    return str(
        getattr(ref, "descriptor_digest", "")
        or getattr(ref, "digest", "")
        or ""
    )


def _get_execute_subgraph():
    global _execute_subgraph
    if _execute_subgraph is None:
        from app.domain.materialization.execute_agent import build_execute_agent_graph

        _execute_subgraph = build_execute_agent_graph(checkpointer=None)
    return _execute_subgraph


def _to_typed(data: Any, cls: type) -> Any:
    if data is None or isinstance(data, cls):
        return data
    if isinstance(data, dict):
        try:
            return cls(**data)
        except Exception:
            return data
    return data


def _build_exec_repair_payload(
    compilation: Any,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Serialize VALIDATE repair directives for EXECUTE worker consumption.

    Returns ``(payload, require_source_evidence_target_ids)``.  The payload maps
    target_id -> closed directive fields so workers can honor
    ``rebuild_strategy`` / ``affected_bsms`` instead of silently re-running.
    Targets under ``REQUIRE_SOURCE_EVIDENCE`` are not re-dispatched (a worker
    rerun cannot invent missing upstream evidence) and are returned separately
    so EXECUTE records an explicit unresolved instead of a pointless rerun.
    """
    payload: dict[str, dict[str, Any]] = {}
    require_evidence: list[str] = []
    for directive in list(getattr(compilation, "directives", None) or []):
        target_id = str(getattr(directive, "target_id", "") or "")
        if not target_id:
            continue
        directive_type = getattr(directive, "directive_type", None)
        type_value = (
            directive_type.value
            if hasattr(directive_type, "value")
            else str(directive_type or "")
        )
        entry = {
            "directive_id": str(getattr(directive, "directive_id", "") or ""),
            "directive_type": type_value,
            "affected_bsms": sorted(
                {
                    str(item)
                    for item in (getattr(directive, "affected_bsms", None) or [])
                    if str(item)
                }
            ),
            "exclude_bsms": sorted(
                {
                    str(item)
                    for item in (getattr(directive, "exclude_bsms", None) or [])
                    if str(item)
                }
            ),
            "rebuild_strategy": getattr(directive, "rebuild_strategy", None),
            "evidence_scope": getattr(directive, "evidence_scope", None),
            "required_evidence": sorted(
                {
                    str(item)
                    for item in (getattr(directive, "required_evidence", None) or [])
                    if str(item)
                }
            ),
            "reason_code": str(getattr(directive, "reason_code", "") or ""),
        }
        if type_value == "require_source_evidence":
            require_evidence.append(target_id)
        payload[target_id] = entry
    return payload, sorted(set(require_evidence))


def _mark_require_evidence_unresolved(
    outcome: Dict[str, Any],
    execution_plan: Any,
    require_evidence_target_ids: list[str],
) -> Dict[str, Any]:
    """Record targets blocked on missing upstream evidence as explicit unresolved.

    These targets are not re-dispatched: a worker rerun cannot invent the
    evidence the directive requires.  Every affected planned task receives a
    stable ``require_source_evidence`` diagnostic so VALIDATE attributes the
    finding to the responsible upstream stage instead of an EXECUTE rerun.
    """
    from app.contracts.workflow.execution_plan_contracts import TaskExecutionResult

    target_ids = set(require_evidence_target_ids)
    if not target_ids:
        return outcome
    existing = {
        str(getattr(item, "target_id", "") if not isinstance(item, dict) else item.get("target_id", ""))
        for item in list(outcome.get("task_results", []) or [])
    }
    task_by_target: Dict[str, Any] = {}
    for task in list(getattr(execution_plan, "worker_tasks", None) or []) + list(
        getattr(execution_plan, "deferred_tasks", None) or []
    ):
        target_id = str(getattr(task, "target_id", "") or "")
        if target_id:
            task_by_target.setdefault(target_id, task)
    marked = 0
    task_results = list(outcome.get("task_results", []) or [])
    for target_id in sorted(target_ids - existing):
        task = task_by_target.get(target_id)
        task_results.append(
            TaskExecutionResult(
                task_id=str(getattr(task, "task_id", "") or "") or f"repair:{target_id}",
                target_id=target_id,
                status="failed",
                expected_output_kind=str(
                    getattr(task, "expected_output_kind", "line")
                )
                if task is not None
                else "line",
                output_artifacts=[],
                errors=["require_source_evidence"],
                diagnostics=[
                    {
                        "code": "require_source_evidence",
                        "target_id": target_id,
                        "message": (
                            "EXECUTE did not dispatch this target: the typed repair "
                            "directive requires upstream source evidence that is absent."
                        ),
                    }
                ],
                feature_bsms=list(getattr(task, "feature_bsms", None) or []) if task is not None else [],
                evidence_refs=list(getattr(task, "evidence_refs", None) or []) if task is not None else [],
                l1_snapshot_ref=str(getattr(task, "l1_snapshot_ref", "") or "") if task is not None else "",
                bundle_snapshot_digest=str(getattr(task, "bundle_snapshot_digest", "") or "") if task is not None else "",
            )
        )
        marked += 1
    if marked:
        outcome = dict(outcome)
        outcome["task_results"] = task_results
        outcome["diagnostics"] = list(outcome.get("diagnostics", []) or []) + [
            {"code": "require_source_evidence", "target_ids": sorted(target_ids)}
        ]
    return outcome


def _apply_execute_repair_to_intent(
    plan_intent: Any,
    exec_repair_payload: dict[str, dict[str, Any]],
) -> tuple[Any, bool]:
    """Fold EXECUTE-bound repair directives into the dispatch intent.

    ``reroute_avoiding_bsms`` strips the offending parcels from a road target's
    candidate/path set so the route generator re-plans around them.  Targets
    under ``require_source_evidence`` are removed from the road dispatch set:
    the generator must not re-run a corridor whose upstream evidence is absent.
    Returns ``(revised_intent, changed)`` without mutating the caller object.
    """
    if not exec_repair_payload or plan_intent is None:
        return plan_intent, False
    if not hasattr(plan_intent, "model_copy"):
        return plan_intent, False
    revised = plan_intent.model_copy(deep=True)
    changed = False

    for road in list(getattr(revised, "road_targets", None) or []):
        target_id = str(getattr(road, "target_id", "") or "")
        entry = exec_repair_payload.get(target_id)
        if entry is None:
            continue
        if entry.get("directive_type") == "require_source_evidence":
            revised.road_targets.remove(road)
            changed = True
            continue
        if entry.get("rebuild_strategy") != "reroute_avoiding_bsms":
            continue
        avoid = {str(item) for item in (entry.get("affected_bsms") or [])}
        if not avoid:
            continue
        for field_name in ("path_bsms", "candidate_bsms"):
            current = list(getattr(road, field_name, None) or [])
            filtered = [item for item in current if str(item) not in avoid]
            if filtered != current:
                setattr(road, field_name, filtered)
                changed = True
    return revised, changed


def _classification_diagnostic_result(
    state: Dict[str, Any], diagnostics: list[dict[str, Any]]
) -> Dict[str, Any]:
    """Stop EXECUTE before any worker/LLM call when the class boundary fails."""
    target_ids = sorted({str(item.get("target_id", "")) for item in diagnostics if item.get("target_id")})
    payload = {
        "code": "classification_decision_required",
        "errors": diagnostics,
        "target_ids": target_ids,
        "message": (
            "EXECUTE stopped: every parcel/polygon target needs an explicit resolved "
            "ClassificationDecision or a valid DeferralLedger entry."
        ),
    }
    diagnostic_ref = None
    try:
        working_state = {**state, "artifact_refs": dict(state.get("artifact_refs") or {})}
        diagnostic_ref = persist_stage_artifact(
            working_state,
            "execute",
            "ExecutionDiagnostics",
            payload,
        )
    except Exception as exc:
        logger.error("[workflow:execute] failed to persist classification diagnostic: %s", type(exc).__name__)
        payload["persistence_error"] = type(exc).__name__
    fatal_error = {
        "stage": "EXECUTE",
        "code": payload["code"],
        "message": payload["message"],
        "target_ids": target_ids,
        "diagnostics": diagnostics,
    }
    return {
        "fatal_error": fatal_error,
        "delivery_status": "diagnostic_only",
        "diagnostic_terminal": {
            "stage": "execute",
            "reason": payload["code"],
            "target_ids": target_ids,
            "diagnostics": diagnostics,
        },
        "artifact_refs": {"execution_diagnostics": diagnostic_ref} if diagnostic_ref else {},
    }


def _approval_boundary_diagnostic(
    state: Dict[str, Any],
    *,
    code: str,
    message: str,
    diagnostics: list[dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Stop formal EXECUTE before workers when its immutable input is absent.

    A run that reached ScenarioSet is already on the formal planning path. It
    must not fall back to an unbound/free-state execution route.  The
    diagnostic-only return deliberately leaves the
    current baseline available to DELIVER while making the missing approval
    explicit for HITL or SELECT resume.
    """
    payload = {
        "code": code,
        "message": message,
        "target_ids": [],
        "diagnostics": list(diagnostics or []),
    }
    diagnostic_ref = None
    try:
        working_state = {**state, "artifact_refs": dict(state.get("artifact_refs") or {})}
        diagnostic_ref = persist_stage_artifact(
            working_state,
            "execute",
            "ExecutionDiagnostics",
            payload,
        )
    except Exception as exc:  # noqa: BLE001 - preserve the typed boundary
        logger.error("[workflow:execute] failed to persist approval diagnostic: %s", type(exc).__name__)
        payload["persistence_error"] = type(exc).__name__
    return {
        "fatal_error": {
            "stage": "EXECUTE",
            "code": code,
            "message": message,
            "target_ids": [],
            "diagnostics": [payload],
        },
        "delivery_status": "diagnostic_only",
        "diagnostic_terminal": {
            "stage": "execute",
            "reason": code,
            "target_ids": [],
            "diagnostics": [payload],
        },
        "artifact_refs": {
            **dict(state.get("artifact_refs") or {}),
            **({"execution_diagnostics": diagnostic_ref} if diagnostic_ref else {}),
        },
    }


def _execute_approval_error(
    state: Dict[str, Any],
    *,
    scenario_set: Any,
    approved_input: Any,
    approved_scenario: Any,
    context: Any,
) -> Dict[str, Any] | None:
    """Return a typed error before EXECUTE derives or mutates a worker plan."""
    if approved_input is None:
        return _approval_boundary_diagnostic(
            state,
            code="EXECUTE_APPROVED_INPUT_REQUIRED",
            message=(
                "EXECUTE received a formal ScenarioSet without an "
                "ApprovedExecutionInput; approval or an explicit SELECT/HITL "
                "revision is required before materialization."
            ),
        )
    if scenario_set is None or approved_scenario is None:
        return _approval_boundary_diagnostic(
            state,
            code="EXECUTE_APPROVED_INPUT_MISMATCH",
            message=(
                "ApprovedExecutionInput cannot be checked because its "
                "ScenarioSet or PlanningScenario artifact is missing."
            ),
        )
    if not approved_input.can_execute:
        return _approval_boundary_diagnostic(
            state,
            code="EXECUTE_APPROVAL_NOT_EXECUTABLE",
            message=(
                "ApprovedExecutionInput is provisional or revoked and "
                "cannot be handed to EXECUTE."
            ),
        )
    context_ref = dict(state.get("context_ref") or {})
    bundle_snapshot_digest = str(
        context_ref.get("snapshot_digest")
        or context_ref.get("bundle_snapshot_digest")
        or ""
    )
    bundle = getattr(getattr(context, "workspace", None), "_bundle", None)
    if not bundle_snapshot_digest and bundle is not None and hasattr(bundle, "spatial_snapshot_digest"):
        try:
            bundle_snapshot_digest = str(bundle.spatial_snapshot_digest() or "")
        except Exception:
            bundle_snapshot_digest = ""
    scenario_ref = (state.get("artifact_refs") or {}).get("scenario_set")
    if isinstance(scenario_ref, dict):
        scenario_set_ref = str(scenario_ref.get("descriptor_digest") or "")
    else:
        scenario_set_ref = str(getattr(scenario_ref, "descriptor_digest", "") or "")
    try:
        approved_input.assert_matches(
            scenario_set,
            approved_scenario,
            scenario_set_ref=scenario_set_ref,
            context_version=str(getattr(context, "version", "") or _context_version(state)),
            bundle_snapshot_digest=bundle_snapshot_digest,
        )
    except (TypeError, ValueError) as exc:
        return _approval_boundary_diagnostic(
            state,
            code="EXECUTE_APPROVED_INPUT_MISMATCH",
            message="ApprovedExecutionInput is stale or substituted.",
            diagnostics=[{"code": "EXECUTE_APPROVED_INPUT_MISMATCH", "exception_type": type(exc).__name__}],
        )
    return None


def _defer_unclassified_targets(
    state: Dict[str, Any],
    execution_plan: Any,
    deferral_ledger: Any,
    classification_diagnostics: list[dict[str, Any]],
) -> tuple[Any, Any] | None:
    """Retired compatibility hook; unresolved classification fails closed."""
    return None


def _task_results_from_execution(execution_plan: Any, result: Dict[str, Any]) -> Any:
    """Classify every planned task from actual worker dispatch and output."""
    from app.contracts.workflow.execution_plan_contracts import ExecutionResult, TaskExecutionResult
    from app.domain.materialization.nodes.worker_common import worker_result_key, worker_route_key

    action_results = list(result.get("action_results", []) or [])
    action_target_ids = {
        str(getattr(item, "target_id", "") or (item.get("target_id") if isinstance(item, dict) else ""))
        for item in action_results
    }
    errors = list(result.get("execution_errors", []) or [])
    worker_results = list(result.get("worker_results", []) or [])
    routed_tasks = result.get("tasks_to_run")
    task_results = []
    for task in list(getattr(execution_plan, "worker_tasks", None) or []):
        task_id = str(getattr(task, "task_id", ""))
        target_id = str(getattr(task, "target_id", ""))
        output_kind = getattr(task, "expected_output_kind", "parcel")
        worker_type = str(getattr(getattr(task, "worker_type", ""), "value", getattr(task, "worker_type", "")))
        stage = worker_route_key(worker_type)
        result_key = worker_result_key(worker_type)
        matching_results = [
            worker for worker in worker_results
            if str(getattr(worker, "worker_type", "") if not isinstance(worker, dict) else worker.get("worker_type", "")) == result_key
        ]
        task_records = [
            item
            for worker in matching_results
            for item in (getattr(worker, "task_results", []) if not isinstance(worker, dict) else worker.get("task_results", [])) or []
            if str(getattr(item, "task_id", "") if not isinstance(item, dict) else item.get("task_id", "")) == task_id
        ]
        task_errors = [
            item for item in errors
            if str(item.get("stage", "") if isinstance(item, dict) else "") in {stage, worker_type, target_id}
        ]
        diagnostics = [item for item in task_errors if isinstance(item, dict)]
        failed = False
        if isinstance(routed_tasks, list) and stage not in routed_tasks:
            diagnostics.append({"code": "worker_not_dispatched", "stage": stage})
            failed = True
        elif not task_records:
            diagnostics.append({"code": "task_result_missing", "task_id": task_id})
            failed = True
        else:
            record = task_records[-1]
            status = getattr(record, "status", "failed") if not isinstance(record, dict) else record.get("status", "failed")
            record_diagnostics = getattr(record, "diagnostics", []) if not isinstance(record, dict) else record.get("diagnostics", [])
            diagnostics.extend(item for item in (record_diagnostics or []) if isinstance(item, dict))
            failed = status != "succeeded" or bool(task_errors)
            if output_kind == "action" and target_id not in action_target_ids:
                diagnostics.append({"code": "action_result_missing", "target_id": target_id})
                failed = True
        record = task_records[-1] if task_records else None
        assignment = getattr(task, "assignment", None)
        binding = getattr(task, "target_binding", {}) or {}
        record_value = lambda name, default=None: (
            getattr(record, name, default)
            if record is not None and not isinstance(record, dict)
            else (record.get(name, default) if isinstance(record, dict) else default)
        )
        task_results.append(TaskExecutionResult(
            task_id=task_id,
            target_id=target_id,
            status="failed" if failed else "succeeded",
            expected_output_kind=output_kind,
            output_artifacts=[] if failed else [output_kind],
            feature_ids=list(record_value("feature_ids", None) or getattr(task, "feature_ids", None) or binding.get("feature_ids", []) or []),
            scenario_id=(
                str(getattr(task_records[-1], "scenario_id", "") or getattr(task, "scenario_id", "") or "")
                if task_records and not isinstance(task_records[-1], dict)
                else str((task_records[-1].get("scenario_id", "") if task_records else "") or getattr(task, "scenario_id", "") or "")
            ),
            candidate_id=(
                str(getattr(task_records[-1], "candidate_id", "") or getattr(task, "candidate_id", "") or "")
                if task_records and not isinstance(task_records[-1], dict)
                else str((task_records[-1].get("candidate_id", "") if task_records else "") or getattr(task, "candidate_id", "") or "")
            ),
            candidate_ids=list(getattr(task, "candidate_ids", None) or []),
            relation_ids=list(record_value("relation_ids", None) or getattr(task, "relation_ids", None) or []),
            source_feature_ids=list(record_value("source_feature_ids", None) or getattr(task, "source_feature_ids", None) or binding.get("source_feature_ids", []) or []),
            entity_refs=list(record_value("entity_refs", None) or getattr(task, "entity_refs", None) or binding.get("entity_refs", []) or []),
            relation_refs=list(record_value("relation_refs", None) or getattr(task, "relation_refs", None) or binding.get("relation_refs", []) or []),
            feature_bsms=list(getattr(task, "feature_bsms", None) or []),
            evidence_refs=list(getattr(task, "evidence_refs", None) or []),
            l1_snapshot_ref=str(getattr(task, "l1_snapshot_ref", "") or ""),
            bundle_snapshot_digest=str(getattr(task, "bundle_snapshot_digest", "") or ""),
            source_binding_ref=str(getattr(task, "source_binding_ref", "") or ""),
            errors=[str(item) for item in task_errors] + (
                list(getattr(task_records[-1], "errors", []) if not isinstance(task_records[-1], dict) else task_records[-1].get("errors", []))
                if task_records else []
            ),
            diagnostics=diagnostics,
        ))
    for task in list(getattr(execution_plan, "deferred_tasks", None) or []):
        task_results.append(TaskExecutionResult(
            task_id=str(getattr(task, "task_id", "")),
            target_id=str(getattr(task, "target_id", "")),
            status="deferred",
            expected_output_kind=getattr(task, "expected_output_kind", "parcel"),
            candidate_id=str(getattr(task, "candidate_id", "") or ""),
            candidate_ids=list(getattr(task, "candidate_ids", None) or []),
            feature_ids=list(getattr(task, "feature_ids", None) or []),
            source_feature_ids=list(getattr(task, "source_feature_ids", None) or []),
            entity_refs=list(getattr(task, "entity_refs", None) or []),
            relation_refs=list(getattr(task, "relation_refs", None) or getattr(task, "relation_ids", None) or []),
            feature_bsms=list(getattr(task, "feature_bsms", None) or []),
            evidence_refs=list(getattr(task, "evidence_refs", None) or []),
            l1_snapshot_ref=str(getattr(task, "l1_snapshot_ref", "") or ""),
            bundle_snapshot_digest=str(getattr(task, "bundle_snapshot_digest", "") or ""),
            source_binding_ref=str(getattr(task, "source_binding_ref", "") or ""),
        ))
    return {
        "task_results": task_results,
        "action_results": action_results,
        "diagnostics": list(result.get("worker_conflict_diagnostics", []) or []) + errors,
    }


async def execute_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Run the worker subgraph and persist only typed output references."""
    from app.domain.materialization.execute_state import ExecuteAgentState
    from app.domain.materialization.execution_boundaries import (
        candidate_geometry_drift_diagnostics,
        classification_boundary_diagnostics,
    )
    from app.domain.materialization.planned_state_builder import changeset_to_planned_state
    from app.contracts.artifacts.deferral_contracts import DeferralLedger
    from app.contracts.workflow.parse_contracts import SpatialPlanningIntent
    from app.contracts.workflow.parse_result_contracts import IntentCompilationResult
    from app.contracts.spatial.grounding_contracts import GroundingResult
    from app.contracts.spatial.grounded_problem import GroundedPlanningProblem
    from app.contracts.workflow.execution_plan_contracts import ExecutionPlan, ExecutionResult
    from app.domain.suitability.model import SuitabilitySurface
    from app.contracts.planning.approval import ApprovedExecutionInput

    intent = _load_ref_artifact(state, "target_projection", IntentCompilationResult)
    plan_intent = _to_typed(getattr(intent, "typed_intent", None) or intent, SpatialPlanningIntent)
    approved_input = _load_ref_artifact(
        state, "approved_execution_input", ApprovedExecutionInput
    )
    from app.contracts.planning.scenario import ScenarioSet

    scenario_set = _load_ref_artifact(state, "scenario_set", ScenarioSet)
    grounding = _load_ref_artifact(state, "grounding_result", GroundingResult)
    scoped_problem = _load_ref_artifact(
        state, "scoped_grounding_problem", GroundedPlanningProblem
    )
    suitability_surface = _load_ref_artifact(
        state,
        "suitability_surface",
        SuitabilitySurface,
    )
    deferral_ledger = _load_ref_artifact(state, "deferral_ledger", DeferralLedger)
    execution_plan = _load_ref_artifact(state, "execution_plan", ExecutionPlan)
    context = None
    from app.contracts.planning.scenario import PlanningScenario

    approved_scenario = (
        _load_ref_artifact(state, "planning_scenario", PlanningScenario)
        if approved_input is not None
        else None
    )
    if approved_input is None:
        return _execute_approval_error(
            state,
            scenario_set=scenario_set,
            approved_input=None,
            approved_scenario=None,
            context=None,
        )
    if not approved_input.can_execute or scenario_set is None or approved_scenario is None:
        return _execute_approval_error(
            state,
            scenario_set=scenario_set,
            approved_input=approved_input,
            approved_scenario=approved_scenario,
            context=None,
        )
    try:
        approved_input.assert_execution_plan_matches(execution_plan)
    except (TypeError, ValueError) as exc:
        return _approval_boundary_diagnostic(
            state,
            code="EXECUTE_EXECUTION_PLAN_MISMATCH",
            message="ExecutionPlan is missing, stale, or not approval-bound.",
            diagnostics=[{"code": "EXECUTE_EXECUTION_PLAN_MISMATCH", "exception_type": type(exc).__name__}],
        )
    plan_candidate_ids = [
        str(getattr(task, "candidate_id", "") or "")
        for task in list(getattr(execution_plan, "worker_tasks", None) or [])
        if str(getattr(task, "candidate_id", "") or "")
    ]
    approved_candidate_ids = sorted(str(item) for item in (approved_input.candidate_ids or []) if str(item))
    if sorted(plan_candidate_ids) != approved_candidate_ids:
        return _approval_boundary_diagnostic(
            state,
            code="EXECUTE_APPROVED_CANDIDATE_LINEAGE_MISMATCH",
            message=(
                "Every approved candidate must have exactly one materializer task; "
                f"plan={sorted(plan_candidate_ids)!r}, approval={approved_candidate_ids!r}"
            ),
        )
    context = await _require_context(state)
    approval_error = _execute_approval_error(
        state,
        scenario_set=scenario_set,
        approved_input=approved_input,
        approved_scenario=approved_scenario,
        context=context,
    )
    if approval_error is not None:
        return approval_error
    from app.contracts.workflow.repair_directive_contracts import (
        RepairDirectiveCompilation,
    )

    repair_directives = _load_ref_artifact(
        state,
        "repair_directives",
        RepairDirectiveCompilation,
    )
    exec_repair_payload, require_evidence_target_ids = _build_exec_repair_payload(
        repair_directives
    )
    if exec_repair_payload:
        return _approval_boundary_diagnostic(
            state,
            code="EXECUTE_EXECUTION_PLAN_REBUILD_REQUIRED",
            message="EXECUTE repair directives require a new SELECT plan and approval.",
        )
    if plan_intent is not None:
        classification_diagnostics = classification_boundary_diagnostics(
            plan_intent,
            execution_plan,
            deferral_ledger=deferral_ledger,
        )
        if classification_diagnostics:
            return _classification_diagnostic_result(state, classification_diagnostics)

    if getattr(execution_plan, "deferred_tasks", None):
        return _approval_boundary_diagnostic(
            state,
            code="EXECUTE_EXECUTION_PLAN_INCOMPLETE",
            message="EXECUTE requires a complete plan; deferred tasks need new planning and approval.",
        )

    from app.domain.allocation.refined_candidate_catalog import (
        build_refined_candidate_catalog,
    )

    candidate_catalog = build_refined_candidate_catalog(
        scoped_problem or getattr(grounding, "problem", None), suitability_surface
    )
    geometry_diagnostics = candidate_geometry_drift_diagnostics(
        execution_plan,
        candidate_catalog,
    )
    if geometry_diagnostics:
        return _approval_boundary_diagnostic(
            state,
            code="EXECUTE_APPROVED_CANDIDATE_GEOMETRY_MISMATCH",
            message="Current candidate catalog differs from the approval-bound task geometry or lineage.",
            diagnostics=geometry_diagnostics,
        )
    exec_state = ExecuteAgentState(
        session_id=state.get("session_id", ""),
        village_name=state.get("config", {}).get("village_name", ""),
        spatial_workspace=getattr(context, "workspace", None),
        facility_anchors=getattr(context, "village_anchors", None),
        candidate_geometry_by_id=candidate_catalog,
        land_design_briefs=list(getattr(execution_plan, "land_design_briefs", None) or []),
        execution_plan=execution_plan,
        approved_execution_input=approved_input,
        approved_input_fingerprint=approved_input.fingerprint,
        kg_session_ref=getattr(context, "kg_session_ref", "") or "",
        kg_three_lines=list(state.get("kg_three_lines") or []),
        messages=list(state.get("messages") or []),
        repair_directives=exec_repair_payload,
        required_source_evidence_target_ids=require_evidence_target_ids,
    )
    from app.domain.materialization.nodes.worker_common import _execution_intent_from_plan
    execution_intent = _execution_intent_from_plan(exec_state)
    graph = _get_execute_subgraph()
    kg_obj = getattr(context, "kg", None)
    if kg_obj is not None and execution_intent is not None:
        try:
            from app.infrastructure.kg.builder.layer3 import build_intent_layer
            build_intent_layer(kg_obj, execution_intent)
        except Exception as exc:
            logger.warning("[workflow:execute] build_intent_layer failed: %s", type(exc).__name__)
    import asyncio
    from app.core.settings import LLM_REQUEST_TIMEOUT
    try:
        async with asyncio.timeout(max(900, int(LLM_REQUEST_TIMEOUT) * 5)):
            result = await graph.ainvoke(
                exec_state,
                config={"configurable": {"thread_id": state.get("session_id", "")}},
            )
    except TimeoutError as exc:
        logger.error("[workflow:execute] subgraph timeout; failing closed")
        # Surface a typed diagnostic instead of re-raising: a hard exception
        # becomes a pending ERROR write that resume re-runs forever without
        # ever recording the real failure.
        payload = {
            "code": "EXECUTE_TIMEOUT",
            "message": "GIS worker subgraph exceeded its cancellation boundary",
            "errors": [{"code": "EXECUTE_TIMEOUT", "exception_type": type(exc).__name__}],
            "target_ids": [],
        }
        diagnostic_ref = None
        try:
            working_state = {**state, "artifact_refs": dict(state.get("artifact_refs") or {})}
            diagnostic_ref = persist_stage_artifact(
                working_state,
                "execute",
                "ExecutionDiagnostics",
                payload,
            )
        except Exception as persist_exc:  # noqa: BLE001 - diagnostic must not mask the timeout
            logger.error("[workflow:execute] failed to persist timeout diagnostic: %s", type(persist_exc).__name__)
            payload["persistence_error"] = type(persist_exc).__name__
        return {
            "fatal_error": {
                "stage": "EXECUTE",
                "code": "EXECUTE_TIMEOUT",
                "message": payload["message"],
                "target_ids": [],
                "diagnostics": payload["errors"],
            },
            "delivery_status": "diagnostic_only",
            "diagnostic_terminal": {
                "stage": "execute",
                "reason": "EXECUTE_TIMEOUT",
                "target_ids": [],
                "diagnostics": payload["errors"],
            },
            "artifact_refs": {
                **dict(state.get("artifact_refs") or {}),
                **({"execution_diagnostics": diagnostic_ref} if diagnostic_ref else {}),
            },
        }

    changeset = result.get("parcel_changeset")
    planned_state = result.get("planned_state")
    blocking_conflicts = [
        item
        for item in list(result.get("worker_conflict_diagnostics", []) or [])
        if isinstance(item, dict) and bool(item.get("blocking"))
    ]
    if planned_state is None and changeset is not None and not blocking_conflicts:
        planned_state = changeset_to_planned_state(
            changeset,
            execution_intent,
            list(result.get("layout_configs", []) or []),
        )
    outcome = _task_results_from_execution(execution_plan, result)
    result_candidate_ids = sorted(
        str(getattr(item, "candidate_id", "") or "")
        for item in list(outcome.get("task_results", []) or [])
        if str(getattr(item, "candidate_id", "") or "")
    )
    if result_candidate_ids != approved_candidate_ids:
        blocking_conflicts.append({
            "code": "EXECUTE_OUTPUT_CANDIDATE_LINEAGE_MISMATCH",
            "blocking": True,
            "message": (
                "materializer output candidate lineage must match approved candidates; "
                f"output={result_candidate_ids!r}, approval={approved_candidate_ids!r}"
            ),
        })
    if require_evidence_target_ids:
        outcome = _mark_require_evidence_unresolved(
            outcome,
            execution_plan,
            require_evidence_target_ids,
        )
    from app.domain.materialization.atomic_commit import (
        ExecutionBatch,
        commit_execution_batch,
    )

    commit_result = commit_execution_batch(
        ExecutionBatch(
            approved_input=approved_input,
            expected_task_ids=[
                str(getattr(task, "task_id", "") or "")
                for task in list(getattr(execution_plan, "worker_tasks", None) or [])
                if str(getattr(task, "task_id", "") or "").strip()
            ],
            worker_results=list(outcome.get("task_results", []) or []),
            planned_state=planned_state,
            diagnostics=[
                str(item.get("code") or item.get("message") or "")
                for item in blocking_conflicts
                if isinstance(item, dict)
            ],
        )
    )
    l4_write_result: Dict[str, Any] = {}
    working_state = {**state, "artifact_refs": dict(state.get("artifact_refs") or {})}
    scenario_ref = (
        (state.get("artifact_refs") or {}).get("planning_scenario")
        or (state.get("artifact_refs") or {}).get("scenario")
        or ""
    )
    if isinstance(scenario_ref, dict):
        scenario_ref = str(
            scenario_ref.get("descriptor_digest")
            or scenario_ref.get("digest")
            or ""
        )
    from app.contracts.planning.scenario import PlanningScenario

    scenario_artifact = (
        _load_ref_artifact(
            state,
            "planning_scenario",
            PlanningScenario,
        )
        if (state.get("artifact_refs") or {}).get("planning_scenario")
        else None
    )
    if scenario_artifact is not None:
        selection_scenario_id = str(
            getattr(scenario_artifact, "scenario_id", "")
            or (scenario_artifact.get("scenario_id", "") if isinstance(scenario_artifact, dict) else "")
            or str(getattr(approved_input, "scenario_id", "") or "")
        )
    scenario_id = str(
        state.get("scenario_id")
        or str(getattr(approved_input, "scenario_id", "") or "")
        or ""
    )
    if planned_state is not None and hasattr(planned_state, "model_copy"):
        planned_state = planned_state.model_copy(update={
            "scenario_id": scenario_id or getattr(planned_state, "scenario_id", ""),
            "scenario_ref": scenario_ref,
            "execution_trace_refs": list(
                dict.fromkeys(
                    list(getattr(planned_state, "execution_trace_refs", []) or [])
                    + [
                        f"trace:{item.get('task_id')}:{item.get('event')}"
                        for item in list(result.get("execution_trace", []) or [])
                        if item.get("task_id") and item.get("event")
                    ]
                )
            ),
        })
    from app.contracts.artifacts.execution_staging_contracts import ExecutionStaging

    staged_changeset_ref = None
    if changeset is not None:
        staged_changeset_ref = persist_stage_artifact(
            working_state,
            "execute",
            "ParcelChangeSet",
            changeset,
            artifact_key="staged_parcel_changeset",
        )
        working_state["artifact_refs"]["staged_parcel_changeset"] = staged_changeset_ref
    staged_planned_state_ref = None
    if planned_state is not None:
        staged_planned_state_ref = persist_stage_artifact(
            working_state,
            "execute",
            "PlannedState",
            planned_state,
            artifact_key="staged_planned_state",
        )
        working_state["artifact_refs"]["staged_planned_state"] = staged_planned_state_ref
    staged_layout_configs_ref = persist_stage_artifact(
        working_state,
        "execute",
        "LayoutConfigs",
        list(result.get("layout_configs", []) or []),
        artifact_key="staged_layout_configs",
    )
    working_state["artifact_refs"]["staged_layout_configs"] = staged_layout_configs_ref
    execution_plan_ref = (state.get("artifact_refs") or {}).get("execution_plan")
    approved_input_ref = (state.get("artifact_refs") or {}).get("approved_execution_input")
    staging_ref = persist_stage_artifact(
        working_state,
        "execute",
        "ExecutionStaging",
        ExecutionStaging(
            staging_id=f"staging:{_run_id(state)}:{scenario_id or 'baseline'}",
            approved_input_ref=_ref_digest(approved_input_ref),
            execution_plan_ref=_ref_digest(execution_plan_ref),
            staged_parcel_changeset_ref=_ref_digest(staged_changeset_ref),
            staged_planned_state_ref=_ref_digest(staged_planned_state_ref),
            staged_layout_configs_ref=_ref_digest(staged_layout_configs_ref),
            worker_task_ids=[
                str(getattr(item, "task_id", "") or "")
                for item in list(outcome.get("task_results", []) or [])
                if str(getattr(item, "task_id", "") or "")
            ],
            failed_task_ids=[
                str(getattr(item, "task_id", "") or "")
                for item in list(outcome.get("task_results", []) or [])
                if str(getattr(item, "status", "") or "") in {"failed", "error"}
            ],
            status="staged" if commit_result.status == "committed" else "aborted",
            commit_id="",
            diagnostics=list(commit_result.diagnostics),
        ),
    )
    working_state["artifact_refs"]["execution_staging"] = staging_ref

    if commit_result.status == "committed" and planned_state is not None:
        from app.domain.materialization.nodes.write_l4 import _write_l4_node

        exec_state.parcel_changeset = changeset
        exec_state.layout_configs = list(result.get("layout_configs", []) or [])
        exec_state.planned_state = planned_state
        exec_state.execution_result = outcome
        exec_state.validation_result = dict(result.get("validation_result") or {})
        try:
            l4_write_result = await _write_l4_node(exec_state) or {}
        except Exception as exc:
            logger.error(
                "[workflow:execute] L4 write failed (exception_type=%s)",
                type(exc).__name__,
            )
            l4_write_result = {
                "l4_write_error": "l4_write_failed",
                "error_type": type(exc).__name__,
                "message": "L4 write failed after atomic execution commit.",
            }
    elif commit_result.status == "aborted":
        l4_write_result = {
            "l4_write_error": "atomic_commit_aborted",
            "atomic_commit_diagnostics": list(commit_result.diagnostics),
        }

    l4_error = l4_write_result.get("l4_write_error")
    staged_commit_succeeded = commit_result.status == "committed" and not l4_error
    parcel_changeset_ref = staged_changeset_ref if staged_commit_succeeded else None
    planned_state_ref = staged_planned_state_ref if staged_commit_succeeded else None
    layout_configs_ref = staged_layout_configs_ref if staged_commit_succeeded else None
    if staged_commit_succeeded:
        # Include the promotion refs in the final staging revision's parent
        # set.  A replay from the committed checkpoint then sees the exact
        # same parent graph instead of creating a spurious staging revision.
        working_state["artifact_refs"].update(
            {
                **({"parcel_changeset": parcel_changeset_ref} if parcel_changeset_ref else {}),
                **({"planned_state": planned_state_ref} if planned_state_ref else {}),
                "layout_configs": layout_configs_ref,
            }
        )
    staging_ref = persist_stage_artifact(
        working_state,
        "execute",
        "ExecutionStaging",
        ExecutionStaging(
            staging_id=f"staging:{_run_id(state)}:{scenario_id or 'baseline'}",
            approved_input_ref=_ref_digest(approved_input_ref),
            execution_plan_ref=_ref_digest(execution_plan_ref),
            staged_parcel_changeset_ref=_ref_digest(staged_changeset_ref),
            staged_planned_state_ref=_ref_digest(staged_planned_state_ref),
            staged_layout_configs_ref=_ref_digest(staged_layout_configs_ref),
            worker_task_ids=[
                str(getattr(item, "task_id", "") or "")
                for item in list(outcome.get("task_results", []) or [])
                if str(getattr(item, "task_id", "") or "")
            ],
            failed_task_ids=[
                str(getattr(item, "task_id", "") or "")
                for item in list(outcome.get("task_results", []) or [])
                if str(getattr(item, "status", "") or "") in {"failed", "error"}
            ],
            status="committed" if staged_commit_succeeded else "aborted",
            commit_id=(commit_result.commit_id if staged_commit_succeeded else ""),
            diagnostics=[
                *list(commit_result.diagnostics),
                *(
                    [str(l4_error)]
                    if l4_error
                    else []
                ),
            ],
        ),
    )
    working_state["artifact_refs"]["execution_staging"] = staging_ref
    execution_errors = list(result.get("execution_errors", []) or [])
    if l4_error:
        execution_errors.append({"stage": "L4", "code": l4_error, "missing_targets": l4_write_result.get("missing_targets", [])})
    fatal_error = None
    diagnostic_terminal = None
    if l4_error:
        from app.infrastructure.artifacts.fingerprint import semantic_checksum
        missing_targets = _jsonable(l4_write_result.get("missing_targets", []))
        fatal_error = {"stage": "EXECUTE", "code": str(l4_error), "message": f"L4 write failed: {l4_error}", "missing_targets": missing_targets}
        diagnostic_terminal = {"stage": "execute", "reason": str(l4_error), "issue_fingerprint": semantic_checksum(l4_write_result), "missing_targets": missing_targets}
    diagnostics_ref = persist_stage_artifact(
        working_state,
        "execute",
        "ExecutionDiagnostics",
        {"errors": _jsonable(execution_errors), "l4_write": _jsonable(l4_write_result), "target_coverage": _jsonable(l4_write_result.get("execution_result_target_ids", []))},
    )
    if diagnostics_ref:
        working_state["artifact_refs"]["execution_diagnostics"] = diagnostics_ref
    task_result_records = list(outcome.get("task_results", []) or [])
    bundle_snapshot_digests = sorted(
        {
            str(
                getattr(item, "bundle_snapshot_digest", "")
                if not isinstance(item, dict)
                else item.get("bundle_snapshot_digest", "")
            )
            for item in task_result_records
            if str(
                getattr(item, "bundle_snapshot_digest", "")
                if not isinstance(item, dict)
                else item.get("bundle_snapshot_digest", "")
            ).strip()
        }
    )
    execution_evidence_refs = sorted(
        {
            str(ref)
            for item in task_result_records
            for ref in (
                getattr(item, "evidence_refs", [])
                if not isinstance(item, dict)
                else item.get("evidence_refs", [])
            )
            if str(ref).strip()
        }
    )
    lineage_diagnostics = (
        [{"code": "mixed_bundle_snapshot", "digests": bundle_snapshot_digests}]
        if len(bundle_snapshot_digests) > 1
        else []
    )
    execution_diagnostics = list(outcome.get("diagnostics", []) or []) + lineage_diagnostics
    if l4_write_result:
        execution_diagnostics.append({"l4_write": _jsonable(l4_write_result)})
    if commit_result.diagnostics:
        execution_diagnostics.append({"atomic_commit": list(commit_result.diagnostics)})
    execution_result = ExecutionResult(
        execution_plan_ref=(state.get("artifact_refs") or {}).get("execution_plan", {}),
        parcel_changeset_ref=parcel_changeset_ref,
        planned_state_ref=planned_state_ref,
        layout_configs_ref=layout_configs_ref,
        task_results=list(outcome.get("task_results", []) or []),
        action_results=list(outcome.get("action_results", []) or []),
        diagnostics=execution_diagnostics,
        scenario_id=scenario_id,
        scenario_ref=scenario_ref if isinstance(scenario_ref, str) else str(scenario_ref or ""),
        execution_trace_refs=list(
            dict.fromkeys(
                [
                    f"trace:{item.get('task_id')}:{item.get('event')}"
                    for item in list(result.get("execution_trace", []) or [])
                    if item.get("task_id") and item.get("event")
                ]
            )
        ),
        bundle_snapshot_digest=(
            bundle_snapshot_digests[0] if len(bundle_snapshot_digests) == 1 else ""
        ),
        evidence_refs=execution_evidence_refs,
        approved_input_ref=(state.get("artifact_refs") or {}).get("approved_execution_input"),
        atomic_commit_id=(
            commit_result.commit_id
            if commit_result.status == "committed" and not l4_error
            else ""
        ),
        atomic_commit_status=(
            "aborted"
            if l4_error or commit_result.status == "aborted"
            else "committed"
        ),
    )
    execution_result_ref = persist_stage_artifact(
        working_state, "execute", "ExecutionResult", execution_result
    )
    return {
        **({"fatal_error": fatal_error, "delivery_status": "diagnostic_only", "diagnostic_terminal": diagnostic_terminal} if l4_error else {}),
        "artifact_refs": {
            **dict(state.get("artifact_refs") or {}),
            "execution_result": execution_result_ref,
            **({"parcel_changeset": parcel_changeset_ref} if parcel_changeset_ref else {}),
            **({"planned_state": planned_state_ref} if planned_state_ref else {}),
            **({"layout_configs": layout_configs_ref} if layout_configs_ref else {}),
            "execution_staging": staging_ref,
            **({"execution_diagnostics": diagnostics_ref} if diagnostics_ref else {}),
        },
        **_adopt_context(state, context),
    }


__all__ = ["execute_node"]
