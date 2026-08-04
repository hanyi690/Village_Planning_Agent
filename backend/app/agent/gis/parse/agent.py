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
import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.modules.schema.contracts.parse_contracts import (
    AxisTarget,
    FacilityTarget,
    ProjectTarget,
    RoadTarget,
    SpatialPlanningIntent,
    SpatialPreference,
    ZoneTarget,
)
from app.modules.schema.contracts.semantic_fields import SemanticMetadata
from app.modules.parsing.spatial_language import direction_from_location
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


# ── P8: INSTRUCTION 段结构化提取 ────────────────────────────────────

_INSTRUCTION_MARKER = "【INSTRUCTION】"

# 类型闭集：L3 = 项目/功能分区/设施/轴线；L1 = 现状设施/现状项目/现状分区
_INSTRUCTION_TYPE_MAP = {
    "项目": "project",
    "功能分区": "zone",
    "分区": "zone",
    "设施": "facility",
    "道路": "road",
    "轴线": "axis",
    "现状设施": "facility",
    "现状项目": "project",
    "现状分区": "zone",
}

_INSTRUCTION_LOCATION_HEADER_RE = re.compile(r"(位置|选址|所在位置|方位|位于)")
_INSTRUCTION_NAME_HEADER_RE = re.compile(r"(名称|项目|工程)")

_direction_from_location = direction_from_location


def _extract_instruction_section(text: str) -> str:
    """取【INSTRUCTION】标记起的结构化段（含标记行）。无标记返回空。"""
    if not text:
        return ""
    idx = text.find(_INSTRUCTION_MARKER)
    if idx < 0:
        return ""
    return text[idx:]


