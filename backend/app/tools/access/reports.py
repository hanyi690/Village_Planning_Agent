"""layer_reports — L1/L2/L3 报告访问（summary 先行，全文按需）。

Follows progressive disclosure: the tool returns per-dimension summaries first
(compact), and only materializes full ``content`` when ``include_content`` is
explicitly requested. Reads the snapshot-first bundle path.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from .shared import budget_check, resolve_bundle, tool_reply


def _dimension_names() -> Dict[str, str]:
    try:
        from app.config import list_dimensions
        return {d.key: d.name for d in list_dimensions()}
    except Exception:
        return {}


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    return text if len(text) <= limit else text[:limit] + f"...[截断 {len(text) - limit} 字符]"


async def layer_reports_impl(
    session_id: str,
    layer: Optional[int] = None,
    dim_key: str = "",
    include_content: bool = False,
    max_summary_chars: int = 1200,
) -> Dict[str, Any]:
    """Summary-first layer reports view from the session snapshot."""
    names = _dimension_names()
    bundle = await resolve_bundle(session_id)
    layer_reports = bundle.layer_reports or {}

    if layer is not None and layer in layer_reports:
        layer_reports = {layer: layer_reports[layer]}

    result: Dict[str, Any] = {}
    for l, dims in layer_reports.items():
        for dk, rec in dims.items():
            if dim_key and dk != dim_key:
                continue
            content = str(rec.get("content") or "")
            entry: Dict[str, Any] = {
                "dimension_key": dk,
                "layer": l,
                "dimension_name": names.get(dk, dk),
                "version": rec.get("version"),
                "generated_at": rec.get("generated_at"),
                "summary": _truncate(str(rec.get("summary") or ""), max_summary_chars),
                "report_available": bool(content),
            }
            if include_content:
                entry["content"] = _truncate(content, max_summary_chars * 4)
            result.setdefault(str(l), {})[dk] = entry

    if not result:
        # Snapshot has no reports — fall back to the live dimension_reports DB.
        try:
            from app.services.report_store import ReportStore

            store = ReportStore.get_instance()
            layers = [layer] if layer is not None else [1, 2, 3]
            for l in layers:
                reports = await store.get_layer_reports_with_sources(session_id, l)
                for dk, rec in reports.items():
                    if dim_key and dk != dim_key:
                        continue
                    content = str(rec.get("content") or "")
                    result.setdefault(str(l), {})[dk] = {
                        "dimension_key": dk,
                        "layer": l,
                        "dimension_name": names.get(dk, dk),
                        "version": None,
                        "generated_at": None,
                        "summary": _truncate(content, max_summary_chars),
                        "report_available": bool(content),
                    }
        except Exception as e:
            result["_fallback_error"] = str(e)

    return budget_check(result)


@tool
async def layer_reports(
    session_id: str = "",
    layer: int = 0,
    dim_key: str = "",
    include_content: bool = False,
    state: Annotated[Optional[Dict[str, Any]], InjectedState()] = None,
) -> str:
    """返回 L1/L2/L3 维度报告清单与摘要。

    默认只返回每维度的摘要/版本/可用性（紧凑形态）。传 ``include_content=true``
    才返回报告全文。``layer`` 指定层级（1/2/3），``dim_key`` 指定维度。
    """
    if not session_id and state:
        session_id = state.get("session_id", "")
    return tool_reply(
        await layer_reports_impl(
            session_id,
            layer=layer or None,
            dim_key=dim_key,
            include_content=include_content,
        )
    )


__all__ = ["layer_reports", "layer_reports_impl"]
