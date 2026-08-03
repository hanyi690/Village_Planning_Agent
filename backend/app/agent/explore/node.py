"""EXPLORE 主图节点 — L3 完成后桥接文本与空间。

职责：
  1. 读 L1+L2+L3 报告摘要（build_report_summary_index，已存在）。
  2. 对 high/medium 空间相关维度的 spatial_hints 调
     spatial_ops.grounding.resolve_spatial_description（KG 拓扑优先）。
  3. 产出 ExplorationInstructionCollection + ReportSummaryIndex 写入 AgentState。
  4. 写 StepReport(stage="EXPLORE")，供 positioning-trace 定位。

非致命：任何失败仅告警，返回空产出，不阻断主图（后续 gis_agent 仍可独立运行）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from app.agent.explore.contracts import (
    ExplorationInstruction,
    ExplorationInstructionCollection,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SPATIAL_DIMS = {
    "land_use", "natural_environment", "ecological_green", "traffic",
    "public_services", "infrastructure", "architecture", "location",
    "superior_planning", "resource_endowment", "planning_positioning",
    "spatial_structure", "land_use_planning", "settlement_planning",
    "traffic_planning", "public_service", "ecological",
}
# 每维度最多产出的 grounding 描述数（token 预算）
_MAX_HINTS_PER_DIM = 4


async def explore_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """EXPLORE 桥接节点（L3 完成后自动触发）。

    Returns:
        更新 explore_instructions + report_summary_index（可能为空）。
    """
    session_id = state.get("session_id", "")
    if not session_id:
        return {}

    # 1. 构建 ReportSummaryIndex（读 L1/L2/L3 报告摘要）
    index_data: Dict[str, Any] = {}
    try:
        from app.agent.explore.summaries import build_report_summary_index

        index_data = await build_report_summary_index(session_id)
    except Exception as e:
        logger.warning("[explore_node] summary index failed: %s", e)

    entries = index_data.get("entries") or {}

    # 2. L3 INSTRUCTION → formal ExplorationInstruction records.
    formal_instructions: List[ExplorationInstruction] = []
    try:
        from app.agent.explore.agent import ExploreFlashAgent
        from app.services.report_store import ReportStore

        store = ReportStore.get_instance()
        l3_reports = await store.get_layer_reports_with_sources(session_id, 3)
        explorer = ExploreFlashAgent(
            session_id=session_id,
            village_name=index_data.get("village_name", ""),
        )
        for dim_key, record in (l3_reports or {}).items():
            source_text = (
                (record or {}).get("instruction")
                or (record or {}).get("content")
                or ""
            )
            if not source_text:
                continue
            collection = explorer.explore(source_text)
            for item in collection.instructions:
                item.source_chunk_id = f"{dim_key}:{item.source_chunk_id}"
                formal_instructions.append(item)
    except Exception as e:
        logger.warning("[explore_node] L3 instruction exploration failed: %s", e)

    # 3. Resolve every instruction independently (KG topology first).
    grounding_stats: Dict[str, Any] = {"total": 0, "resolved": 0, "unresolved": 0}
    try:
        from app.modules.spatial_ops.grounding import resolve_spatial_description
        from app.tools.access.shared import resolve_bundle, session_kg

        bundle = await resolve_bundle(session_id)
        kg = session_kg(session_id)
        # 调用方注入 gazetteer（P0 多源坐标+组合名）与 KG 查询回调
        gazetteer = None
        kg_query_fn = None
        try:
            from app.modules.kg.gazetteer import load_gazetteer
            gazetteer = load_gazetteer(
                getattr(bundle, "village_name", None) or "jintian"
            )
        except Exception:
            pass
        if kg is not None:
            try:
                from app.modules.kg.queries.sparql import query_kg as _qkg

                def kg_query_fn(template_name, **kw):
                    return _qkg(kg, template_name, **kw)
            except Exception:
                kg_query_fn = None
        if bundle is None:
            bundle = type("B", (), {"polygons": {"get": lambda *a, **k: []}})()
        if not formal_instructions:
            for dim_key, entry in entries.items():
                if dim_key not in _SPATIAL_DIMS:
                    continue
                hints = entry.get("spatial_hints") or entry.get("key_spatial_findings") or []
                for hint in hints[: _MAX_HINTS_PER_DIM]:
                    if not hint or len(str(hint)) < 2:
                        continue
                    formal_instructions.append(ExplorationInstruction(
                        instruction_id=f"EXP-{len(formal_instructions) + 1:04d}",
                        source_chunk_id=f"{dim_key}:summary",
                        section_title=entry.get("dimension_name", dim_key),
                        evidence_text=str(hint),
                        domain="project",
                        entity_mentions=list(entry.get("mentioned_entities") or []),
                        confidence=0.5,
                        requires_human_confirmation=True,
                    ))

        for instruction in formal_instructions:
            grounding_stats["total"] += 1
            description = " ".join(
                [instruction.evidence_text, *instruction.entity_mentions]
            ).strip()
            try:
                resolved = resolve_spatial_description(
                    description,
                    bundle,
                    kg=kg,
                    gazetteer=gazetteer,
                    kg_query_fn=kg_query_fn,
                )
            except Exception as e:
                logger.debug(
                    "[explore_node] grounding %s failed: %s",
                    instruction.instruction_id,
                    e,
                )
                grounding_stats["unresolved"] += 1
                continue
            if resolved.candidate_bsms:
                grounding_stats["resolved"] += 1
                instruction.candidate_bsm_list = list(dict.fromkeys(
                    [*instruction.candidate_bsm_list, *resolved.candidate_bsms]
                ))[:50]
                if resolved.candidate_bbox:
                    instruction.candidate_bbox = list(resolved.candidate_bbox)
                instruction.confidence = max(
                    instruction.confidence,
                    resolved.confidence,
                )
                instruction.requires_human_confirmation = (
                    len(instruction.candidate_bsm_list) != 1
                )
            else:
                grounding_stats["unresolved"] += 1
    except Exception as e:
        logger.warning("[explore_node] grounding pass failed: %s", e)

    # 4. Persist the canonical Explore contract in AgentState.
    collection = ExplorationInstructionCollection(
        session_id=session_id,
        village_name=index_data.get("village_name", ""),
        instructions=formal_instructions,
        kg_session_ref=session_id,
    )
    explore_output = collection.model_dump()
    explore_output["grounding_stats"] = grounding_stats
    explore_output["spatial_relevant_count"] = index_data.get("spatial_relevant_count", 0)

    # 5. StepReport
    try:
        from app.services.step_report import save_step_report

        await save_step_report(
            session_id, "EXPLORE",
            step_name="explore_bridge",
            outputs={
                "instructions": len(formal_instructions),
                "spatial_relevant_count": index_data.get("spatial_relevant_count", 0),
                "entries": len(entries),
            },
            diagnostics=grounding_stats,
            artifacts=[
                {"kind": "summary_index", "entries": len(entries)},
            ],
        )
    except Exception as e:
        logger.debug("[explore_node] step report failed: %s", e)

    logger.info(
        "[explore_node] %d instructions, %s",
        len(formal_instructions), grounding_stats,
    )
    return {
        "explore_instructions": explore_output,
        "report_summary_index": index_data,
        "explore_done": True,
    }


__all__ = ["explore_node"]
