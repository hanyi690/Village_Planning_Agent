"""PARSE Agent - unified planning text parser (rule-based).

Consolidates the previous ReAct StateGraph and parse_v2 into a single
deterministic implementation. LLM enhancement can be added later behind
GIS_PARSE_LLM_ENABLED without changing the public API.

Public API:
  parse(planning_text, village_name, ...) -> ParseResult
  parse_async(...) -> ParseResult
  ParseResult: dataclass with .intent (SpatialPlanningIntent)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.modules.schema.contracts.parse_contracts import (
    SpatialPlanningIntent,
    ZoneTarget,
    FacilityTarget,
    AxisTarget,
    RoadTarget,
)
from app.modules.schema.contracts.semantic_fields import SemanticMetadata
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Public result type ───────────────────────────────────────────────


@dataclass
class ParseResult:
    """PARSE output container."""

    intent: SpatialPlanningIntent
    operation_sequence: List[Any] = None
    constraint_set: List[Any] = None
    validation_errors: List[str] = None

    def __post_init__(self):
        if self.operation_sequence is None:
            self.operation_sequence = []
        if self.constraint_set is None:
            self.constraint_set = []
        if self.validation_errors is None:
            self.validation_errors = []


# ── Extraction patterns ──────────────────────────────────────────────

_ZONE_TARGET_RE = re.compile(
    r"(?:分区|用地|目标|规划)\s*[:：]\s*([^\n]{2,30})?\s*"
    r"(?:面积|比例|占比)?\s*[:：]?\s*(\d+(?:\.\d+)?)\s*%?|"
    r"(\d+(?:\.\d+)?)\s*%\s*(?:用于|分配给|作为)\s*([^\n，,]+)",
    re.MULTILINE,
)

_FACILITY_RE = re.compile(
    r"(?:设施|服务中心|卫生室|学校|广场|停车场|公园)\s*"
    r"([^\n，,]{0,20})(?:位置|位于|建于)?\s*[:：]?\s*([^\n]{0,30})?",
    re.MULTILINE,
)

_AXIS_RE = re.compile(
    r"(?:发展轴|景观轴|生态廊道|道路轴线)\s*"
    r"([^\n]{0,30})?(?:沿|从|至|连接)?\s*([^\n]{0,30})?",
    re.MULTILINE,
)

_ROAD_RE = re.compile(
    r"(?:道路|公路|村道|乡道)\s*"
    r"([^\n]{0,20})?\s*(?:宽度|宽)?\s*[:：]?\s*(\d+(?:\.\d+)?)\s*m?",
    re.MULTILINE,
)


# ── Extractors ───────────────────────────────────────────────────────


def _extract_zone_targets(text: str) -> List[ZoneTarget]:
    targets = []
    for match in _ZONE_TARGET_RE.finditer(text):
        land_use = match.group(1) or match.group(4) or "村庄建设区"
        area_ratio = float(match.group(2) or match.group(3) or 0) / 100.0
        if area_ratio > 0:
            targets.append(
                ZoneTarget(
                    zone_id=f"zone_{len(targets)}",
                    land_use=land_use.strip() if land_use else "村庄建设区",
                    area_ratio=area_ratio,
                    semantic=SemanticMetadata(
                        natural_language_description=f"规划{land_use}占比{area_ratio*100:.0f}%",
                        spatial_hint="",
                    ),
                )
            )
    return targets


def _extract_facilities(text: str) -> List[FacilityTarget]:
    facilities = []
    for match in _FACILITY_RE.finditer(text):
        ftype = match.group(1) or "公共服务设施"
        location = match.group(2) or ""
        facilities.append(
            FacilityTarget(
                type=ftype.strip(),
                status="planned_new",
                location_hint=location.strip() if location else "",
                semantic=SemanticMetadata(
                    natural_language_description=f"规划{ftype}",
                    spatial_hint=location.strip() if location else "",
                ),
            )
        )
    return facilities


def _extract_axes(text: str) -> List[AxisTarget]:
    axes = []
    for match in _AXIS_RE.finditer(text):
        ref = match.group(1) or ""
        direction = match.group(2) or ""
        if ref or direction:
            axes.append(
                AxisTarget(
                    reference_feature=ref.strip() if ref else "发展轴",
                    direction=direction.strip() if direction else "",
                    semantic=SemanticMetadata(
                        natural_language_description=f"沿{ref}方向发展" if ref else "发展轴线",
                        spatial_hint=direction.strip() if direction else "",
                    ),
                )
            )
    return axes


def _extract_roads(text: str) -> List[RoadTarget]:
    roads = []
    for match in _ROAD_RE.finditer(text):
        name = match.group(1) or "规划道路"
        width = float(match.group(2) or 6)
        roads.append(
            RoadTarget(
                road_level=name.strip() if name else "村道",
                width_m=width,
                semantic=SemanticMetadata(
                    natural_language_description=f"规划{name}宽度{width}m",
                    spatial_hint="",
                ),
            )
        )
    return roads


# ── Markdown table extractors moved to .tables (unit-level detection) ──

# ── Public API ───────────────────────────────────────────────────────


def parse(
    planning_text: str,
    village_name: str = "",
    planning_period: str = "2022-2035年",
) -> ParseResult:
    """Parse planning text into SpatialPlanningIntent.

    Args:
        planning_text: Raw planning text from LLM report.
        village_name: Village name for context.
        planning_period: Planning period string.

    Returns:
        ParseResult with extracted intent.
    """
    zone_targets = _extract_zone_targets(planning_text)
    facilities = _extract_facilities(planning_text)
    axes = _extract_axes(planning_text)
    roads = _extract_roads(planning_text)

    # P3: 结构化表格（单位级检测，见 app.modules.parsing.tables）
    from app.modules.parsing.tables import _extract_project_tables as _ept, _extract_zone_tables as _ezt

    zone_targets += _ezt(planning_text)
    facilities += _ept(planning_text)

    intent = SpatialPlanningIntent(
        village_name=village_name,
        planning_period=planning_period,
        zone_targets=zone_targets,
        facilities=facilities,
        development_axes=axes,
        road_targets=roads,
        raw_text=planning_text[:2000],
    )

    logger.info(
        "[PARSE] Extracted: %d zones, %d facilities, %d axes, %d roads",
        len(zone_targets), len(facilities), len(axes), len(roads),
    )

    return ParseResult(intent=intent)


async def parse_async(
    planning_text: str,
    village_name: str = "",
    planning_period: str = "2022-2035年",
) -> ParseResult:
    """Async wrapper for parse."""
    import asyncio

    return await asyncio.to_thread(
        parse, planning_text, village_name, planning_period
    )


# ── EXPLORE KG-enrichment: extract_bindings ──────────────────────────────


@dataclass
class PendingBinding:
    """Candidate village/BSM binding extracted from a wave of reports."""

    natural_village: Optional[str]
    feature_type: str
    candidate_bsms: List[str]
    description: str
    confidence: float
    source_report_keys: List[str]


def _get_semantic_memory():
    from app.modules.kg import get_semantic_memory

    return get_semantic_memory()


def _lookup_entity_by_bsm(kg: Any, bsm: str) -> Any:
    """Duck-typed BSM entity lookup: kg instance method or module-level fallback."""
    method = getattr(kg, "get_entity_by_bsm", None)
    if callable(method):
        return method(bsm)
    from app.modules.kg import get_entity_by_bsm

    return get_entity_by_bsm(kg, bsm)


_VLL_RE = re.compile(r"([\u4e00-\u9fff]{2,8}村)")
_BSM_NUM_RE = re.compile(r"(\d{15,25})")


def _extract_bindings_deterministic(reports: Dict[str, str]) -> List[PendingBinding]:
    """Rule-based fallback: village mention followed by a BSM within 120 chars."""
    bindings: List[PendingBinding] = []
    for dim_key, content in (reports or {}).items():
        for m in _VLL_RE.finditer(content or ""):
            name = m.group(1)
            window = (content or "")[m.end(): m.end() + 120]
            bsms = _BSM_NUM_RE.findall(window)
            if not bsms or any(b.natural_village == name for b in bindings):
                continue
            bindings.append(
                PendingBinding(
                    natural_village=name,
                    feature_type="parcel",
                    candidate_bsms=list(dict.fromkeys(bsms))[:8],
                    description=window[:60],
                    confidence=0.7,
                    source_report_keys=[dim_key],
                )
            )
    return bindings


_BINDING_PROMPT = """你是村庄规划报告语义抽取助手。从下列报告中识别自然村/地名与地块BSM的绑定关系。

