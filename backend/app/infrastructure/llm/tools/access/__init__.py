"""Access tools — EXPLORE 会话统一读路径工具集。

Semantic-first, DATA-catalog-first, token-budgeted.  Callers use DATA resource
and representation references and never need a legacy parcel or BSM field.
"""

from .knowledge import knowledge_graph
from .evidence import (
    data_geometry_by_ref,
    query_evidence_graph,
    query_facility_bsms,
)
from .reports import layer_reports

ACCESS_TOOLS = [
    layer_reports,
    knowledge_graph,
    query_evidence_graph,
    query_facility_bsms,
    data_geometry_by_ref,
]

_ACCESS_METADATA = {
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
        "description": "返回 DATA 候选引用、实体身份与拓扑的有界证据包。",
        "estimated_time": 1.5,
        "display_hints": {"primary_view": "text", "priority_fields": ["candidate_refs", "relation_evidence"]},
    },
    "query_facility_bsms": {
        "display_name": "设施 BSM 查询",
        "description": "按村域查询已验证设施 BSM，不接受模型生成的身份。",
        "estimated_time": 1.0,
        "display_hints": {"primary_view": "text", "priority_fields": ["status", "candidates"]},
    },
    "data_geometry_by_ref": {
        "display_name": "按 DATA 引用取几何",
        "description": "仅对 EvidencePacket 返回的 DATA resource/representation/geometry ref 读取几何。",
        "estimated_time": 1.0,
        "display_hints": {"primary_view": "map", "priority_fields": ["geometry_ref", "geometry"]},
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
    "layer_reports",
    "knowledge_graph",
    "query_evidence_graph",
    "query_facility_bsms",
    "data_geometry_by_ref",
]
