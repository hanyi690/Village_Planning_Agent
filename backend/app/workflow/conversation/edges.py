"""
统一路由逻辑 - 简化版

使用 LangGraph Send API 实现动态路由。
纯函数风格，配置驱动。

路由函数：
- after_conversation: 对话后路由（级联修订、推进意图）
- after_analysis: 分析后路由（层级完成、波次推进）

Migrated from agent/routing.py per docs/architecture/agent-graph.md §5.
"""

from typing import Union, List, Dict, Any, Optional
from langgraph.graph import END
from langgraph.types import Send

from app.workflow.layers.phase_machine import PlanningPhase, get_layer_dimensions, _phase_to_layer
from app.workflow.layers.layer_router import _worker_for_phase, _dispatch_state, _send_worker
from app.workflow.state import load_root_gate
from app.config.dependency import compute_impact_tree
from app.infrastructure.llm.tools.intent_tools import advance_planning_intent, gis_analysis
from app.infrastructure.logging import get_logger


logger = get_logger(__name__)


def after_conversation(
    state: Dict[str, Any],
) -> Union[str, List[Send]]:
    """
    对话后路由 - 新架构核心

    处理：
    1. 级联修订：feedback 存在时计算影响树
    2. 推进意图：AdvancePlanningIntent -> 分发维度
    3. 工具执行：其他工具 -> execute_tools
    4. 普通对话：END
    """
    messages = state.get("messages", [])
    if not messages:
        logger.info("[after_conversation] No messages, returning END")
        return END

    last_msg = messages[-1]

    # 1. 级联修订 - 修复：同时检查feedback和human_feedback，以及need_revision标志
    feedback = state.get("feedback") or state.get("human_feedback")
    need_revision = state.get("need_revision", False)

    if need_revision and feedback:
        # 从revision_target_dimensions获取目标维度，或从反馈推断
        target_dims = state.get("revision_target_dimensions", [])
        if not target_dims:
            target_dim = _infer_dim_from_feedback(state)
            if target_dim:
                target_dims = [target_dim]

        if not target_dims:
            logger.warning("[after_conversation] No target dimensions for revision")
            return END

        # Use pre-computed impact_tree from submit_feedback, or compute if missing
        final_tree = state.get("revision_impact_tree")
        if not final_tree:
            downstream_tree: Dict[int, List[str]] = {}
            for target_dim in target_dims:
                tree = compute_impact_tree(target_dim)
                for wave, dims in tree.items():
                    downstream_tree.setdefault(wave, []).extend(dims)

            wave0_dims = list(set(target_dims))
            final_tree = {0: wave0_dims}
            for wave in sorted(downstream_tree.keys()):
                final_tree[wave] = list(set(downstream_tree[wave]))

        wave0_dims = final_tree.get(0, target_dims)

        logger.info(
            "[after_conversation] Cascade revision: targets=%s, impact_tree waves=%s dims=%s",
            target_dims, len(final_tree),
            {w: len(d) for w, d in final_tree.items()},
        )

        all_dims = [d for dims in final_tree.values() for d in dims]
        new_completed = _reset_dimensions(state.get("completed_dimensions", {}), all_dims)

        # 仅分发 Wave 0（目标维度），保留 feedback 供下游读取
        logger.info(
            "[after_conversation] Wave 0 dispatch: %s -> analyze_dimension, final_tree=%s",
            wave0_dims,
            final_tree,
        )
        for d in wave0_dims:
            logger.debug("[after_conversation] Sending dimension: %s", d)
        worker = _worker_for_phase(state.get("phase", "layer1"))
        return [_send_worker(worker, _dispatch_state(state,
            dimension_key=d,
            completed_dimensions=new_completed,
            is_revision=True,
            revision_impact_tree=final_tree,
            revision_feedback=feedback,
            revision_completed_dims={},
            feedback=None,
            need_revision=False,
        )) for d in wave0_dims]

    # 2. 推进意图检测
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        for tc in last_msg.tool_calls:
            name = tc.get("name", "")
            # Normalize: LLM may emit PascalCase from old prompts
            if name in (advance_planning_intent.name, "AdvancePlanningIntent"):
                logger.info("[after_conversation] ROUTE: advance_planning_intent detected -> _dispatch_current")
                return _dispatch_current(state)
            if name in (gis_analysis.name, "GISAnalysis"):
                # Manual GIS/spatial intent enters the target-projection chain,
                # 不再经过 gis_agent 黑盒节点。
                logger.info("[after_conversation] ROUTE: gis_analysis detected -> target_projection")
                return "target_projection"
        logger.info("[after_conversation] ROUTE: unknown tool_call -> execute_tools (name=%s)", last_msg.tool_calls[0].get("name"))
        return "execute_tools"

    phase = state.get("phase", "unknown")
    layer = _phase_to_layer(phase)
    logger.info(
        "[after_conversation] ROUTE: no tool_calls, no revision -> END (phase=%s layer=%s)",
        phase, layer,
    )
    return END