候选地块（BSM + 用地描述，前200条）：
{parcels}

报告原文：
{reports}

只输出 JSON（不要任何其他文字），格式：
{{"bindings": [{{"natural_village": "田坑自然村", "candidate_bsms": ["441426211000049104"], "feature_type": "parcel", "description": "田坑自然村现有耕地12.5公顷", "confidence": 0.85}}]}}
若没有可绑定的实体，输出 {{"bindings": []}}。
"""


async def _extract_bindings_llm(
    llm: Any,
    reports: Dict[str, str],
    candidate_bsms: List[str],
) -> List[PendingBinding]:
    """Flash LLM extraction with a constrained JSON schema."""
    import json

    parcels = "\n".join(candidate_bsms[:200]) or "（无候选地块）"
    reports_text = "\n\n".join(f"[{k}]\n{v}" for k, v in (reports or {}).items())
    prompt = _BINDING_PROMPT.format(parcels=parcels, reports=reports_text[:8000])

    resp = await llm.ainvoke(prompt)
    content = getattr(resp, "content", "") or ""
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        logger.warning("[PARSE-bindings] LLM output not JSON: %s", content[:200])
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        logger.warning("[PARSE-bindings] JSON parse failed: %s", e)
        return []
    bindings: List[PendingBinding] = []
    for item in data.get("bindings") or []:
        bindings.append(
            PendingBinding(
                natural_village=item.get("natural_village") or None,
                feature_type=str(item.get("feature_type", "parcel")),
                candidate_bsms=[str(b) for b in (item.get("candidate_bsms") or [])],
                description=str(item.get("description", "")),
                confidence=float(item.get("confidence", 0.0)),
                source_report_keys=list(reports.keys()),
            )
        )
    return bindings


def _find_annotation_point(bundle: Any, name: str) -> Optional[tuple]:
    """Find the Point annotation whose 注记/text matches a village name."""
    if bundle is None:
        return None
    for group in ("annotations_current", "annotations_planned"):
        for f in (bundle.points.get(group) or []):
            if isinstance(f, dict):
                props = f.get("properties") or {}
                text = str(props.get("注记", "") or props.get("text", "") or "")
                geom = f.get("geometry") or {}
            else:
                text = str(getattr(f, "text", "") or "")
                geom = getattr(f, "geometry", {}) or {}
            if text and (text == name or text in name or name in text):
                if geom.get("type") == "Point":
                    c = geom.get("coordinates") or []
                    if len(c) == 2:
                        return (float(c[0]), float(c[1]))
    return None


def _find_parcel_by_bsm(bundle: Any, bsm: str) -> Any:
    parcels = (bundle.polygons.get("landuse_current") or []) if bundle is not None else []
    for f in parcels:
        if str(getattr(f, "bsm", "") or "") == bsm:
            return f
    if parcels:
        return parcels[-1]
    return None


def _point_in_annotation_parcel(point: tuple, bsm: str, bundle: Any) -> bool:
    """注记点在候选地块多边形内。"""
    from app.modules.spatial_ops.geometry import point_in_polygon

    parcel = _find_parcel_by_bsm(bundle, bsm)
    if parcel is None:
        return False
    return point_in_polygon(point, getattr(parcel, "geometry", {}) or {})


def _parcel_inside_boundary(bsm: str, boundary: Dict[str, Any], bundle: Any) -> bool:
    """地块中心点位于村界多边形内。"""
    from app.modules.spatial_ops.geometry import _compute_centroid, point_in_polygon

    parcel = _find_parcel_by_bsm(bundle, bsm)
    if parcel is None:
        return False
    centroid = _compute_centroid(
        {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {}, "geometry": getattr(parcel, "geometry", {})}
            ],
        }
    )
    if centroid is None:
        return False
    return point_in_polygon(centroid, boundary)


def _validate_binding(binding: PendingBinding, kg: Any, bundle: Any) -> tuple:
    """kgg write-gate: KG exists + 村界包含 + confidence >= 0.6.

    村内/村外规则（实测验证）：
      - annotation.geojson 中 分类='村名' 的 4 个注记点（八社村/上举村/符坑村/文贵村）
        全部位于金田村村界外 → 是毗邻行政村（村外），禁止绑定；
      - 村内 12 个自然村（田坑/黄竹/园寨/社前/分水/清明/塘笃/长塘/炉池/肩丰/营仔/新山）
        无注记点 → 以"地块中心点在村界内"作为空间基座。
    """
    from app.modules.spatial_ops.geometry import point_in_polygon, village_boundary_geometry

    if binding.confidence < 0.6:
        return (False, f"confidence {binding.confidence} < 0.6")
    if not binding.candidate_bsms:
        return (False, "no candidate bsms")
    for bsm in binding.candidate_bsms:
        if _lookup_entity_by_bsm(kg, bsm) is None:
            return (False, f"bsm {bsm} not in KG")

    boundary = village_boundary_geometry(bundle)
    point = _find_annotation_point(bundle, binding.natural_village) if binding.natural_village else None

    if point is not None:
        # 有注记点：必须先通过村界包含（村外行政村 → 拒绝）
        if boundary is not None and not point_in_polygon(point, boundary):
            return (False, f"{binding.natural_village} 为村外毗邻行政村，非本村居民点")
        # 再验注记点在候选地块内
        if not _point_in_annotation_parcel(point, binding.candidate_bsms[0], bundle):
            return (False, f"{binding.natural_village} point outside parcel {binding.candidate_bsms[0]}")
    elif binding.natural_village and boundary is not None:
        # 无注记点（村内自然村）：地块中心点必须在村界内
        if not _parcel_inside_boundary(binding.candidate_bsms[0], boundary, bundle):
            return (False, f"parcel {binding.candidate_bsms[0]} 不在村界内，疑似村外")
    return (True, "")


def _extract_entity_semantics(reports: Dict[str, str]) -> List[Dict[str, str]]:
    """P4: 功能分区/项目实体语义提取（纯语义注解，无空间绑定）。

    Reuses the P3 table extractors to pull FunctionalZone / Project names
    from report tables, so L1/L2/L3 report semantics flow back into the KG
    semantic memory (the L1 loop: explore -> parse -> KG entity enrichment).
    """
    entities: List[Dict[str, str]] = []
    seen = set()
    for dim_key, content in (reports or {}).items():
        from app.modules.parsing.tables import _extract_project_tables as _ept2, _extract_zone_tables as _ezt2

        for zt in _ezt2(content):
            key = ("FunctionalZone", zt.land_use)
            if key in seen:
                continue
            seen.add(key)
            entities.append(
                {
                    "entity_name": zt.land_use,
                    "entity_type": "FunctionalZone",
                    "description": f"功能分区{zt.land_use}（源自{dim_key}报告分区表）",
                }
            )
        for ft in _ept2(content):
            key = ("Project", ft.type)
            if key in seen:
                continue
            seen.add(key)
            entities.append(
                {
                    "entity_name": ft.type,
                    "entity_type": "Project",
                    "description": f"规划项目{ft.type}（源自{dim_key}报告项目库）",
                }
            )
    return entities


def _queue_review(session_id: str, wave: int, skipped: List[Dict[str, Any]]) -> None:
    from app.modules.kg.memory import get_memory_dir

    d = get_memory_dir() / "_review"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{session_id}_wave_{wave}.json"
    path.write_text(json.dumps(skipped, ensure_ascii=False, indent=2), encoding="utf-8")


async def extract_bindings(
    session_id: str,
    wave: int,
    reports: Dict[str, str],
    llm: Any = None,
    kg: Any = None,
    bundle: Any = None,
) -> Dict[str, Any]:
    """Deprecated forwarder — KG multi-level enrichment now lives in
    ``app.modules.kg.enrichment`` (PARSE stays intent-only)."""
    from app.modules.kg.enrichment import extract_bindings as _enrich

    return await _enrich(
        session_id=session_id,
        wave=wave,
        reports=reports,
        llm=llm,
        kg=kg,
        bundle=bundle,
    )


__all__ = ["parse", "parse_async", "ParseResult", "PendingBinding", "extract_bindings"]
