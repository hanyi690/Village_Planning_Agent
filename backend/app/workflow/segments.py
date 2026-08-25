"""A5: four-segment subgraph decomposition of the unified planning graph.

The flat ~25-node ``StateGraph(WorkflowState)`` is split into four compiled
subgraphs that share the full ``WorkflowState`` schema:

- ``intent_loop``   : conversation / execute_tools (意图环)
- ``cognitive``     : L1/L2/L3 workers + completion barrier + aggregate +
                      advance/revision/provider dispatch (认知层 map-reduce)
- ``spatial_chain`` : target_projection -> ... -> deliver (空间链, gate 驱动)
- ``hitl``          : human_review_prepare/publish/wait/apply (HITL)

The parent graph keeps only ``bootstrap_context``, the four segment nodes,
and ``end_diagnostic``.  All cross-segment jumps are emitted by router nodes
inside a segment as ``Command(graph=Command.PARENT, goto=<segment>, update=
{subgraph_entry: ...})``; the target segment's START entry router dispatches
to the right internal node.  Parallel dimension fan-out from the intent loop
rides a transient ``pending_dispatches`` channel so the cognitive map-reduce
(parallel workers -> one deferred completion barrier) stays inside one
subgraph invocation.

Verified LangGraph primitives (tests/contracts/test_langgraph_primitives.py):
compiled-subgraph-as-node, interrupt-in-subgraph + parent Command(resume=),
Command(PARENT) cross jumps, Command(PARENT, goto=[Send(sub, arg)...]).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send

# ── segment membership ──────────────────────────────────────────────────

_INTENT_INTERNAL = frozenset({"conversation", "execute_tools"})
_COGNITIVE_INTERNAL = frozenset({
    "l1_worker",
    "l2_worker",
    "l3_worker",
    "layer_completion_check",
    "layer_aggregate",
    "advance_phase",
    "revision_dispatch",
    "provider_resume_dispatch",
})
_SPATIAL_INTERNAL = frozenset({
    "target_projection",
    "ground",
    "select",
    "execute",
    "validate",
    "reconcile",
    "deliver",
})
_HITL_INTERNAL = frozenset({
    "human_review_prepare",
    "human_review_publish",
    "human_review_wait",
    "human_review_apply",
})

# Entry points the cognitive segment can be resumed at (set via
# ``subgraph_entry`` by the HITL / spatial router nodes).
_COGNITIVE_ENTRY_NODES = frozenset({
    "advance_phase",
    "revision_dispatch",
    "provider_resume_dispatch",
    "l1_worker",
    "l2_worker",
    "l3_worker",
})

# ── cross-segment maps: route target -> (parent node, subgraph_entry hint) ──

_INTENT_CROSS = {
    "target_projection": ("spatial_chain", None),
}

_COGNITIVE_CROSS = {
    "target_projection": ("spatial_chain", None),
    "conversation": ("intent_loop", None),
    "human_review": ("hitl", None),
}

_SPATIAL_CROSS = {
    "human_review": ("hitl", None),
    "revision_dispatch": ("cognitive", "revision_dispatch"),
}

_HITL_CROSS = {
    "conversation": ("intent_loop", None),
    "advance_phase": ("cognitive", "advance_phase"),
    "revision_dispatch": ("cognitive", "revision_dispatch"),
    "provider_resume_dispatch": ("cognitive", "provider_resume_dispatch"),
    "l1_worker": ("cognitive", "l1_worker"),
    "l2_worker": ("cognitive", "l2_worker"),
    "l3_worker": ("cognitive", "l3_worker"),
    "target_projection": ("spatial_chain", None),
    "ground": ("spatial_chain", "ground"),
    "select": ("spatial_chain", "select"),
    "execute": ("spatial_chain", "execute"),
    "validate": ("spatial_chain", "validate"),
    "reconcile": ("spatial_chain", "reconcile"),
    "deliver": ("spatial_chain", "deliver"),
}

# ── small helpers ────────────────────────────────────────────────────────


def _path_map(*targets: str, aliases: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Build a conditional-edge path map carrying the END_DIAGNOSTIC sentinel.

    ``aliases`` may remap the sentinel to a segment-local escape node
    (e.g. ``{"end_diagnostic": "diag_exit"}``) for audited internal edges.
    """
    mapping = {target: target for target in targets}
    mapping["end_diagnostic"] = "end_diagnostic"
    mapping.update(dict(aliases or {}))
    return mapping


