"""
维度分析节点 - 简化版

直接执行维度分析，无需中间 executor 层。
"""

import asyncio
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional
from langchain_core.messages import AIMessage

from ...config import get_dimension_config, get_dimension_layer, list_dimensions
from ...core.llm import create_llm
from ...core.settings import LLM_MODEL, MAX_TOKENS
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Cached LLM instance — reused across all dimension analyses
_llm_cache: Optional[Any] = None


def _get_llm():
    global _llm_cache
    if _llm_cache is None:
        _llm_cache = create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS, streaming=True)
    return _llm_cache


class ParamSource(str, Enum):
    """工具参数来源"""
    LITERAL = "literal"
    GIS_CACHE = "gis_cache"
    CONFIG = "config"
    CONTEXT = "context"


# 维度名称映射
DIMENSION_NAMES = {dim.key: dim.name for dim in list_dimensions()}


def get_layer_from_dimension(dimension_key: str) -> int:
    layer = get_dimension_layer(dimension_key)
    return layer if layer is not None else 3


def create_dimension_state(dimension_key: str, parent_state: Dict[str, Any]) -> Dict[str, Any]:
    """创建维度状态（Send API 用）"""
    layer = get_dimension_layer(dimension_key) or 3
    return {
        "dimension_key": dimension_key,
        "dimension_name": DIMENSION_NAMES.get(dimension_key, dimension_key),
        "session_id": parent_state.get("session_id", ""),
        "project_name": parent_state.get("project_name", ""),
        "config": parent_state.get("config", {}),
        "image_ids": parent_state.get("image_ids", []) if layer == 1 else [],
        "reports": parent_state.get("reports", {}),
        "completed_dimensions": parent_state.get("completed_dimensions", {}),
    }