def after_analysis(
    state: Dict[str, Any],
) -> Union[str, List[Send]]:
    """
    分析后路由 - 波次推进逻辑（B2：纯编排，分支语义抽到处理器）

    处理顺序：
    1. 级联修订（is_revision）-> ``_route_revision``
    2. provider/fatal 失败 -> ``_terminal_failure_route``
    3. post_l3 -> target_projection
    4. 层 gate 路由 -> ``_route_layer_gate``（PASS/EXPLORE/HUMAN/L1/L2/L3）
    5. 就绪维度派发 / 依赖死锁 -> ``_route_dimension_dispatch``
    """
    if state.get("is_revision", False):
        return _route_revision(state)
    fatal = _terminal_failure_route(state)
    if fatal is not None:
        return fatal
    if state.get("provider_resume_dimensions"):
        # A resumed set may contain same-layer dependencies.  Dispatch one
        # ready wave and leave blocked dimensions in the checkpoint until the
        # completed reports make them eligible.
        return "provider_resume_dispatch"
    phase = state.get("phase", "layer1")
    if phase == "post_l3":
        # L3 is not a terminal state.  The post-L3 chain owns target projection
        # through DELIVER and is entered only through advance_phase.
        return "target_projection"
    gate_route = _route_layer_gate(state, phase)
    if gate_route is not None:
        return gate_route
    return _route_dimension_dispatch(state, phase)


def _route_revision(state: Dict[str, Any]) -> Union[str, List[Send]]:
    """级联修订：依赖检查驱动波次，直到全部修订维度完成。"""
    # need_revision=False 表示 layer_completion_check 已判定修订完成
    if not state.get("need_revision", False):
        logger.info("[after_analysis] Revision completed, END")
        return END

    impact_tree = state.get("revision_impact_tree") or {}
    completed = state.get("revision_completed_dims", {})
    all_revision_dims_set = {d for dims in impact_tree.values() for d in dims}
    revision_completed = [d for dims in completed.values() for d in dims]
    target_dims = state.get("revision_target_dimensions", [])

    logger.info(
        "[after_analysis] Revision state: impact_tree=%s, completed=%s, revision_completed=%s, target_dims=%s",
        {w: len(d) for w, d in impact_tree.items()} if impact_tree else {},
        completed,
        revision_completed,
        target_dims,
    )

    # 获取所有需要修订的维度（目标 + 下游；impact_tree 已含 Wave 0，去重）
    all_revision_dims = list(all_revision_dims_set)

    # 基线已完成的维度（不受修订影响的维度，作为依赖检查的基准）
    baseline_completed = state.get("completed_dimensions", {})
    logger.info("[after_analysis] baseline_completed type=%s, keys=%s", type(baseline_completed).__name__, list(baseline_completed.keys()) if isinstance(baseline_completed, dict) else "N/A")
    baseline_dims = [d for dims in baseline_completed.values() for d in dims]

    # 合并：基线完成 + 修订完成
    all_completed = baseline_dims + revision_completed

    from app.config.loader import list_dimensions, get_dimension_layer

    logger.info(
        "[after_analysis] Checking deps: all_completed=%s",
        all_completed,
    )

    ready_dims = []
    for dim_key in all_revision_dims:
        # 跳过已修订完成的维度（不是基线完成的维度！）
        if dim_key in revision_completed:
            logger.info("[after_analysis] %s already revision_completed, skipping", dim_key)
            continue

        dim_layer = get_dimension_layer(dim_key)
        dim_configs = list_dimensions(dim_layer)
        dim_config = next((d for d in dim_configs if d.key == dim_key), None)

        if not dim_config:
            logger.info("[after_analysis] %s config not found", dim_key)
            continue

        same_layer_deps = dim_config.depends_on or []
        cross_layer_deps = list(dim_config.layer_depends_on or []) + list(dim_config.phase_depends_on or [])

        same_layer_ok = all(dep in all_completed for dep in same_layer_deps)
        cross_layer_ok = all(dep in all_completed for dep in cross_layer_deps)

        logger.info(
            "[after_analysis] %s check: same_layer_deps=%s cross_layer_deps=%s, same_layer_ok=%s cross_layer_ok=%s",
            dim_key, same_layer_deps, cross_layer_deps, same_layer_ok, cross_layer_ok,
        )

        if same_layer_ok and cross_layer_ok:
            ready_dims.append(dim_key)
        else:
            missing_same = [d for d in same_layer_deps if d not in all_completed]
            missing_cross = [d for d in cross_layer_deps if d not in all_completed]
            if missing_same or missing_cross:
                logger.info(
                    "[after_analysis] %s not ready: missing_same=%s missing_cross=%s",
                    dim_key, missing_same, missing_cross,
                )

    if ready_dims:
        logger.info("[after_analysis] Revision ready dims (dependency-checked): %s", ready_dims)
        worker = _worker_for_phase(state.get("phase", "layer1"))
        return [_send_worker(worker, _dispatch_state(state, dimension_key=d, is_revision=True, revision_impact_tree=impact_tree)) for d in ready_dims]

    # 检查是否所有修订维度都已完成（只检查 revision_completed，不含基线）
    if set(revision_completed) >= set(all_revision_dims):
        logger.info("[after_analysis] All revision dims complete")
        return END

    # 还有维度未完成但依赖未就绪，等待
    pending = [d for d in all_revision_dims if d not in revision_completed]
    logger.info("[after_analysis] Revision waiting for deps: %s", pending)
    return END