def _extract_instruction_tables(text: str) -> Dict[str, List[Any]]:
    """从【INSTRUCTION】段解析固定列 markdown 表格 → 空间目标列表。

    行级容错：坏行 / 未知类型 / 空名称 丢弃，不影响其余行。
    返回项目主对象，并按项目类别派生设施/道路/分区执行目标。
    """
    from app.modules.parsing.tables import _iter_tables

    section = _extract_instruction_section(text)
    if not section:
        return {"zones": [], "facilities": [], "axes": []}

    projects: List[ProjectTarget] = []
    zones: List[ZoneTarget] = []
    facilities: List[FacilityTarget] = []
    axes: List[AxisTarget] = []
    roads: List[RoadTarget] = []
    seen = {"projects": set(), "zones": set(), "facilities": set(), "axes": set(), "roads": set()}
    kind_to_seen = {
        "project": "projects",
        "zone": "zones",
        "facility": "facilities",
        "axis": "axes",
        "road": "roads",
    }
    bad_rows = 0
    no_location = 0

    for header, rows in _iter_tables(section):
        type_idx = 0 if any("类型" in h for h in header) else None
        name_idx = next(
            (i for i, h in enumerate(header) if _INSTRUCTION_NAME_HEADER_RE.search(h)),
            None,
        )
        loc_idx = next(
            (i for i, h in enumerate(header) if _INSTRUCTION_LOCATION_HEADER_RE.search(h)),
            None,
        )
        desc_idx = next(
            (i for i, h in enumerate(header) if "描述" in h or "内容" in h),
            None,
        )
        scale_idx = next(
            (i for i, h in enumerate(header) if "规模" in h),
            None,
        )
        if type_idx is None or name_idx is None:
            continue

        for row in rows:
            if type_idx >= len(row) or name_idx >= len(row):
                bad_rows += 1
                continue
            kind = _INSTRUCTION_TYPE_MAP.get(str(row[type_idx]).strip())
            name = row[name_idx].strip()
            seen_key = kind_to_seen.get(kind) if kind else None
            if seen_key is None or not name or len(name) < 2 or name in seen[seen_key]:
                bad_rows += 1
                continue
            location = (row[loc_idx].strip() if loc_idx is not None and loc_idx < len(row) else "") or ""
            if not location:
                no_location += 1
            description = (row[desc_idx].strip() if desc_idx is not None and desc_idx < len(row) else "") or ""
            scale = (row[scale_idx].strip() if scale_idx is not None and scale_idx < len(row) else "") or ""

            semantic = SemanticMetadata(
                natural_language_description=f"{name}：{description}" if description else name,
                spatial_hint=location or "",
                raw_text=" | ".join(str(cell) for cell in row),
            )
            instruction_seed = f"{name}|{location}|{description}|{scale}"
            instruction_id = "INS-" + hashlib.sha1(
                instruction_seed.encode("utf-8")
            ).hexdigest()[:12]
            if kind == "project":
                seen["projects"].add(name)
                project_id = "PRJ-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]
                category = _classify_project_category(name, description)
                project = ProjectTarget(
                    project_id=project_id,
                    name=name,
                    category=category,
                    scale_text=scale,
                    location_hint=location,
                    source_instruction_id=instruction_id,
                    source_row=len(projects) + 1,
                    semantic=semantic,
                )
                projects.append(project)
                if category == "road":
                    roads.append(RoadTarget(
                        road_level=name,
                        connects=[location] if location else [],
                        source_project_id=project_id,
                        source_instruction_id=instruction_id,
                        semantic=semantic,
                    ))
                elif category in {"facility", "infrastructure"}:
                    facilities.append(FacilityTarget(
                        type=name,
                        status="planned_new",
                        location_hint=location,
                        anchor_village=location,
                        source_project_id=project_id,
                        source_instruction_id=instruction_id,
                        semantic=semantic,
                    ))
            elif kind == "zone":
                seen["zones"].add(name)
                zones.append(ZoneTarget(
                    land_use=name,
                    source_instruction_id=instruction_id,
                    semantic=semantic,
                    spatial_preference=SpatialPreference(
                        direction=_direction_from_location(location),
                        reference=location or None,
                    ) if location else None,
                ))
            elif kind == "facility":
                seen["facilities"].add(name)
                facilities.append(FacilityTarget(
                    type=name,
                    status="planned_new",
                    location_hint=location,
                    anchor_village=location,
                    source_instruction_id=instruction_id,
                    semantic=semantic,
                ))
            elif kind == "axis":
                seen["axes"].add(name)
                axes.append(AxisTarget(
                    label=name,
                    reference_feature=location or "",
                    source_instruction_id=instruction_id,
                    semantic=semantic,
                ))
            elif kind == "road":
                seen["roads"].add(name)
                roads.append(RoadTarget(
                    road_level=name,
                    connects=[location] if location else [],
                    source_instruction_id=instruction_id,
                    semantic=semantic,
                ))

    total = len(projects) + len(zones) + len(facilities) + len(axes) + len(roads)
    logger.info(
        "[PARSE] INSTRUCTION: %d zones, %d facilities, %d axes "
        "(bad_rows=%d no_location=%d)",
        len(zones), len(facilities), len(axes),
        bad_rows, no_location,
    )
    return {
        "projects": projects,
        "zones": zones,
        "facilities": facilities,
        "axes": axes,
        "roads": roads,
    }


def _classify_project_category(name: str, description: str = "") -> str:
    text = f"{name} {description}"
    if any(word in text for word in ("道路", "村道", "公路", "桥", "路网")):
        return "road"
    if any(word in text for word in ("服务中心", "卫生", "学校", "广场", "停车", "公园", "设施")):
        return "facility"
    if any(word in text for word in ("污水", "供水", "排水", "电力", "通信", "环卫")):
        return "infrastructure"
    if any(word in text for word in ("整治", "修复", "复垦")):
        return "land_consolidation"
    if any(word in text for word in ("产业", "基地", "园区", "旅游", "民宿")):
        return "industry"
    return "other"


# ── Extraction patterns ──────────────────────────────────────────────

