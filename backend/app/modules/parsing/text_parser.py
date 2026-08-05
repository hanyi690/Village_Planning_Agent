"""Text parser - deterministic planning text -> SpatialPlanningIntent.

Migrated from app.agent.select.parse_agent.py (Wave M2).
Public API: parse / parse_async / ParseResult.

This module provides the text->intent parsing path that gis_test_routes and
tests consume. The new app.agent.parse package consumes PlanningProgram
(typed), not raw text; this module fills the text->intent gap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List

from app.modules.schema.contracts.parse_contracts import (
    AxisTarget,
    FacilityTarget,
    RoadTarget,
    SpatialPlanningIntent,
    ZoneTarget,
)
from app.modules.schema.contracts.provenance import SemanticMetadata
from app.modules.parsing.tables import extract_instruction_tables
from app.utils.logger import get_logger

logger = get_logger(__name__)


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


# ── Extraction patterns ──

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


# ── Public API ──

def parse(
    planning_text: str,
    village_name: str = "",
    planning_period: str = "2022-2035年",
) -> ParseResult:
    """Parse planning text into SpatialPlanningIntent."""
    regex_zone_targets = _extract_zone_targets(planning_text)
    regex_facilities = _extract_facilities(planning_text)
    axes = _extract_axes(planning_text)
    roads = _extract_roads(planning_text)

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

    instruction = extract_instruction_tables(planning_text)
    if not any(instruction.values()):
        instruction = extract_instruction_tables(
            f"【INSTRUCTION】\n{planning_text}"
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
        "[text_parser] Extracted: %d zones, %d facilities, %d axes, %d roads",
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


__all__ = ["parse", "parse_async", "ParseResult"]
