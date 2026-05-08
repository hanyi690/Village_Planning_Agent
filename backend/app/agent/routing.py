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
from ..config.dependency import get_impact_tree_compat
from ..constants.tools import ADVANCE_PLANNING_TOOL, GIS_ANALYSIS_TOOL
from ..utils.logger import get_logger
from ..utils.sse_publisher import SSEPublisher

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

    # 1. 级联修订
    if state.get("feedback"):
        target_dim = _infer_dim_from_feedback(state)
        if not target_dim:
            return END
        impacted = get_impact_tree_compat(target_dim)
        all_dims = [target_dim]
        for wave_dims in impacted.values():
            all_dims.extend(wave_dims)

        new_completed = _reset_dimensions(state.get("completed_dimensions", {}), all_dims)
        return [Send("analyze_dimension", {
            **state, "dimension_key": dim,
            "completed_dimensions": new_completed,
            "feedback": None
        }) for dim in all_dims]

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
    2. 层级完成 -> 推进或暂停
    3. 波次推进 -> 继续执行
    """
    phase = state.get("phase", "layer1")
    if phase == "completed":
        return END

    layer = _phase_to_layer(phase)
    if layer is None:
        return END

    completed = state.get("completed_dimensions", {}).get(f"layer{layer}", [])
    total_dims = get_layer_dimensions(layer)

    if set(completed) == set(total_dims):
        if state.get("pause_after_layer"):
            return "conversation"

        next_layer = layer + 1
        if next_layer > 3:
            return END

        session_id = state.get("session_id", "")
        SSEPublisher.send_layer_start(
            session_id=session_id,
            layer=next_layer,
            layer_name=f"Layer {next_layer}",
            dimension_count=len(get_layer_dimensions(next_layer))
        )

        pending = [d for d in get_layer_dimensions(next_layer)
                   if d not in state.get("completed_dimensions", {}).get(f"layer{next_layer}", [])]
        return [Send("analyze_dimension", {
            **state, "dimension_key": d, "phase": f"layer{next_layer}", "current_wave": 1
        }) for d in pending]

    # 波次未完成，继续执行
    pending = [d for d in total_dims if d not in completed]
    return [Send("analyze_dimension", {**state, "dimension_key": d}) for d in pending]


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

    layer = _phase_to_layer(phase)
    if layer is None:
        return END

    completed = state.get("completed_dimensions", {}).get(f"layer{layer}", [])
    pending = [d for d in get_layer_dimensions(layer) if d not in completed]

    if not pending:
        return END

    return [Send("analyze_dimension", {**state, "dimension_key": d, "phase": phase}) for d in pending]


__all__ = ["after_conversation", "after_analysis"]