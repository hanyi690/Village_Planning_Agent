"""
统一路由逻辑

使用 LangGraph Send API 实现动态路由，消灭子图嵌套。
支持 Router Agent 架构的意图路由和规划路由。
"""

from typing import List, Dict, Any, Optional, Union, Literal
from langgraph.graph import END
from langgraph.types import Send
from langchain_core.messages import AIMessage

from .state import (
    PlanningPhase,
    get_layer_dimensions,
    get_wave_dimensions,
    get_total_waves,
    get_next_phase,
    _phase_to_layer,
    _layer_to_phase,
)
from .nodes.dimension_node import create_dimension_state, DIMENSION_NAMES
from ..utils.logger import get_logger

logger = get_logger(__name__)


# ==========================================
# 意图路由（对话后）
# ==========================================

def intent_router(state: Dict[str, Any]) -> str:
    """
    意图路由 - 根据最后一条消息决定下一步

    Returns:
        "execute_tools": 执行工具调用
        "route_planning": 推进规划流程
        END: 普通对话，结束本轮
    """
    messages = state.get("messages", [])
    if not messages:
        return END

    last_msg = messages[-1]

    # 检查是否有工具调用
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        # 检查是否是 AdvancePlanningIntent
        for tool_call in last_msg.tool_calls:
            tool_name = tool_call.get("name", "")
            if tool_name == "AdvancePlanningIntent":
                logger.info("[意图路由] 检测到 AdvancePlanningIntent，推进规划")
                return "route_planning"
        # 其他工具调用
        logger.info(f"[意图路由] 检测到工具调用: {[tc.get('name') for tc in last_msg.tool_calls]}")
        return "execute_tools"

    # 检查是否需要修订
    if state.get("need_revision"):
        logger.info("[意图路由] 检测到 need_revision，进入修订流程")
        return "route_planning"

    # 普通对话，结束本轮
    return END


# ==========================================
# 规划路由（Send API）
# ==========================================

def route_by_phase(state: Dict[str, Any]) -> Union[List[Send], str]:
    """
    根据当前 phase 路由到对应的维度分析

    Send API 实现：
    - 返回 List[Send]：并行执行多个维度
    - 返回 str：跳转到指定节点或 END
    """
    phase = state.get("phase", PlanningPhase.INIT.value)
    current_wave = state.get("current_wave", 1)

    logger.info(f"[路由] 当前阶段: {phase}, 波次: {current_wave}")

    # 特殊状态优先
    if state.get("need_revision"):
        logger.info("[路由] 检测到 need_revision，进入修订")
        return "revision"

    if phase == PlanningPhase.COMPLETED.value:
        logger.info("[路由] 已完成，结束")
        return END

    if phase == PlanningPhase.INIT.value:
        # 初始化阶段，开始 Layer 1
        return _check_layer_completion(state, layer=1)

    elif phase == PlanningPhase.LAYER1.value:
        return _check_layer_completion(state, layer=1)

    elif phase == PlanningPhase.LAYER2.value:
        return _route_wave_layer(state, layer=2, current_wave=current_wave)

    elif phase == PlanningPhase.LAYER3.value:
        return _route_wave_layer(state, layer=3, current_wave=current_wave)

    return []


def _check_layer_completion(state: Dict[str, Any], layer: int) -> Union[List[Send], str]:
    """
    检查层级完成状态并路由

    如果当前层所有维度完成，推进到下一阶段。
    否则继续执行未完成的维度。
    """
    completed = state.get("completed_dimensions", {})
    layer_key = f"layer{layer}"
    completed_dims = completed.get(layer_key, [])
    total_dims = get_layer_dimensions(layer)

    pending = [d for d in total_dims if d not in completed_dims]

    if not pending:
        next_phase = get_next_phase(state.get("phase", ""))
        logger.info(f"[路由] Layer {layer} 完成，推进到 {next_phase}")
        return "collect_results"

    logger.info(f"[路由] Layer {layer}: {len(pending)} 个维度待执行")
    return [Send("analyze_dimension", create_dimension_state(d, state)) for d in pending]


