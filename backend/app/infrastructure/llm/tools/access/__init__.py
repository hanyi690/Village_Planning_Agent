"""Access tools — EXPLORE 会话统一读路径工具集。

Semantic-first, DATA-catalog-first, token-budgeted.  Legacy Bundle tools are
kept as an explicit compatibility surface; V2 callers use DATA resource /
representation references and never need a parcel or BSM field.
"""

from .bundle import bundle_overview, spatial_features, spatial_context
from .knowledge import knowledge_graph
from .evidence import (
    bundle_geometry_by_feature_ref,
    data_geometry_by_ref,
    query_evidence_graph,
    query_facility_bsms,
)
from .rag import index_bundle_texts, rag_search
from .reports import layer_reports

ACCESS_TOOLS = [
    bundle_overview,
    spatial_context,
    spatial_features,
    layer_reports,
    knowledge_graph,
    query_evidence_graph,
    query_facility_bsms,
    bundle_geometry_by_feature_ref,
    data_geometry_by_ref,
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
    "query_evidence_graph": {
        "display_name": "证据图查询",
        "description": "返回 DATA 候选引用、实体身份与拓扑的有界证据包（兼容模式才出现 Bundle/BSM）。",
        "estimated_time": 1.5,
        "display_hints": {"primary_view": "text", "priority_fields": ["candidate_refs", "relation_evidence"]},
    },
    "query_facility_bsms": {
        "display_name": "设施 BSM 查询",
        "description": "按村域查询已验证设施 BSM，不接受模型生成的身份。",
        "estimated_time": 1.0,
        "display_hints": {"primary_view": "text", "priority_fields": ["status", "candidates"]},
    },
    "bundle_geometry_by_feature_ref": {
        "display_name": "按要素引用取几何",
        "description": "兼容工具：仅对 EvidencePacket 返回的 legacy Bundle feature ref 读取几何；V2 使用 DATA representation/resource ref。",
        "estimated_time": 1.0,
        "display_hints": {"primary_view": "map", "priority_fields": ["feature_ref", "geometry"]},
    },
    "data_geometry_by_ref": {
        "display_name": "按 DATA 引用取几何",
        "description": "仅对 EvidencePacket 返回的 DATA resource/representation/geometry ref 读取几何。",
        "estimated_time": 1.0,
        "display_hints": {"primary_view": "map", "priority_fields": ["geometry_ref", "geometry"]},
    },
    "rag_search": {
        "display_name": "会话文本检索",
        "description": "在会话文本清单内检索（支持 source/name 过滤，向量+关键词兜底）。",
        "estimated_time": 2.0,
        "display_hints": {"primary_view": "text", "priority_fields": ["results"]},
    },
}


def _register() -> None:
    from app.infrastructure.llm.tools.registry import ToolRegistry

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
    "query_evidence_graph",
    "query_facility_bsms",
    "bundle_geometry_by_feature_ref",
    "data_geometry_by_ref",
    "rag_search",
    "index_bundle_texts",
]