_ZONE_TARGET_RE = re.compile(
    r"(?:分区|用地|目标|规划)\s*[:：]\s*([^\n，,：]{2,30}?)\s*"
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
    regex_zone_targets = _extract_zone_targets(planning_text)
    regex_facilities = _extract_facilities(planning_text)
    axes = _extract_axes(planning_text)
    roads = _extract_roads(planning_text)

    # P3: 结构化表格（单位级检测，见 app.modules.parsing.tables）
    from app.modules.parsing.tables import (
        _extract_project_tables as _ept,
        _extract_road_tables as _ert,
        _extract_zone_tables as _ezt,
    )

    table_zone_targets = _ezt(planning_text)
    zone_targets = list(table_zone_targets)
    zone_names = {target.land_use for target in zone_targets}
    for target in regex_zone_targets:
        name = (target.land_use or "").strip()
        if name.endswith("区") and name not in zone_names:
            zone_targets.append(target)
            zone_names.add(name)
    table_facilities = _ept(planning_text)
    facilities = table_facilities or regex_facilities
    table_roads = _ert(planning_text)
    roads = table_roads or roads

    # P8: INSTRUCTION 段（文末固定列表格，L1/L3 报告生成端产出）→ 结构化空间目标
    # 与上述提取合并：按名称去重，INSTRUCTION 优先（位置信息更完整）
    instruction = _extract_instruction_tables(planning_text)
    if not any(instruction.values()):
        instruction = _extract_instruction_tables(
            f"{_INSTRUCTION_MARKER}\n{planning_text}"
        )
    zone_names = {zt.land_use for zt in zone_targets if zt.land_use}
    facility_names = {ft.type for ft in facilities if ft.type}
    axis_names = {ax.label or ax.reference_feature for ax in axes}
    for izt in instruction["zones"]:
        if izt.land_use and izt.land_use not in zone_names:
            zone_targets.append(izt)
            zone_names.add(izt.land_use)
    for ift in instruction["facilities"]:
        if ift.type and ift.type not in facility_names:
            facilities.append(ift)
            facility_names.add(ift.type)
    if instruction["axes"]:
        axes = []
        axis_names = set()
    for iax in instruction["axes"]:
        key = iax.label or iax.reference_feature
        if key and key not in axis_names:
            axes.append(iax)
            axis_names.add(key)
    road_names = {road.road_level for road in roads if road.road_level}
    for road in instruction["roads"]:
        if road.road_level and road.road_level not in road_names:
            roads.append(road)
            road_names.add(road.road_level)

    # 过滤表格残片：既有正则会把正文 markdown 表格行误提取为设施
    # （类型/位置含 "|" 的行无实体意义，丢弃避免稀释下游定位）
    facilities = [
        ft for ft in facilities
        if "|" not in ft.type and "|" not in ft.location_hint
    ]
    axes = [
        axis for axis in axes
        if "|" not in axis.reference_feature and "|" not in axis.direction
    ]
    roads = [
        road for road in roads
        if "|" not in road.road_level
    ]

    intent = SpatialPlanningIntent(
        village_name=village_name,
        planning_period=planning_period,
        zone_targets=zone_targets,
        facilities=facilities,
        development_axes=axes,
        road_targets=roads,
        project_targets=instruction["projects"],
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


# ── P8: 自然村/位置名 → BSM（gazetteer 解析，intent 原地填充）────────
# Token 提取与 gazetteer 解析已上移至 app.modules.spatial_ops.resolver
# （单一空间解析入口）。此处仅保留对旧名称的兼容再导出。


def _extract_location_tokens(location: str) -> List[str]:
    """位置文本 → 候选 token（委托 spatial_ops.resolver）。"""
    from app.modules.spatial_ops.resolver import _extract_location_tokens as _impl

    return _impl(location)


def _resolve_gazetteer_bsms(token: str, gazetteer: Any) -> List[str]:
    """token → gazetteer 解析 → BSM 列表（委托 spatial_ops.resolver）。"""
    from app.modules.spatial_ops.resolver import _resolve_gazetteer_bsms as _impl

    return _impl(token, gazetteer)


def resolve_spatial_anchors(
    intent: Any,
    village_name: str = "",
    village_anchors: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """将 intent 中位置文本（INSTRUCTION/表格提取）解析为具体 BSM 集。

    委托 ``app.modules.spatial_ops.resolver.resolve_intent_anchors``
    （唯一空间解析入口）。仅读取 gazetteer（不落盘）；无匹配保留原文
    spatial_hint 供语义使用。返回成功解析的实体数。
    """
    from app.modules.spatial_ops.resolver import resolve_intent_anchors as _resolve

    return _resolve(
        intent,
        village_name=village_name,
        village_anchors=village_anchors,
    )


__all__ = ["parse", "parse_async", "ParseResult", "PendingBinding", "extract_bindings"]
