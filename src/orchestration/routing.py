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
    get_layer_name,
    get_wave_dimensions,
    get_total_waves,
    get_next_phase,
    _phase_to_layer,
    _layer_to_phase,
)
from .nodes.dimension_node import create_dimension_state, DIMENSION_NAMES
from ..config.dimension_metadata import get_dimension_layer
from ..utils.logger import get_logger
from ..utils.event_factory import create_layer_completed_event, create_pause_event
from ..utils.sse_publisher import SSEPublisher

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

    知识预加载：
    - 检测 knowledge_cache 是否为空
    - 如果为空，先进入 knowledge_preload 节点

    恢复执行检测：
    - 当 phase 推进到 layer2/3 且 previous_layer=0 时
    - 表示用户刚批准，需要发送 layer_started
    """
    phase = state.get("phase", PlanningPhase.INIT.value)
    current_wave = state.get("current_wave", 1)
    config = state.get("config", {})
    knowledge_cache = config.get("knowledge_cache", {})
    previous_layer = state.get("previous_layer", 0)

    logger.debug(f"[路由] 当前阶段: {phase}, 波次: {current_wave}, previous_layer={previous_layer}")

    # 暂停状态优先检测
    if state.get("pause_after_step", False):
        logger.info("[路由] 检测到 pause_after_step=True，等待用户审查")
        return END

    layer = _phase_to_layer(phase)

    # INIT 阶段需要推进到 layer1
    if layer == 0:
        logger.info("[路由] INIT 阶段，返回 advance_phase")
        return "advance_phase"

    # 知识预加载检测：如果缓存为空，先预加载
    if not knowledge_cache:
        layer = _phase_to_layer(phase)
        if layer and layer in [1, 2, 3]:
            logger.info(f"[路由] knowledge_cache 为空，进入预加载 (Layer {layer})")
            return "knowledge_preload"

    # 特殊状态优先
    if state.get("need_revision"):
        logger.info("[路由] 检测到 need_revision，进入修订")
        return "revision"

    if phase == PlanningPhase.COMPLETED.value:
        logger.info("[路由] 已完成，结束")
        return END

    # Layer 1/2/3 路由
    if phase == PlanningPhase.LAYER1.value:
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

    logger.debug(f"[路由] Layer {layer}: {len(pending)} 个维度待执行")
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

            # 返回 Send 列表，波次推进由 collect_layer_results 处理
            return [Send("analyze_dimension", create_dimension_state(dim, state)) for dim in pending]

    # 执行当前波次的未完成维度
    pending_dims = [d for d in wave_dims if d not in completed]
    logger.debug(f"[路由] Layer {layer} Wave {current_wave}: {len(pending_dims)} 个维度待执行")

    return [
        Send("analyze_dimension", create_dimension_state(dim, state))
        for dim in pending_dims
    ]


# ==========================================
# 收集节点
# ==========================================


def _send_layer_completion_events(
    session_id: str,
    layer: int,
    phase: str,
    reports: Dict[str, Any],
    step_mode: bool,
) -> None:
    """统一发送层级完成的 SSE 事件

    Args:
        session_id: Session ID
        layer: 完成的层级
        phase: 当前阶段
        reports: 报告数据
        step_mode: 是否分步模式

    Note:
        checkpoint_saved 事件由 _trigger_planning_execution 在 checkpoint 持久化后发送，
        此函数只发送 layer_completed 和 pause 事件。
    """
    sse_events = []

    # 发送 layer_completed 事件
    sse_events.append(create_layer_completed_event(
        layer=layer,
        phase=phase,
        reports=reports,
        pause_after_step=True,
        previous_layer=layer,
        session_id=session_id,
    ))

    # step_mode 下额外发送 pause 事件
    if step_mode:
        sse_events.append(create_pause_event(
            previous_layer=layer,
            step_mode=True,
            session_id=session_id,
        ))

    SSEPublisher.send_events_batch(session_id, sse_events)
    logger.info(f"[收集] Layer {layer} 发送 {len(sse_events)} 个 SSE 事件: {[e.get('type') for e in sse_events]}")


async def collect_layer_results(state: Dict[str, Any]) -> Dict[str, Any]:
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

    # Guard: completed 或未知阶段无对应层级
    if layer is None:
        logger.info(f"[收集] Phase {phase} 无对应层级，跳过结果收集")
        return {
            "dimension_results": [],
            "reports": state.get("reports", {}),
            "completed_dimensions": state.get("completed_dimensions", {}),
        }

    layer_key = f"layer{layer}"

    # 初始化该层的报告
    if layer_key not in reports:
        reports[layer_key] = {}
    if layer_key not in completed_dimensions:
        completed_dimensions[layer_key] = []

    # 合并结果（带维度归属验证，防止跨层污染）
    layer_dims = set(get_layer_dimensions(layer))
    for result in dimension_results:
        dim_key = result.get("dimension_key")
        if result.get("success") and dim_key:
            # 维度归属验证：只处理属于当前层的维度
            if dim_key in layer_dims:
                reports[layer_key][dim_key] = result.get("result", "")
                if dim_key not in completed_dimensions[layer_key]:
                    completed_dimensions[layer_key].append(dim_key)
            else:
                # 记录跨层维度警告（用于调试）
                dim_layer = get_dimension_layer(dim_key)
                logger.debug(f"[收集] 跳过跨层维度: {dim_key} (属于 Layer {dim_layer}, 当前 Layer {layer})")

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
        # 当前层完成
        if layer and layer < 3:
            # Layer 1/2 完成时，设置暂停等待用户审查
            # ⚠️ 不推进 phase，保持当前阶段表示"刚完成，等待审查"
            # approve 时才推进 phase 到下一阶段
            logger.info(f"[收集] {phase} 完成，设置暂停等待审查（phase 保持不变）")
            updates["current_wave"] = 1

            # 设置暂停状态（等待用户批准后才发送 layer_started）
            updates["pause_after_step"] = True
            updates["previous_layer"] = layer
            logger.info(f"[收集] Layer {layer} 完成，设置 pause_after_step=True，phase={phase}")

            # 更新 metadata 中的进度
            current_metadata = dict(state.get("metadata", {}))
            current_metadata["progress"] = (layer / 3) * 100
            current_metadata["version"] = current_metadata.get("version", 0) + 1
            updates["metadata"] = current_metadata

            # 发送层级完成事件（checkpoint_saved 由 _trigger_planning_execution 发送）
            session_id = state.get("session_id", "")
            _send_layer_completion_events(
                session_id=session_id,
                layer=layer,
                phase=phase,
                reports=reports,
                step_mode=state.get("step_mode", False),
            )

            updates["sse_events"] = []
        elif layer == 3:
            # Layer 3 completion: also pause for review
            logger.info(f"[collect] Layer 3 completed, setting pause for review")
            updates["current_wave"] = 1
            updates["pause_after_step"] = True
            updates["previous_layer"] = layer

            # Update metadata
            current_metadata = dict(state.get("metadata", {}))
            current_metadata["progress"] = 100
            current_metadata["version"] = current_metadata.get("version", 0) + 1
            updates["metadata"] = current_metadata

            # 发送层级完成事件（checkpoint_saved 由 _trigger_planning_execution 发送）
            session_id = state.get("session_id", "")
            _send_layer_completion_events(
                session_id=session_id,
                layer=layer,
                phase=phase,
                reports=reports,
                step_mode=state.get("step_mode", False),
            )

            updates["sse_events"] = []
    else:
        # 层级未完成，检查波次推进
        if layer in [2, 3]:
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
        logger.debug("[SSE-emit] 无事件需要发送")
        return {"sse_events": []}

    # Log event details
    event_types = [e.get("type", "unknown") for e in sse_events]
    logger.info(f"[SSE-emit] session_id={session_id}, 准备发送 {len(sse_events)} 个事件: {event_types}")

    # Check subscriber count before sending
    try:
        from backend.services.sse_manager import SSEManager
        subscriber_count = SSEManager.get_subscriber_count(session_id)
        logger.info(f"[SSE-emit] subscriber_count={subscriber_count} for session_id={session_id}")
        if subscriber_count == 0:
            logger.warning(f"[SSE-emit] 无订阅者，事件可能丢失！session_id={session_id}")
    except Exception as e:
        logger.warning(f"[SSE-emit] 无法获取订阅者数量: {e}")

    try:
        from ..utils.sse_publisher import SSEPublisher
        SSEPublisher.send_events_batch(session_id, sse_events)
        logger.info(f"[SSE-emit] 批量发送成功: {len(sse_events)} 个事件")
    except Exception as e:
        logger.error(f"[SSE-emit] 批量发送失败: {e}", exc_info=True)

    return {"sse_events": []}


# ==========================================
# 阶段推进检查
# ==========================================

def check_phase_completion(state: Dict[str, Any]) -> Literal["continue", "advance", "complete", "pause"]:
    """
    检查当前阶段是否完成

    Returns:
        "continue": 继续执行下一维度/波次（自动回到 route_planning）
        "advance": 推进到下一阶段
        "complete": 规划完成
        "pause": 暂停等待审查
    """
    # 暂停状态返回 pause
    if state.get("pause_after_step", False):
        logger.info("[完成检查] pause_after_step=True，返回 pause")
        return "pause"

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