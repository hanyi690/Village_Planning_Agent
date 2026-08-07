"""Main-graph post-L3 node functions (Wave M).

Each function is a LangGraph node operating on the main ``AgentState`` dict
(single state source). It reads the typed inputs produced by the previous
stage, calls the underlying deterministic aggregate (PARSE/GROUND/SELECT/
EXECUTE/VALIDATE/RECONCILE/DELIVER), evaluates the stage gate and writes the
typed artifacts + gate back into the shared AgentState.

The main graph uses these nodes directly so the L3 gate PASS flows into PARSE
without a wrapper graph or a ``gis_agent`` black-box node.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.modules.schema.contracts.workflow_contracts import GateDecision
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Stage -> routes that indicate a retryable outcome (the node owns the counter).
_RETRY_ROUTES: Dict[str, frozenset[str]] = {
    "parse": frozenset({"REPAIR", "REVISE"}),
    "ground": frozenset({"EXPLORE"}),
    "select": frozenset({"RETRY_GROUND"}),
    "validate": frozenset({"RETRY_EXECUTE", "RETRY_SELECT", "RETRY_GROUND", "RETRY_PARSE", "RETRY_L3"}),
    "reconcile": frozenset({"RETRY_EXECUTE", "RETRY_L3"}),
    "deliver": frozenset({"RETRY_VALIDATE"}),
}

# Stage -> next stage after a HUMAN approve (forward chain).
_STAGE_FORWARD_TARGET = {
    "parse": "ground",
    "ground": "select",
    "select": "execute",
    "validate": "reconcile",
    "reconcile": "deliver",
    "deliver": "__end__",
}

# Gate state channel names (there is no execute_gate).
_GATE_CHANNELS = (
    "parse_gate", "ground_gate", "select_gate",
    "validate_gate", "reconcile_gate", "deliver_gate",
)


def _pass_gate(stage: str) -> GateDecision:
    """Construct a force-pass GateDecision for a stage (approve path)."""
    return GateDecision(
        stage=stage, passed=True, feedback_route=None,
        pending_requests=[], evidence_requests=[],
    )


def _gate_route(gate: Any) -> str:
    """Extract feedback_route from a gate (typed or dict), defaulting to PASS."""
    if gate is None:
        return "PASS"
    route = getattr(gate, "feedback_route", None)
    if route is None and isinstance(gate, dict):
        route = gate.get("feedback_route")
    return route or "PASS"


def _gate_failure_context(gate: Any) -> str:
    """Human-readable failure reason from a gate decision."""
    if gate is None:
        return ""
    if isinstance(gate, dict):
        pending = gate.get("pending_requests") or []
        evidence = gate.get("evidence_requests") or []
        route = gate.get("feedback_route")
    else:
        pending = getattr(gate, "pending_requests", None) or []
        evidence = getattr(gate, "evidence_requests", None) or []
        route = getattr(gate, "feedback_route", None)

    for pr in pending:
        ctx = pr.get("context") if isinstance(pr, dict) else getattr(pr, "context", None)
        if isinstance(ctx, dict):
            for key in ("message", "detail"):
                val = ctx.get(key)
                if val:
                    return str(val)
        req_type = pr.get("request_type") if isinstance(pr, dict) else getattr(pr, "request_type", None)
        if req_type:
            return str(req_type)
    if evidence:
        return str(evidence[0])
    if route:
        return f"route={route}"
    return ""


def _retry_patch(state: Dict[str, Any], stage: str) -> Dict[str, Any]:
    """Compose retry side-effects (counts bump + error_feedback) for a stage."""
    gate = state.get(f"{stage}_gate")
    if gate is None:
        return {}
    if _gate_route(gate) not in _RETRY_ROUTES.get(stage, frozenset()):
        return {}
    counts = dict(state.get("retry_counts") or {})
    feedback = dict(state.get("error_feedback") or {})
    return {
        "retry_counts": {
            **counts,
            stage: counts.get(stage, 0) + 1,
        },
        "error_feedback": {
            **feedback,
            stage: _gate_failure_context(gate),
        },
    }


def _accumulate_gate(gates: List[Any], gate: Any) -> List[Any]:
    return list(gates or []) + ([gate] if gate is not None else [])


def _run_id(state: Dict[str, Any]) -> str:
    return state.get("run_id") or state.get("session_id", "")


def _context_version(state: Dict[str, Any]) -> str:
    return state.get("context_version", "")


def _get_cached_context(state: Dict[str, Any]) -> Any:
    session_id = state.get("session_id", "")
    if not session_id:
        return None
    try:
        from app.services.context.planning_context import get_cached_context
        return get_cached_context(session_id)
    except Exception:
        return None


def _to_typed(data: Any, cls: type) -> Any:
    """Reconstruct a typed Pydantic object from a dict (for aggregate consumption)."""
    if data is None:
        return None
    if isinstance(data, cls):
        return data
    if isinstance(data, dict):
        try:
            return cls(**data)
        except Exception:
            return data
    return data


def _dump(obj: Any) -> Any:
    """Serialize typed Pydantic objects to JSON-safe dicts for checkpoint."""
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json")
        except Exception:
            return obj
    return obj


def _dump_list(items: list) -> list:
    """Serialize a list of typed objects (or pass through dicts)."""
    return [_dump(i) for i in (items or [])]


def _jsonable(obj: Any) -> Any:
    """Recursively convert to msgpack/JSON-safe primitives.

    Handles pydantic models, SimpleNamespace, dataclasses, numpy scalars/arrays
    and nested containers so checkpoint serialization never hits an unserializable
    type (e.g. ``types.SimpleNamespace``) inside GeoJSON/layout payloads.
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if hasattr(obj, "model_dump"):
        try:
            return _jsonable(obj.model_dump(mode="json"))
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        return _jsonable(vars(obj))
    if hasattr(obj, "tolist"):
        try:
            return _jsonable(obj.tolist())
        except Exception:
            pass
    return str(obj)


