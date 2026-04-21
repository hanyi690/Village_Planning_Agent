"""
统一维度分析节点

将所有层级（Layer 1/2/3）的维度分析统一到一个节点，
使用 LangGraph Send API 实现动态路由和并行执行。

状态驱动的 SSE 事件发布，废弃回调模式。
"""

import asyncio
import time
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional, AsyncGenerator, Union, TYPE_CHECKING
from langchain_core.messages import AIMessage

from ...core.config import LLM_MODEL, MAX_TOKENS, LLM_STREAM_TIMEOUT, RAG_ENABLED, DEFAULT_IMAGE_FORMAT, LLM_MAX_CONCURRENT
from ...core.llm_factory import create_llm
from ...core.message_builder import build_multimodal_message
from ...config.dimension_metadata import get_dimension_config, get_dimension_layer
from ...utils.logger import get_logger
from ..state import PlanningPhase, get_layer_dimensions, get_wave_dimensions, _phase_to_layer
from ...tools.types import normalize_tool_result, NormalizedToolResult, ResultDataType

logger = get_logger(__name__)

# ==========================================
# 全局 LLM 并发控制 - Send API 跨节点共享
# ==========================================
_LLM_SEMAPHORE = asyncio.Semaphore(LLM_MAX_CONCURRENT)


# ==========================================
# ParamSource 枚举 - 工具参数来源类型
# ==========================================

class ParamSource(str, Enum):
    """工具参数来源枚举"""
    LITERAL = "literal"      # 固定值
    GIS_CACHE = "gis_cache"  # 从 GIS 分析结果缓存取值
    CONFIG = "config"        # 从 state.config 取值
    CONTEXT = "context"      # 从 context 直接取值


# ==========================================
# RAG 知识预加载
# ==========================================

