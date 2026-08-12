"""Human-readable Markdown rendering of the full GIS pipeline stage reports."""
from __future__ import annotations

import json
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
    from app.infrastructure.artifacts import ContentAddressedArtifactRepository
    from app.contracts.artifacts.artifact_descriptor import ArtifactDescriptor
    from app.infrastructure.paths import run_tmp_root

    payloads: Dict[str, Any] = {}
    repository = ContentAddressedArtifactRepository(run_tmp_root())
    for report in reports:
        for artifact in report.get("artifacts") or []:
            descriptor_digest = artifact.get("descriptor_digest")
            if not descriptor_digest:
                continue
            try:
                descriptor = repository.get_descriptor(descriptor_digest)
                payloads[artifact.get("key") or descriptor_digest] = repository.get_json(descriptor)
            except Exception as exc:  # noqa: BLE001 - preserve report even if artifact is unavailable
                payloads[artifact.get("key") or descriptor_digest] = {
                    "_load_error": type(exc).__name__,
                    "detail": str(exc),
                }
    return payloads


def _artifact_payload_link(report: Dict[str, Any], artifact: Dict[str, Any]) -> str:
    """Return a report-relative link to the authoritative full payload."""
    descriptor_digest = artifact.get("descriptor_digest")
    if not descriptor_digest:
        return ""
    return f"cas://{descriptor_digest}"