def _route_wave_layer(state: Dict[str, Any], layer: int, current_wave: int) -> Union[List[Send], str]:
    """
    路由到波次执行的层级（Layer 2 或 Layer 3）

    统一的波次路由逻辑，避免重复代码。

    Args:
        state: 当前状态
        layer: 层级（2 或 3）
        current_wave: 当前波次

    Returns:
        Send 列表或节点名称
    """
    completed = state.get("completed_dimensions", {}).get(f"layer{layer}", [])
    total_waves = get_total_waves(layer)

    # 检查当前波次是否完成
    wave_dims = get_wave_dimensions(layer, current_wave)
    wave_completed = all(d in completed for d in wave_dims)

    if wave_completed:
        if current_wave >= total_waves:
            # 当前层完成
            logger.info(f"[路由] Layer {layer} 完成")
            return "collect_results"
        else:
            # 推进到下一波次
            next_wave = current_wave + 1
            logger.info(f"[路由] Layer {layer} Wave {current_wave} 完成，推进到 Wave {next_wave}")
            next_wave_dims = get_wave_dimensions(layer, next_wave)
            pending = [d for d in next_wave_dims if d not in completed]

            return [
                Send("analyze_dimension", create_dimension_state(dim, state))
                for dim in pending
            ]

    # 执行当前波次的未完成维度
    pending_dims = [d for d in wave_dims if d not in completed]
    logger.info(f"[路由] Layer {layer} Wave {current_wave}: {len(pending_dims)} 个维度待执行")

    return [
        Send("analyze_dimension", create_dimension_state(dim, state))
        for dim in pending_dims
    ]


# ==========================================
# 收集节点
# ==========================================

def collect_layer_results(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    收集当前层所有维度结果，推进到下一 phase

    Returns:
        状态更新字典
    """
    phase = state.get("phase", PlanningPhase.INIT.value)
    dimension_results = state.get("dimension_results", [])

    # 合并维度结果到 reports
    reports = dict(state.get("reports", {}))
    completed_dimensions = dict(state.get("completed_dimensions", {}))

    layer = _phase_to_layer(phase)
    layer_key = f"layer{layer}"

    # 初始化该层的报告
    if layer_key not in reports:
        reports[layer_key] = {}
    if layer_key not in completed_dimensions:
        completed_dimensions[layer_key] = []

    # 合并结果
    for result in dimension_results:
        dim_key = result.get("dimension_key")
        if result.get("success") and dim_key:
            reports[layer_key][dim_key] = result.get("result", "")
            if dim_key not in completed_dimensions[layer_key]:
                completed_dimensions[layer_key].append(dim_key)

    # 检查是否完成当前层
    total_dims = get_layer_dimensions(layer)
    completed_count = len(completed_dimensions.get(layer_key, []))

    logger.info(f"[收集] {phase}: {completed_count}/{len(total_dims)} 维度完成")

    updates = {
        "reports": reports,
        "completed_dimensions": completed_dimensions,
        "dimension_results": [],  # 清空，为下一轮准备
    }

    # 检查是否需要推进波次或阶段
    if completed_count >= len(total_dims):
        # 当前层完成，推进到下一阶段
        next_phase = get_next_phase(phase)
        if next_phase:
            logger.info(f"[收集] {phase} 完成，推进到 {next_phase}")
            updates["phase"] = next_phase
            updates["current_wave"] = 1
    else:
        # 检查波次推进
        current_wave = state.get("current_wave", 1)
        total_waves = get_total_waves(layer)
        wave_dims = get_wave_dimensions(layer, current_wave)
        wave_completed = all(d in completed_dimensions.get(layer_key, []) for d in wave_dims)

        if wave_completed and current_wave < total_waves:
            updates["current_wave"] = current_wave + 1
            logger.info(f"[收集] 推进到 Wave {current_wave + 1}")

    return updates


def emit_sse_events(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    发送 SSE 事件节点

    从 sse_events 字段读取事件并批量发送，然后清空。
    """
    sse_events = state.get("sse_events", [])
    session_id = state.get("session_id", "")

    if not sse_events:
        return {"sse_events": []}

    try:
        from ..utils.sse_publisher import SSEPublisher
        SSEPublisher.send_events_batch(session_id, sse_events)
        logger.info(f"[SSE] 批量发送 {len(sse_events)} 个事件")
    except Exception as e:
        logger.error(f"[SSE] 批量发送失败: {e}")

    return {"sse_events": []}


# ==========================================
# 阶段推进检查
# ==========================================

def check_phase_completion(state: Dict[str, Any]) -> Literal["continue", "advance", "complete"]:
    """
    检查当前阶段是否完成

    Returns:
        "continue": 继续当前阶段
        "advance": 推进到下一阶段
        "complete": 规划完成
    """
    phase = state.get("phase", PlanningPhase.INIT.value)

    if phase == PlanningPhase.COMPLETED.value:
        return "complete"

    layer = _phase_to_layer(phase)
    if layer == 0:  # INIT
        return "advance"

    completed = state.get("completed_dimensions", {}).get(f"layer{layer}", [])
    total = get_layer_dimensions(layer)

    if len(completed) >= len(total):
        if layer >= 3:
            return "complete"
        return "advance"

    return "continue"


__all__ = [
    "intent_router",
    "route_by_phase",
    "collect_layer_results",
    "emit_sse_events",
    "check_phase_completion",
]