async def knowledge_preload_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    知识预加载节点 - 在维度分析前批量检索相关知识（并行版本）

    预加载模式下，知识由本节点统一检索并缓存到 knowledge_cache。
    后续维度节点从缓存读取，避免重复 RAG 调用。

    使用 asyncio.gather 并行执行，将总时间从串行时间降至 max(各维度时间)。

    Args:
        state: 当前状态，包含 phase, config 等

    Returns:
        {"config": {"knowledge_cache": {维度键: 知识内容}}}
    """
    existing_config = state.get("config", {})
    if not RAG_ENABLED:
        logger.info("[知识预加载] RAG 未启用，跳过")
        return {"config": {**existing_config, "knowledge_cache": {}, "knowledge_sources_cache": {}}}

    phase = state.get("phase", PlanningPhase.INIT.value)
    config = state.get("config", {})
    existing_cache = config.get("knowledge_cache", {})
    existing_sources_cache = config.get("knowledge_sources_cache", {})

    layer = _phase_to_layer(phase)
    if layer is None:
        logger.info(f"[知识预加载] 阶段 {phase} 无对应层级，跳过")
        return {"config": {**existing_config, "knowledge_cache": existing_cache, "knowledge_sources_cache": existing_sources_cache}}

    dimensions = get_layer_dimensions(layer)
    if not dimensions:
        logger.info(f"[知识预加载] Layer {layer} 无维度，跳过")
        return {"config": {**existing_config, "knowledge_cache": existing_cache, "knowledge_sources_cache": existing_sources_cache}}

    logger.info(f"[知识预加载] 开始预加载 Layer {layer} 知识，维度: {len(dimensions)} 个（并行执行）")

    from ...rag.core.tools import search_knowledge, extract_sources_from_documents
    from ...rag.core.cache import get_vector_cache

    knowledge_cache = {}
    knowledge_sources_cache = {}
    task_description = config.get("task_description", "")
    success_details = []

    # Separate cached dimensions (skip) vs. dimensions needing fetch
    cached_dims = []
    fetch_dims = []
    for dim_key in dimensions:
        if dim_key in existing_cache and existing_cache[dim_key]:
            cached_dims.append(dim_key)
        else:
            fetch_dims.append(dim_key)

    # Process cached dimensions immediately
    for dim_key in cached_dims:
        knowledge_cache[dim_key] = existing_cache[dim_key]
        if dim_key in existing_sources_cache:
            knowledge_sources_cache[dim_key] = existing_sources_cache[dim_key]
        success_details.append(f"{dim_key}(cached)")

    # Parallel fetch for non-cached dimensions with semaphore
    semaphore = asyncio.Semaphore(LLM_MAX_CONCURRENT)

    async def fetch_one(dim_key: str) -> tuple:
        """Fetch knowledge for one dimension with dynamic query enhancement"""
        async with semaphore:
            dim_name = DIMENSION_NAMES.get(dim_key, dim_key)

            # Dynamic query: use summary tags for Layer 2/3
            from ...utils.summary_generator import build_dynamic_query

            if layer >= 2:
                # Use dynamic query with summary tags (Phase 2 enhancement)
                enhanced_query = build_dynamic_query(dim_key, layer, state)
                fallback_query = f"{dim_name} 规划标准 技术指标"
                if task_description:
                    fallback_query = f"{fallback_query} {task_description[:50]}"
                query = enhanced_query
            else:
                # Layer 1: traditional query (no dependency summaries yet)
                query = f"{dim_name} 规划标准 技术指标"
                if task_description:
                    query = f"{query} {task_description[:50]}"
                fallback_query = None

            context_params = {
                "top_k": 3,
                "context_mode": "standard",
                "dimension": dim_key,
                "terrain": None,
                "doc_type": None,
                "task_id": None,
                "include_summaries": False,
            }

            try:
                result = await asyncio.to_thread(
                    search_knowledge,
                    query=query,
                    top_k=3,
                    context_mode="standard",
                    dimension=dim_key,
                )
                final_query = query

                if layer >= 2 and fallback_query and (not result or result.startswith("❌") or len(result) < 100):
                    logger.info(f"[知识预加载] {dim_key} 增强查询结果不足，尝试降级查询")
                    result = await asyncio.to_thread(
                        search_knowledge,
                        query=fallback_query,
                        top_k=3,
                        context_mode="standard",
                        dimension=dim_key,
                    )
                    final_query = fallback_query

                sources = []
                if result and not result.startswith("❌"):
                    cache = get_vector_cache()
                    cached_docs = cache.get_cached_query(final_query, context_params)
                    if cached_docs:
                        sources = extract_sources_from_documents(cached_docs)
                    logger.info(f"[知识预加载] {dim_key} 检索成功，长度: {len(result)}, 切片数: {len(sources)}")
                    return (dim_key, result, sources)
                else:
                    logger.debug(f"[知识预加载] {dim_key} 检索无结果")
                    return (dim_key, "", [])
            except Exception as e:
                logger.error(f"[知识预加载] {dim_key} 检索失败: {e}")
                return (dim_key, "", [])

    # Execute parallel fetch
    start_time = asyncio.get_event_loop().time()
    if fetch_dims:
        results = await asyncio.gather(*[fetch_one(dim) for dim in fetch_dims])
        elapsed = asyncio.get_event_loop().time() - start_time

        for dim_key, result, sources in results:
            knowledge_cache[dim_key] = result
            knowledge_sources_cache[dim_key] = sources
            if result:
                success_details.append(f"{dim_key}({len(result)})")

        success_count = len([r for r in results if r[1]])
        fail_count = len(fetch_dims) - success_count
        logger.info(f"[知识预加载] 完成: {success_count} 成功, {fail_count} 失败, 耗时: {elapsed:.1f}s（并行）")
    else:
        logger.info(f"[知识预加载] 全部维度已缓存，无需重新检索")

    if success_details:
        logger.info(f"[知识预加载] 成功维度: {', '.join(success_details[:6])}")

    existing_config = state.get("config", {})
    return {"config": {**existing_config, "knowledge_cache": knowledge_cache, "knowledge_sources_cache": knowledge_sources_cache}}


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


def _extract_gis_data_for_sse(gis_tool_result: Optional[NormalizedToolResult]) -> Optional[Dict[str, Any]]:
    """从规范化 GIS 工具结果提取 SSE 事件所需的 GIS 数据

    Args:
        gis_tool_result: NormalizedToolResult 实例

    Returns:
        SSE 事件数据字典
    """
    if not gis_tool_result or not gis_tool_result.success:
        return None

    result = {}

    # 1. 直接使用规范化结果的图层属性
    if gis_tool_result.has_geojson:
        result["layers"] = gis_tool_result.layers_data or []

    # 2. 分析数据
    if gis_tool_result.has_analysis:
        result["analysisData"] = gis_tool_result.analysis_data

    # 3. 地图选项
    if gis_tool_result.center:
        result["mapOptions"] = {
            "center": gis_tool_result.center,
            "zoom": gis_tool_result.raw_data.get("zoom", 14),
        }

    return result if result else None


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
    # GIS 分析结果将在审查后通过 bind_tools 触发，规划阶段不再使用

    dimension_name = DIMENSION_NAMES.get(dimension_key, dimension_key)
    layer = get_layer_from_dimension(dimension_key)
    # [调试] 记录维度执行开始
    logger.info(f"[维度节点-Send] START: {dimension_key} ({dimension_name}), Layer={layer}")

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
    knowledge_sources_cache = config.get("knowledge_sources_cache", {})  # 新增：获取切片缓存
    images = state.get("images", [])  # 从顶层获取图片（仅 Layer 1 有）

    # GIS 工具调用已移至审查后 bind_tools 触发，规划阶段不再调用
    # 保留 dimension_config 读取以供后续 bind_tools 使用
    dimension_config = get_dimension_config(dimension_key)
    gis_tool_name = dimension_config.get("tool") if dimension_config else None
    if gis_tool_name:
        logger.debug(f"[维度节点] {dimension_key} 配置了工具: {gis_tool_name}（审查后触发）")

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

    # 构建 prompt（规划阶段不传入 gis_tool_result）
    prompt = _build_dimension_prompt(
        dimension_key=dimension_key,
        dimension_name=dimension_name,
        village_data=village_data,
        village_name=village_name,
        task_description=task_description,
        constraints=constraints,
        reports=reports,
        knowledge_cache=knowledge_cache,
        images=images,
        dimension_summaries=state.get("dimension_summaries", {})  # Phase 3
    )

    # 使用统一 LLM，根据图片情况构建输入
    llm = create_llm(model=LLM_MODEL, max_tokens=MAX_TOKENS, streaming=True)
    if images:
        logger.info(f"[维度节点-Send] {dimension_name} 检测到图片，构建多模态输入")
        first_image = images[0]
        llm_input = [build_multimodal_message(
            text_content=prompt,
            image_base64=first_image.get("image_base64"),
            image_format=first_image.get("image_format", DEFAULT_IMAGE_FORMAT),
            role="human"
        )]
    else:
        llm_input = prompt

    # Record start time for diagnostics
    start_time = asyncio.get_event_loop().time()
    logger.debug(f"[维度节点-Send] LLM 调用开始: {dimension_name}")

    # 实时发送：直接调用 SSEPublisher 发送 delta 事件
    # 不再收集到 sse_events 数组，避免批量发送时的队列溢出
    from ...utils.sse_publisher import SSEPublisher

    async def collect_stream():
        """Collect streaming result with real-time SSE publishing

        Uses hybrid throttling: character threshold primary, time interval secondary.
        Only checks time.time() when character threshold is met, reducing syscalls.
        """
        collected_result = ""
        last_send_time = time.monotonic()  # Faster than time.time()
        last_send_len = 0
        SEND_INTERVAL = 0.5  # Send every 0.5 seconds
        CHAR_THRESHOLD = 100  # Check time every 100 chars

        async for chunk in llm.astream(llm_input):
            if chunk.content:
                token = chunk.content
                collected_result += token

                # Primary: character threshold triggers time check
                # Secondary: first 50 chars sent immediately
                if len(collected_result) <= 50 or len(collected_result) - last_send_len >= CHAR_THRESHOLD:
                    current_time = time.monotonic()
                    if current_time - last_send_time >= SEND_INTERVAL or len(collected_result) <= 50:
                        SSEPublisher.send_dimension_delta(
                            session_id=session_id,
                            layer=layer,
                            dimension_key=dimension_key,
                            dimension_name=dimension_name,
                            token=token,
                            accumulated=collected_result
                        )
                        last_send_time = current_time
                        last_send_len = len(collected_result)

        return collected_result

    try:
        # Use global semaphore to limit concurrent LLM calls
        async with _LLM_SEMAPHORE:
            logger.debug(f"[维度节点-Send] {dimension_name} 获取 semaphore，开始 LLM 调用")
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

        # 获取当前维度的切片数据
        knowledge_sources_for_event = knowledge_sources_cache.get(dimension_key, [])

        # Send dimension complete event（规划阶段不携带 gis_data）
        SSEPublisher.send_dimension_complete(
            session_id=session_id,
            layer=layer,
            dimension_key=dimension_key,
            dimension_name=dimension_name,
            full_content=result,
            knowledge_sources=knowledge_sources_for_event
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
        logger.info(f"[维度节点-Send] COMPLETE: {dimension_key} ({dimension_name}), Layer={layer}, len={len(result)}, time={elapsed_total:.1f}s")

        return {
            "dimension_results": [{
                "dimension_key": dimension_key,
                "dimension_name": dimension_name,
                "result": result,
                "success": True,
                "layer": layer,
            }],
            "sse_events": sse_events,
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

    # 构建 prompt（旧版本不执行 GIS 工具调用）
    prompt = _build_dimension_prompt(
        dimension_key=dimension_key,
        dimension_name=dimension_name,
        village_data=village_data,
        village_name=village_name,
        task_description=task_description,
        constraints=constraints,
        reports=reports,
        knowledge_cache=knowledge_cache,
        dimension_summaries=state.get("dimension_summaries", {})  # Phase 3
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

def _build_summary_context(
    dimension_key: str,
    dimension_summaries: Dict[str, Any],
) -> str:
    """
    构建摘要背景上下文（Phase 3）

    从 dimension_summaries 中获取依赖维度的摘要，
    格式化为显式区分的 XML 标签结构。

    Args:
        dimension_key: 当前维度键名
        dimension_summaries: 维度摘要索引

    Returns:
        格式化的摘要背景字符串（用于注入 prompt）
    """
    if not dimension_summaries:
        return ""

    from ...config.dimension_metadata import get_full_dependency_chain_func

    chain = get_full_dependency_chain_func(dimension_key)
    layer1_deps = chain.get("layer1_analyses", [])
    layer2_deps = chain.get("layer2_concepts", [])

    # 收集依赖维度的摘要
    layer1_summaries = []
    layer2_summaries = []

    for dep in layer1_deps:
        if dep in dimension_summaries:
            layer1_summaries.append(dimension_summaries[dep])

    for dep in layer2_deps:
        if dep in dimension_summaries:
            layer2_summaries.append(dimension_summaries[dep])

    if not layer1_summaries and not layer2_summaries:
        return ""

    # 格式化输出（XML 标签显式区分）
    parts = ["<Village_Status_Context>"]
    parts.append("【村庄现状特征】（来自 Layer 1 摘要）")

    for summary in layer1_summaries:
        dim_name = summary.get("dimension_name", summary.get("dimension_key", ""))
        summary_text = summary.get("summary", "")
        key_points = summary.get("key_points", [])
        tags = summary.get("tags", [])

        parts.append(f"- {dim_name}: {summary_text[:100]}...")
        if key_points:
            parts.append(f"  关键要点: {', '.join(key_points[:3])}")
        if tags:
            parts.append(f"  特征标签: {', '.join(tags[:3])}")

    parts.append("</Village_Status_Context>")

    if layer2_summaries:
        parts.append("\n<Planning_Context>")
        parts.append("【规划思路背景】（来自 Layer 2 摘要）")

        for summary in layer2_summaries:
            dim_name = summary.get("dimension_name", summary.get("dimension_key", ""))
            summary_text = summary.get("summary", "")
            parts.append(f"- {dim_name}: {summary_text[:100]}...")

        parts.append("</Planning_Context>")

    result = "\n".join(parts)
    logger.info(f"[摘要背景] {dimension_key}: 构建摘要背景, Layer1={len(layer1_summaries)}, Layer2={len(layer2_summaries)}")
    return result


def _build_dimension_prompt(
    dimension_key: str,
    dimension_name: str,
    village_data: str,
    task_description: str,
    constraints: str,
    reports: Dict[str, Dict[str, str]],
    village_name: str = "",
    knowledge_cache: Dict[str, str] = None,
    images: List[Dict[str, Any]] = None,
    professional_data: Optional[str] = None,  # 审查后 bind_tools 触发时传入
    dimension_summaries: Dict[str, Any] = None,  # Phase 3: 摘要索引
) -> str:
    """构建维度分析 prompt - 使用专业模板

    Args:
        professional_data: GIS 分析结果格式化文本（审查后 bind_tools 触发时传入，
                          规划阶段为 None）
        dimension_summaries: 维度摘要索引（用于 Layer 2/3 关联检索）
    """
    layer = get_dimension_layer(dimension_key) or 3
    knowledge_cache = knowledge_cache or {}
    dimension_summaries = dimension_summaries or {}

    # 从缓存获取当前维度的知识
    knowledge_context = knowledge_cache.get(dimension_key, "")

    # Phase 3: 构建摘要背景（Layer 2/3）
    summary_context = ""
    if layer >= 2 and dimension_summaries:
        summary_context = _build_summary_context(
            dimension_key=dimension_key,
            dimension_summaries=dimension_summaries,
        )

    # Layer 1: 使用 analysis_prompts 模板
    if layer == 1:
        from ...subgraphs.analysis_prompts import get_dimension_prompt
        return get_dimension_prompt(
            dimension_key=dimension_key,
            raw_data=village_data,
            village_name=village_name,
            professional_data=professional_data,
            task_description=task_description,
            constraints=constraints,
            knowledge_context=knowledge_context,
            has_images=bool(images)
        )

    # Layer 2: 使用 concept_prompts 模板（按依赖配置筛选）
    elif layer == 2:
        from ...subgraphs.concept_prompts import get_dimension_prompt
        from ...config.dimension_metadata import (
            get_full_dependency_chain_func,
            get_analysis_dimension_names,
            get_concept_dimension_names,
            filter_reports_by_dependency,
        )

        chain = get_full_dependency_chain_func(dimension_key)
        layer1_reports = reports.get("layer1", {})
        layer2_reports = reports.get("layer2", {})

        analysis_summary = filter_reports_by_dependency(
            required_keys=chain.get("layer1_analyses", []),
            reports=layer1_reports,
            name_mapping=get_analysis_dimension_names()
        )

        # Layer2 同层依赖筛选
        layer2_contexts = filter_reports_by_dependency(
            required_keys=chain.get("layer2_concepts", []),
            reports=layer2_reports,
            name_mapping=get_concept_dimension_names()
        )

        logger.info(f"[Dimension-Prompt] {dimension_key}: "
                   f"筛选后 Layer1={len(chain.get('layer1_analyses', []))}/{len(layer1_reports)} 个, "
                   f"Layer2={len(chain.get('layer2_concepts', []))}/{len(layer2_reports)} 个")

        return get_dimension_prompt(
            dimension_key=dimension_key,
            analysis_report=analysis_summary,
            layer2_contexts=layer2_contexts,
            task_description=task_description,
            constraints=constraints,
            superior_planning_context=_get_superior_planning_context(reports),
            knowledge_context=knowledge_context,
            summary_context=summary_context
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
            professional_data=professional_data,
            dimension_plans=dimension_plans,
            knowledge_context=knowledge_context,
            summary_context=summary_context  # Phase 3: 注入摘要背景
        )

    # Fallback: 使用简化 prompt
    return _build_fallback_prompt(dimension_name, village_data, task_description, constraints)


def _format_gis_tool_result(gis_tool_result: Optional[NormalizedToolResult]) -> Optional[str]:
    """
    格式化规范化 GIS 工具结果为 professional_data 文本

    Args:
        gis_tool_result: NormalizedToolResult 实例

    Returns:
        格式化的文本，可用于 prompt 注入
    """
    if not gis_tool_result:
        return None

    if not gis_tool_result.success:
        return f"GIS分析失败: {gis_tool_result.error or '未知错误'}"

    # 文本类型直接返回
    if gis_tool_result.has_text:
        return gis_tool_result.text_data

    # 提取关键信息
    parts = ["## GIS分析结果"]
    raw_data = gis_tool_result.raw_data

    # 设施验证结果
    if "facility_type" in raw_data:
        parts.append(f"- 设施类型: {raw_data.get('facility_type')}")
        parts.append(f"- 综合评分: {raw_data.get('overall_score', 0)}/100")
        parts.append(f"- 适宜性等级: {raw_data.get('suitability_level', 'Unknown')}")
        if raw_data.get("recommendations"):
            parts.append("- 建议:")
            for rec in raw_data.get("recommendations", [])[:3]:
                parts.append(f"  * {rec}")

    # 生态敏感性评估结果
    elif "sensitivity_class" in raw_data:
        parts.append(f"- 敏感性等级: {raw_data.get('sensitivity_class')}")
        parts.append(f"- 研究区域: {raw_data.get('study_area_km2', 0)} km²")
        parts.append(f"- 敏感区域: {raw_data.get('sensitive_area_km2', 0)} km²")
        if raw_data.get("recommendations"):
            parts.append("- 保护建议:")
            for rec in raw_data.get("recommendations", [])[:3]:
                parts.append(f"  * {rec}")

    # 等时圈分析结果
    elif "isochrones" in raw_data or gis_tool_result.has_geojson:
        parts.append("- 等时圈分析已完成")
        if gis_tool_result.center:
            parts.append(f"- 中心点: {gis_tool_result.center}")
        if raw_data.get("travel_mode"):
            parts.append(f"- 出行方式: {raw_data.get('travel_mode')}")

    # 规划矢量化结果
    elif "zones" in raw_data or "facilities" in raw_data:
        if raw_data.get("zones"):
            zone_data = raw_data["zones"]
            parts.append(f"- 功能区数量: {zone_data.get('feature_count', 0)}")
            parts.append(f"- 总面积: {zone_data.get('total_area_ha', 0)} 公顷")
        if raw_data.get("facilities"):
            facility_data = raw_data["facilities"]
            parts.append(f"- 设施点数量: {facility_data.get('feature_count', 0)}")

    # GIS 数据获取结果
    elif gis_tool_result.location:
        parts.append(f"- 位置: {gis_tool_result.location}")
        if gis_tool_result.layers_data:
            layer_names = [l.get("layerName", "") for l in gis_tool_result.layers_data]
            parts.append(f"- 已获取图层: {', '.join(layer_names)}")

    # 分析数据摘要
    elif gis_tool_result.has_analysis:
        analysis = gis_tool_result.analysis_data
        if analysis.get("summary"):
            parts.append(f"- 分析摘要: {analysis['summary'][:100]}...")
        if analysis.get("coverage_rate"):
            parts.append(f"- 覆盖率: {analysis['coverage_rate']:.1%}")
        if analysis.get("reachable_count"):
            parts.append(f"- 可达设施: {analysis['reachable_count']} 个")

    # 默认情况
    else:
        parts.append("- 分析已完成")
        # 添加所有非嵌套的键值对
        for k, v in raw_data.items():
            if k not in ["geojson", "data", "success", "layers"] and isinstance(v, (str, int, float, bool)):
                parts.append(f"- {k}: {v}")

    return "\n".join(parts)


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
# GIS 工具执行辅助函数
# ==========================================

def _get_nested_value(data: Dict[str, Any], path: str) -> Any:
    """
    嵌套路径取值 - 支持 NormalizedToolResult 对象和 dict

    Args:
        data: 数据字典
        path: 嵌套路径，如 "_auto_fetched.center"

    Returns:
        找到的值，不存在则返回 None
    """
    if not data or not path:
        return None

    keys = path.split(".")
    current = data

    for key in keys:
        # 处理 NormalizedToolResult 对象
        if isinstance(current, NormalizedToolResult):
            # 支持的属性: center, location, success, raw_data, geojson_data, etc.
            if hasattr(current, key):
                current = getattr(current, key)
                continue
            # 尝试从 raw_data 提取
            if hasattr(current, "raw_data") and isinstance(current.raw_data, dict):
                current = current.raw_data.get(key)
                if current is None:
                    return None
                continue
            return None

        # 处理 dict 类型
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if current is None:
            return None

    return current


def _resolve_tool_params(
    tool_params_config: Dict[str, Dict[str, Any]],
    context: Dict[str, Any]
) -> Dict[str, Any]:
    """
    解析工具参数配置

    根据 tool_params 配置从不同来源解析参数值。

    Args:
        tool_params_config: 参数配置字典
            {
                "param_name": {"source": "literal", "value": xxx},
                "param_name": {"source": "gis_cache", "path": "_auto_fetched.center"},
                "param_name": {"source": "config", "path": "village_name"}
            }
        context: 工具上下文，包含 village_data, village_name, config, reports 等

    Returns:
        解析后的参数字典
    """
    resolved = {}
    config = context.get("config", {})
    # 修复: 从 context 顶层获取 gis_analysis_results，而非从 config 内部
    gis_results = context.get("gis_analysis_results", {})

    for param_name, param_config in tool_params_config.items():
        source = param_config.get("source", ParamSource.LITERAL.value)

        if source == ParamSource.LITERAL.value:
            # 固定值
            resolved[param_name] = param_config.get("value")

        elif source == ParamSource.GIS_CACHE.value:
            # 从 GIS 分析结果缓存取值
            path = param_config.get("path", "")
            value = _get_nested_value(gis_results, path)
            if value is not None:
                resolved[param_name] = value
            else:
                logger.warning(f"[参数解析] gis_cache 路径 {path} 未找到值")

                # Center 参数容错：当 center 为 None 时，尝试从 village_name 计算
                # 使用缓存避免多次冗余 API 调用
                if path.endswith("center"):
                    # 先检查缓存
                    fallback_center = gis_results.get("_center_fallback")
                    if fallback_center is None and not gis_results.get("_center_fallback_failed"):
                        # 使用 GISDataFetcher 单例（避免重复创建 TiandituProvider）
                        fallback_center = _compute_center_fallback(config.get("village_name", ""))
                        if fallback_center:
                            gis_results["_center_fallback"] = fallback_center  # 缓存成功结果
                            logger.info(f"[参数解析] center 容错计算成功并缓存: {fallback_center}")
                        else:
                            gis_results["_center_fallback_failed"] = True  # 标记失败，避免重复尝试
                            logger.warning(f"[参数解析] center 容错计算失败，已标记跳过后续尝试")

                    if fallback_center:
                        resolved[param_name] = fallback_center

        elif source == ParamSource.CONFIG.value:
            # 从 state.config 取值
            path = param_config.get("path", "")
            value = _get_nested_value(config, path)
            if value is not None:
                resolved[param_name] = value
            else:
                logger.warning(f"[参数解析] config 路径 {path} 未找到值")

        elif source == ParamSource.CONTEXT.value:
            # 从 context 直接取值
            key = param_config.get("key", param_name)
            if key in context:
                resolved[param_name] = context[key]
            else:
                logger.warning(f"[参数解析] context.{key} 未找到值")

    return resolved


def _compute_center_fallback(location: str) -> Optional[tuple]:
    """
    Center 参数容错计算 - 使用 GISDataFetcher 单例

    Args:
        location: 地名（如 village_name）

    Returns:
        中心点坐标元组 (lon, lat) 或 None
    """
    if not location:
        return None

    try:
        from ...tools.core.gis_data_fetcher import get_fetcher
        fetcher = get_fetcher()  # 使用单例，避免重复创建 TiandituProvider

        # 复用 GISDataFetcher.get_village_center() 的分层定位策略
        center, metadata = fetcher.get_village_center(location, buffer_km=2.0)

        if center:
            logger.info(f"[容错计算] 定位成功: {location} -> {center}, 策略: {metadata.get('strategy_used')}")
            return center

        logger.warning(f"[容错计算] 无法定位 {location}")
        return None

    except Exception as e:
        logger.error(f"[容错计算] 异常: {e}")
        return None


def _execute_gis_tool(
    tool_name: str,
    context: Dict[str, Any],
    tool_params_config: Optional[Dict[str, Dict[str, Any]]] = None
) -> Optional[NormalizedToolResult]:
    """
    执行 GIS 工具并返回规范化结果

    Args:
        tool_name: 工具名称
        context: 工具上下文
        tool_params_config: 工具参数配置（可选）
            如果提供，将根据配置解析参数；否则使用 context 作为参数

    Returns:
        NormalizedToolResult 实例，失败返回 None
    """
    import json
    from ...tools.registry import ToolRegistry

    tool_func = ToolRegistry.get_tool(tool_name)
    if not tool_func:
        logger.warning(f"[GIS工具] 工具未注册: {tool_name}")
        return None

    try:
        # 解析参数配置
        if tool_params_config:
            resolved_params = _resolve_tool_params(tool_params_config, context)
            logger.info(f"[GIS工具] {tool_name} 参数解析结果: {list(resolved_params.keys())}")
        else:
            resolved_params = context

        result_str = tool_func(resolved_params)

        # 规范化结果
        return normalize_tool_result(result_str, tool_name)

    except Exception as e:
        logger.error(f"[GIS工具] 执行失败 {tool_name}: {e}")
        return NormalizedToolResult(
            success=False,
            data_type=ResultDataType.ERROR,
            error=str(e)
        )


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
    layer = get_dimension_layer(dimension_key) or 3

    # Layer 1 需要图片进行多模态分析，Layer 2/3 不需要原始图片
    if layer == 1:
        images = parent_state.get("images", [])
    else:
        images = []  # Layer 2/3 不传递图片

    return {
        "dimension_key": dimension_key,
        "dimension_name": DIMENSION_NAMES.get(dimension_key, dimension_key),
        "session_id": parent_state.get("session_id", ""),
        "project_name": parent_state.get("project_name", ""),
        "config": parent_state.get("config", {}),
        "images": images,  # 作为独立属性传递
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
    "ParamSource",
]