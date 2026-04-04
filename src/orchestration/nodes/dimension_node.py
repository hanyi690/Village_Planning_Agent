"""
统一维度分析节点

将所有层级（Layer 1/2/3）的维度分析统一到一个节点，
使用 LangGraph Send API 实现动态路由和并行执行。

状态驱动的 SSE 事件发布，废弃回调模式。
"""

from datetime import datetime
from typing import Dict, Any, List, Optional, AsyncGenerator
from langchain_core.messages import AIMessage

from ...core.config import LLM_MODEL, MAX_TOKENS
from ...core.llm_factory import create_llm
from ...config.dimension_metadata import get_dimension_config, get_dimension_layer
from ...utils.logger import get_logger
from ..state import PlanningPhase, get_layer_dimensions, get_wave_dimensions

logger = get_logger(__name__)


# ==========================================
# 维度配置 - 从 authoritative source 获取
# ==========================================

def _get_dimension_name(dimension_key: str) -> str:
    """从权威配置获取维度显示名称"""
    config = get_dimension_config(dimension_key)
    return config.get("name", dimension_key) if config else dimension_key


# 缓存 DIMENSION_NAMES 用于快速查找
def _build_dimension_names() -> Dict[str, str]:
    """构建维度名称映射表"""
    from ...config.dimension_metadata import list_dimensions
    return {dim["key"]: dim["name"] for dim in list_dimensions()}


DIMENSION_NAMES = _build_dimension_names()


def get_layer_from_dimension(dimension_key: str) -> int:
    """根据维度键名判断所属层级"""
    layer = get_dimension_layer(dimension_key)
    return layer if layer is not None else 3


# ==========================================
# SSE 事件构建辅助函数
# ==========================================

def _create_sse_event(
    event_type: str,
    session_id: str,
    layer: int,
    dimension_key: str,
    dimension_name: str,
    **kwargs
) -> Dict[str, Any]:
    """构建 SSE 事件字典"""
    return {
        "type": event_type,
        "timestamp": datetime.now().isoformat(),
        "session_id": session_id,
        "layer": layer,
        "dimension_key": dimension_key,
        "dimension_name": dimension_name,
        **kwargs
    }


# ==========================================
# 维度分析节点（状态驱动版本）
# ==========================================