def _persist_artifact(
    state: Dict[str, Any], module: str, artifact_type: str, payload: Any,
) -> Dict[str, Any]:
    """Store a typed artifact and update the canonical ref-only map."""
    try:
        from app.agent.bootstrap.artifact_runtime import store_artifact
        key_by_type = {
            "GroundingResult": "grounding_result",
            "SiteSelectionDecision": "site_selection",
            "ParcelChangeSet": "parcel_changeset",
            "PlannedState": "planned_state",
            "ValidationReport": "validation_report",
            "ReconciliationReport": "reconciliation_report",
            "DeliveryManifest": "delivery_manifest",
            "PlanningProgram": "planning_program",
            "IntentCompilationResult": "intent_compilation",
            "ExecutionPlan": "execution_plan",
            "AllocatedGeoJSON": "allocated_geojson",
            "RenderLayers": "render_layers",
        }
        key = key_by_type.get(artifact_type, artifact_type.lower())
        return store_artifact(state, key, module, artifact_type, payload)
    except Exception as exc:
        from app.agent.bootstrap.artifact_runtime import ArtifactReplayError
        if isinstance(exc, ArtifactReplayError):
            raise
        logger.warning("[post_l3:main] artifact persist failed (%s): %s", artifact_type, exc)
        return {}


def _load_planning_program(state: Dict[str, Any]) -> Any:
    from app.modules.schema.contracts.l3_contracts import PlanningProgram
    program = _load_ref_artifact(state, "planning_program", PlanningProgram)
    return program


def _load_ref_artifact(state: Dict[str, Any], key: str, cls: type) -> Any:
    """Load a typed artifact from the canonical refs, with legacy fallback."""
    try:
        from app.agent.bootstrap.artifact_runtime import (
            ArtifactReplayError,
            load_artifact,
            migrate_legacy_artifacts,
        )
        migrated = dict(state)
        migrated["artifact_refs"] = migrate_legacy_artifacts(state)
        value = load_artifact(migrated, key, cls)
        return value
    except ArtifactReplayError:
        raise
    except Exception as exc:
        logger.warning("[post_l3:main] ref load failed for %s: %s", key, exc)
        return None


# ── PARSE ──────────────────────────────────────────────────────────────


async def parse_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """PARSE node: compile PlanningProgram -> IntentCompilationResult + specs."""
    from app.agent.parse.aggregate import compile_program_async

    retry_patch = _retry_patch(state, "parse")
    program = _load_planning_program(state)
    if program is None:
        logger.warning("[post_l3:main:parse] no planning_program; empty compile")
    result, specs, gate = await compile_program_async(
        program,
        run_id=_run_id(state),
        context_version=_context_version(state),
    )
    intent_ref = _persist_artifact(state, "parse", "IntentCompilationResult", result)
    return {
        "specs": _dump_list(specs),
        "parse_gate": _dump(gate),
        "upstream_gates": _accumulate_gate(state.get("upstream_gates"), _dump(gate)),
        "artifact_refs": {"intent_compilation": intent_ref} if intent_ref else {},
        **retry_patch,
    }


