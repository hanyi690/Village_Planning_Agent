"""Human-readable Markdown rendering of the full GIS pipeline stage reports."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def _summary(value: Any, *, depth: int = 0) -> Any:
    """Keep the operator report readable while retaining useful structure."""
    if depth >= 2:
        if isinstance(value, dict):
            compact: Dict[str, Any] = {
                "keys": list(value)[:20],
                "key_count": len(value),
            }
            if value.get("type"):
                compact["type"] = value["type"]
            if isinstance(value.get("features"), list):
                compact["feature_count"] = len(value["features"])
            return compact
        if isinstance(value, list):
            return {"items": len(value)}
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for key, item in list(value.items())[:40]:
            if isinstance(item, str) and len(item) > 800:
                result[key] = {"chars": len(item), "preview": item[:500]}
            else:
                result[key] = _summary(item, depth=depth + 1)
        if len(value) > 40:
            result["_omitted_keys"] = len(value) - 40
        return result
    if isinstance(value, list):
        return {
            "items": len(value),
            "sample": [_summary(item, depth=depth + 1) for item in value[:3]],
        }
    return value


def _fmt(value: Any) -> str:
    """Render a concise, human-readable value for the audit report."""
    if isinstance(value, (dict, list)):
        return json.dumps(_summary(value), ensure_ascii=False, indent=2, sort_keys=True)
    if isinstance(value, str) and len(value) > 1200:
        return json.dumps({"chars": len(value), "preview": value[:800]}, ensure_ascii=False)
    return str(value)


def _artifact_payloads(reports: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Load full persisted payloads for the report without changing checkpoint state."""
    from app.modules.ports.artifact_store import ArtifactRef
    from app.services.artifact_store import FilesystemArtifactStore

    payloads: Dict[str, Any] = {}
    store = FilesystemArtifactStore()
    for report in reports:
        for artifact in report.get("artifacts") or []:
            artifact_id = artifact.get("artifact_id")
            run_id = artifact.get("run_id") or report.get("session_id")
            module = artifact.get("module")
            if not artifact_id or not run_id or not module:
                continue
            try:
                ref = ArtifactRef(**{
                    "artifact_id": artifact_id,
                    "run_id": run_id,
                    "module": module,
                    "artifact_type": artifact.get("artifact_type", ""),
                    "context_version": artifact.get("context_version", ""),
                    "revision": artifact.get("revision", "v1"),
                })
                payloads[artifact.get("key") or artifact_id] = store.retrieve(ref)
            except Exception as exc:  # noqa: BLE001 - preserve report even if artifact is unavailable
                payloads[artifact.get("key") or artifact_id] = {
                    "_load_error": type(exc).__name__,
                    "detail": str(exc),
                }
    return payloads


