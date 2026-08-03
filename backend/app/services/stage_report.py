"""Human-readable Markdown rendering of the full GIS pipeline stage reports."""
from __future__ import annotations

import json
from typing import Any, Dict, List


def _fmt(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)[:200]
    return str(value)


def render_stage_report_markdown(
    reports: List[Dict[str, Any]],
    summary: Dict[str, Any],
) -> str:
    lines = ["# GIS 全链阶段报告", ""]
    lines.append(f"- **Session**: {summary.get('session_id', '')}")
    lines.append(f"- **Feasible**: {summary.get('feasible', False)}")
    lines.append("")
    for r in reports:
        stage = r.get("stage", "?")
        step = r.get("step_name", "")
        lines.append(f"## {stage} / {step}")
        lines.append(f"- timestamp: {r.get('timestamp', '')}")
        outputs = r.get("outputs") or {}
        if outputs:
            lines.append("### 产出")
            for k, v in sorted(outputs.items()):
                lines.append(f"- **{k}**: {_fmt(v)}")
        diag = r.get("diagnostics") or {}
        if diag:
            lines.append("### 诊断")
            for k, v in sorted(diag.items()):
                lines.append(f"- {k}: {_fmt(v)}")
        artifacts = r.get("artifacts") or []
        if artifacts:
            lines.append("### 产物")
            for a in artifacts:
                lines.append(f"- {a.get('kind')}: `{a.get('path')}`")
        lines.append("")
    return "\n".join(lines)


async def build_stage_report_markdown(session_id: str) -> str:
    from app.services.step_report import build_backend_run_report, get_session_step_reports

    reports = await get_session_step_reports(session_id)
    if not reports:
        return ""
    try:
        summary = await build_backend_run_report(session_id)
    except Exception:  # noqa: BLE001 — non-fatal
        summary = {}
    return render_stage_report_markdown(reports, summary)
