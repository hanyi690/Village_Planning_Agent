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
from ..tools.constants import ADVANCE_PLANNING_TOOL, GIS_ANALYSIS_TOOL
from ..utils.logger import get_logger


logger = get_logger(__name__)


def after_conversation(state: Dict[str, Any]) -> Union[str, List[Send]]:
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

        # 计算影响树（wave 0 = 目标维度，wave 1+ = 下游波次）
        impact_tree: Dict[int, List[str]] = {}
        for target_dim in target_dims:
            tree = get_impact_tree_compat(target_dim)
            for wave, dims in tree.items():
                impact_tree.setdefault(wave + 1, []).extend(dims)

        wave0_dims = list(set(target_dims))
        final_tree = {0: wave0_dims}
        for wave in sorted(impact_tree.keys()):
            final_tree[wave] = list(set(impact_tree[wave]))

        logger.info(
            "[after_conversation] Cascade revision: targets=%s, impact_tree waves=%s dims=%s",
            target_dims, len(final_tree),
            {w: len(d) for w, d in final_tree.items()},
        )

        all_dims = [d for dims in final_tree.values() for d in dims]
        new_completed = _reset_dimensions(state.get("completed_dimensions", {}), all_dims)

        # 仅分发 Wave 0（目标维度），保留 feedback 供下游读取
        return [Send("analyze_dimension", {
            **state, "dimension_key": d,
            "completed_dimensions": new_completed,
            "is_revision": True,
            "revision_impact_tree": final_tree,
            "revision_feedback": feedback,
            "revision_completed_dims": {},
            "feedback": None,
            "need_revision": False,
            "revision_target_dimensions": [],
        }) for d in wave0_dims]

    # 2. 推进意图检测
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        for tc in last_msg.tool_calls:
            name = tc.get("name", "")
            if name == ADVANCE_PLANNING_TOOL["function"]["name"]:
                return _dispatch_current(state)
            if name == GIS_ANALYSIS_TOOL["function"]["name"]:
                return "execute_tools"
        return "execute_tools"

    return END


def after_analysis(state: Dict[str, Any]) -> Union[str, List[Send]]:
    """
    分析后路由 - 波次推进逻辑

    处理：
    1. completed -> END
    2. execution_paused -> END（等待审批）
    3. 待处理维度 -> Send 分发（检查同层依赖）
    """
    # 级联修订波次推进：按 impact_tree 波次顺序分发
    is_revision = state.get("is_revision", False)
    if is_revision:
        impact_tree = state.get("revision_impact_tree", {})
        completed = state.get("revision_completed_dims", {})
        all_completed = [d for dims in completed.values() for d in dims]
        next_wave = get_next_revision_wave(impact_tree, all_completed)
        if next_wave:
            logger.info("[after_analysis] Revision wave dispatch: %s", next_wave)
            return [Send("analyze_dimension", {**state, "dimension_key": d}) for d in next_wave]
        logger.info("[after_analysis] All revision waves complete")
        return END

    phase = state.get("phase", "layer1")
    if phase == "completed":
        return END

    # Paused waiting for user approval — stop graph execution
    if state.get("execution_paused"):
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

    logger.info(
        "[after_analysis] phase=%s layer=%s completed=%s ready=%s",
        phase, layer, completed, ready_dims,
    )

    # Dispatch ready dimensions (dependencies satisfied)
    if ready_dims:
        return [Send("analyze_dimension", {**state, "dimension_key": d}) for d in ready_dims]

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
    """分发当前 phase 的维度"""
    phase = state.get("phase", PlanningPhase.INIT.value)
    if phase == PlanningPhase.INIT.value:
        phase = PlanningPhase.LAYER1.value

    logger.info("[_dispatch_current] input phase=%s step_mode=%s", phase, state.get("step_mode"))

    layer = _phase_to_layer(phase)
    if layer is None:
        return END

    completed = state.get("completed_dimensions", {}).get(f"layer{layer}", [])
    pending = [d for d in get_layer_dimensions(layer) if d not in completed]

    if not pending:
        return END

    return [Send("analyze_dimension", {**state, "dimension_key": d, "phase": phase}) for d in pending]


__all__ = ["after_conversation", "after_analysis"]