_TRANSIENT_LLM_CODES = frozenset({
    "llm_stream_timeout",
    "llm_timeout",
    "llm_provider_error",
    "llm_provider_circuit_open",
    "dimension_quality_failed",
})


def _terminal_failure_route(state: Dict[str, Any]) -> Optional[str]:
    """Provider 瞬态失败进入 HUMAN 断点，其余终止失败停止派发。"""
    fatal_error = state.get("fatal_error")
    if not isinstance(fatal_error, dict):
        failures = state.get("provider_failures") or []
        if failures and isinstance(failures[0], dict):
            fatal_error = failures[0]
    if not fatal_error:
        failures = state.get("dimension_failures") or []
        if failures and isinstance(failures[0], dict):
            fatal_error = failures[0]
    if not fatal_error:
        return None
    # A provider stream timeout is a transient infrastructure breakpoint.
    # Preserve the exact failed dimension in the checkpoint and enter the
    # normal HUMAN interrupt so an operator can resume the pending L3
    # worker without replaying completed dimensions.
    if (
        isinstance(fatal_error, dict)
        and fatal_error.get("code") in _TRANSIENT_LLM_CODES
        and str(state.get("phase", "")).lower() in {"layer1", "layer2", "layer3"}
    ):
        return "human_review"
    logger.error("[after_analysis] terminal failure; stopping dispatch: %s", fatal_error)
    return END