def _diag_exit(state: Dict[str, Any]) -> Command:
    """Escape hatch: an audited fixed edge inside a segment was denied."""
    return Command(graph=Command.PARENT, goto="end_diagnostic")


def _map_route_result(
    result: Any,
    *,
    source_segment: str,
    internal_nodes: frozenset[str],
    cross_map: Dict[str, tuple[str, str | None]],
) -> Command:
    """Convert an authorized route result into a Command for this segment."""
    if isinstance(result, str):
        if result == END:
            return Command(graph=Command.PARENT, goto=END)
        if result in internal_nodes:
            return Command(goto=result)
        if result == "end_diagnostic":
            return Command(graph=Command.PARENT, goto="end_diagnostic")
        if result in cross_map:
            segment, entry = cross_map[result]
            return Command(
                graph=Command.PARENT,
                update={"subgraph_entry": entry},
                goto=segment,
            )
        raise ValueError(
            f"route target {result!r} is neither internal nor cross for {source_segment}"
        )
    if isinstance(result, list):
        if source_segment == "intent_loop":
            # Workers live in the cognitive segment; keep the map-reduce in a
            # single cognitive invocation by parking the payloads.
            return Command(
                graph=Command.PARENT,
                update={"pending_dispatches": [item.arg for item in result]},
                goto="cognitive",
            )
        if source_segment == "cognitive":
            return Command(goto=[Send(item.node, item.arg) for item in result])
        raise ValueError(f"Send fan-out is not supported from {source_segment}")
    raise ValueError(f"unrecognized route result: {result!r}")


def _make_router(
    source_stage: str,
    route_fn: Callable[[Dict[str, Any]], Any],
    *,
    source_segment: str,
    internal_nodes: frozenset[str],
    cross_map: Dict[str, tuple[str, str | None]],
) -> Callable[[Dict[str, Any]], Command]:
    """Build a node that evaluates ``route_fn`` under the dispatch audit and
    emits a Command (internal jump, or Command(PARENT) cross-segment jump)."""

    def router(state: Dict[str, Any]) -> Command:
        from app.workflow.routing import authorize_route_result
        from app.workflow.terminal import diagnostic_terminal, terminal_patch

        result = route_fn(state)
        authorization = authorize_route_result(state, source_stage, result)
        if not authorization.accepted:
            diagnostic = authorization.diagnostic
            update = {}
            if diagnostic is not None:
                update = terminal_patch(diagnostic_terminal(diagnostic))
            return Command(
                update=update,
                graph=Command.PARENT,
                goto="end_diagnostic",
            )
        command = _map_route_result(
            result,
            source_segment=source_segment,
            internal_nodes=internal_nodes,
            cross_map=cross_map,
        )
        if command.graph == Command.PARENT:
            # A compiled subgraph does not reliably expose the final child
            # channel write when it exits through Command(PARENT).  Carry the
            # current immutable refs explicitly so the parent checkpoint keeps
            # DELIVER products (and any earlier stage outputs) after a normal
            # or diagnostic terminal exit.
            update = dict(command.update or {})
            refs = state.get("artifact_refs") or {}
            if refs:
                update["artifact_refs"] = dict(refs)
            return Command(
                graph=command.graph,
                update=update,
                resume=command.resume,
                goto=command.goto,
            )
        return command

    return router


def _remap_command(command: Command, internal_nodes: frozenset[str]) -> Command:
    """Rewrite a Command emitted by a node inside a segment so cross-segment
    targets become Command(PARENT) jumps (used for advance/revision/provider)."""
    if command.graph == Command.PARENT:
        return command
    goto = command.goto
    if isinstance(goto, str):
        if goto in internal_nodes:
            return command
        if goto == END:
            return Command(
                graph=Command.PARENT,
                update=command.update,
                resume=command.resume,
                goto=END,
            )
        if goto == "target_projection":
            return Command(
                graph=Command.PARENT,
                update={**(dict(command.update or {})), "subgraph_entry": None},
                resume=command.resume,
                goto="spatial_chain",
            )
        if goto == "end_diagnostic":
            return Command(
                graph=Command.PARENT,
                update=command.update,
                resume=command.resume,
                goto="end_diagnostic",
            )
    return command


