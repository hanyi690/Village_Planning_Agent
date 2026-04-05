"""
IntentRouter - 意图路由服务

从图中提取的意图决策逻辑，支持：
1. API 层直接调用（/chat 端点）
2. 返回结构化的路由决策

Architecture:
    API Layer → IntentRouter → LangGraph (conversation_node logic)
"""

import logging
from typing import Dict, Any, Optional, List
from enum import Enum

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from src.core.config import LLM_MODEL, MAX_TOKENS
from src.core.llm_factory import create_llm
from src.constants.tools import ADVANCE_PLANNING_TOOL

logger = logging.getLogger(__name__)


class IntentType(str, Enum):
    """意图类型枚举"""
    CHAT = "chat"
    TOOL_CALL = "tool_call"
    ADVANCE_PLANNING = "advance_planning"


class IntentRouter:
    """
    意图路由服务 - 简化版

    复用图中的 conversation_node 逻辑，不创建新的 LLM 实例。
    """

    @staticmethod
    async def route(
        session_id: str,
        user_message: str,
        state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行意图路由，返回决策结果。

        Args:
            session_id: 会话 ID
            user_message: 用户消息
            state: 当前状态（包含 messages, phase, config, reports 等）

        Returns:
            {
                "intent": IntentType,
                "response": str,  # LLM 响应内容
                "tool_calls": List,  # 工具调用列表（如果有）
                "ai_message": AIMessage  # 原始 AI 消息
            }
        """
        from src.orchestration.state import PHASE_DESCRIPTIONS, LAYER_NAMES
        from src.orchestration.nodes.dimension_node import DIMENSION_NAMES

        messages = list(state.get("messages", []))
        phase = state.get("phase", "init")
        project_name = state.get("project_name", "")
        config = state.get("config", {})
        reports = state.get("reports", {})

        # 构建系统提示（与 conversation_node 一致）
        reports_summary = ""
        for layer_key, layer_reports in reports.items():
            if layer_reports:
                layer_name = LAYER_NAMES.get(layer_key, layer_key)
                reports_summary += f"\n{layer_name}:\n"
                for dim_key, content in list(layer_reports.items())[:3]:
                    dim_name = DIMENSION_NAMES.get(dim_key, dim_key)
                    preview = content[:100] + "..." if len(content) > 100 else content
                    reports_summary += f"  - {dim_name}: {preview}\n"

        system_prompt = f"""你是村庄规划助手，正在进行 {project_name} 的规划工作。

当前阶段：{PHASE_DESCRIPTIONS.get(phase, '未知')}

规划任务：{config.get('task_description', '制定村庄发展规划')}
约束条件：{config.get('constraints', '无特殊约束')}
{f"已有成果：{reports_summary}" if reports_summary else ""}

你可以：
1. 回答用户关于规划的问题
2. 调用工具获取数据（使用标准工具调用格式）
3. 推进规划进度（调用 AdvancePlanningIntent 工具）

请根据用户意图自然地响应。如果用户表示要"继续规划"、"开始分析"、"下一步"等，请调用 AdvancePlanningIntent 工具。"""

        # 构建消息列表
        full_messages = [SystemMessage(content=system_prompt)] + messages + [HumanMessage(content=user_message)]

        # 获取 LLM 并绑定工具
        llm = create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS)
        llm_with_tools = llm.bind_tools([ADVANCE_PLANNING_TOOL])

        # 调用 LLM
        response = await llm_with_tools.ainvoke(full_messages)

        logger.info(f"[IntentRouter] [{session_id}] LLM 响应: tool_calls={getattr(response, 'tool_calls', None)}")

        # 解析意图
        if hasattr(response, "tool_calls") and response.tool_calls:
            for tool_call in response.tool_calls:
                tool_name = tool_call.get("name", "")
                if tool_name == "AdvancePlanningIntent":
                    return {
                        "intent": IntentType.ADVANCE_PLANNING,
                        "response": response.content or "",
                        "tool_calls": response.tool_calls,
                        "ai_message": response
                    }
            # 其他工具调用
            return {
                "intent": IntentType.TOOL_CALL,
                "response": response.content or "",
                "tool_calls": response.tool_calls,
                "tool_name": response.tool_calls[0].get("name", "") if response.tool_calls else "",
                "ai_message": response
            }

        # 普通对话
        return {
            "intent": IntentType.CHAT,
            "response": response.content or "",
            "tool_calls": None,
            "ai_message": response
        }

    @staticmethod
    def parse_intent_from_state(state: Dict[str, Any]) -> IntentType:
        """
        从现有状态解析意图（用于路由检查）

        Args:
            state: 包含 messages 的状态

        Returns:
            IntentType 枚举值
        """
        messages = state.get("messages", [])
        if not messages:
            return IntentType.CHAT

        last_msg = messages[-1]

        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            for tool_call in last_msg.tool_calls:
                if tool_call.get("name") == "AdvancePlanningIntent":
                    return IntentType.ADVANCE_PLANNING
            return IntentType.TOOL_CALL

        return IntentType.CHAT


# Singleton instance
intent_router = IntentRouter()


__all__ = ["IntentRouter", "IntentType", "intent_router"]