def _route_explore(state: Dict[str, Any], layer_num: int) -> Union[str, List[Send]]:
    """Run bounded gate evidence retrieval, then dispatch only affected dims.

    The graph keeps conditional edges synchronous, so the evidence service
    exposes a small sync adapter.  Results are cached by the service and are
    merged into the next canonical Explore context request; workers therefore
    receive one unified evidence section instead of a second RAG prompt.
    """
    pending: list[Any] = []
    try:
        gate_decision = load_root_gate(state, f"l{layer_num}")
        gate_payload = gate_decision.model_dump(mode="json")
        pending = list(gate_payload.get("pending_requests") or [])
        if pending:
            from app.evidence.retrieval.evidence_service import retrieve_evidence_for_gate_sync

            retrieve_evidence_for_gate_sync(
                gate_payload,
                str(state.get("session_id") or state.get("run_id") or ""),
                str((state.get("config") or {}).get("village_name") or ""),
            )
    except Exception as exc:
        logger.warning("[after_analysis] gate evidence retrieval failed: %s", exc)

    # L3 evidence gaps are business review findings, not a license to replay
    # all twelve expensive L3 workers.  The design contract requires an
    # auditable HUMAN checkpoint so an operator can supply or defer the
    # missing evidence.
    if layer_num == 3:
        logger.warning("[after_analysis] L3 EXPLORE gap -> HUMAN without full-layer replay")
        return "human_review"
    # 死循环防护：同一层 EXPLORE 重试超过 2 次 -> HUMAN（不再 re-dispatch）
    counts = state.get("retry_counts") or {}
    explore_count = counts.get(f"l{layer_num}_explore", 0)
    if explore_count >= 2:
        logger.warning("[after_analysis] EXPLORE retry exhausted for L%d -> HUMAN", layer_num)
        # Convert exhaustion into an explicit business gate.  END loses the
        # breakpoint and makes a real session look like a successful stop;
        # the HITL path preserves the pending evidence requests and allows
        # an operator to approve or reject the next revision.
        return "human_review"
    from app.config.loader import list_dimensions
    dim_configs = list_dimensions(layer_num)
    requested_dims = []
    for pending_item in pending:
        context = pending_item.get("context") or {} if isinstance(pending_item, dict) else getattr(pending_item, "context", {}) or {}
        dimension = context.get("dimension") if isinstance(context, dict) else ""
        if dimension and dimension not in requested_dims:
            requested_dims.append(dimension)
    configured_dims = {d.key for d in dim_configs}
    explore_dims = [dimension for dimension in requested_dims if dimension in configured_dims]
    # Legacy gates may not have emitted a dimension.  Preserve bounded
    # behaviour by using the configured layer only in that case; a concrete
    # dimension always wins and never expands to a full-layer replay.
    if not explore_dims:
        explore_dims = [d.key for d in dim_configs]
    if explore_dims:
        logger.info("[after_analysis] Gate EXPLORE (attempt %d): re-dispatching %s", explore_count + 1, explore_dims)
        worker = _worker_for_phase(state.get("phase", "layer1"))
        return [_send_worker(worker, _dispatch_state(state, dimension_key=d)) for d in explore_dims]
    return END


def _route_gate_rework(
    state: Dict[str, Any],
    layer_num: int,
    gate_decision: Any,
) -> Union[str, List[Send]]:
    """L1/L2/L3 业务重试：预算内重派发本层维度，超预算/契约失败进 HUMAN。"""
    counts = state.get("retry_counts") or {}
    retry_count = int(counts.get(f"l{layer_num}_explore", 0))
    retry_limit = int(state.get("max_retries") or 3)
    # L3 protocol/spatial contract violations are not transient infrastructure
    # failures. Re-running all 12 expensive L3 calls amplifies memory and can
    # reproduce the same malformed output. Preserve the exact pending requests
    # and enter HITL after the first failed aggregate.
    pending = list(gate_decision.pending_requests or [])
    hard_contract_failure = layer_num == 3 and any(
        any(code in str(item) for code in ("missing_instruction_marker", "missing_spatial_instruction"))
        for item in pending
    )
    if hard_contract_failure:
        logger.warning("[after_analysis] L3 contract failure -> HUMAN without full-layer replay")
        return "human_review"
    # L3 gate failures are business/contract findings over a complete
    # 12-dimension plan, not transient infrastructure errors.
    if layer_num == 3:
        logger.warning("[after_analysis] L3 business gate -> HUMAN without full-layer replay")
        return "human_review"
    if retry_count >= retry_limit:
        logger.warning(
            "[after_analysis] %s rework exhausted for L%d -> HUMAN",
            gate_decision.feedback_route,
            layer_num,
        )
        return "human_review"
    # Rework: re-dispatch dimensions of this layer
    from app.config.loader import list_dimensions
    dim_configs = list_dimensions(layer_num)
    rework_dims = [d.key for d in dim_configs]
    if rework_dims:
        logger.info("[after_analysis] Gate rework: re-dispatching %s", rework_dims)
        worker = _worker_for_phase(state.get("phase", "layer1"))
        return [_send_worker(worker, _dispatch_state(state, dimension_key=d)) for d in rework_dims]
    return END


