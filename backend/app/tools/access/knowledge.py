"""knowledge_graph — 会话 KG 语义查询工具。

Wraps the KG semantic query layer (kg/queries/semantic.py + cognition.py).
Returns token-budgeted semantic context for villages, parcels, entities,
constraints — never raw SPARQL / turtle.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from .shared import budget_check, session_kg, tool_reply


async def knowledge_graph_impl(
    session_id: str,
    kind: str = "cognition",
    bsm: str = "",
    entity_type: str = "",
    label: str = "",
) -> Dict[str, Any]:
    kg = session_kg(session_id)
    if kg is None:
        return {"success": False, "error": f"无 session KG（session_id={session_id}）"}

    try:
        from app.modules.kg.queries import (
            get_entity_by_bsm,
            get_entity_semantics,
            get_parcel_neighbors_semantic,
            get_parcel_semantic_context,
            get_parcels_semantic_list,
            get_village_constraint_coverage,
            get_village_semantic_summary,
        )
        from app.modules.kg.queries.cognition import get_village_cognition

        if kind == "cognition":
            r = get_village_cognition(kg, mode="full")
            return budget_check({"semantic": r.semantic, "structured": r.structured})
        if kind == "village":
            return budget_check(get_village_semantic_summary(kg) or {})
        if kind == "constraints":
            return budget_check({"constraint_coverage": get_village_constraint_coverage(kg) or []})
        if kind == "parcel":
            if bsm:
                payload = {
                    "bsm": bsm,
                    "detail": get_parcel_semantic_context(kg, bsm) or {},
                    "neighbors": get_parcel_neighbors_semantic(kg, bsm) or [],
                }
            else:
                payload = {"parcels": get_parcels_semantic_list(kg) or []}
            return budget_check(payload)
        if kind == "entity":
            if bsm:
                return budget_check({"entity": get_entity_by_bsm(kg, bsm, entity_type) or {}})
            return budget_check(get_entity_semantics(kg, entity_label=label, entity_type=entity_type) or {})
        return {"success": False, "error": f"未知查询类型: {kind}"}
    except Exception as e:
        return {"success": False, "error": f"KG 查询失败: {e}"}


@tool
async def knowledge_graph(
    session_id: str = "",
    kind: str = "cognition",
    bsm: str = "",
    entity_type: str = "",
    label: str = "",
    state: Annotated[Optional[Dict[str, Any]], InjectedState()] = None,
) -> str:
    """查询会话知识图谱（KG）的语义上下文。

    kind 取值:
      - cognition:   村庄三层认知摘要（默认）
      - village:     村庄语义概览
      - constraints: 约束覆盖
      - parcel:      地块详情+邻接（需 bsm，或省略返回地块清单）
      - entity:      实体语义（按 bsm 或 label/entity_type 检索）
    """
    if not session_id and state:
        session_id = state.get("session_id", "")
    return tool_reply(
        await knowledge_graph_impl(
            session_id, kind=kind, bsm=bsm, entity_type=entity_type, label=label
        )
    )


__all__ = ["knowledge_graph", "knowledge_graph_impl"]
