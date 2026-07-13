"""
统一路由逻辑 - 简化版

使用 LangGraph Send API 实现动态路由。
纯函数风格，配置驱动。

路由函数：
- after_conversation: 对话后路由（级联修订、推进意图）
- after_analysis: 分析后路由（层级完成、波次推进）
"""

from typing import Union, List, Dict, Any, Optional
from langgraph.graph import END
from langgraph.types import Send
from langchain_core.messages import AIMessage

from .state import PlanningPhase, get_layer_dimensions, _phase_to_layer
from ..config import get_dimension_layer
from ..config.dependency import get_impact_tree_compat, get_next_revision_wave
from ..tools.intent_tools import advance_planning_intent, gis_analysis
from ..utils.logger import get_logger


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
                tree = get_impact_tree_compat(target_dim)
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
        return [Send("analyze_dimension", {
            **state, "dimension_key": d,
            "completed_dimensions": new_completed,
            "is_revision": True,
            "revision_impact_tree": final_tree,
            "revision_feedback": feedback,
            "revision_completed_dims": {},
            "feedback": None,
            "need_revision": False,
        }) for d in wave0_dims]

    # 2. 推进意图检测
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        for tc in last_msg.tool_calls:
            name = tc.get("name", "")
            # Normalize: LLM may emit PascalCase from old prompts
            if name in (advance_planning_intent.name, "AdvancePlanningIntent"):
                logger.info("[after_conversation] ROUTE: advance_planning_intent detected -> _dispatch_current")
                return _dispatch_current(state)
            if name in (gis_analysis.name, "GISAnalysis"):
                logger.info("[after_conversation] ROUTE: gis_analysis detected -> gis_agent")
                return "gis_agent"
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
    分析后路由 - 波次推进逻辑

    处理：
    1. completed -> END
    2. interrupt -> END（等待审批）
    3. 待处理维度 -> Send 分发（检查同层依赖）
    """
    is_revision = state.get("is_revision", False)

    # 级联修订：使用依赖检查逻辑，而非简单波次分发
    if is_revision:
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

        # 获取所有需要修订的维度（目标 + 下游）
        # 注意：impact_tree 包含 Wave 0，所以不需要再加 target_dims
        # all_revision_dims 已在上面计算并去重
        all_revision_dims = list(all_revision_dims_set)

        # 基线已完成的维度（不受修订影响的维度，作为依赖检查的基准）
        baseline_completed = state.get("completed_dimensions", {})
        logger.info("[after_analysis] baseline_completed type=%s, keys=%s", type(baseline_completed).__name__, list(baseline_completed.keys()) if isinstance(baseline_completed, dict) else "N/A")
        baseline_dims = [d for dims in baseline_completed.values() for d in dims]

        # 合并：基线完成 + 修订完成
        all_completed = baseline_dims + revision_completed

        # 检查哪些维度的依赖已完成
        from ..config.loader import list_dimensions, get_dimension_layer

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

            # 获取维度配置
            dim_layer = get_dimension_layer(dim_key)
            dim_configs = list_dimensions(dim_layer)
            dim_config = next((d for d in dim_configs if d.key == dim_key), None)

            if not dim_config:
                logger.info("[after_analysis] %s config not found", dim_key)
                continue

            # 检查同层依赖是否完成
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
                # Debug: why not ready
                missing_same = [d for d in same_layer_deps if d not in all_completed]
                missing_cross = [d for d in cross_layer_deps if d not in all_completed]
                if missing_same or missing_cross:
                    logger.info(
                        "[after_analysis] %s not ready: missing_same=%s missing_cross=%s",
                        dim_key, missing_same, missing_cross,
                    )

        if ready_dims:
            logger.info("[after_analysis] Revision ready dims (dependency-checked): %s", ready_dims)
            return [Send("analyze_dimension", {**state, "dimension_key": d, "is_revision": True, "revision_impact_tree": impact_tree}) for d in ready_dims]

        # 检查是否所有修订维度都已完成（只检查 revision_completed，不含基线）
        if set(revision_completed) >= set(all_revision_dims):
            logger.info("[after_analysis] All revision dims complete")
            return END

        # 还有维度未完成但依赖未就绪，等待
        pending = [d for d in all_revision_dims if d not in revision_completed]
        logger.info("[after_analysis] Revision waiting for deps: %s", pending)
        return END

    phase = state.get("phase", "layer1")
    if phase == "completed":
        return END

    layer = _phase_to_layer(phase)
    if layer is None:
        return END

    completed = state.get("completed_dimensions", {}).get(f"layer{layer}", [])
    total_dims = get_layer_dimensions(layer)

    # 检查同层依赖，只分发依赖已完成的 dimensions
    from ..config.loader import list_dimensions

    dim_configs = list_dimensions(layer)
    ready_dims = []
    for dim in dim_configs:
        if dim.key in completed:
            continue
        # 检查同层依赖是否都已完成
        if all(dep in completed for dep in dim.depends_on):
            ready_dims.append(dim.key)

    # Continuous mode: check next-layer dims whose cross-layer deps are ready
    # Must run even when current-layer has no ready dims (all dispatched)
    cross_ready = []
    next_layer = layer + 1
    step_mode = state.get("step_mode", False)
    if next_layer <= 3 and not step_mode:
        next_dims = list_dimensions(next_layer)
        next_completed = state.get("completed_dimensions", {}).get(f"layer{next_layer}", [])
        completed_all = state.get("completed_dimensions", {})
        for dim in next_dims:
            if dim.key in next_completed:
                continue
            if not all(dep in next_completed for dep in dim.depends_on):
                continue
            cross_deps = list(getattr(dim, 'layer_depends_on', []) or [])
            if not all(dep in completed for dep in cross_deps):
                continue
            phase_deps = list(getattr(dim, 'phase_depends_on', []) or [])
            prev_layer_key = f"layer{layer}"
            prev_completed = completed_all.get(prev_layer_key, [])
            if not all(dep in prev_completed for dep in phase_deps):
                continue
            cross_ready.append(dim.key)
            logger.info(
                "[after_analysis] Cross-layer early dispatch: %s (layer=%s, cross_deps=%s)",
                dim.key, next_layer, cross_deps + phase_deps,
            )

    logger.info(
        "[after_analysis] phase=%s layer=%s completed=%s/%s ready=%s cross_ready=%s step_mode=%s is_revision=%s",
        phase, layer, len(completed), len(total_dims),
        ready_dims, cross_ready, step_mode, is_revision,
    )

    all_ready = ready_dims + cross_ready
    if all_ready:
        return [Send("analyze_dimension", {**state, "dimension_key": d}) for d in all_ready]

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
    from ..config.loader import list_dimensions
    dim_configs = list_dimensions(layer)
    config_map = {d.key: d for d in dim_configs}

    ready = []
    for dim_key in pending:
        cfg = config_map.get(dim_key)
        if cfg and all(dep in completed for dep in (cfg.depends_on or [])):
            ready.append(dim_key)

    if not ready:
        return END

    return [Send("analyze_dimension", {**state, "dimension_key": d, "phase": phase}) for d in ready]


__all__ = ["after_conversation", "after_analysis"]