def _route_layer_gate(
    state: Dict[str, Any],
    phase: str,
) -> Optional[Union[str, List[Send]]]:
    """Wave M2 gate-aware routing：PASS 推进、EXPLORE/L1/L2/L3/HUMAN 分派。

    ``layer_just_completed`` 优先（robust），回退到 phase —— 完成节点修复后
    二者在 gate PASS 前一致（phase 只在 PASS 时推进）。gate 通过 CAS artifact
    ref 读取；内联 layer gate payload 已不存在。phase 是权威游标：旧 checkpoint
    的过期 layer_just_completed 绝不能对着旧层 gate 路由。
    """
    layer_num = _phase_to_layer(phase)
    if layer_num is None:
        return None
    try:
        gate_decision = load_root_gate(state, f"l{layer_num}")
    except Exception:
        gate_decision = None
    if gate_decision is None:
        return None
    route = gate_decision.feedback_route
    if route is None or route == "PASS":
        # Gate PASS -> phase is advanced by the `advance_phase` node
        # (it writes phase + dispatches the next layer's dimensions).
        logger.info("[after_analysis] Gate l%d PASS -> advance_phase", layer_num)
        return "advance_phase"
    logger.info("[after_analysis] Gate l%d routed %s", layer_num, route)
    if route == "EXPLORE":
        return _route_explore(state, layer_num)
    if route == "HUMAN":
        # Always enter the persisted HITL checkpoint. Returning END here
        # loses the gate route and leaves real sessions looking like an
        # unexplained stop.
        return "human_review"
    if route in ("L1", "L2", "L3"):
        return _route_gate_rework(state, layer_num, gate_decision)
    # 未识别的 feedback_route：不吞掉，落到就绪维度派发（与 gate 缺失一致）。
    return None


def _route_dimension_dispatch(state: Dict[str, Any], phase: str) -> Union[str, List[Send]]:
    """就绪维度派发；部分完成且无就绪维度 = 依赖死锁 -> HUMAN。"""
    layer = _phase_to_layer(phase)
    if layer is None:
        return END

    from app.workflow.layers.layer_router import _ready_dispatch

    sends = _ready_dispatch(state, phase)
    if sends:
        logger.info("[after_analysis] phase=%s layer=%s dispatching %d dim(s) is_revision=%s",
                    phase, layer, len(sends), state.get("is_revision", False))
        return sends

    # A partially completed layer with no ready dimension is a dependency
    # deadlock, not a successful end. Preserve it as an auditable HUMAN
    # checkpoint so the operator can inspect the missing dimensions.
    if phase in {"layer1", "layer2", "layer3"}:
        from app.config.loader import list_dimensions

        layer_dims = list_dimensions(_phase_to_layer(phase) or 0)
        completed = set((state.get("completed_dimensions") or {}).get(phase, []))
        if len(completed) < len(layer_dims):
            logger.warning(
                "[after_analysis] dependency deadlock in %s: completed=%s/%s -> HUMAN",
                phase, len(completed), len(layer_dims),
            )
            return "human_review"

    logger.info("[after_analysis] No ready dims, returning END")
    return END


def _infer_dim_from_feedback(state: Dict[str, Any]) -> Optional[str]:
    """从反馈推断目标维度"""
    feedback = state.get("feedback", "")
    phase = state.get("phase", "layer1")
    layer = _phase_to_layer(phase)
    if not layer:
        return None
    completed = state.get("completed_dimensions", {}).get(f"layer{layer}", [])
    pending = [d for d in get_layer_dimensions(layer) if d not in completed]
    return pending[0] if pending else None


def _reset_dimensions(completed: Dict[str, List[str]], impacted: List[str]) -> Dict[str, List[str]]:
    """重置受影响维度的完成状态"""
    new = {}
    for layer_key, dims in completed.items():
        new[layer_key] = [d for d in dims if d not in impacted]
    return new


def _dispatch_current(state: Dict[str, Any]) -> Union[List[Send], str]:
    """分发当前 phase 的维度（同层依赖感知）"""
    phase = state.get("phase", PlanningPhase.INIT.value)
    if phase == PlanningPhase.INIT.value:
        phase = PlanningPhase.LAYER1.value

    logger.info("[_dispatch_current] input phase=%s", phase)

    layer = _phase_to_layer(phase)
    if layer is None:
        return END

    completed = state.get("completed_dimensions", {}).get(f"layer{layer}", [])
    pending = [d for d in get_layer_dimensions(layer) if d not in completed]

    if not pending:
        return END

    # 只分发同层依赖已完成的维度
    from app.config.loader import list_dimensions
    dim_configs = list_dimensions(layer)
    config_map = {d.key: d for d in dim_configs}

    ready = []
    for dim_key in pending:
        cfg = config_map.get(dim_key)
        if cfg and all(dep in completed for dep in (cfg.depends_on or [])):
            ready.append(dim_key)

    if not ready:
        return END

    worker = _worker_for_phase(phase)
    return [_send_worker(worker, _dispatch_state(state, dimension_key=d, phase=phase)) for d in ready]


__all__ = ["after_conversation", "after_analysis"]
