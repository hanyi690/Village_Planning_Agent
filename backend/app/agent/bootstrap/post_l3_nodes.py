"""Post-L3 chain node functions.

Wave M1: each node wraps a Wave B-L subgraph aggregate and the corresponding
gate evaluator, reading inputs from PostL3ChainState and writing typed
artifacts back. Deterministic (the aggregates are deterministic); no LLM in
this module.
"""

from __future__ import annotations

from typing import Any

from app.agent.ground.aggregate import ground_aggregate
from app.agent.ground.gate import evaluate_ground_gate
from app.agent.parse.aggregate import compile_program
from app.agent.parse.gate_node import evaluate_parse_gate
from app.agent.select_graph.aggregate import select_aggregate
from app.agent.select_graph.gate import evaluate_select_gate
from app.utils.logger import get_logger

from .post_l3_state import PostL3ChainState

logger = get_logger(__name__)


def _accumulate_gate(gates: list[Any], gate: Any) -> list[Any]:
    return list(gates or []) + ([gate] if gate is not None else [])


async def parse_node(state: PostL3ChainState) -> dict[str, Any]:
    """PARSE node: compile PlanningProgram -> IntentCompilationResult + specs."""
    program = state.planning_program
    if program is None:
        logger.warning("[post_l3:parse] no planning_program in state; empty compile")
    run_id = state.run_id or state.session_id
    result, specs, gate = compile_program(
        program,
        run_id=run_id,
        context_version=state.context_version,
    )
    return {
        "intent": result,
        "specs": specs,
        "parse_gate": gate,
        "upstream_gates": _accumulate_gate(state.upstream_gates, gate),
    }


async def ground_node(state: PostL3ChainState) -> dict[str, Any]:
    """GROUND node: specs + context -> GroundingResult + gate."""
    context = state.context
    result = ground_aggregate(list(state.specs or []), context)
    gate = evaluate_ground_gate(result)
    return {
        "grounding_result": result,
        "ground_gate": gate,
        "upstream_gates": _accumulate_gate(state.upstream_gates, gate),
    }


async def select_node(state: PostL3ChainState) -> dict[str, Any]:
    """SELECT node: GroundingResult + intent + context -> SiteSelectionDecision."""
    context = state.context
    decision, briefs = select_aggregate(
        state.grounding_result, state.intent, context
    )
    projects = list(getattr(state.intent, "project_targets", None) or [])
    gate = evaluate_select_gate(decision, target_count=len(projects))
    return {
        "site_selection": decision,
        "land_design_briefs": briefs,
        "select_gate": gate,
        "upstream_gates": _accumulate_gate(state.upstream_gates, gate),
    }


async def execute_node(state: PostL3ChainState) -> dict[str, Any]:
    """EXECUTE node: run the EXECUTE subgraph -> planned state + changeset."""
    from app.agent.execute.execute_agent import build_execute_agent_graph
    from app.agent.execute.execute_state import ExecuteAgentState
    from app.agent.execute.planned_state_builder import changeset_to_planned_state

    context = state.context
    intent = state.intent
    bundle = getattr(context, "bundle", None)
    gis_data = bundle.to_geojson_dict() if bundle is not None and hasattr(bundle, "to_geojson_dict") else {}

    exec_state = ExecuteAgentState(
        session_id=state.session_id,
        village_name=state.village_name,
        gis_data=gis_data,
        gis_bundle=bundle,
        intent=intent,
        facility_anchors=getattr(context, "village_anchors", None),
        site_selection=state.site_selection,
        land_design_briefs=list(state.land_design_briefs or []),
        kg_session_ref=getattr(context, "kg_session_ref", "") or "",
        messages=list(state.messages),
    )

    graph = build_execute_agent_graph()
    exec_dict = exec_state.model_dump()
    exec_dict["gis_bundle"] = bundle
    exec_dict["intent"] = intent
    exec_dict["site_selection"] = state.site_selection
    result = await graph.ainvoke(exec_dict)

    changeset = result.get("parcel_changeset")
    if changeset is not None:
        planned_state = changeset_to_planned_state(changeset, intent)
    else:
        logger.warning("[post_l3:execute] no parcel_changeset produced")
        planned_state = None

    return {
        "planned_state": planned_state,
        "parcel_changeset": changeset,
        "layout_configs": list(result.get("layout_configs", []) or []),
        "allocated_geojson": result.get("allocated_geojson", {}) or {},
        "execution_errors": list(result.get("execution_errors", []) or []),
    }