def _human_artifact_detail(key: str, payload: Any) -> Dict[str, Any]:
    """Extract operator-facing facts without copying the full typed payload.

    The JSON artifact remains authoritative and complete.  This view is
    deliberately targeted so a reviewer can understand what each stage
    produced without opening a multi-megabyte GeoJSON or losing the important
    facts in a generic ``items=N`` summary.
    """
    if not isinstance(payload, dict):
        return {"value": _summary(payload)}

    def take(name: str, limit: int = 12) -> None:
        value = payload.get(name)
        if value is None or value == [] or value == {}:
            return
        if isinstance(value, list):
            detail[name] = {
                "count": len(value),
                "items": [_summary(item) for item in value[:limit]],
                "omitted": max(0, len(value) - limit),
            }
        elif isinstance(value, dict):
            detail[name] = {
                "count": len(value),
                "items": {str(k): _summary(v) for k, v in list(value.items())[:limit]},
                "omitted": max(0, len(value) - limit),
            }
        else:
            detail[name] = value

    detail: Dict[str, Any] = {}
    if key == "l1_snapshot":
        for name in ("facts", "facts_by_dimension", "location_facts", "gis_evidence", "kg_evidence", "evidence_gaps"):
            take(name, 16 if name in {"facts", "location_facts"} else 12)
    elif key == "l2_strategy":
        for name in ("development_goals", "implementation_priorities", "strategy_issues", "strategy_conflicts", "evidence_gaps"):
            take(name, 12)
    elif key in {"planning_program", "target_projection"}:
        for name in ("typed_intent", "interventions", "spatial_specs", "project_targets", "zone_targets", "facility_targets", "development_axes"):
            take(name, 12)
    elif key == "grounding_result":
        for name in ("candidates", "unresolved", "unresolved_references", "spatial_query_evidence", "issues"):
            take(name, 12)
    elif key == "site_selection":
        for name in ("selections", "selected_sites", "unplaced_targets", "issues"):
            take(name, 12)
    elif key == "execution_plan":
        for name in ("worker_tasks", "deferred_tasks", "dependencies", "provenance"):
            take(name, 12)
    elif key == "execution_result":
        for name in ("task_results", "action_results", "diagnostics"):
            take(name, 20)
    elif key in {"parcel_changeset", "planned_state"}:
        for name in ("changes", "parcels", "zones", "facilities", "roads", "axes", "provenance"):
            take(name, 12)
    elif key == "validation_report":
        for name in ("checks", "violations", "diagnostics", "overall_passed"):
            take(name, 16)
    elif key == "reconciliation_report":
        for name in ("inconsistencies", "diagnostics", "overall_consistent"):
            take(name, 16)
    elif key == "delivery_manifest":
        for name in (
            "delivery_status", "statutory_complete",
            "statutory_complete_breakdown", "pending_human_items",
            "deferral_summary", "diagnostic_summary", "traceability",
            "action_results", "deliverables",
        ):
            take(name, 16)
    elif key == "render_layers":
        if isinstance(payload, list):
            return {"layer_count": len(payload), "layers": [_summary(item) for item in payload[:20]]}
        for name in ("layers", "layer_count", "feature_counts"):
            take(name, 20)
    if not detail:
        for name in ("summary", "issues", "diagnostics", "provenance", "sources"):
            take(name, 8)
    return detail


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
        ["KG_PREBUILD", "L1", "L2", "L3", "TARGET_PROJECTION", "GROUND", "SELECT", "EXECUTE", "VALIDATE", "RECONCILE", "DELIVER"]
    )}
    reports = sorted(
        reports,
        key=lambda r: (order.get(r.get("stage", ""), 99), r.get("timestamp", "")),
    )
    source_files: Dict[str, Dict[str, Any]] = {}
    for report in reports:
        for source in (report.get("inputs") or {}).get("source_refs") or []:
            if isinstance(source, dict):
                name = source.get("filename") or source.get("id") or "source"
                source_files[str(name)] = source
            else:
                source_files[str(source)] = {"reference": source}
    if source_files:
        lines.append("## 真实输入文件")
        lines.append("")
        lines.append("以下是本次 Session 实际上传并进入工作流的文件元数据；原始内容保存在上传存储，checksum 用于复核输入是否变化。")
        lines.append("")
        for name, source in source_files.items():
            if "reference" in source:
                lines.append(f"- **{name}**: {source['reference']}")
                continue
            details = []
            for field, label in (("file_category", "类别"), ("file_type", "类型"), ("size_bytes", "字节"), ("checksum", "checksum"), ("parse_status", "解析")):
                if source.get(field) not in (None, ""):
                    details.append(f"{label}={source[field]}")
            lines.append(f"- **{name}**: " + ("；".join(details) or "已上传"))
        lines.append("")
    # Put the fact lineage up front so an operator can see the producer and
    # consumer without opening raw JSON artifacts.
    fact_records = [
        r for r in reports
        if r.get("stage") in {"KG_PREBUILD", "L1", "L2"}
        and ((r.get("outputs") or {}).get("facts_produced")
             or (r.get("outputs") or {}).get("kg_evidence_consumed")
             or (r.get("outputs") or {}).get("location_facts")
             or (r.get("outputs") or {}).get("artifact_refs", {}).get("l1_snapshot")
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
                detail = _human_artifact_detail(key, payload)
                if detail:
                    lines.append("**关键内容（供人工审计）**")
                    lines.append("```json")
                    lines.append(json.dumps(detail, ensure_ascii=False, indent=2, sort_keys=True))
                    lines.append("```")
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
                artifact_id = a.get("descriptor_digest") or a.get("digest") or a.get("path") or ""
                artifact_type = a.get("schema_id") or a.get("type") or ""
                branch_id = a.get("branch_id") or ""
                checksum = a.get("digest") or ""
                details = ", ".join(
                    part for part in (
                        f"type={artifact_type}" if artifact_type else "",
                        f"branch={branch_id}" if branch_id else "",
                        f"checksum={checksum}" if checksum else "",
                    ) if part
                )
                suffix = f" ({details})" if details else ""
                lines.append(f"- **{key}**: `{artifact_id}`{suffix}")
                payload_link = _artifact_payload_link(r, a)
                if payload_link:
                    lines.append(f"  - 完整 payload：[{key}.payload.json]({payload_link})")
        lines.append("")
    return "\n".join(lines)


async def build_stage_report_markdown(session_id: str) -> str:
    from app.infrastructure.reports.step_report import build_backend_run_report, get_session_step_reports

    reports = await get_session_step_reports(session_id)
    if not reports:
        return ""
    reports = list(reports)
    payloads = _artifact_payloads(reports)
    for report in reports:
        report["artifact_payloads"] = {
            artifact.get("key") or artifact.get("descriptor_digest") or artifact.get("digest"): payloads[artifact.get("key") or artifact.get("descriptor_digest") or artifact.get("digest")]
            for artifact in report.get("artifacts") or []
            if (artifact.get("key") or artifact.get("descriptor_digest") or artifact.get("digest")) in payloads
        }
    try:
        summary = await build_backend_run_report(session_id)
    except Exception:  # noqa: BLE001 — non-fatal
        summary = {}
    # Keep the API response and the operator-facing file identical. The
    # runtime working directory is the backend directory for uvicorn/tests,
    # matching the CAS repository's default `.run-tmp` root.
    markdown = render_stage_report_markdown(reports, summary)
    from app.infrastructure.paths import session_run_dir

    output = session_run_dir(session_id) / "reports" / "stage-report.md"
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown, encoding="utf-8")
    except OSError:
        # Reporting must remain readable through the API even if the optional
        # local operator directory is unavailable.
        pass
    return markdown