# ── GROUND ─────────────────────────────────────────────────────────────


async def ground_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """GROUND node: specs + context -> GroundingResult + gate."""
    from app.agent.ground.aggregate import ground_aggregate
    from app.agent.ground.aggregate import retrieve_evidence
    from app.agent.ground.gate import evaluate_ground_gate
    from app.modules.schema.contracts.spatial_reference_contracts import SpatialReferenceSpec

    retry_patch = _retry_patch(state, "ground")
    context = _get_cached_context(state)
    specs = [_to_typed(s, SpatialReferenceSpec) for s in (state.get("specs") or [])]
    evidence = []
    if retry_patch:
        prior_gate = state.get("ground_gate")
        requests = getattr(prior_gate, "evidence_requests", None)
        if requests is None and isinstance(prior_gate, dict):
            requests = prior_gate.get("evidence_requests")
        try:
            evidence = await retrieve_evidence(context, requests or None)
        except Exception as e:
            logger.warning("[post_l3:main:ground] retrieve_evidence failed: %s", e)
    result = ground_aggregate(specs, context)
    if evidence and hasattr(result, "spatial_query_evidence"):
        result.spatial_query_evidence.extend(evidence)
        refs = [ref for e in evidence for ref in e.result_refs if ref]
        if refs:
            for candidate in (getattr(result, "candidates", None) or []):
                if hasattr(candidate, "evidence_refs"):
                    candidate.evidence_refs.extend(refs)
    gate = evaluate_ground_gate(result)
    ref = _persist_artifact(state, "ground", "GroundingResult", result)
    return {
        "ground_gate": _dump(gate),
        "upstream_gates": _accumulate_gate(state.get("upstream_gates"), _dump(gate)),
        "artifact_refs": {"grounding_result": ref} if ref else {},
        **retry_patch,
    }


# ── SELECT ─────────────────────────────────────────────────────────────


async def select_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """SELECT node: GroundingResult + intent + context -> SiteSelectionDecision."""
    from app.agent.execute.plan_builder import build_execution_plan
    from app.agent.select.aggregate import select_aggregate
    from app.agent.select.gate import evaluate_select_gate
    from app.modules.schema.contracts.grounding_contracts import GroundingResult
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult

    retry_patch = _retry_patch(state, "select")
    context = _get_cached_context(state)
    grounding = _load_ref_artifact(state, "grounding_result", GroundingResult)
    intent = _load_ref_artifact(state, "intent_compilation", IntentCompilationResult)
    plan_intent = _to_typed(getattr(intent, "typed_intent", None) or intent, SpatialPlanningIntent)
    decision, briefs = select_aggregate(grounding, plan_intent, context)
    intent.typed_intent = plan_intent
    projects = list(getattr(plan_intent, "project_targets", None) or [])
    gate = evaluate_select_gate(decision, target_count=len(projects))
    execution_plan = build_execution_plan(
        intent,
        decision,
        briefs,
        run_id=_run_id(state),
        context_version=_context_version(state),
    )
    ref = _persist_artifact(state, "select", "SiteSelectionDecision", decision)
    plan_ref = _persist_artifact(state, "select", "ExecutionPlan", execution_plan)
    return {
        "land_design_briefs": _dump_list(briefs),
        "select_gate": _dump(gate),
        "upstream_gates": _accumulate_gate(state.get("upstream_gates"), _dump(gate)),
        "artifact_refs": {"site_selection": ref, "execution_plan": plan_ref},
        **retry_patch,
    }


# ── EXECUTE ────────────────────────────────────────────────────────────


