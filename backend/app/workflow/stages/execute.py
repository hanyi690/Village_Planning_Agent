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
        logger.error("[workflow:execute] failed to persist classification diagnostic: %s", exc)
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


def _defer_unclassified_targets(
    state: Dict[str, Any],
    execution_plan: Any,
    deferral_ledger: Any,
    classification_diagnostics: list[dict[str, Any]],
) -> tuple[Any, Any] | None:
    """Auto-defer targets blocked on unresolved classification decisions.

    EXECUTE refuses to run parcel/polygon targets without an explicit
    ClassificationDecision or a DeferralLedger entry.  Instead of failing the
    whole run into a diagnostic terminal, record those targets as deferred
    (partial delivery) so the remaining plan executes.  Deterministic only -
    no LLM decision is invented here.
    """
    from app.contracts.artifacts.deferral_contracts import DeferralLedger
    from app.domain.delivery.deferral_ledger import append_ledger, build_target_deferrals
    from app.domain.materialization.plan_builder import defer_plan_tasks

    target_ids = sorted({
        str(item.get("target_id", ""))
        for item in classification_diagnostics
        if str(item.get("target_id", "")).strip()
    })
    if not target_ids:
        return None
    try:
        revised_ledger = append_ledger(
            deferral_ledger,
            build_target_deferrals(
                target_ids,
                reason="classification_decision_required",
                source_refs=("artifact:site_selection",),
                decided_by="execute",
                rationale="unresolved classification deferred for partial delivery",
            ),
        )
        revised_plan = defer_plan_tasks(
            execution_plan, target_ids, review_id="execute-classification-defer"
        )
    except Exception as exc:  # noqa: BLE001 - deferral must never break EXECUTE
        logger.warning("[workflow:execute] classification deferral failed: %s", exc)
        return None

    working_state = {**state, "artifact_refs": dict(state.get("artifact_refs") or {})}
    try:
        ledger_ref = persist_stage_artifact(
            working_state, "execute", "DeferralLedger", revised_ledger
        )
        if ledger_ref:
            working_state["artifact_refs"]["deferral_ledger"] = ledger_ref
    except Exception as exc:  # noqa: BLE001
        logger.warning("[workflow:execute] classification deferral ledger persist failed: %s", exc)
    try:
        plan_ref = persist_stage_artifact(
            working_state, "execute", "ExecutionPlan", revised_plan
        )
        if plan_ref:
            working_state["artifact_refs"]["execution_plan"] = plan_ref
    except Exception as exc:  # noqa: BLE001
        logger.warning("[workflow:execute] classification deferral plan persist failed: %s", exc)
    state["artifact_refs"] = working_state["artifact_refs"]
    logger.info(
        "[workflow:execute] auto-deferred %d unclassified targets for partial delivery",
        len(target_ids),
    )
    return revised_plan, revised_ledger


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
        task_results.append(TaskExecutionResult(
            task_id=task_id,
            target_id=target_id,
            status="failed" if failed else "succeeded",
            expected_output_kind=output_kind,
            output_artifacts=[] if failed else [output_kind],
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
        ))
    return {
        "task_results": task_results,
        "action_results": action_results,
        "diagnostics": list(result.get("worker_conflict_diagnostics", []) or []) + errors,
    }


