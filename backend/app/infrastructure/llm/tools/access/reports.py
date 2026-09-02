"""layer_reports — bundle report-manifest access (summary first, body on demand).

The bundle is the only retrieval entry point. It stores report metadata and
references; report bodies are fetched from the canonical report store only
when ``include_content`` is explicitly requested.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from .shared import budget_check, tool_reply


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
    """Return the report manifest carried by the resolved session bundle."""
    names = _dimension_names()
    from app.infrastructure.reports.report_store import ReportStore

    report_refs = list(
        await ReportStore.get_instance().get_session_report_manifest(
            session_id, layers=(1, 2, 3)
        )
    )
    if layer is not None:
        report_refs = [ref for ref in report_refs if ref.get("layer") == layer]

    store = None
    if include_content:
        from app.infrastructure.reports.report_store import ReportStore

        store = ReportStore.get_instance()

    result: Dict[str, Any] = {}
    for ref in report_refs:
        l = int(ref.get("layer") or 0)
        dk = str(ref.get("dimension_key") or "")
        if not dk or (dim_key and dk != dim_key):
            continue
        entry: Dict[str, Any] = {
            "dimension_key": dk,
            "layer": l,
            "dimension_name": names.get(dk, dk),
            "report_id": ref.get("report_id"),
            "version": ref.get("version"),
            "generated_at": ref.get("generated_at"),
            "summary": _truncate(str(ref.get("summary") or ""), max_summary_chars),
            "knowledge_sources": ref.get("knowledge_sources") or [],
            "report_available": bool(ref.get("report_id")),
        }
        if include_content and store is not None:
            report = await store.get_report(str(ref.get("report_id") or ""))
            if report is None:
                entry["report_available"] = False
                entry["status"] = "missing_report_body"
            else:
                entry["content"] = _truncate(
                    str(report.content or ""), max_summary_chars * 4
                )
        result.setdefault(str(l), {})[dk] = entry

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