def render_stage_report_markdown(
    reports: List[Dict[str, Any]],
    summary: Dict[str, Any],
) -> str:
    lines = ["# GIS 全链阶段报告", ""]
    lines.append(f"- **Session**: {summary.get('session_id', '')}")
    deliver_passed = any(
        r.get("stage") == "DELIVER"
        and (r.get("diagnostics") or {}).get("status") == "stage_completed"
        and (r.get("diagnostics") or {}).get("gate_route") == "PASS"
        for r in reports
    )
    lines.append(f"- **Feasible**: {bool(summary.get('feasible', False) or deliver_passed)}")
    lines.append("")
    order = {stage: index for index, stage in enumerate(
        ["KG_PREBUILD", "L1", "L2", "L3", "PARSE", "GROUND", "SELECT", "EXECUTE", "VALIDATE", "RECONCILE", "DELIVER"]
    )}
    reports = sorted(
        reports,
        key=lambda r: (order.get(r.get("stage", ""), 99), r.get("timestamp", "")),
    )
    # Put the fact lineage up front so an operator can see the producer and
    # consumer without opening raw JSON artifacts.
    fact_records = [
        r for r in reports
        if r.get("stage") in {"KG_PREBUILD", "L1", "L2"}
        and ((r.get("outputs") or {}).get("facts_produced")
             or (r.get("outputs") or {}).get("kg_evidence_consumed")
             or (r.get("outputs") or {}).get("location_facts")
             or (r.get("outputs") or {}).get("l1_snapshot_ref")
             or (r.get("diagnostics") or {}).get("fact_producer")
             or (r.get("diagnostics") or {}).get("fact_consumer"))
    ]
    if fact_records:
        lines.append("## Fact lineage（KG → L1 → L2）")
        lines.append("")
        lines.append("以下内容来自实际 session 的 KG、L1Snapshot 和 L2 输入审计；不是测试占位数据。")
        lines.append("")
        for r in fact_records:
            outputs = r.get("outputs") or {}
            diagnostics = r.get("diagnostics") or {}
            lines.append(f"- **{r.get('stage')} / {r.get('step_name')}**")
            if diagnostics.get("fact_producer"):
                lines.append(f"  - producer: {diagnostics['fact_producer']}")
            if diagnostics.get("fact_consumer"):
                lines.append(f"  - consumer: {diagnostics['fact_consumer']}")
            if outputs.get("facts_produced"):
                lines.append(f"  - facts_produced: {_fmt(outputs['facts_produced'])}")
            if outputs.get("kg_evidence_consumed"):
                lines.append(f"  - kg_evidence_consumed: {_fmt(outputs['kg_evidence_consumed'])}")
            if outputs.get("location_facts"):
                lines.append(f"  - location_facts: {_fmt(outputs['location_facts'])}")
            if diagnostics.get("l1_fact_count") is not None:
                lines.append(f"  - l1_snapshot_facts_consumed: {diagnostics['l1_fact_count']}")
        lines.append("")

    for r in reports:
        stage = r.get("stage", "?")
        step = r.get("step_name", "")
        lines.append(f"## {stage} / {step}")
        lines.append(f"- timestamp: {r.get('timestamp', '')}")
        inputs = r.get("inputs") or {}
        if inputs:
            lines.append("### 输入")
            for k, v in sorted(inputs.items()):
                lines.append(f"- **{k}**: {_fmt(v)}")
        outputs = r.get("outputs") or {}
        if outputs:
            lines.append("### 产出")
            for k, v in sorted(outputs.items()):
                lines.append(f"- **{k}**: {_fmt(v)}")
        payloads = r.get("artifact_payloads") or {}
        if payloads:
            lines.append("### 产物摘要（ArtifactStore）")
            for key, payload in payloads.items():
                lines.append(f"#### {key}")
                lines.append("```json")
                lines.append(json.dumps(_summary(payload), ensure_ascii=False, indent=2, sort_keys=True))
                lines.append("```")
        diag = r.get("diagnostics") or {}
        if diag:
            lines.append("### 诊断")
            for k, v in sorted(diag.items()):
                lines.append(f"- {k}: {_fmt(v)}")
        artifacts = r.get("artifacts") or []
        if artifacts:
            lines.append("### 产物")
            for a in artifacts:
                key = a.get("key") or a.get("kind") or "artifact"
                artifact_id = a.get("artifact_id") or a.get("path") or ""
                artifact_type = a.get("artifact_type") or a.get("type") or ""
                revision = a.get("revision") or ""
                checksum = a.get("checksum") or ""
                details = ", ".join(
                    part for part in (
                        f"type={artifact_type}" if artifact_type else "",
                        f"revision={revision}" if revision else "",
                        f"checksum={checksum}" if checksum else "",
                    ) if part
                )
                suffix = f" ({details})" if details else ""
                lines.append(f"- **{key}**: `{artifact_id}`{suffix}")
        lines.append("")
    return "\n".join(lines)


async def build_stage_report_markdown(session_id: str) -> str:
    from app.services.step_report import build_backend_run_report, get_session_step_reports

    reports = await get_session_step_reports(session_id)
    if not reports:
        return ""
    reports = list(reports)
    payloads = _artifact_payloads(reports)
    for report in reports:
        report["artifact_payloads"] = {
            artifact.get("key") or artifact.get("artifact_id"): payloads[artifact.get("key") or artifact.get("artifact_id")]
            for artifact in report.get("artifacts") or []
            if (artifact.get("key") or artifact.get("artifact_id")) in payloads
        }
    try:
        summary = await build_backend_run_report(session_id)
    except Exception:  # noqa: BLE001 — non-fatal
        summary = {}
    # Keep the API response and the operator-facing file identical. The
    # runtime working directory is the backend directory for uvicorn/tests,
    # matching FilesystemArtifactStore's default `.run-tmp` root.
    markdown = render_stage_report_markdown(reports, summary)
    output = Path(".run-tmp") / session_id / "reports" / "stage-report.md"
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown, encoding="utf-8")
    except OSError:
        # Reporting must remain readable through the API even if the optional
        # local operator directory is unavailable.
        pass
    return markdown