# ── segment builders ─────────────────────────────────────────────────────


def _build_intent_loop(checkpointer) -> StateGraph:
    from app.workflow import root_graph as rg
    from app.workflow.conversation import after_conversation, conversation_node

    builder = StateGraph(rg.WorkflowState)
    builder.add_node("conversation", rg.adapt_node(conversation_node))
    if rg._HAS_RETRY_POLICY:
        builder.add_node(
            "execute_tools",
            rg.adapt_node(rg.execute_tools_node),
            retry_policy=rg._TRANSIENT_RETRY_POLICY,
        )
    else:
        builder.add_node("execute_tools", rg.adapt_node(rg.execute_tools_node))
    builder.add_node(
        "intent_router",
        rg.adapt_node(
            _make_router(
                "conversation",
                after_conversation,
                source_segment="intent_loop",
                internal_nodes=_INTENT_INTERNAL,
                cross_map=_INTENT_CROSS,
            )
        ),
    )
    builder.add_node("diag_exit", rg.adapt_node(_diag_exit))

    builder.add_edge(START, "conversation")
    builder.add_edge("conversation", "intent_router")
    # audited fixed edge: tool execution always returns to conversation
    builder.add_conditional_edges(
        "execute_tools",
        lambda state: rg._dispatch_fixed("execute_tools", "conversation", state),
        _path_map("conversation", aliases={"end_diagnostic": "diag_exit"}),
    )
    return builder.compile(checkpointer=checkpointer)


