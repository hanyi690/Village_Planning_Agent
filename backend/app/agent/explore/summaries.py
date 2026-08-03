"""EXPLORE summaries — 会话读路径的概要层（context blocks）。

- ``build_report_summary_index``: 维度级概要索引（“地图”），供 LLM/下游按维度
  导航，详情按需经 access 工具拉取（progressive disclosure）。
- ``build_spatial_cognition``: 单维度空间认知摘要（KG 语义 + 空间统计），
  可直接注入维度分析 prompt。

全部确定性实现（无 LLM 调用），从 bundle 快照 + 会话 KG 读取。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.modules.schema.types.canonical import VillageBundle
from app.tools.access.shared import group_stats, resolve_bundle, session_kg
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SPATIAL_KEYWORDS = (
    "公顷", "亩", "平方米", "m²", "km²", "公里", "面积", "占地", "位于", "沿",
    "临", "集中", "分布", "覆盖", "红线", "边界", "地块", "道路", "设施", "用地",
)

_ENTITY_PATTERN = re.compile(r"[「“\"']([^」”\"']{2,20})[」”\"']")
_PLACE_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,12}(?:村|镇|山|河|湖|路|园|基地|中心|站|场|区|带|廊道)")
_HINT_KEYWORDS = ("东", "南", "西", "北", "侧", "沿", "临", "靠近", "依托", "集中", "周边", "附近", "内部", "外部")

_SPATIAL_RELEVANCE: Dict[str, str] = {
    "land_use": "high",
    "natural_environment": "high",
    "ecological_green": "high",
    "traffic": "high",
    "public_services": "high",
    "infrastructure": "high",
    "architecture": "high",
    "location": "high",
    "superior_planning": "high",
    "resource_endowment": "medium",
    "planning_positioning": "medium",
    "development_goals": "medium",
    "planning_strategies": "medium",
    "socio_economic": "medium",
}


def _dimension_names() -> Dict[str, str]:
    try:
        from app.config import list_dimensions

        return {d.key: d.name for d in list_dimensions()}
    except Exception:
        return {}


def _split_sentences(content: str) -> List[str]:
    return [s.strip() for s in re.split(r"[。；\n]+", content) if s and len(s.strip()) >= 4]


def _key_spatial_findings(content: str, limit: int = 4) -> List[str]:
    findings = []
    for sent in _split_sentences(content):
        if any(k in sent for k in _SPATIAL_KEYWORDS) and re.search(r"\d", sent):
            findings.append(sent[:120])
        if len(findings) >= limit:
            break
    return findings


def _mentioned_entities(content: str, limit: int = 8) -> List[str]:
    entities: List[str] = []
    for m in _ENTITY_PATTERN.findall(content):
        if m not in entities:
            entities.append(m)
    for m in _PLACE_PATTERN.findall(content):
        if m not in entities:
            entities.append(m)
    return entities[:limit]


def _spatial_hints(content: str, limit: int = 4) -> List[str]:
    hints = []
    for sent in _split_sentences(content):
        if any(k in sent for k in _HINT_KEYWORDS):
            hints.append(sent[:100])
        if len(hints) >= limit:
            break
    return hints


# ============================================================
# ReportSummaryIndex — 维度级概要索引
# ============================================================

async def build_report_summary_index(
    session_id: str = "",
    bundle: Optional[VillageBundle] = None,
) -> Dict[str, Any]:
    """Build the dimension-level summary index (the EXPLORE “map”).

    Reads layer reports from the snapshot-first bundle; falls back to the
    live dimension_reports DB when the snapshot has none.
    """
    names = _dimension_names()
    if bundle is None:
        bundle = await resolve_bundle(session_id)

    layer_reports = dict(bundle.layer_reports or {})
    if not layer_reports:
        try:
            from app.services.report_store import ReportStore

            store = ReportStore.get_instance()
            for layer in (1, 2, 3):
                reports = await store.get_layer_reports_with_sources(session_id, layer)
                if reports:
                    layer_reports[layer] = {
                        dk: {"content": rec.get("content", ""), "summary": "", "version": None, "generated_at": None}
                        for dk, rec in reports.items()
                    }
        except Exception as e:
            logger.warning("[ExploreSummaries] Live report fallback failed: %s", e)

    entries: Dict[str, Any] = {}
    total = 0
    spatial_relevant = 0
    cross_dimension_findings: List[str] = []

    for layer in sorted(layer_reports):
        for dim_key, rec in layer_reports[layer].items():
            content = str(rec.get("content") or "")
            summary = str(rec.get("summary") or "")
            total += 1
            relevance = _SPATIAL_RELEVANCE.get(dim_key, "low")
            if relevance in ("high", "medium"):
                spatial_relevant += 1

            findings = _key_spatial_findings(content or summary)
            entries[dim_key] = {
                "dimension_key": dim_key,
                "layer": layer,
                "dimension_name": names.get(dim_key, dim_key),
                "spatial_relevance": relevance,
                "key_spatial_findings": findings,
                "mentioned_entities": _mentioned_entities(content or summary),
                "spatial_hints": _spatial_hints(content or summary),
                "report_available": bool(content),
            }
            if relevance == "high" and findings:
                cross_dimension_findings.append(f"[L{layer}]{dim_key}: {findings[0]}")

    return {
        "session_id": session_id,
        "village_name": bundle.village_name,
        "total_dimensions": total,
        "spatial_relevant_count": spatial_relevant,
        "entries": entries,
        "cross_dimension_findings": cross_dimension_findings[:12],
    }


# ============================================================
# SpatialCognitionSummary — 单维度空间认知
# ============================================================

def _format_prompt_section(payload: Dict[str, Any]) -> str:
    sections: List[str] = []
    kg = payload.get("kg_cognition") or {}
    semantic = kg.get("semantic") or {}

    ctx = semantic.get("context_block") or {}
    if ctx:
        sections.append(
            f"## 空间语义补充（EXPLORE KG 认知）\n"
            f"**村域概况**: {ctx.get('overview', '')}"
            f"地块数={ctx.get('parcel_count', 0)}, "
            f"总面积={ctx.get('total_area_ha', 0)}ha, "
            f"空间格局={ctx.get('spatial_pattern', '')}\n"
        )

    for card in (semantic.get("layer_cards") or []):
        if card.get("group") in ("current_landuse", "facility", "transport"):
            sections.append(
                f"**{card.get('group')}**: {card.get('distribution', '')}"
                f"（总计{card.get('count', 0)}个要素）\n"
            )

    constraint = semantic.get("constraint_block") or {}
    if constraint:
        sections.append(f"**约束覆盖**: {constraint}\n")

    # P1: L2/L3 拓扑结构认知（KG 拓扑查询，按 dim_layer 分派）
    topology = _build_topology_section(payload.get("_kg"), payload.get("dimension_key"),
                                        payload.get("layer", 1))
    if topology:
        sections.append(topology)

    findings = payload.get("spatial_findings") or []
    if findings:
        sections.append("**空间线索**: " + "; ".join(findings[:5]) + "\n")

    return "\n".join(sections)


def _build_topology_section(kg: Any, dim_key: str, dim_layer: int) -> str:
    """L2/L3 维度注入 KG 现状结构/拓扑认知（替代静态 DIM_KG_MAP 的 execute 查询）。

    - L3 空间结构类维度：道路连通、水体邻接、聚类分布（现状结构）
    - L2 定位类维度：三区三线覆盖、村庄分类校核
    KG 不可用或查询失败时返回 ""（非致命）。
    """
    if kg is None or dim_layer < 2:
        return ""
    try:
        from app.modules.kg.queries.sparql import query_kg

        lines: List[str] = []
        # 道路连通（沿路线性描述素材）
        if dim_layer == 3:
            try:
                roads = query_kg(kg, "get_road_network")
                if roads:
                    names = [str(r.get("name") or "") for r in roads if r.get("name")]
                    lines.append(f"**现状道路**: {'、'.join(names[:8])}（{len(roads)}条）")
            except Exception:
                pass
            try:
                waters = query_kg(kg, "get_water_bodies")
                if waters:
                    wnames = [str(w.get("name") or "") for w in waters if w.get("name")]
                    lines.append(f"**现状水系**: {'、'.join(wnames[:6])}（{len(waters)}处）")
            except Exception:
                pass
            try:
                clusters = query_kg(kg, "get_village_anchors")
                if clusters:
                    cluster_names = [str(c.get("name") or "") for c in clusters
                                     if str(c.get("kind") or "") == "cluster" and c.get("name")]
                    lines.append(f"**居民点聚类**: {'、'.join(cluster_names[:10])}（{len(cluster_names)}个）")
            except Exception:
                pass
        if lines:
            return "## KG 现状结构（EXPLORE 拓扑认知）\n" + "\n".join(lines) + "\n"
    except Exception as e:
        logger.debug("[ExploreSummaries] topology section failed: %s", e)
    return ""


async def build_spatial_cognition(
    session_id: str,
    dim_key: str,
    dim_layer: int,
) -> Dict[str, Any]:
    """Build a single-dimension spatial cognition summary.

    Combines KG three-layer cognition (DualPayload semantic) with bundle
    spatial group statistics and dimension-report spatial findings.
    """
    bundle = await resolve_bundle(session_id)
    payload: Dict[str, Any] = {
        "dimension_key": dim_key,
        "layer": dim_layer,
        "village_name": bundle.village_name,
        "spatial_groups": group_stats(bundle),
        "spatial_findings": [],
        "entity_mentions": [],
        "_kg": None,
    }

    kg = session_kg(session_id)
    payload["_kg"] = kg
    if kg is not None:
        try:
            from app.modules.kg.queries.cognition import get_village_cognition

            result = get_village_cognition(kg, bundle.village_name, mode="full")
            payload["kg_cognition"] = {
                "semantic": result.semantic,
                "structured": result.structured,
            }
        except Exception as e:
            logger.warning("[ExploreSummaries] KG cognition failed: %s", e)

    reports = bundle.layer_reports or {}
    dims = reports.get(dim_layer, {})
    rec = dims.get(dim_key) or {}
    content = str(rec.get("content") or "")
    if content:
        payload["spatial_findings"] = _key_spatial_findings(content, limit=6)
        payload["entity_mentions"] = _mentioned_entities(content, limit=8)

    payload["prompt_section"] = _format_prompt_section(payload)
    return payload


__all__ = [
    "build_report_summary_index",
    "build_spatial_cognition",
]