async def execute_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """EXECUTE node: run the EXECUTE subgraph -> planned state + changeset."""
    from app.services.runtime import PlanningRuntimeService
    from app.agent.execute.execute_state import ExecuteAgentState
    from app.agent.execute.planned_state_builder import changeset_to_planned_state
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision
    from app.modules.schema.contracts.execution_plan_contracts import ExecutionPlan

    context = _get_cached_context(state)
    intent = _load_ref_artifact(state, "intent_compilation", IntentCompilationResult)
    plan_intent = _to_typed(getattr(intent, "typed_intent", None) or intent, SpatialPlanningIntent)
    site_selection = _load_ref_artifact(state, "site_selection", SiteSelectionDecision)
    execution_plan = _load_ref_artifact(state, "execution_plan", ExecutionPlan)
    if execution_plan is None and intent is not None and site_selection is not None:
        from app.agent.execute.plan_builder import build_execution_plan

        execution_plan = build_execution_plan(
            intent,
            site_selection,
            state.get("land_design_briefs") or [],
            run_id=_run_id(state),
            context_version=_context_version(state),
        )
    bundle = getattr(context, "bundle", None)
    gis_data = bundle.to_geojson_dict() if bundle is not None and hasattr(bundle, "to_geojson_dict") else {}

    exec_state = ExecuteAgentState(
        session_id=state.get("session_id", ""),
        village_name=state.get("config", {}).get("village_name", ""),
        gis_data=gis_data,
        gis_bundle=bundle,
        intent=plan_intent,
        facility_anchors=getattr(context, "village_anchors", None),
        site_selection=site_selection,
        land_design_briefs=list(state.get("land_design_briefs") or []),
        execution_plan=execution_plan,
        kg_session_ref=getattr(context, "kg_session_ref", "") or "",
        messages=list(state.get("messages") or []),
    )

    graph = PlanningRuntimeService._execute_subgraph
    if graph is None:
        await PlanningRuntimeService.ensure_initialized()
        graph = PlanningRuntimeService._execute_subgraph
    kg_obj = getattr(context, "kg", None)
    if kg_obj is not None and plan_intent is not None:
        try:
            from app.modules.kg.builder.layer3 import build_intent_layer

            build_intent_layer(kg_obj, plan_intent)
        except Exception as e:
            logger.warning("[post_l3:main:execute] build_intent_layer failed: %s", e)
    result = await graph.ainvoke(
        exec_state,
        config={"configurable": {"thread_id": state.get("session_id", "")}},
    )

    changeset = result.get("parcel_changeset")
    if changeset is not None:
        planned_state = changeset_to_planned_state(changeset, plan_intent)
    else:
        logger.warning("[post_l3:main:execute] no parcel_changeset produced")
        planned_state = None

    refs = {
        "parcel_changeset": _persist_artifact(state, "execute", "ParcelChangeSet", changeset),
        "planned_state": _persist_artifact(state, "execute", "PlannedState", planned_state),
        "allocated_geojson": _persist_artifact(
            state, "execute", "AllocatedGeoJSON", result.get("allocated_geojson", {}) or {}
        ),
    }
    return {
        "layout_configs": _jsonable(list(result.get("layout_configs", []) or [])),
        "execution_errors": _jsonable(list(result.get("execution_errors", []) or [])),
        "artifact_refs": refs,
    }


# ── VALIDATE ───────────────────────────────────────────────────────────


async def validate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """VALIDATE node: run validate_aggregate + gate."""
    from app.agent.validate.aggregate import validate_aggregate
    from app.agent.validate.gate import evaluate_validate_gate
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent
    from app.modules.schema.contracts.planned_state_contracts import PlannedState
    from app.modules.schema.contracts.parcel_change_contracts import ParcelChangeSet
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult

    retry_patch = _retry_patch(state, "validate")
    context = _get_cached_context(state)
    constraint_index = getattr(context, "constraint_index", None)
    planned_state = _load_ref_artifact(state, "planned_state", PlannedState)
    changeset = _load_ref_artifact(state, "parcel_changeset", ParcelChangeSet)
    intent = _load_ref_artifact(state, "intent_compilation", IntentCompilationResult)
    plan_intent = _to_typed(getattr(intent, "typed_intent", None) or intent, SpatialPlanningIntent)
    report = validate_aggregate(
        planned_state,
        changeset,
        state.get("layout_configs"),
        plan_intent,
        constraint_index,
        run_id=_run_id(state),
    )
    gate = evaluate_validate_gate(report)
    ref = _persist_artifact(state, "validate", "ValidationReport", report)
    return {
        "validate_gate": _dump(gate),
        "upstream_gates": _accumulate_gate(state.get("upstream_gates"), _dump(gate)),
        "artifact_refs": {"validation_report": ref} if ref else {},
        **retry_patch,
    }


# ── RECONCILE ──────────────────────────────────────────────────────────


