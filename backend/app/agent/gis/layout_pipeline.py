"""LAYOUT hybrid pipeline — deterministic skeleton + ReAct adaptive loop.

Architecture:
  Deterministic skeleton guarantees step ordering (KG before ALLOCATE, VALIDATE must run).
  ReAct subgraph in allocate_and_generate node gives LLM adaptive decision-making.
  Worker-Evaluator pattern: validate_layout as evaluator gate with retry loop (max 3 rounds).

References:
  [1] LangGraph Plan-and-Execute: deterministic skeleton + LLM planning
  [2] Worker-Evaluator: validate → retry with feedback injection
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from typing_extensions import Annotated

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages

from app.utils.logger import get_logger

logger = get_logger(__name__)


class LayoutPipelineState(dict):
    """State for the LAYOUT hybrid pipeline (StateGraph).

    Uses plain dict subclass for LangGraph compatibility.
    """

    # Identity
    session_id: str
    village_name: str

    # Input
    gis_data: Dict[str, Optional[Dict[str, Any]]]
    intent: Dict[str, Any]

    # KG stage
    kg_turtle: str
    kg_constraints: List[Dict[str, Any]]

    # Allocate + Generate stage
    allocated_geojson: Dict[str, Any]
    allocation_summary: Dict[str, Any]
    layout_configs: List[Dict[str, Any]]

    # Validate stage
    validation_result: Dict[str, Any]
    validation_round: int

    # Export stage
    export_result: Dict[str, Any]

    # Render stage
    render_result: List[Dict[str, Any]]

    # Agent messages (accumulated across ReAct subgraph calls)
    messages: List[BaseMessage]


# ── Deterministic nodes ──────────────────────────────────────────────


async def _build_kg_node(state: dict) -> dict:
    """Build knowledge graph from reports and GIS data."""
    from app.tools.gis.kg import build_knowledge_graph

    gis_data = state.get("gis_data", {})
    village_name = state.get("village_name", "")

    result = await build_knowledge_graph.ainvoke({})
    kg_turtle = result.get("kg_turtle", "") if isinstance(result, dict) else ""
    kg_constraints = result.get("constraints", []) if isinstance(result, dict) else []

    logger.info(
        "[Pipeline:build_kg] KG built: %d triples, %d constraints",
        len(kg_turtle.split("\n")) if kg_turtle else 0,
        len(kg_constraints),
    )

    return {
        "kg_turtle": kg_turtle,
        "kg_constraints": kg_constraints,
    }


async def _detect_conflicts_node(state: dict) -> dict:
    """Detect cross-dimension conflicts."""
    from app.tools.gis.conflict import detect_conflicts

    result = await detect_conflicts.ainvoke({})

    conflict_count = 0
    if isinstance(result, dict):
        report = result.get("report", result)
        conflict_count = report.get("total_count", 0) if isinstance(report, dict) else 0

    logger.info("[Pipeline:detect_conflicts] %d conflicts detected", conflict_count)
    return {}


async def _validate_layout_node(state: dict) -> dict:
    """Evaluator gate: validate layout, decide retry or pass."""
    from app.tools.gis.validate import validate_layout

    layout_configs = state.get("layout_configs", [])
    kg_constraints = state.get("kg_constraints", [])

    result = await validate_layout.ainvoke({})

    passed = False
    violations = []
    if isinstance(result, dict):
        passed = result.get("is_valid", result.get("passed", False))
        violations = result.get("violations", [])

    round_num = state.get("validation_round", 0) + 1

    logger.info(
        "[Pipeline:validate] Round %d: %s (%d violations)",
        round_num,
        "PASS" if passed else "FAIL",
        len(violations),
    )

    return {
        "validation_result": {
            "passed": passed,
            "violations": violations if not passed else [],
        },
        "validation_round": round_num,
    }


async def _export_gdb_node(state: dict) -> dict:
    """Export 12-layer GeoJSON package + land balance table."""
    from app.tools.gis.export import export_gdb

    result = await export_gdb.ainvoke({})

    logger.info("[Pipeline:export_gdb] Export complete")
    return {"export_result": result if isinstance(result, dict) else {}}


async def _render_map_node(state: dict) -> dict:
    """Render map layers for frontend MapLibre."""
    from app.tools.gis.render import render_map

    result = await render_map.ainvoke({})

    logger.info("[Pipeline:render_map] Render complete")
    return {"render_result": result if isinstance(result, dict) else {}}


# ── ReAct subgraph node ──────────────────────────────────────────────


async def _allocate_generate_react_node(state: dict) -> dict:
    """ReAct subgraph: LLM adaptively decides allocation strategy and layout params.

    Within the deterministic skeleton, this node gives LLM flexibility:
    - LLM queries KG constraints then decides allocation targets
    - LLM can adjust strategy based on validation feedback from prior rounds
    - But cannot skip KG or skip VALIDATE (skeleton guarantees)
    """
    from .agent import create_layout_agent_graph

    # Build validation feedback (if retrying)
    validation_feedback = ""
    validation_result = state.get("validation_result", {})
    if validation_result and not validation_result.get("passed", True):
        violations = validation_result.get("violations", [])
        violation_summary = str(violations[:3]) if violations else "unknown"
        validation_feedback = (
            f"上轮验证发现 {len(violations)} 个违规，请调整分配策略。"
            f"违规详情：{violation_summary}"
        )

    # Inject feedback into messages
    messages = list(state.get("messages", []))
    if validation_feedback:
        messages.append(HumanMessage(content=validation_feedback))

    # Call ReAct subgraph (LLM decides strategy)
    layout_agent = create_layout_agent_graph()
    result = await layout_agent.ainvoke({
        "session_id": state.get("session_id", ""),
        "village_name": state.get("village_name", ""),
        "gis_data": state.get("gis_data", {}),
        "intent": state.get("intent", {}),
        "kg_turtle": state.get("kg_turtle", ""),
        "kg_constraints": state.get("kg_constraints", []),
        "layout_configs": state.get("layout_configs", []),
        "allocated_geojson": state.get("allocated_geojson", {}),
        "allocation_summary": state.get("allocation_summary", {}),
        "messages": messages,
    })

    return {
        "allocated_geojson": result.get("allocated_geojson", {}),
        "allocation_summary": result.get("allocation_summary", {}),
        "layout_configs": result.get("layout_configs", []),
        "messages": result.get("messages", []),
    }


# ── Conditional routing ──────────────────────────────────────────────


def _route_after_validation(state: dict) -> str:
    """Route after validation: pass→export, fail→retry (max 3 rounds)."""
    result = state.get("validation_result", {})
    round_num = state.get("validation_round", 0)

    if result.get("passed", False):
        return "pass"
    if round_num >= 3:
        logger.warning(
            "[Pipeline] 验证 %d 轮未通过，使用当前最佳结果",
            round_num,
        )
        return "pass"
    return "retry"


# ── Pipeline builder ─────────────────────────────────────────────────


def build_layout_pipeline():
    """Build the LAYOUT hybrid pipeline: deterministic skeleton + ReAct adaptive loop.

    Deterministic skeleton guarantees step completeness
    (KG must run before ALLOCATE, VALIDATE must execute).
    ReAct subgraph in allocate_and_generate provides LLM adaptive capability.
    Worker-Evaluator pattern in validate_layout implements constraint feedback retry.
    """
    graph = StateGraph(LayoutPipelineState)

    # ── Deterministic nodes (direct service calls) ──
    graph.add_node("build_kg", _build_kg_node)
    graph.add_node("detect_conflicts", _detect_conflicts_node)

    # ── Adaptive node (ReAct subgraph, LLM decides strategy) ──
    graph.add_node("allocate_and_generate", _allocate_generate_react_node)

    # ── Evaluator gate (deterministic + conditional routing) ──
    graph.add_node("validate_layout", _validate_layout_node)

    # ── Deterministic post-processing ──
    graph.add_node("export_gdb", _export_gdb_node)
    graph.add_node("render_map", _render_map_node)

    # ── Deterministic edges (skeleton) ──
    graph.add_edge(START, "build_kg")
    graph.add_edge("build_kg", "detect_conflicts")
    graph.add_edge("detect_conflicts", "allocate_and_generate")
    graph.add_edge("allocate_and_generate", "validate_layout")

    # ── Conditional edges: Worker-Evaluator retry loop ──
    graph.add_conditional_edges(
        "validate_layout",
        _route_after_validation,
        {
            "retry": "allocate_and_generate",
            "pass": "export_gdb",
        },
    )

    graph.add_edge("export_gdb", "render_map")
    graph.add_edge("render_map", END)

    compiled = graph.compile()
    logger.info("[Pipeline] LAYOUT hybrid pipeline compiled: 6 nodes, 1 conditional edge")
    return compiled


__all__ = ["build_layout_pipeline", "LayoutPipelineState"]
