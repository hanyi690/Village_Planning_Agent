"""Access tools — EXPLORE 会话统一读路径工具集。

Semantic-first, snapshot-first, token-budgeted. Consumed by the explore agent
scope (``ToolRegistry.for_agent("explore")``); any other agent can adopt them
by declaring the same scope.
"""

from .bundle import bundle_overview, spatial_features, spatial_context
from .knowledge import knowledge_graph
from .rag import index_bundle_texts, rag_search
from .reports import layer_reports

ACCESS_TOOLS = [
    bundle_overview,
    spatial_context,
    spatial_features,
    layer_reports,
    knowledge_graph,
    rag_search,
]

_ACCESS_METADATA = {
    "bundle_overview": {
        "display_name": "会话数据概览",
        "description": "返回会话的空间数据与文本概览（图层组/文档/报告维度清单，不含坐标）。",
        "estimated_time": 1.0,
        "display_hints": {"primary_view": "text", "priority_fields": ["village_name", "spatial_groups"]},
    },
    "spatial_context": {
        "display_name": "空间语义认知",
        "description": "空间图层统计 + 知识图谱三层认知摘要（村域概况/地块卡片/约束覆盖）。",
        "estimated_time": 2.0,
        "display_hints": {"primary_view": "text", "priority_fields": ["kg_cognition"]},
    },
    "spatial_features": {
        "display_name": "空间要素清单",
        "description": "要素元数据清单（默认无坐标）；include_geometry 可选返回精简几何供落图。",
        "estimated_time": 1.5,
        "display_hints": {"primary_view": "text", "priority_fields": ["bsm", "layer_type"]},
    },
    "layer_reports": {
        "display_name": "维度报告",
        "description": "L1/L2/L3 维度报告摘要；include_content 可选返回全文。",
        "estimated_time": 1.0,
        "display_hints": {"primary_view": "text", "priority_fields": ["dimension_key", "summary"]},
    },
    "knowledge_graph": {
        "display_name": "知识图谱查询",
        "description": "查询会话 KG 语义上下文（村庄/地块/实体/约束）。",
        "estimated_time": 1.5,
        "display_hints": {"primary_view": "text", "priority_fields": ["semantic"]},
    },
    "rag_search": {
        "display_name": "会话文本检索",
        "description": "在会话文本清单内检索（支持 source/name 过滤，向量+关键词兜底）。",
        "estimated_time": 2.0,
        "display_hints": {"primary_view": "text", "priority_fields": ["results"]},
    },
}


def _register() -> None:
    from app.tools.registry import ToolRegistry

    by_name = {t.name: t for t in ACCESS_TOOLS}
    for name, meta in _ACCESS_METADATA.items():
        tool = by_name.get(name)
        if tool is not None:
            ToolRegistry.register(name, tool=tool, **meta)


_register()


__all__ = [
    "ACCESS_TOOLS",
    "bundle_overview",
    "spatial_context",
    "spatial_features",
    "layer_reports",
    "knowledge_graph",
    "rag_search",
    "index_bundle_texts",
]