async def execute_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Run the worker subgraph and persist only typed output references."""
    from app.domain.materialization.execute_state import ExecuteAgentState
    from app.domain.materialization.plan_builder import (
        build_execution_plan,
        classification_boundary_diagnostics,
    )
    from app.domain.materialization.planned_state_builder import changeset_to_planned_state
    from app.contracts.artifacts.deferral_contracts import DeferralLedger
    from app.contracts.workflow.parse_contracts import SpatialPlanningIntent
    from app.contracts.workflow.parse_result_contracts import IntentCompilationResult
    from app.contracts.domain.selection_contracts import SiteSelectionDecision
    from app.contracts.spatial.global_zone_allocation_contracts import GlobalZoneAllocationResult
    from app.contracts.workflow.execution_plan_contracts import ExecutionPlan, ExecutionResult

    intent = _load_ref_artifact(state, "target_projection", IntentCompilationResult)
    plan_intent = _to_typed(getattr(intent, "typed_intent", None) or intent, SpatialPlanningIntent)
    site_selection = _load_ref_artifact(state, "site_selection", SiteSelectionDecision)
    global_zone_allocation = _load_ref_artifact(
        state,
        "global_zone_allocation",
        GlobalZoneAllocationResult,
    )
    deferral_ledger = _load_ref_artifact(state, "deferral_ledger", DeferralLedger)
    execution_plan = _load_ref_artifact(state, "execution_plan", ExecutionPlan)
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
        logger.info(
            "[workflow:execute] applying %d repair directives; %d targets require source evidence",
            len(exec_repair_payload),
            len(require_evidence_target_ids),
        )
        if plan_intent is not None:
            plan_intent, intent_repaired = _apply_execute_repair_to_intent(
                plan_intent,
                exec_repair_payload,
            )
            if intent_repaired:
                intent.typed_intent = plan_intent
                execution_plan = build_execution_plan(
                    intent,
                    site_selection,
                    [],
                    run_id=_run_id(state),
                    context_version=_context_version(state),
                    deferral_ledger=deferral_ledger,
                )
    if execution_plan is None and intent is not None and site_selection is not None:
        execution_plan = build_execution_plan(
            intent,
            site_selection,
            [],
            run_id=_run_id(state),
            context_version=_context_version(state),
            deferral_ledger=deferral_ledger,
        )
    if plan_intent is not None:
        classification_diagnostics = classification_boundary_diagnostics(
            plan_intent,
            execution_plan,
            deferral_ledger=deferral_ledger,
        )
        if classification_diagnostics:
            deferral = _defer_unclassified_targets(
                state,
                execution_plan,
                deferral_ledger,
                classification_diagnostics,
            )
            if deferral is None:
                return _classification_diagnostic_result(
                    state, classification_diagnostics
                )
            execution_plan, deferral_ledger = deferral

    context = await _require_context(state)
    exec_state = ExecuteAgentState(
        session_id=state.get("session_id", ""),
        village_name=state.get("config", {}).get("village_name", ""),
        spatial_workspace=getattr(context, "workspace", None),
        facility_anchors=getattr(context, "village_anchors", None),
        site_selection=site_selection,
        global_zone_allocation_result=global_zone_allocation,
        land_design_briefs=list(getattr(execution_plan, "land_design_briefs", None) or []),
        execution_plan=execution_plan,
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
            logger.warning("[workflow:execute] build_intent_layer failed: %s", exc)
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
            "errors": [{"code": "EXECUTE_TIMEOUT", "message": str(exc)}],
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
            logger.error("[workflow:execute] failed to persist timeout diagnostic: %s", persist_exc)
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
            "artifact_refs": {"execution_diagnostics": diagnostic_ref} if diagnostic_ref else {},
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
    if require_evidence_target_ids:
        outcome = _mark_require_evidence_unresolved(
            outcome,
            execution_plan,
            require_evidence_target_ids,
        )
    l4_write_result: Dict[str, Any] = {}
    if planned_state is not None:
        from app.domain.materialization.nodes.write_l4 import _write_l4_node
        exec_state.parcel_changeset = changeset
        exec_state.layout_configs = list(result.get("layout_configs", []) or [])
        exec_state.planned_state = planned_state
        exec_state.execution_result = outcome
        exec_state.validation_result = dict(result.get("validation_result") or {})
        try:
            l4_write_result = await _write_l4_node(exec_state) or {}
        except Exception as exc:
            logger.exception("[workflow:execute] L4 write failed")
            l4_write_result = {"l4_write_error": "l4_write_failed", "error_type": type(exc).__name__, "message": str(exc)}
    working_state = {**state, "artifact_refs": dict(state.get("artifact_refs") or {})}
    parcel_changeset_ref = persist_stage_artifact(working_state, "execute", "ParcelChangeSet", changeset)
    working_state["artifact_refs"]["parcel_changeset"] = parcel_changeset_ref
    planned_state_ref = persist_stage_artifact(working_state, "execute", "PlannedState", planned_state)
    working_state["artifact_refs"]["planned_state"] = planned_state_ref
    layout_configs_ref = persist_stage_artifact(
        working_state, "execute", "LayoutConfigs", list(result.get("layout_configs", []) or [])
    )
    working_state["artifact_refs"]["layout_configs"] = layout_configs_ref
    l4_error = l4_write_result.get("l4_write_error")
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
    execution_result = ExecutionResult(
        execution_plan_ref=(state.get("artifact_refs") or {}).get("execution_plan", {}),
        parcel_changeset_ref=parcel_changeset_ref,
        planned_state_ref=planned_state_ref,
        layout_configs_ref=layout_configs_ref,
        task_results=list(outcome.get("task_results", []) or []),
        action_results=list(outcome.get("action_results", []) or []),
        diagnostics=list(outcome.get("diagnostics", []) or []) + (
            [{"l4_write": _jsonable(l4_write_result)}] if l4_write_result else []
        ),
    )
    execution_result_ref = persist_stage_artifact(
        working_state, "execute", "ExecutionResult", execution_result
    )
    return {
        **({"fatal_error": fatal_error, "delivery_status": "diagnostic_only", "diagnostic_terminal": diagnostic_terminal} if l4_error else {}),
        "artifact_refs": {
            "execution_result": execution_result_ref,
            "parcel_changeset": parcel_changeset_ref,
            "planned_state": planned_state_ref,
            "layout_configs": layout_configs_ref,
            **({"execution_diagnostics": diagnostics_ref} if diagnostics_ref else {}),
        },
        **_adopt_context(state, context),
    }


__all__ = ["execute_node"]
