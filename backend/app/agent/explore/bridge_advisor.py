"""BridgeAdvisor — 组合 EXPLORE 空间认知 brief（纯自然语言，供 L1 注入）。

Deterministic by default (no LLM): composes KG three-layer cognition, bundle
annotation points (村内自然村 vs 村外毗邻行政村) and semantic-memory
annotations into a ``SpatialCognitionBrief``.  An optional Flash ``llm`` is
accepted for future refinement but is never required for the baseline path.

村内/村外铁律：annotation.geojson 中 分类='村名' 的注记点若位于村界外（如
八社村/上举村/符坑村/文贵村）是毗邻行政村，归入 external_villages，绝不进
relevant_entities；村内 12 个自然村（田坑/黄竹/园寨等）无注记点，由 KG 语义
记忆与地块清单承载。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.utils.logger import get_logger

logger = get_logger(__name__)

_DIM_HINTS: Dict[str, List[str]] = {
    "land_use": ["关注田坑/黄竹等自然村的耕地集中区与建设用地形态"],
    "natural_environment": ["关注公王河水系与林地斑块的空间分布"],
    "ecological_green": ["关注生态保护红线与地块重叠的约束"],
    "traffic": ["关注通村道路走向、宽度与自然村连通性"],
    "public_services": ["关注设施点与自然村的服务半径覆盖"],
    "socio_economic": ["结合自然村人口分布核对经济数据"],
}


@dataclass
class SpatialCognitionBrief:
    """纯自然语言空间认知，注入 L1 prompt 的 reference 位置。"""
    village_overview: str
    spatial_pattern: str
    spatial_constraints: str
    relevant_entities: str
    focus_hints: List[str] = field(default_factory=list)
    kg_confidence: float = 0.0
    external_villages: List[str] = field(default_factory=list)


class BridgeAdvisor:
    """Deterministic composition of KG cognition + bundle stats + memory."""

    def __init__(self, session_id: str, llm: Any = None):
        self.session_id = session_id
        self.llm = llm  # reserved for Flash refinement; baseline is deterministic

    async def compose_dim_brief(self, dim_key: str, dim_layer: int) -> SpatialCognitionBrief:
        from app.tools.access.shared import resolve_bundle, session_kg

        bundle = await resolve_bundle(self.session_id)
        kg = session_kg(self.session_id)

        overview = ""
        pattern = ""
        constraints = ""
        kg_confidence = 0.0
        if kg is not None:
            try:
                from app.modules.kg.queries.cognition import get_village_cognition

                result = get_village_cognition(kg, bundle.village_name or "", mode="full")
                ctx = result.semantic.get("context_block") or {}
                overview = str(ctx.get("overview", ""))
                pattern = str(ctx.get("spatial_pattern", ""))
                cb = result.semantic.get("constraint_block") or {}
                constraints = str(cb.get("constraint_coverage", ""))
                kg_confidence = 0.8 if ctx.get("parcel_count") else 0.3
            except Exception as e:
                logger.warning("[BridgeAdvisor] KG cognition failed: %s", e)

        entities, external = self._build_entity_lines(bundle, kg)
        hints = list(_DIM_HINTS.get(dim_key, []))
        if not hints:
            hints.append("结合现状图核对空间布局描述")

        try:
            from app.modules.kg import get_semantic_memory

            bound = len(get_semantic_memory().entity_annotations)
            if bound:
                kg_confidence = min(1.0, kg_confidence + 0.1)
        except Exception:
            pass

        return SpatialCognitionBrief(
            village_overview=overview,
            spatial_pattern=pattern,
            spatial_constraints=constraints,
            relevant_entities="；".join(entities) if entities else "KG 尚未绑定村内自然村地名",
            focus_hints=hints,
            kg_confidence=kg_confidence,
            external_villages=external,
        )

    def _build_entity_lines(self, bundle: Any, kg: Any) -> List[str]:
        names: List[str] = []
        external: List[str] = []
        if bundle is not None:
            from app.modules.spatial_ops.geometry import (
                point_in_polygon,
                village_boundary_geometry,
            )

            boundary = village_boundary_geometry(bundle)
            for group in ("annotations_current", "annotations_planned"):
                for f in bundle.points.get(group) or []:
                    text = str(getattr(f, "text", "") or "")
                    category = str(getattr(f, "category", "") or "")
                    if category != "村名" or not text:
                        continue
                    geom = getattr(f, "geometry", {}) or {}
                    c = geom.get("coordinates") or []
                    if len(c) == 2:
                        point = (float(c[0]), float(c[1]))
                        inside = point_in_polygon(point, boundary) if boundary else True
                        (names if inside else external).append(text)
        names = list(dict.fromkeys(names))
        external = list(dict.fromkeys(external))
        try:
            from app.modules.kg import get_semantic_memory

            mem = get_semantic_memory()
            for uri, ann in mem.entity_annotations.items():
                label = (ann.description or uri)[:20]
                if label not in names:
                    names.append(label)
        except Exception:
            pass
        if kg is not None:
            try:
                from app.modules.kg import get_parcels_semantic_list

                for p in get_parcels_semantic_list(kg)[:5]:
                    desc = p.get("description", "")
                    if desc and desc not in names:
                        names.append(desc)
            except Exception as e:
                logger.debug("[BridgeAdvisor] parcel list failed: %s", e)
        return names, external


def format_brief_section(brief: SpatialCognitionBrief) -> str:
    """Render the brief as a markdown block for prompt injection."""
    lines = [
        "**【EXPLORE 空间基础（供分析参考）】**",
        f"- 村域概况：{brief.village_overview or '数据中未提供'}",
        f"- 空间格局：{brief.spatial_pattern or '数据中未提供'}",
        f"- 空间约束：{brief.spatial_constraints or '数据中未提供'}",
        f"- 关键实体（村内）：{brief.relevant_entities}",
        f"- 参考提示：{'；'.join(brief.focus_hints[:3])}",
        f"- KG 置信度：{brief.kg_confidence:.2f}",
    ]
    if brief.external_villages:
        lines.append(f"- 毗邻行政村（村外，非本村居民点）：{'、'.join(brief.external_villages[:6])}")
    return "\n".join(lines)


__all__ = ["SpatialCognitionBrief", "BridgeAdvisor", "format_brief_section"]