async def analyze_dimension_for_send(
    state: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Send API 专用维度分析节点

    返回 dimension_results 和 sse_events，支持状态自动合并。

    Args:
        state: 包含 dimension_key, session_id, config, reports 等的状态字典

    Returns:
        {
            "dimension_results": [{dimension_key, dimension_name, result, success, layer}],
            "sse_events": [事件列表]
        }
    """
    dimension_key = state.get("dimension_key", "")
    session_id = state.get("session_id", "")
    project_name = state.get("project_name", "")
    config = state.get("config", {})
    reports = state.get("reports", {})

    dimension_name = DIMENSION_NAMES.get(dimension_key, dimension_key)
    layer = get_layer_from_dimension(dimension_key)
    logger.info(f"[维度节点-Send] 开始分析: {dimension_name} ({dimension_key}), Layer: {layer}")

    # 构建 SSE 事件列表
    sse_events = []

    # 发送维度开始事件
    sse_events.append(_create_sse_event(
        event_type="dimension_start",
        session_id=session_id,
        layer=layer,
        dimension_key=dimension_key,
        dimension_name=dimension_name
    ))

    # 获取上下文
    village_data = config.get("village_data", "")
    task_description = config.get("task_description", "")
    constraints = config.get("constraints", "")

    # 构建 prompt
    prompt = _build_dimension_prompt(
        dimension_key=dimension_key,
        dimension_name=dimension_name,
        village_data=village_data,
        task_description=task_description,
        constraints=constraints,
        reports=reports
    )

    # 调用 LLM（流式，收集 token 事件）
    llm = create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS, streaming=True)

    try:
        # 流式模式：收集所有 token 事件
        result = ""
        async for chunk in llm.astream(prompt):
            if chunk.content:
                token = chunk.content
                result += token
                # 每 10 个字符发送一次 delta 事件（减少事件数量）
                if len(result) % 50 == 0 or len(result) < 100:
                    sse_events.append(_create_sse_event(
                        event_type="dimension_delta",
                        session_id=session_id,
                        layer=layer,
                        dimension_key=dimension_key,
                        dimension_name=dimension_name,
                        delta=token,
                        accumulated=result
                    ))

        # 发送最后一次 delta（确保完整内容）
        sse_events.append(_create_sse_event(
            event_type="dimension_delta",
            session_id=session_id,
            layer=layer,
            dimension_key=dimension_key,
            dimension_name=dimension_name,
            delta="",
            accumulated=result
        ))

        # 发送维度完成事件
        sse_events.append(_create_sse_event(
            event_type="dimension_complete",
            session_id=session_id,
            layer=layer,
            dimension_key=dimension_key,
            dimension_name=dimension_name,
            full_content=result
        ))

        logger.info(f"[维度节点-Send] 分析完成: {dimension_name}, 长度: {len(result)}")

        return {
            "dimension_results": [{
                "dimension_key": dimension_key,
                "dimension_name": dimension_name,
                "result": result,
                "success": True,
                "layer": layer
            }],
            "sse_events": sse_events
        }

    except Exception as e:
        logger.error(f"[维度节点-Send] 分析失败: {dimension_name}, 错误: {e}")

        # 发送错误事件
        sse_events.append(_create_sse_event(
            event_type="dimension_error",
            session_id=session_id,
            layer=layer,
            dimension_key=dimension_key,
            dimension_name=dimension_name,
            error=str(e)
        ))

        return {
            "dimension_results": [{
                "dimension_key": dimension_key,
                "dimension_name": dimension_name,
                "result": f"分析失败: {str(e)}",
                "success": False,
                "layer": layer
            }],
            "sse_events": sse_events
        }


# ==========================================
# 兼容旧版本的节点（保留回调模式）
# ==========================================

async def analyze_dimension_node(
    state: Dict[str, Any],
    on_token: Optional[callable] = None
) -> Dict[str, Any]:
    """
    统一维度分析节点（兼容版本）

    根据当前 phase 和 dimension 执行分析，支持三层。
    保持向后兼容，支持 on_token 回调。

    Args:
        state: 包含 dimension_key, session_id, config, reports 等的状态字典
        on_token: 可选的 token 回调函数 (token: str, accumulated: str) -> None（废弃）

    Returns:
        包含 dimension_key, dimension_name, result, success 的字典
    """
    # 如果没有 on_token，使用 Send API 版本
    if on_token is None:
        result = await analyze_dimension_for_send(state)
        # 提取单个结果
        if result["dimension_results"]:
            return result["dimension_results"][0]
        return {"success": False, "result": "", "dimension_key": state.get("dimension_key", "")}

    # 有 on_token，使用旧版本流式模式
    dimension_key = state.get("dimension_key", "")
    session_id = state.get("session_id", "")
    project_name = state.get("project_name", "")
    config = state.get("config", {})
    reports = state.get("reports", {})

    dimension_name = DIMENSION_NAMES.get(dimension_key, dimension_key)
    layer = get_layer_from_dimension(dimension_key)
    logger.info(f"[维度节点] 开始分析: {dimension_name} ({dimension_key}), Layer: {layer}")

    # 获取上下文
    village_data = config.get("village_data", "")
    task_description = config.get("task_description", "")
    constraints = config.get("constraints", "")

    # 构建 prompt
    prompt = _build_dimension_prompt(
        dimension_key=dimension_key,
        dimension_name=dimension_name,
        village_data=village_data,
        task_description=task_description,
        constraints=constraints,
        reports=reports
    )

    # 调用 LLM（流式）
    llm = create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS, streaming=True)

    try:
        result = await _stream_llm(llm, prompt, dimension_key, on_token)

        logger.info(f"[维度节点] 分析完成: {dimension_name}, 长度: {len(result)}")

        return {
            "dimension_key": dimension_key,
            "dimension_name": dimension_name,
            "result": result,
            "success": True
        }
    except Exception as e:
        logger.error(f"[维度节点] 分析失败: {dimension_name}, 错误: {e}")
        return {
            "dimension_key": dimension_key,
            "dimension_name": dimension_name,
            "result": f"分析失败: {str(e)}",
            "success": False
        }


async def _stream_llm(
    llm,
    prompt: str,
    dimension_key: str,
    on_token: callable
) -> str:
    """
    流式调用 LLM 并发送 token 回调（旧版本兼容）

    Args:
        llm: LLM 实例
        prompt: 提示词
        dimension_key: 维度键名
        on_token: token 回调函数

    Returns:
        完整的结果字符串
    """
    accumulated = ""

    async for chunk in llm.astream(prompt):
        if chunk.content:
            token = chunk.content
            accumulated += token
            on_token(token, accumulated)

    return accumulated


# ==========================================
# Prompt 构建 - 使用专业模板
# ==========================================

def _build_dimension_prompt(
    dimension_key: str,
    dimension_name: str,
    village_data: str,
    task_description: str,
    constraints: str,
    reports: Dict[str, Dict[str, str]]
) -> str:
    """构建维度分析 prompt - 使用专业模板"""
    layer = get_dimension_layer(dimension_key) or 3

    # Layer 1: 使用 analysis_prompts 模板
    if layer == 1:
        from ...subgraphs.analysis_prompts import get_dimension_prompt
        return get_dimension_prompt(
            dimension_key=dimension_key,
            raw_data=village_data,
            professional_data=None,  # TODO: 从 state 获取专业数据
            task_description=task_description,
            constraints=constraints
        )

    # Layer 2: 使用 concept_prompts 模板
    elif layer == 2:
        from ...subgraphs.concept_prompts import get_dimension_prompt
        # 构建 Layer 1 报告摘要
        layer1_reports = reports.get("layer1", {})
        analysis_summary = _format_layer1_summary(layer1_reports)

        return get_dimension_prompt(
            dimension_key=dimension_key,
            analysis_report=analysis_summary,
            task_description=task_description,
            constraints=constraints,
            superior_planning_context=_get_superior_planning_context(reports)
        )

    # Layer 3: 使用 detailed_plan_prompts 模板
    elif layer == 3:
        from ...subgraphs.detailed_plan_prompts import get_dimension_prompt
        # 构建 Layer 1 和 Layer 2 报告摘要
        layer1_reports = reports.get("layer1", {})
        layer2_reports = reports.get("layer2", {})
        analysis_summary = _format_layer1_summary(layer1_reports)
        concept_summary = _format_layer2_summary(layer2_reports)

        # 前序详细规划（project_bank 专用）
        dimension_plans = _get_dimension_plans(reports, dimension_key)

        return get_dimension_prompt(
            dimension_key=dimension_key,
            project_name="",  # TODO: 从 state 获取项目名
            analysis_report=analysis_summary,
            planning_concept=concept_summary,
            constraints=constraints,
            professional_data=None,  # TODO: 从 state 获取专业数据
            dimension_plans=dimension_plans,
            knowledge_context=""  # TODO: 从 state 获取 RAG 知识
        )

    # Fallback: 使用简化 prompt（不应到达）
    return _build_fallback_prompt(dimension_name, village_data, task_description, constraints)


def _format_layer1_summary(layer1_reports: Dict[str, str]) -> str:
    """格式化 Layer 1 报告摘要"""
    if not layer1_reports:
        return "暂无现状分析报告"

    parts = []
    for key, content in layer1_reports.items():
        dim_name = DIMENSION_NAMES.get(key, key)
        # 截取前 500 字符作为摘要
        summary = content[:500] if len(content) > 500 else content
        parts.append(f"### {dim_name}\n{summary}\n")
    return "\n".join(parts)


def _format_layer2_summary(layer2_reports: Dict[str, str]) -> str:
    """格式化 Layer 2 报告摘要"""
    if not layer2_reports:
        return "暂无规划思路报告"

    parts = []
    for key, content in layer2_reports.items():
        dim_name = DIMENSION_NAMES.get(key, key)
        summary = content[:500] if len(content) > 500 else content
        parts.append(f"### {dim_name}\n{summary}\n")
    return "\n".join(parts)


def _get_superior_planning_context(reports: Dict) -> str:
    """获取上位规划上下文（从 Layer 1 的 superior_planning 维度）"""
    layer1 = reports.get("layer1", {})
    superior = layer1.get("superior_planning", "")
    if superior:
        return f"基于现状分析中的上位规划分析：\n{superior[:800]}"
    return "暂无上位规划参考"


def _get_dimension_plans(reports: Dict, current_key: str) -> str:
    """获取前序详细规划内容（project_bank 维度专用）"""
    layer3 = reports.get("layer3", {})
    if current_key != "project_bank":
        return ""

    # 收集所有已完成的 Layer 3 规划
    plans = []
    for key, content in layer3.items():
        if key != "project_bank" and content:
            dim_name = DIMENSION_NAMES.get(key, key)
            plans.append(f"### {dim_name}\n{content[:300]}\n")
    return "\n".join(plans)


def _build_fallback_prompt(dimension_name: str, village_data: str,
                           task_description: str, constraints: str) -> str:
    """构建备用简化 prompt（仅用于未知维度）"""
    return f"""
你是一位专业的村庄规划师，正在为村庄制定规划方案。

## 任务
请完成「{dimension_name}」分析。

## 村庄基础数据
{village_data[:3000]}

## 规划任务
{task_description}

## 约束条件
{constraints}

## 要求
1. 分析要专业、全面、具体
2. 结合村庄实际情况提出建议
3. 输出格式清晰，使用 Markdown 格式

请开始分析：
"""


# ==========================================
# 维度状态创建
# ==========================================

def create_dimension_state(
    dimension_key: str,
    parent_state: Dict[str, Any]
) -> Dict[str, Any]:
    """
    为单个维度分析创建状态（Send API 用）

    Args:
        dimension_key: 维度标识
        parent_state: 父状态

    Returns:
        维度分析状态
    """
    return {
        "dimension_key": dimension_key,
        "dimension_name": DIMENSION_NAMES.get(dimension_key, dimension_key),
        "session_id": parent_state.get("session_id", ""),
        "project_name": parent_state.get("project_name", ""),
        "config": parent_state.get("config", {}),
        "reports": parent_state.get("reports", {}),
        "completed_dimensions": parent_state.get("completed_dimensions", {}),
    }


__all__ = [
    "analyze_dimension_node",
    "analyze_dimension_for_send",
    "create_dimension_state",
    "DIMENSION_NAMES",
    "get_layer_from_dimension",
]