async def reconcile_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """RECONCILE node: run reconcile_aggregate + gate."""
    from app.agent.reconcile.aggregate import reconcile_aggregate
    from app.agent.reconcile.gate import evaluate_reconcile_gate
    from app.modules.schema.contracts.l3_contracts import PlanningProgram
    from app.modules.schema.contracts.spatial_reference_contracts import SpatialReferenceSpec
    from app.modules.schema.contracts.grounding_contracts import GroundingResult
    from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision
    from app.modules.schema.contracts.parcel_change_contracts import ParcelChangeSet
    from app.modules.schema.contracts.planned_state_contracts import PlannedState
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult

    retry_patch = _retry_patch(state, "reconcile")
    context = _get_cached_context(state)
    program = _load_planning_program(state)
    if program is None:
        from app.modules.schema.contracts.reconciliation_contracts import (
            ReconciliationInconsistency,
            ReconciliationReport,
        )
        report = ReconciliationReport(
            inconsistencies=[
                ReconciliationInconsistency(
                    intervention_id="__missing_program__",
                    field="planning_program",
                    expected="non-null PlanningProgram",
                    actual="None",
                    severity="error",
                    responsible_stage="L3",
                )
            ],
        )
        gate = evaluate_reconcile_gate(report)
        ref = _persist_artifact(state, "reconcile", "ReconciliationReport", report)
        return {
            "reconcile_gate": _dump(gate),
            "upstream_gates": _accumulate_gate(state.get("upstream_gates"), _dump(gate)),
            "artifact_refs": {"reconciliation_report": ref} if ref else {},
            **retry_patch,
        }
    specs = [_to_typed(s, SpatialReferenceSpec) for s in (state.get("specs") or [])]
    grounding = _load_ref_artifact(state, "grounding_result", GroundingResult)
    decision = _load_ref_artifact(state, "site_selection", SiteSelectionDecision)
    changeset = _load_ref_artifact(state, "parcel_changeset", ParcelChangeSet)
    planned_state = _load_ref_artifact(state, "planned_state", PlannedState)
    intent = _load_ref_artifact(state, "intent_compilation", IntentCompilationResult)
    report = reconcile_aggregate(
        program,
        specs,
        grounding,
        decision,
        changeset,
        planned_state,
        intent,
        run_id=_run_id(state),
    )
    gate = evaluate_reconcile_gate(report)
    ref = _persist_artifact(state, "reconcile", "ReconciliationReport", report)
    return {
        "reconcile_gate": _dump(gate),
        "upstream_gates": _accumulate_gate(state.get("upstream_gates"), _dump(gate)),
        "artifact_refs": {"reconciliation_report": ref} if ref else {},
        **retry_patch,
    }


# ── DELIVER ────────────────────────────────────────────────────────────


async def deliver_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """DELIVER node: export + deliver_aggregate + gate + render layers."""
    from app.agent.deliver.aggregate import deliver_aggregate
    from app.agent.deliver.gate import evaluate_deliver_gate
    from app.modules.spatial_ops.output.export_package import export_gdb_package
    from app.modules.schema.contracts.planned_state_contracts import PlannedState
    from app.modules.schema.contracts.validation_report_contracts import ValidationReport
    from app.modules.schema.contracts.reconciliation_contracts import ReconciliationReport

    retry_patch = _retry_patch(state, "deliver")
    context = _get_cached_context(state)
    bundle = getattr(context, "bundle", None)
    gis_data = bundle.to_geojson_dict() if bundle is not None and hasattr(bundle, "to_geojson_dict") else {}
    planned_state = _load_ref_artifact(state, "planned_state", PlannedState)
    validation_report = _load_ref_artifact(state, "validation_report", ValidationReport)
    reconciliation_report = _load_ref_artifact(state, "reconciliation_report", ReconciliationReport)
    allocated_geojson = _load_ref_artifact(state, "allocated_geojson", dict) or {}

    validation_result = {}
    if validation_report is not None:
        validation_result = {"passed": validation_report.overall_passed}

    export_result = None
    if planned_state is not None and state.get("layout_configs"):
        try:
            export_result = export_gdb_package(
                layout_configs=state.get("layout_configs"),
                allocated_geojson=allocated_geojson or None,
                gis_data=gis_data,
                village_name=state.get("config", {}).get("village_name", ""),
                session_id=state.get("session_id", ""),
                validation_result=validation_result,
            )
        except Exception as e:
            logger.warning("[post_l3:main:deliver] export failed: %s", e)
            export_result = None

    current_parcels = []
    if bundle is not None and hasattr(bundle, "bundle_parcels"):
        current_parcels = list(bundle.bundle_parcels())
    elif bundle is not None and hasattr(bundle, "polygons"):
        current_parcels = list(bundle.polygons.get("landuse_current") or [])

    manifest = deliver_aggregate(
        planned_state,
        validation_report,
        reconciliation_report,
        list(state.get("upstream_gates") or []),
        export_result,
        current_parcels=current_parcels,
        run_id=_run_id(state),
    )
    gate = evaluate_deliver_gate(manifest)
    manifest_ref = _persist_artifact(state, "deliver", "DeliveryManifest", manifest)

    render_result = []
    try:
        from app.agent.deliver.render_layers import build_render_layers

        render_result = build_render_layers(
            planned_state,
            list(state.get("layout_configs") or []),
            gis_data,
        )
    except Exception as e:
        logger.warning("[post_l3:main:deliver] render_layers failed: %s", e)
        render_result = []

    render_ref = _persist_artifact(state, "deliver", "RenderLayers", render_result)

    return {
        "artifact_refs": {
            key: ref for key, ref in {
                "delivery_manifest": manifest_ref,
                "render_layers": render_ref,
            }.items() if ref
        },
        "deliver_gate": _dump(gate),
        "export_result": export_result,
        "upstream_gates": _accumulate_gate(state.get("upstream_gates"), _dump(gate)),
        **retry_patch,
    }


