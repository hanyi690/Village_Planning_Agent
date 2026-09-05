"""knowledge_graph — 会话 current-world 语义查询工具。

Reads the bounded DATA-backed World Model port. Returns token-budgeted
entity/representation context and never exposes raw RDF or a legacy Bundle.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from .shared import budget_check, session_world_model, tool_reply


async def knowledge_graph_impl(
    session_id: str,
    kind: str = "cognition",
    bsm: str = "",
    entity_type: str = "",
    label: str = "",
) -> Dict[str, Any]:
    world_model = session_world_model(session_id)
    if world_model is None:
        return {"success": False, "error": f"无 current-world view（session_id={session_id}）"}

    try:
        find_entities = getattr(world_model, "find_entities", None)
        if not callable(find_entities):
            return {"success": False, "error": "当前世界模型没有可用的只读查询端口"}
        rows = list(find_entities(
            entity_ref=bsm if bsm else "",
            name=label if label else "",
            entity_type=entity_type if entity_type else "",
            limit=32,
        ))
        if kind in {"cognition", "village"}:
            return budget_check({
                "semantic": {
                    "village": session_id,
                    "entity_count": len(rows),
                },
                "structured": {"entities": rows},
            })
        if kind == "constraints":
            return budget_check({"constraint_coverage": [], "entities": rows})
        if kind in {"parcel", "entity"}:
            return budget_check({
                "query": {"entity_ref": bsm, "label": label, "entity_type": entity_type},
                "entities": rows,
            })
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
