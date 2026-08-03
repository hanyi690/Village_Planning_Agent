"""Strict, tool-free conversion of Explore/Binder artifacts to planning intent.

v4 extensions (P6):
  - ``project`` domain → ``CustomZoneTarget`` (vocabulary_name / category_code
    matched against the session vocabulary, target_bsms from the binder)
  - zone/landuse targets get ``area_ratio`` extracted from evidence text
    (e.g. "生态保护区 15.39%" / "南药产业园 0.15公顷").
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Mapping, Optional

from app.modules.schema.contracts.custom_zone_contracts import CustomZoneTarget
from app.modules.schema.contracts.parse_contracts import (
    AxisTarget,
    FacilityTarget,
    ProjectTarget,
    RoadTarget,
    SpatialPlanningIntent,
    ZoneTarget,
)
from app.modules.schema.contracts.semantic_fields import SemanticMetadata


def _feature_props(features: Mapping[str, Any]) -> Iterable[Dict[str, Any]]:
    for feature in features.get("features", []):
        if isinstance(feature, Mapping):
            yield dict(feature.get("properties") or {})


_AREA_RATIO_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_AREA_HA_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:公顷|ha|hm)")


def _extract_area_ratio(evidence: str) -> Optional[float]:
    """From evidence text: '15.39%' → 0.1539; else '0.15公顷' → None (needs total)."""
    m = _AREA_RATIO_RE.search(evidence)
    if m:
        return float(m.group(1)) / 100.0
    return None


def format_bound_spatial_intent(
    *,
    village_name: str,
    bound_entities: Mapping[str, Any],
    fallback_intent: SpatialPlanningIntent | None = None,
    vocabulary_name: str = "",
) -> SpatialPlanningIntent:
    """Make a Pydantic intent without GIS queries or coordinate inference.

    Existing parse output is preserved and only missing target collections are
    populated.  A bbox/multiple candidate remains a semantic hint; it never
    becomes a RoadTarget endpoint.
    """
    intent = fallback_intent.model_copy(deep=True) if fallback_intent is not None else SpatialPlanningIntent()
    intent.village_name = village_name or intent.village_name
    existing_roads = list(intent.road_targets)
    for props in _feature_props(bound_entities):
        domain = props.get("domain")
        evidence = str(props.get("evidence_text") or "")
        bsms = [str(v) for v in props.get("source_bsm_list") or []]
        confirmed = props.get("binding_status") == "confirmed"
        instruction_ids = [
            str(value) for value in props.get("source_instruction_ids") or []
        ]
        instruction_id = instruction_ids[0] if instruction_ids else str(
            props.get("entity_id") or ""
        )
        chunk_ids = [str(value) for value in props.get("source_chunk_ids") or []]
        source_report_key = (
            chunk_ids[0].split(":", 1)[0] if chunk_ids else ""
        )
        semantic = SemanticMetadata(
            raw_text=evidence,
            natural_language_description=evidence,
            spatial_hint=", ".join(bsms) if bsms else "candidate/unresolved spatial reference",
            reasoning_trace=f"binder={props.get('binding_status')}; source_instruction_ids={props.get('source_instruction_ids')}",
        )
        if domain == "road":
            # Explicitly no coordinates: only confirmed BSM becomes path input.
            existing_roads.append(RoadTarget(
                road_level="village_road",
                path_bsms=bsms if confirmed else [],
                candidate_bsms=[] if confirmed else bsms,
                candidate_bbox=props.get("candidate_bbox"),
                requires_human_confirmation=bool(props.get("requires_human_confirmation")),
                source_instruction_id=instruction_id,
                source_report_key=source_report_key,
                semantic=semantic,
            ))
        elif domain == "facility":
            intent.facilities.append(FacilityTarget(
                type=str(props.get("name") or "planned_facility"),
                status="planned_new",
                candidate_bsms=bsms,
                source_instruction_id=instruction_id,
                source_report_key=source_report_key,
                semantic=semantic,
            ))
        elif domain == "axis":
            intent.development_axes.append(AxisTarget(
                label=str(props.get("name") or ""),
                corridor_bsms=bsms,
                source_instruction_id=instruction_id,
                source_report_key=source_report_key,
                requires_human_confirmation=bool(
                    props.get("requires_human_confirmation")
                ),
                semantic=semantic,
            ))
        elif domain in {"landuse", "zone"}:
            target = ZoneTarget(
                land_use=str(props.get("planning_zone") or props.get("name") or ""),
                candidate_bsms=bsms,
                source_instruction_id=instruction_id,
                source_report_key=source_report_key,
                semantic=semantic,
            )
            ratio = _extract_area_ratio(evidence)
            if ratio:
                target.area_ratio = ratio
            intent.zone_targets.append(target)
        elif domain == "project":
            name = str(props.get("name") or props.get("entity_id") or "").strip()
            project_id = str(props.get("entity_id") or instruction_id or name)
            intent.project_targets.append(ProjectTarget(
                project_id=project_id,
                name=name,
                category=_project_category(name, evidence),
                location_hint=evidence,
                candidate_bsms=bsms,
                source_instruction_id=instruction_id,
                source_report_key=source_report_key,
                semantic=semantic,
            ))
            # Project-driven custom zoning remains an optional derived target.
            category_code = _match_category_code(name, vocabulary_name)
            if category_code:
                intent.custom_zone_targets.append(CustomZoneTarget(
                    vocabulary_name=vocabulary_name,
                    category_code=category_code,
                    target_bsms=bsms if confirmed else [],
                    decided_by="llm",
                    confidence=float(props.get("confidence") or 0.7),
                ))
    intent.road_targets = existing_roads

    # P6.6: 分区表类别（zone_targets.land_use）与词汇表匹配 → 补 custom_zone_targets。
    # 这样"生态保护区/农田保护区/…"各生成一个功能区面（target_bsms 空 → generator 按
    # 类别 typing_rules 规则选择地块），功能区类别完全由 L3 报告动态决定。
    if vocabulary_name and intent.zone_targets:
        for zt in intent.zone_targets:
            code = _match_category_code(str(zt.land_use or ""), vocabulary_name)
            if code and not any(c.category_code == code for c in intent.custom_zone_targets):
                area_ha = None
                hint = getattr(zt.semantic, "spatial_hint", "") if zt.semantic else ""
                if hint.startswith("AREA:"):
                    try:
                        area_ha = float(hint.split(":", 1)[1])
                    except (TypeError, ValueError):
                        area_ha = None
                intent.custom_zone_targets.append(CustomZoneTarget(
                    vocabulary_name=vocabulary_name,
                    category_code=code,
                    target_bsms=[],
                    area_target_ha=area_ha,
                    decided_by="rule",
                    confidence=0.7,
                ))
    return intent


def _project_category(name: str, evidence: str) -> str:
    text = f"{name} {evidence}"
    if any(word in text for word in ("道路", "村道", "公路", "桥", "路网")):
        return "road"
    if any(word in text for word in ("服务中心", "卫生", "学校", "广场", "停车", "公园")):
        return "facility"
    if any(word in text for word in ("污水", "供水", "排水", "电力", "通信", "环卫")):
        return "infrastructure"
    if any(word in text for word in ("产业", "基地", "园区", "旅游", "民宿")):
        return "industry"
    return "other"


def _match_category_code(name: str, vocabulary_name: str) -> str:
    """Match a project/zone name against the session vocabulary categories."""
    if not vocabulary_name or not name:
        return ""
    try:
        from app.modules.schema.encodings.dicts.vocabularies.loader import get_vocabulary

        vocab = get_vocabulary(vocabulary_name)
    except Exception:
        return ""
    for category in vocab.categories:
        if category.name_zh and (category.name_zh in name or name in category.name_zh):
            return category.code
    return ""