# Keep stage audit behavior at the graph boundary so every real session
# records the same input/output contract without duplicating persistence code.
from app.agent.bootstrap.stage_audit import audited_stage

parse_node = audited_stage("PARSE")(parse_node)
ground_node = audited_stage("GROUND")(ground_node)
select_node = audited_stage("SELECT")(select_node)
execute_node = audited_stage("EXECUTE")(execute_node)
validate_node = audited_stage("VALIDATE")(validate_node)
reconcile_node = audited_stage("RECONCILE")(reconcile_node)
deliver_node = audited_stage("DELIVER")(deliver_node)

# ── HUMAN REVIEW ───────────────────────────────────────────────────────


def _collect_human_items(state: Dict[str, Any]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Extract pending_requests from the most recent HUMAN gate decision.

    Returns (stage, items); stage is None when no gate routed HUMAN.
    """
    items: List[Dict[str, Any]] = []
    for gate_attr in _GATE_CHANNELS:
        gate = state.get(gate_attr)
        if gate is None:
            continue
        route = getattr(gate, "feedback_route", None)
        if route is None and isinstance(gate, dict):
            route = gate.get("feedback_route")
        if route != "HUMAN":
            continue
        pending = getattr(gate, "pending_requests", None)
        if pending is None and isinstance(gate, dict):
            pending = gate.get("pending_requests")
        pending = pending or []
        for pr in pending:
            if hasattr(pr, "model_dump"):
                items.append(pr.model_dump())
            elif isinstance(pr, dict):
                items.append(pr)
        return gate_attr.replace("_gate", ""), items
    return None, items


def _retry_exhaustion_items(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Synthetic review items when retries were exhausted without a HUMAN gate."""
    if not state.get("error_feedback"):
        return []
    return [
        {
            "request_id": "post-l3-retry-exhausted",
            "stage": "post_l3",
            "request_type": "retry_exhausted",
            "context": {
                "message": "post-L3 retries exhausted; manual intervention required",
                "detail": dict(state.get("error_feedback") or {}),
                "retry_counts": dict(state.get("retry_counts") or {}),
                "max_retries": state.get("max_retries", 3),
            },
        }
    ]


def collect_human_review_items(state: Dict[str, Any]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Public helper: return (stage, human-review items) for the current state.

    Falls back to synthetic retry-exhaustion items when no gate routed HUMAN.
    """
    stage, items = _collect_human_items(state)
    if stage is not None:
        return stage, items
    return None, _retry_exhaustion_items(state)


__all__ = [
    "parse_node", "ground_node", "select_node", "execute_node",
    "validate_node", "reconcile_node", "deliver_node",
    "collect_human_review_items",
    "_gate_route", "_retry_patch", "_pass_gate",
    "_STAGE_FORWARD_TARGET", "_GATE_CHANNELS",
]
