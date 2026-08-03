"""StepReport 服务 — 全链步骤 Report 落库与查询。

每步执行（KG_PREBUILD / L1 / L3 / EXPLORE / PARSE / EXECUTE）产出一条
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

VALID_STAGES = {"KG_PREBUILD", "L1", "L3", "EXPLORE", "PARSE", "EXECUTE"}


class StepReport(BaseModel):
    """全链步骤 Report 契约。"""

    stage: str                                     # KG_PREBUILD / L1 / L3 / EXPLORE / PARSE / EXECUTE
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
            from app.utils.sse_publisher import SSEPublisher

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
    return {
        "session_id": session_id,
        "stages": stages,
        "by_dimension": by_dim,
        "reports": reports,
    }


__all__ = [
    "StepReport",
    "VALID_STAGES",
    "save_step_report",
    "get_session_step_reports",
    "build_positioning_trace",
]