def _build_cognitive(checkpointer) -> StateGraph:
    from app.workflow import root_graph as rg
    from app.workflow.layers.layer_router import _worker_for_phase
    from app.workflow.plan_state.completion_node import layer_completion_check
    from app.workflow.layers.layer_aggregate_node import layer_aggregate_node
    from app.workflow.conversation import after_analysis

    builder = StateGraph(rg.WorkflowState)

    def cognitive_entry(state: Dict[str, Any]) -> Command:
        pending = list(state.get("pending_dispatches") or [])
        if pending:
            sends = [
                Send(_worker_for_phase(str(item.get("phase") or "layer1")), item)
                for item in pending
            ]
            return Command(
                update={"pending_dispatches": [], "subgraph_entry": None},
                goto=sends,
            )
        entry = state.get("subgraph_entry")
        if entry in _COGNITIVE_ENTRY_NODES:
            return Command(update={"subgraph_entry": None}, goto=entry)
        raise RuntimeError(
            "cognitive segment entered without a dispatch payload or entry hint: "
            f"pending_dispatches={bool(pending)} subgraph_entry={entry!r}"
        )

    builder.add_node("cognitive_entry", rg.adapt_node(cognitive_entry))
    if rg._HAS_RETRY_POLICY:
        # Provider transport failures that escape the audited worker are
        # retried at the LangGraph node boundary.  The retry is scoped to the
        # failed dimension Send task; completed dimensions and checkpoints are
        # not replayed.  Failures converted by the worker into the typed
        # provider_failures channel still use the explicit HUMAN retry path.
        builder.add_node(
            "l1_worker",
            rg.adapt_node(rg.audited_l1_worker, worker=True),
            retry_policy=rg._TRANSIENT_RETRY_POLICY,
        )
        builder.add_node(
            "l2_worker",
            rg.adapt_node(rg.audited_l2_worker, worker=True),
            retry_policy=rg._TRANSIENT_RETRY_POLICY,
        )
        builder.add_node(
            "l3_worker",
            rg.adapt_node(rg.audited_l3_worker, worker=True),
            retry_policy=rg._TRANSIENT_RETRY_POLICY,
        )
    else:
        builder.add_node("l1_worker", rg.adapt_node(rg.audited_l1_worker, worker=True))
        builder.add_node("l2_worker", rg.adapt_node(rg.audited_l2_worker, worker=True))
        builder.add_node("l3_worker", rg.adapt_node(rg.audited_l3_worker, worker=True))
    # ── B1: 为什么 layer_completion_check / layer_aggregate / advance_phase
    # 不能合并成一个节点 ──────────────────────────────────────────────
    # 1. layer_completion_check 是 defer=True 屏障：它必须在所有 Send worker
    #    分支（同一 map super-step）合并后只运行一次，否则多个 completion /
    #    aggregate 任务会残留在同一 checkpoint 里与 post-L3 链竞争。
    # 2. interrupt() 恢复时整节点重跑：completion 的 SSE 事件必须晚于
    #    interrupt 点触发，聚合/推进等副作用必须与 interrupt 分节点，否则
    #    恢复时会重复发出（LangGraph 官方推荐“interrupt 与副作用分节点”）。
    # 3. advance_phase 返回 Command(update=phase, goto=[Send]|END)：条件边
    #    不能返回 Command，Send payload 也不会写回父状态，阶段推进必须由
    #    真实节点完成。
    builder.add_node(
        "layer_completion_check",
        # This is the deferred serial barrier after Send fan-out, not another
        # worker.  Keep the full patch/runtime channel so the following
        # aggregate can checkpoint the completed layer and its gate refs.
        rg.adapt_node(layer_completion_check),
        defer=True,
    )
    # The aggregate is a single serial reducer after the deferred completion
    # barrier.  It is not a Send worker: marking it as worker=True projects
    # only the control view and can leave layer_just_completed/artifact refs
    # stranded in the pre-aggregate checkpoint, preventing the next layer
    # from being scheduled after an interrupt/resume.
    builder.add_node("layer_aggregate", rg.adapt_node(layer_aggregate_node))
    builder.add_node(
        "advance_phase",
        rg.adapt_node(lambda state: _remap_command(rg._authorized_advance_phase(state), _COGNITIVE_INTERNAL)),
    )
    builder.add_node(
        "revision_dispatch",
        rg.adapt_node(lambda state: _remap_command(rg._authorized_revision_dispatch(state), _COGNITIVE_INTERNAL)),
    )
    builder.add_node(
        "provider_resume_dispatch",
        rg.adapt_node(lambda state: _remap_command(rg._authorized_provider_resume_dispatch(state), _COGNITIVE_INTERNAL)),
    )
    builder.add_node(
        "cognitive_router",
        rg.adapt_node(
            _make_router(
                "layer_aggregate",
                after_analysis,
                source_segment="cognitive",
                internal_nodes=_COGNITIVE_INTERNAL,
                cross_map=_COGNITIVE_CROSS,
            )
        ),
    )
    builder.add_node("diag_exit", rg.adapt_node(_diag_exit))

    builder.add_edge(START, "cognitive_entry")
    builder.add_conditional_edges(
        "l1_worker",
        lambda state: rg._dispatch_fixed("l1_worker", "layer_completion_check", state),
        _path_map("layer_completion_check", aliases={"end_diagnostic": "diag_exit"}),
    )
    builder.add_conditional_edges(
        "l2_worker",
        lambda state: rg._dispatch_fixed("l2_worker", "layer_completion_check", state),
        _path_map("layer_completion_check", aliases={"end_diagnostic": "diag_exit"}),
    )
    builder.add_conditional_edges(
        "l3_worker",
        lambda state: rg._dispatch_fixed("l3_worker", "layer_completion_check", state),
        _path_map("layer_completion_check", aliases={"end_diagnostic": "diag_exit"}),
    )
    builder.add_conditional_edges(
        "layer_completion_check",
        lambda state: rg._dispatch_fixed("layer_completion_check", "layer_aggregate", state),
        _path_map("layer_aggregate", aliases={"end_diagnostic": "diag_exit"}),
    )
    builder.add_edge("layer_aggregate", "cognitive_router")
    return builder.compile(checkpointer=checkpointer)