async def validate_node(state: PostL3ChainState) -> dict[str, Any]:
    """VALIDATE node: run validate_aggregate + gate."""
    from app.agent.validate.aggregate import validate_aggregate
    from app.agent.validate.gate import evaluate_validate_gate

    context = state.context
    constraint_index = getattr(context, "constraint_index", None)
    report = validate_aggregate(
        state.planned_state,
        state.parcel_changeset,
        state.layout_configs,
        state.intent,
        constraint_index,
        run_id=state.run_id or state.session_id,
    )
    gate = evaluate_validate_gate(report)
    return {
        "validation_report": report,
        "validate_gate": gate,
        "upstream_gates": _accumulate_gate(state.upstream_gates, gate),
    }


async def reconcile_node(state: PostL3ChainState) -> dict[str, Any]:
    """RECONCILE node: run reconcile_aggregate + gate."""
    from app.agent.reconcile.aggregate import reconcile_aggregate
    from app.agent.reconcile.gate import evaluate_reconcile_gate

    report = reconcile_aggregate(
        state.planning_program,
        list(state.specs or []),
        state.grounding_result,
        state.site_selection,
        state.parcel_changeset,
        state.planned_state,
        state.intent,
        run_id=state.run_id or state.session_id,
    )
    gate = evaluate_reconcile_gate(report)
    return {
        "reconciliation_report": report,
        "reconcile_gate": gate,
        "upstream_gates": _accumulate_gate(state.upstream_gates, gate),
    }


async def deliver_node(state: PostL3ChainState) -> dict[str, Any]:
    """DELIVER node: export + deliver_aggregate + gate."""
    from app.agent.deliver.aggregate import deliver_aggregate
    from app.agent.deliver.gate import evaluate_deliver_gate
    from app.modules.spatial_ops.export_package import export_gdb_package

    context = state.context
    bundle = getattr(context, "bundle", None)
    gis_data = bundle.to_geojson_dict() if bundle is not None and hasattr(bundle, "to_geojson_dict") else {}

    validation_result = {}
    if state.validation_report is not None:
        validation_result = {
            "passed": state.validation_report.overall_passed,
        }

    export_result = None
    if state.planned_state is not None and state.layout_configs:
        try:
            export_result = export_gdb_package(
                layout_configs=state.layout_configs,
                allocated_geojson=state.allocated_geojson or None,
                gis_data=gis_data,
                village_name=state.village_name,
                session_id=state.session_id,
                validation_result=validation_result,
            )
        except Exception as e:
            logger.warning("[post_l3:deliver] export failed: %s", e)
            export_result = None

    current_parcels = []
    if bundle is not None and hasattr(bundle, "bundle_parcels"):
        current_parcels = list(bundle.bundle_parcels())
    elif bundle is not None and hasattr(bundle, "polygons"):
        current_parcels = list(bundle.polygons.get("landuse_current") or [])

    manifest = deliver_aggregate(
        state.planned_state,
        state.validation_report,
        state.reconciliation_report,
        list(state.upstream_gates or []),
        export_result,
        current_parcels=current_parcels,
        run_id=state.run_id or state.session_id,
    )
    gate = evaluate_deliver_gate(manifest)
    return {
        "delivery_manifest": manifest,
        "deliver_gate": gate,
        "export_result": export_result,
        "upstream_gates": _accumulate_gate(state.upstream_gates, gate),
    }


__all__ = [
    "parse_node",
    "ground_node",
    "select_node",
    "execute_node",
    "validate_node",
    "reconcile_node",
    "deliver_node",
]
