"""StepReport 服务 — 全链步骤 Report 落库与查询。

每步执行（L1 / L2 / L3 / KG / EXPLORE / TARGET_PROJECTION / EXECUTE / OUTPUT / RENDER）产出一条
StepReport，记录输入摘要 / 输出摘要 / 产物引用 / 诊断指标，供
positioning-trace 面板按 session + stage + dimension_key 下钻，
定位"文本说 X 但几何算出 Y"的断点。

设计：
  - 独立 ``step_reports`` 表（不复用 dimension_reports，字段语义干净）。
  - ``save_step_report`` 非致命：任何失败仅告警，不阻断规划主流程。
  - ``get_session_step_reports`` 按 session 拉全量，供 API 聚合。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.utils.logger import get_logger

logger = get_logger(__name__)

VALID_STAGES = {
    "KG_PREBUILD",
    "L1",
    "L2",
    "L3",
    "KG",
    "CONFLICT",
    "EXPLORE",
    "TARGET_PROJECTION",
    "GROUND",
    "SELECT",
    "EXECUTE",
    "VALIDATE",
    "RECONCILE",
    "DELIVER",
    "OUTPUT",
    "RENDER",
}


class StepReport(BaseModel):
    """全链步骤 Report 契约。"""

    stage: str
    step_name: str = ""                            # "analyze_dimension:location"
    session_id: str = ""
    dimension_key: str = ""
    layer: int = 0
    inputs: Dict[str, Any] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    diagnostics: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = ""


async def save_step_report(
    session_id: str,
    stage: str,
    *,
    step_name: str = "",
    dimension_key: str = "",
    layer: int = 0,
    inputs: Optional[Dict[str, Any]] = None,
    outputs: Optional[Dict[str, Any]] = None,
    artifacts: Optional[List[Dict[str, Any]]] = None,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> bool:
    """落库一条 StepReport（非致命）。

    Returns:
        True 成功；False 失败（已记录告警）。
    """
    if not session_id:
        return False
    if stage not in VALID_STAGES:
        stage = "OTHER"
    try:
        from app.database.engine import get_async_session
        from app.database.models import StepReportModel

        rec = StepReportModel(
            session_id=session_id,
            stage=stage,
            step_name=step_name or stage,
            dimension_key=dimension_key,
            layer=layer,
            inputs=inputs or {},
            outputs=outputs or {},
            artifacts=artifacts or [],
            diagnostics=diagnostics or {},
            timestamp=datetime.now(),
        )
        async with get_async_session() as db:
            db.add(rec)
            await db.commit()
        logger.info("[StepReport] saved %s/%s (%s)", session_id, stage, step_name)
        # P2: SSE 推送 step_report 事件（实时可见）
        try:
            from app.infrastructure.events.sse_publisher import SSEPublisher

            SSEPublisher.send_event(
                session_id=session_id,
                event_type="step_report",
                stage=stage,
                step_name=step_name or stage,
                dimension_key=dimension_key,
                outputs=outputs or {},
                diagnostics=diagnostics or {},
                timestamp=datetime.now().isoformat(),
            )
        except Exception as sse_e:
            logger.debug("[StepReport] SSE publish failed: %s", sse_e)
        return True
    except Exception as e:  # noqa: BLE001 — 非致命
        logger.warning("[StepReport] save failed %s/%s: %s", session_id, stage, e)
        return False


async def get_session_step_reports(
    session_id: str,
    stage: Optional[str] = None,
    dimension_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """按 session 查询 StepReport 列表（可选 stage / dimension_key 过滤）。

    Returns:
        list of dict（按 timestamp 升序）。
    """
    try:
        from sqlalchemy import select
        from app.database.engine import get_async_session
        from app.database.models import StepReportModel

        async with get_async_session() as db:
            statement = select(StepReportModel).where(
                StepReportModel.session_id == session_id,
            )
            if stage:
                statement = statement.where(StepReportModel.stage == stage)
            if dimension_key:
                statement = statement.where(StepReportModel.dimension_key == dimension_key)
            statement = statement.order_by(StepReportModel.timestamp.asc())
            result = await db.execute(statement)
            rows = result.scalars().all()
            return [
                {
                    "id": r.id,
                    "session_id": r.session_id,
                    "stage": r.stage,
                    "step_name": r.step_name,
                    "dimension_key": r.dimension_key,
                    "layer": r.layer,
                    "inputs": r.inputs or {},
                    "outputs": r.outputs or {},
                    "artifacts": r.artifacts or [],
                    "diagnostics": r.diagnostics or {},
                    "timestamp": r.timestamp.isoformat() if r.timestamp else "",
                }
                for r in rows
            ]
    except Exception as e:  # noqa: BLE001 — 查询失败非致命
        logger.warning("[StepReport] query failed %s: %s", session_id, e)
        return []


async def build_positioning_trace(session_id: str) -> Dict[str, Any]:
    """聚合全链 StepReport 为定位面板数据。

    Returns:
        {
          "session_id": ...,
          "stages": ["KG_PREBUILD", "L1", ...],        # 有数据的 stage 列表
          "by_dimension": {dim_key: [step_report, ...]}, # 按维度索引
          "reports": [...],                              # 全量（时间升序）
        }
    """
    reports = await get_session_step_reports(session_id)
    by_dim: Dict[str, List[Dict[str, Any]]] = {}
    for r in reports:
        dk = r.get("dimension_key") or "__global__"
        by_dim.setdefault(dk, []).append(r)
    stages = list(dict.fromkeys(r.get("stage", "") for r in reports if r.get("stage")))
    required_stages = [
        "L1", "L2", "L3", "KG", "EXPLORE", "TARGET_PROJECTION", "CONFLICT",
        "GROUND", "SELECT", "EXECUTE", "VALIDATE", "RECONCILE", "DELIVER",
        "OUTPUT", "RENDER",
    ]
    stage_coverage = {
        stage: any(r.get("stage") == stage for r in reports)
        for stage in required_stages
    }
    return {
        "session_id": session_id,
        "stages": stages,
        "stage_coverage": stage_coverage,
        "complete": all(stage_coverage.values()),
        "by_dimension": by_dim,
        "reports": reports,
    }


async def build_backend_run_report(session_id: str) -> Dict[str, Any]:
    """Build an auditable feasibility report for one backend planning run."""
    from app.infrastructure.reports.report_store import ReportStore

    trace = await build_positioning_trace(session_id)
    store = ReportStore.get_instance()
    layers: Dict[str, Any] = {}
    issues: List[Dict[str, Any]] = []

    for layer in (1, 2, 3):
        reports = await store.get_layer_reports_with_sources(session_id, layer)
        dimensions = sorted(reports)
        char_count = sum(len((item or {}).get("content", "")) for item in reports.values())
        source_count = sum(
            len((item or {}).get("knowledge_sources", []) or [])
            for item in reports.values()
        )
        layers[f"L{layer}"] = {
            "report_count": len(reports),
            "dimensions": dimensions,
            "char_count": char_count,
            "knowledge_source_count": source_count,
            "available": bool(reports) and char_count > 0,
        }
        if not reports or char_count <= 0:
            issues.append({
                "code": f"missing_l{layer}_reports",
                "message": f"No L{layer} reports were persisted.",
            })

    latest_by_stage: Dict[str, Dict[str, Any]] = {}
    for report in trace["reports"]:
        latest_by_stage[report.get("stage", "")] = report

    execute = latest_by_stage.get("EXECUTE", {})
    output = latest_by_stage.get("OUTPUT", {})
    render = latest_by_stage.get("RENDER", {})
    validation_passed = bool(
        (execute.get("diagnostics") or {}).get("validation_passed", False)
    )
    output_status = (output.get("outputs") or {}).get("status", "")
    render_layer_count = int(
        (render.get("outputs") or {}).get("render_layers", 0) or 0
    )
    preview_status = (render.get("outputs") or {}).get("preview_status", "")
    html_status = (render.get("outputs") or {}).get("html_status", "")
    render_quality = (render.get("outputs") or {}).get("render_quality") or {}
    projection_outputs = (latest_by_stage.get("TARGET_PROJECTION", {}).get("outputs") or {})
    execute_outputs = execute.get("outputs") or {}
    feature_counts = execute_outputs.get("valid_geometry_counts") or {}

    for stage, present in trace["stage_coverage"].items():
        if not present:
            issues.append({
                "code": f"missing_stage_{stage.lower()}",
                "message": f"No interaction report was recorded for {stage}.",
            })
    if not validation_passed:
        issues.append({
            "code": "validation_not_passed",
            "message": "GIS validation did not pass.",
        })
    if output_status != "completed":
        issues.append({
            "code": "output_not_completed",
            "message": f"Output package status is '{output_status or 'missing'}'.",
        })
    if render_layer_count <= 0:
        issues.append({
            "code": "render_empty",
            "message": "No renderable map layers were produced.",
        })
    if preview_status != "completed":
        issues.append({
            "code": "preview_not_completed",
            "message": f"Static preview status is '{preview_status or 'missing'}'.",
        })
    if html_status != "completed":
        issues.append({
            "code": "html_map_not_completed",
            "message": f"Interactive HTML map status is '{html_status or 'missing'}'.",
        })
    if render_quality and render_quality.get("status") != "passed":
        issues.append({
            "code": "render_quality_failed",
            "message": "Rendered output is missing a current or complete planned layer, or contains empty geometry.",
        })
    if int(projection_outputs.get("facilities", 0) or 0) > 0 and int(
        feature_counts.get("facility_point", 0) or 0
    ) <= 0:
        issues.append({
            "code": "planned_facilities_unresolved",
            "message": "Facility targets were projected but no planned facility geometry was produced.",
        })
    formal_road_count = sum(
        int(feature_counts.get(layer_type, 0) or 0)
        for layer_type in ("planned_road", "planned_road_candidates")
    )
    if int(projection_outputs.get("road_targets", 0) or 0) > 0 and formal_road_count <= 0:
        issues.append({
            "code": "planned_roads_unresolved",
            "message": "Road targets were projected but no formal planned road geometry was produced.",
        })

    kg_steps = [
        {
            "step_name": report.get("step_name", ""),
            "inputs": report.get("inputs") or {},
            "outputs": report.get("outputs") or {},
            "diagnostics": report.get("diagnostics") or {},
        }
        for report in trace["reports"]
        if report.get("stage") == "KG"
    ]
    kg_build = next(
        (
            step
            for step in kg_steps
            if step.get("step_name") == "build_static_layers"
        ),
        {},
    )
    if int((kg_build.get("outputs") or {}).get("triple_count", 0) or 0) <= 0:
        issues.append({
            "code": "kg_empty",
            "message": "The static knowledge graph has no triples.",
        })
    providers = list((kg_build.get("inputs") or {}).get("provider_sources", []) or [])
    has_upload = any(str(source).startswith("upload:") for source in providers)
    has_demo = any("jintian" in str(source).lower() for source in providers)
    if not providers:
        issues.append({
            "code": "gis_sources_missing",
            "message": "No GIS provider sources were recorded.",
        })
    if has_upload and has_demo:
        issues.append({
            "code": "mixed_demo_sources",
            "message": "Session GIS uploads were mixed with Jintian demo sources.",
        })
    report = {
        "session_id": session_id,
        "feasible": not issues,
        "layers": layers,
        "interaction_trace": {
            "complete": trace["complete"],
            "stage_coverage": trace["stage_coverage"],
            "report_count": len(trace["reports"]),
        },
        "kg": {
            "steps": kg_steps,
        },
        "execution": {
            "validation_passed": validation_passed,
            "diagnostics": execute.get("diagnostics") or {},
        },
        "output": output.get("outputs") or {},
        "render": render.get("outputs") or {},
        "artifacts": [
            artifact
            for report in trace["reports"]
            for artifact in (report.get("artifacts") or [])
        ],
        "issues": issues,
    }
    try:
        from app.infrastructure.reports.stage_report import render_stage_report_markdown
        report_md = render_stage_report_markdown(trace["reports"], report)
    except Exception:  # noqa: BLE001
        report_md = ""
    report["markdown"] = report_md
    return report


__all__ = [
    "StepReport",
    "VALID_STAGES",
    "save_step_report",
    "get_session_step_reports",
    "build_positioning_trace",
    "build_backend_run_report",
]