def _build_spatial_chain(checkpointer) -> StateGraph:
    from app.workflow import root_graph as rg

    builder = StateGraph(rg.WorkflowState)

    def spatial_entry(state: Dict[str, Any]) -> Command:
        entry = state.get("subgraph_entry")
        target = entry if entry in _SPATIAL_INTERNAL else "target_projection"
        return Command(update={"subgraph_entry": None}, goto=target)

    builder.add_node("spatial_entry", rg.adapt_node(spatial_entry))
    builder.add_node("target_projection", rg.adapt_node(rg.target_projection_node))
    builder.add_node("ground", rg.adapt_node(rg.ground_node))
    builder.add_node("select", rg.adapt_node(rg.select_node))
    builder.add_node("execute", rg.adapt_node(rg.execute_node))
    builder.add_node("validate", rg.adapt_node(rg.validate_node))
    builder.add_node("reconcile", rg.adapt_node(rg.reconcile_node))
    builder.add_node("deliver", rg.adapt_node(rg.deliver_node))

    _SPATIAL_ROUTERS = {
        "target_projection": ("route_after_target_projection", "target_projection"),
        "ground": ("route_after_ground", "ground"),
        "select": ("route_after_select", "select"),
        "execute": ("route_after_execute", "execute"),
        "validate": ("route_after_validate", "validate"),
        "reconcile": ("route_after_reconcile", "reconcile"),
        "deliver": ("route_after_deliver", "deliver"),
    }
    for stage, (route_name, _stage) in _SPATIAL_ROUTERS.items():
        route_fn = getattr(rg, route_name)
        builder.add_node(
            f"{stage}_router",
            rg.adapt_node(
                _make_router(
                    stage,
                    route_fn,
                    source_segment="spatial_chain",
                    internal_nodes=_SPATIAL_INTERNAL,
                    cross_map=_SPATIAL_CROSS,
                )
            ),
        )
        builder.add_edge(stage, f"{stage}_router")

    builder.add_edge(START, "spatial_entry")
    return builder.compile(checkpointer=checkpointer)


def _build_hitl(checkpointer) -> StateGraph:
    from app.workflow import root_graph as rg

    builder = StateGraph(rg.WorkflowState)
    builder.add_node("human_review_prepare", rg.adapt_node(rg.prepare_human_review))
    builder.add_node("human_review_publish", rg.adapt_node(rg.publish_human_review_pause))
    builder.add_node("human_review_wait", rg.adapt_node(rg.await_human_review))
    builder.add_node("human_review_apply", rg.adapt_node(rg.apply_human_review_decision))
    builder.add_node(
        "hitl_router",
        rg.adapt_node(
            _make_router(
                "human_review_apply",
                rg.route_after_human_review,
                source_segment="hitl",
                internal_nodes=_HITL_INTERNAL,
                cross_map=_HITL_CROSS,
            )
        ),
    )
    builder.add_node("diag_exit", rg.adapt_node(_diag_exit))

    builder.add_edge(START, "human_review_prepare")
    builder.add_conditional_edges(
        "human_review_prepare",
        lambda state: rg._dispatch_fixed("human_review_prepare", "human_review_publish", state),
        _path_map("human_review_publish", aliases={"end_diagnostic": "diag_exit"}),
    )
    builder.add_conditional_edges(
        "human_review_publish",
        lambda state: rg._dispatch_fixed("human_review_publish", "human_review_wait", state),
        _path_map("human_review_wait", aliases={"end_diagnostic": "diag_exit"}),
    )
    builder.add_conditional_edges(
        "human_review_wait",
        lambda state: rg._dispatch_fixed("human_review_wait", "human_review_apply", state),
        _path_map("human_review_apply", aliases={"end_diagnostic": "diag_exit"}),
    )
    builder.add_edge("human_review_apply", "hitl_router")
    return builder.compile(checkpointer=checkpointer)


def build_segments(checkpointer):
    """Compile the four segment subgraphs against the shared checkpointer."""
    return {
        "intent_loop": _build_intent_loop(checkpointer),
        "cognitive": _build_cognitive(checkpointer),
        "spatial_chain": _build_spatial_chain(checkpointer),
        "hitl": _build_hitl(checkpointer),
    }


__all__ = ["build_segments"]
