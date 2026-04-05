"""
统一维度分析节点

将所有层级（Layer 1/2/3）的维度分析统一到一个节点，
使用 LangGraph Send API 实现动态路由和并行执行。

状态驱动的 SSE 事件发布，废弃回调模式。
"""

import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional, AsyncGenerator
from langchain_core.messages import AIMessage

from ...core.config import LLM_MODEL, MAX_TOKENS, LLM_STREAM_TIMEOUT, RAG_ENABLED
from ...core.llm_factory import create_llm
from ...config.dimension_metadata import get_dimension_config, get_dimension_layer
from ...utils.logger import get_logger
from ..state import PlanningPhase, get_layer_dimensions, get_wave_dimensions, _phase_to_layer

logger = get_logger(__name__)


# ==========================================
# RAG 知识预加载
# ==========================================

async def knowledge_preload_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    知识预加载节点 - 在维度分析前批量检索相关知识

    预加载模式下，知识由本节点统一检索并缓存到 knowledge_cache。
    后续维度节点从缓存读取，避免重复 RAG 调用。

    Args:
        state: 当前状态，包含 phase, config 等

    Returns:
        {"config": {"knowledge_cache": {维度键: 知识内容}}}
    """
    existing_config = state.get("config", {})
    if not RAG_ENABLED:
        logger.info("[知识预加载] RAG 未启用，跳过")
        return {"config": {**existing_config, "knowledge_cache": {}}}

    phase = state.get("phase", PlanningPhase.INIT.value)
    config = state.get("config", {})
    existing_cache = config.get("knowledge_cache", {})

    # 确定当前层级的维度列表
    layer = _phase_to_layer(phase)
    if layer is None:
        existing_config = state.get("config", {})
        logger.info(f"[知识预加载] 阶段 {phase} 无对应层级，跳过")
        return {"config": {**existing_config, "knowledge_cache": existing_cache}}

    dimensions = get_layer_dimensions(layer)
    if not dimensions:
        existing_config = state.get("config", {})
        logger.info(f"[知识预加载] Layer {layer} 无维度，跳过")
        return {"config": {**existing_config, "knowledge_cache": existing_cache}}

    logger.info(f"[知识预加载] 开始预加载 Layer {layer} 知识，维度: {len(dimensions)} 个")

    # 批量检索知识
    from ...rag.core.tools import search_knowledge

    knowledge_cache = {}
    task_description = config.get("task_description", "")
    success_count = 0
    fail_count = 0
    success_details = []

    for dim_key in dimensions:
        # 如果已有缓存，跳过
        if dim_key in existing_cache and existing_cache[dim_key]:
            knowledge_cache[dim_key] = existing_cache[dim_key]
            logger.debug(f"[知识预加载] {dim_key} 已缓存，跳过")
            success_count += 1
            success_details.append(f"{dim_key}({len(existing_cache[dim_key])})")
            continue

        try:
            # 构建检索查询：维度名称 + 任务描述
            dim_name = DIMENSION_NAMES.get(dim_key, dim_key)
            query = f"{dim_name} 规划标准 技术指标"

            # 添加任务上下文
            if task_description:
                query = f"{query} {task_description[:50]}"

            # 移除 dimension 参数：ChromaDB 不支持数组类型的 metadata 过滤
            # dimension_tags 存储为逗号分隔字符串，$in 操作符只能精确匹配整个字符串
            # 依赖向量相似度搜索自然偏向相关内容即可
            result = search_knowledge(
                query=query,
                top_k=3,
                context_mode="standard"
            )

            if result and not result.startswith("❌"):
                knowledge_cache[dim_key] = result
                success_count += 1
                success_details.append(f"{dim_key}({len(result)})")
                logger.debug(f"[知识预加载] {dim_key} 检索成功，长度: {len(result)}")
            else:
                knowledge_cache[dim_key] = ""
                fail_count += 1
                logger.debug(f"[知识预加载] {dim_key} 检索无结果")

        except Exception as e:
            logger.error(f"[知识预加载] {dim_key} 检索失败: {e}")
            knowledge_cache[dim_key] = ""
            fail_count += 1

    # 汇总日志
    logger.info(f"[知识预加载] 完成: {success_count} 成功, {fail_count} 失败")
    if success_details:
        logger.info(f"[知识预加载] 成功维度: {', '.join(success_details[:6])}")

    existing_config = state.get("config", {})
    return {"config": {**existing_config, "knowledge_cache": knowledge_cache}}


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
    logger.debug(f"[维度节点-Send] 开始分析: {dimension_name} ({dimension_key}), Layer: {layer}")

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

    # 获取上下文 - 根据层级区分数据来源
    village_data = config.get("village_data", "")
    village_name = config.get("village_name", "")
    task_description = config.get("task_description", "")
    constraints = config.get("constraints", "")
    knowledge_cache = config.get("knowledge_cache", {})

    # 区分层级数据来源
    if layer == 2:
        layer1_reports = reports.get("layer1", {})
        if layer1_reports:
            logger.debug(f"[维度节点] Layer 2 使用 Layer 1 报告，维度数: {len(layer1_reports)}")
        else:
            logger.warning(f"[维度节点] Layer 2 执行但 Layer 1 报告为空!")
    elif layer == 3:
        layer1_reports = reports.get("layer1", {})
        layer2_reports = reports.get("layer2", {})
        logger.debug(f"[维度节点] Layer 3 使用 Layer 1 ({len(layer1_reports)}) + Layer 2 ({len(layer2_reports)}) 报告")
    else:
        logger.debug(f"[维度节点] Layer 1 使用 village_data")

    # 构建 prompt
    prompt = _build_dimension_prompt(
        dimension_key=dimension_key,
        dimension_name=dimension_name,
        village_data=village_data,
        village_name=village_name,
        task_description=task_description,
        constraints=constraints,
        reports=reports,
        knowledge_cache=knowledge_cache
    )

    # 调用 LLM（流式，收集 token 事件）
    llm = create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS, streaming=True)

    # Record start time for diagnostics
    start_time = asyncio.get_event_loop().time()
    logger.debug(f"[维度节点-Send] LLM 调用开始: {dimension_name}")

    # 实时发送：直接调用 SSEPublisher 发送 delta 事件
    # 不再收集到 sse_events 数组，避免批量发送时的队列溢出
    from ...utils.sse_publisher import SSEPublisher

    async def collect_stream():
        """Collect streaming result with real-time SSE publishing"""
        collected_result = ""
        async for chunk in llm.astream(prompt):
            if chunk.content:
                token = chunk.content
                collected_result += token
                # 实时发送 delta 事件（不再收集到数组）
                if len(collected_result) % 15 == 0 or len(collected_result) <= 30:
                    SSEPublisher.send_dimension_delta(
                        session_id=session_id,
                        layer=layer,
                        dimension_key=dimension_key,
                        dimension_name=dimension_name,
                        token=token,
                        accumulated=collected_result
                    )
        return collected_result

    try:
        # Use asyncio.wait_for for timeout protection
        result = await asyncio.wait_for(
            collect_stream(),
            timeout=LLM_STREAM_TIMEOUT
        )

        elapsed = asyncio.get_event_loop().time() - start_time
        logger.info(f"[维度节点-Send] LLM 调用完成: {dimension_name}, 耗时: {elapsed:.1f}s")

        # Send final delta (实时发送，确保完整内容)
        SSEPublisher.send_dimension_delta(
            session_id=session_id,
            layer=layer,
            dimension_key=dimension_key,
            dimension_name=dimension_name,
            token="",
            accumulated=result
        )

        # Send dimension complete event (实时发送，确保事件不丢失)
        SSEPublisher.send_dimension_complete(
            session_id=session_id,
            layer=layer,
            dimension_key=dimension_key,
            dimension_name=dimension_name,
            full_content=result
        )

        # Keep a placeholder in sse_events for state tracking only
        sse_events.append(_create_sse_event(
            event_type="dimension_complete_sent",
            session_id=session_id,
            layer=layer,
            dimension_key=dimension_key,
            dimension_name=dimension_name
        ))

        elapsed_total = asyncio.get_event_loop().time() - start_time
        logger.info(f"[维度节点-Send] 分析完成: {dimension_name}, 长度: {len(result)}, 总耗时: {elapsed_total:.1f}s")

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

    except asyncio.TimeoutError:
        elapsed = asyncio.get_event_loop().time() - start_time
        logger.error(f"[维度节点-Send] LLM 调用超时: {dimension_name}, 耗时: {elapsed:.1f}s")

        # Send timeout error event
        sse_events.append(_create_sse_event(
            event_type="dimension_error",
            session_id=session_id,
            layer=layer,
            dimension_key=dimension_key,
            dimension_name=dimension_name,
            error=f"LLM 调用超时 (>{LLM_STREAM_TIMEOUT}s)",
            error_type="timeout"
        ))

        return {
            "dimension_results": [{
                "dimension_key": dimension_key,
                "dimension_name": dimension_name,
                "result": f"分析超时: LLM 调用超过 {LLM_STREAM_TIMEOUT} 秒",
                "success": False,
                "layer": layer,
                "error_type": "timeout"
            }],
            "sse_events": sse_events
        }

    except Exception as e:
        elapsed = asyncio.get_event_loop().time() - start_time
        logger.error(f"[维度节点-Send] 分析失败: {dimension_name}, 耗时: {elapsed:.1f}s, 错误: {e}")

        # Send error event
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
    village_name = config.get("village_name", "")
    task_description = config.get("task_description", "")
    constraints = config.get("constraints", "")
    knowledge_cache = config.get("knowledge_cache", {})

    # 构建 prompt
    prompt = _build_dimension_prompt(
        dimension_key=dimension_key,
        dimension_name=dimension_name,
        village_data=village_data,
        village_name=village_name,
        task_description=task_description,
        constraints=constraints,
        reports=reports,
        knowledge_cache=knowledge_cache
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
    reports: Dict[str, Dict[str, str]],
    village_name: str = "",
    knowledge_cache: Dict[str, str] = None
) -> str:
    """构建维度分析 prompt - 使用专业模板"""
    layer = get_dimension_layer(dimension_key) or 3
    knowledge_cache = knowledge_cache or {}

    # 从缓存获取当前维度的知识
    knowledge_context = knowledge_cache.get(dimension_key, "")

    # Layer 1: 使用 analysis_prompts 模板
    if layer == 1:
        from ...subgraphs.analysis_prompts import get_dimension_prompt
        return get_dimension_prompt(
            dimension_key=dimension_key,
            raw_data=village_data,
            village_name=village_name,
            professional_data=None,
            task_description=task_description,
            constraints=constraints,
            knowledge_context=knowledge_context
        )

    # Layer 2: 使用 concept_prompts 模板（按依赖配置筛选）
    elif layer == 2:
        from ...subgraphs.concept_prompts import get_dimension_prompt
        from ...config.dimension_metadata import (
            get_full_dependency_chain_func,
            get_analysis_dimension_names,
            filter_reports_by_dependency,
        )

        chain = get_full_dependency_chain_func(dimension_key)
        layer1_reports = reports.get("layer1", {})

        analysis_summary = filter_reports_by_dependency(
            required_keys=chain.get("layer1_analyses", []),
            reports=layer1_reports,
            name_mapping=get_analysis_dimension_names()
        )

        logger.info(f"[Dimension-Prompt] {dimension_key}: "
                   f"筛选后 Layer1={len(chain.get('layer1_analyses', []))}/{len(layer1_reports)} 个")

        return get_dimension_prompt(
            dimension_key=dimension_key,
            analysis_report=analysis_summary,
            task_description=task_description,
            constraints=constraints,
            superior_planning_context=_get_superior_planning_context(reports),
            knowledge_context=knowledge_context
        )

    # Layer 3: 使用 detailed_plan_prompts 模板（按依赖配置筛选）
    elif layer == 3:
        from ...subgraphs.detailed_plan_prompts import get_dimension_prompt
        from ...config.dimension_metadata import (
            get_full_dependency_chain_func,
            get_analysis_dimension_names,
            get_concept_dimension_names,
            get_detailed_dimension_names,
            filter_reports_by_dependency,
        )

        chain = get_full_dependency_chain_func(dimension_key)
        layer1_reports = reports.get("layer1", {})
        layer2_reports = reports.get("layer2", {})
        layer3_reports = reports.get("layer3", {})

        analysis_summary = filter_reports_by_dependency(
            required_keys=chain.get("layer1_analyses", []),
            reports=layer1_reports,
            name_mapping=get_analysis_dimension_names()
        )
        concept_summary = filter_reports_by_dependency(
            required_keys=chain.get("layer2_concepts", []),
            reports=layer2_reports,
            name_mapping=get_concept_dimension_names()
        )
        dimension_plans = filter_reports_by_dependency(
            required_keys=chain.get("layer3_plans", []),
            reports=layer3_reports,
            name_mapping=get_detailed_dimension_names()
        )

        logger.info(f"[Dimension-Prompt] {dimension_key}: "
                   f"筛选后 Layer1={len(chain.get('layer1_analyses', []))}/{len(layer1_reports)} 个, "
                   f"Layer2={len(chain.get('layer2_concepts', []))}/{len(layer2_reports)} 个, "
                   f"Layer3={len(chain.get('layer3_plans', []))} 个")

        return get_dimension_prompt(
            dimension_key=dimension_key,
            project_name="",
            analysis_report=analysis_summary,
            planning_concept=concept_summary,
            constraints=constraints,
            professional_data=None,
            dimension_plans=dimension_plans,
            knowledge_context=knowledge_context
        )

    # Fallback: 使用简化 prompt
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
    "knowledge_preload_node",
    "DIMENSION_NAMES",
    "get_layer_from_dimension",
]