async def analyze_dimension(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    维度分析节点 - 直接执行

    流程：
    1. 获取配置
    2. 并行 GIS 工具
    3. RAG 查询
    4. 组装 Prompt
    5. 流式 LLM + SSE
    6. 保存版本
    7. 返回状态更新
    """
    from ...services import GisService, RagService
    from ...services.sse import sse_manager
    from ...services.report_store import ReportStore

    dim_key = state.get("dimension_key")
    if not dim_key:
        return {"messages": [AIMessage(content="[执行失败] 缺少维度标识")]}

    session_id = state.get("session_id", "")
    phase = state.get("phase", "layer1")
    logger.info(f"[analyze_dimension] {dim_key} (phase={phase})")

    # 1. 获取配置
    cfg = get_dimension_config(dim_key)
    if not cfg:
        return {"messages": [AIMessage(content=f"[执行失败] 配置缺失: {dim_key}")]}

    dim_name = getattr(cfg, 'name', dim_key)
    dim_layer = getattr(cfg, 'layer', get_dimension_layer(dim_key) or 3)

    # 2. 并行 GIS 工具
    tool_results = []
    tools = getattr(cfg, 'tools', [])
    if tools:
        context = {
            "session_id": session_id,
            "project_name": state.get("project_name", ""),
            "village_data": state.get("config", {}).get("village_data", ""),
            "reports": state.get("reports", {}),
        }
        tool_results = await GisService.run_parallel(tools, context)

    # 3. RAG 查询（两级开关：会话级 rag_enabled + 维度级 rag_query）
    rag_context = ""
    rag_enabled = state.get("config", {}).get("rag_enabled", True)
    dim_rag_query = getattr(cfg, 'rag_query', '')
    if rag_enabled and dim_rag_query:
        rag_context = await RagService.get_instance().get_context(dim_key, state, cfg)
        if rag_context:
            logger.info(f"[analyze_dimension] {dim_key}: RAG 检索到 {len(rag_context)} 字符上下文")
        else:
            logger.info(f"[analyze_dimension] {dim_key}: RAG 检索无结果")
    else:
        reason = "会话级 RAG 已关闭" if not rag_enabled else f"维度 rag_query 为空"
        logger.info(f"[analyze_dimension] {dim_key}: 跳过 RAG（{reason}）")

    # 4. 组装 Prompt
    prompt = _build_prompt(cfg, state, tool_results, rag_context)

    # 5. 流式 LLM + SSE
    llm = _get_llm()

    llm_response = ""
    await sse_manager.publish(session_id, {
        "type": "dimension_start",
        "dimension_key": dim_key,
        "dimension_name": dim_name,
        "layer": dim_layer,
    })

    try:
        async for chunk in llm.astream(prompt):
            if hasattr(chunk, 'content') and chunk.content:
                llm_response += chunk.content
                await sse_manager.publish(session_id, {
                    "type": "dimension_delta",
                    "dimension_key": dim_key,
                    "dimension_name": dim_name,
                    "layer": dim_layer,
                    "delta": chunk.content,
                    "accumulated": llm_response,
                })
    except Exception as e:
        logger.error(f"[analyze_dimension] LLM 失败: {e}")
        return {"messages": [AIMessage(content=f"[执行失败] LLM错误: {e}")]}

    # 6. 保存版本
    store = ReportStore.get_instance()
    current_versions = state.get("report_versions", {}).get(dim_key, [])
    next_version = len(current_versions) + 1
    revision_reason = state.get("feedback")

    report_id = await store.save(
        session_id=session_id,
        dim_key=dim_key,
        version=next_version,
        content=llm_response,
        metadata={"revision_reason": revision_reason},
    )

    # 7. 发送完成事件 (含 GIS 数据)
    gis_data = []
    for r in tool_results:
        if r and getattr(r, 'success', False):
            gis_data.append({
                "tool": getattr(r, 'tool_name', 'unknown'),
                "data": getattr(r, 'data', None),
            })

    await sse_manager.publish(session_id, {
        "type": "dimension_complete",
        "dimension_key": dim_key,
        "dimension_name": dim_name,
        "full_content": llm_response,
        "report_id": report_id,
        "version": next_version,
        "summary": llm_response[:200],
        "gis_data": gis_data,
        "layer": dim_layer,
    })

    # 8. 状态更新 - 仅返回增量，reducer 负责合并
    now_iso = datetime.utcnow().isoformat() + "Z"
    summary_excerpt = llm_response[:200]
    phase_key = f"layer{dim_layer}"

    return {
        "messages": [AIMessage(content=llm_response, metadata={"dimension_key": dim_key})],
        "completed_dimensions": {phase_key: [dim_key]},
        "reports": {phase_key: {dim_key: llm_response}},
        "report_versions": {
            dim_key: [{
                "version": next_version, "report_id": report_id,
                "summary": summary_excerpt,
                "generated_at": now_iso,
                "revision_trigger": revision_reason,
            }]
        },
        "summaries": {
            dim_key: {
                "dimension_key": dim_key, "dimension_name": dim_name, "layer": dim_layer,
                "summary": summary_excerpt, "key_points": [], "metrics": {},
                "tags": [], "created_at": now_iso,
            }
        },
    }


def _build_prompt(cfg, state, tool_results, rag_context) -> str:
    """组装 Prompt - 使用 prompts 模块模板"""
    from ...services.modules.prompts.analysis import get_dimension_prompt as get_layer1_prompt
    from ...services.modules.prompts.concept import get_dimension_prompt as get_layer2_prompt
    from ...services.modules.prompts.detailed import get_dimension_prompt as get_layer3_prompt

    dim_key = getattr(cfg, 'key', state.get("dimension_key", ""))
    layer = getattr(cfg, 'layer', get_dimension_layer(dim_key) or 1)
    dim_name = getattr(cfg, 'name', DIMENSION_NAMES.get(dim_key, dim_key))

    project_name = state.get("project_name", "村庄")
    village_data = state.get("config", {}).get("village_data", "")
    task_desc = state.get("config", {}).get("task_description", "制定村庄发展规划")
    constraints = state.get("config", {}).get("constraints", "无特殊约束")

    # GIS 工具数据
    tool_section = ""
    for r in tool_results:
        if r and getattr(r, 'success', False):
            tool_section += f"\n【GIS数据】\n{str(getattr(r, 'data', r))[:1000]}\n"

    # 前序依赖
    reports = state.get("reports", {})
    deps = ""
    if layer == 1:
        # Layer 1 无依赖，直接传入 village_data
        pass
    elif layer == 2:
        # Layer 2 依赖 Layer 1 报告
        layer1_reports = reports.get("layer1", {})
        deps = "\n".join([f"【{k}】{v[:800]}..." for k, v in layer1_reports.items() if v])
    elif layer == 3:
        # Layer 3 依赖 Layer 1 和 Layer 2
        layer1_reports = reports.get("layer1", {})
        layer2_reports = reports.get("layer2", {})
        deps = "\n".join([f"【{k}】{v[:500]}..." for k, v in layer1_reports.items() if v])
        deps += "\n" + "\n".join([f"【{k}】{v[:500]}..." for k, v in layer2_reports.items() if v])

    # 根据层级选择 Prompt 模板
    if layer == 1:
        return get_layer1_prompt(
            dimension_key=dim_key,
            raw_data=village_data + tool_section,
            village_name=project_name,
            task_description=task_desc,
            constraints=constraints,
            knowledge_context=rag_context or "",
            has_images=bool(state.get("image_ids")),
        )
    elif layer == 2:
        return get_layer2_prompt(
            dimension_key=dim_key,
            analysis_report=deps,
            task_description=task_desc,
            constraints=constraints,
            knowledge_context=rag_context or "",
            layer2_contexts="\n".join([
                f"【{k}】{v[:400]}" for k, v in reports.get("layer2", {}).items()
                if v and k != dim_key
            ]),
        )
    elif layer == 3:
        return get_layer3_prompt(
            dimension_key=dim_key,
            project_name=project_name,
            analysis_report=deps,
            planning_concept="\n".join([
                f"【{k}】{v[:600]}" for k, v in reports.get("layer2", {}).items() if v
            ]),
            constraints=constraints,
            knowledge_context=rag_context or "",
            professional_data_section=tool_section,
        )

    # 默认通用模板
    return f"""请对 "{project_name}" 进行 {dim_name} 分析。

## 基础数据
{village_data[:2000]}

## 规划任务
{task_desc}

{tool_section}

{deps}

{rag_context if rag_context else ""}

请生成完整的分析报告："""


__all__ = [
    "analyze_dimension",
    "create_dimension_state",
    "DIMENSION_NAMES",
    "get_layer_from_dimension",
    "ParamSource",
]