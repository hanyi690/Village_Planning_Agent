"""parse_intent tool — LLM-driven planning text → UnifiedSpatialIntent.

Merges:
  - layout/planning_intent.py  (data models)
  - tools/gis/layout_tools.py  (parse_planning_text @tool logic)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Annotated

from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Intent Data Models ────────────────────────────────────────

class Direction(str, Enum):
    CENTER = "center"
    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"
    NORTHEAST = "northeast"
    NORTHWEST = "northwest"
    SOUTHEAST = "southeast"
    SOUTHWEST = "southwest"
    PERIPHERY = "periphery"
    EAST_WEST = "east-west"
    NORTH_SOUTH = "north-south"


class Density(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ZoneIntent:
    zone_id: str
    land_use: str
    dlbm: str = ""
    area_ratio: float = 0.0
    direction: Direction = Direction.CENTER
    reference_feature: str = ""
    adjacent_to: List[str] = field(default_factory=list)
    avoid_adjacent_to: List[str] = field(default_factory=list)
    density: Density = Density.MEDIUM
    preserve_existing: bool = True
    dlbm_aliases: List[str] = field(default_factory=list)


@dataclass
class FacilityIntent:
    facility_id: str
    facility_type: str
    target_zone: str
    location_hint: str = ""
    status: str = "existing"


@dataclass
class AxisIntent:
    axis_id: str
    axis_type: str
    direction: Direction
    connects: List[str] = field(default_factory=list)
    label: str = ""


@dataclass
class ConstraintIntent:
    constraint_id: str
    constraint_type: str
    geometry_ref: str = ""
    strict: bool = True


@dataclass
class UnifiedSpatialIntent:
    zones: List[ZoneIntent] = field(default_factory=list)
    facilities: List[FacilityIntent] = field(default_factory=list)
    axes: List[AxisIntent] = field(default_factory=list)
    constraints: List[ConstraintIntent] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_area_ratio(self) -> float:
        return sum(z.area_ratio for z in self.zones)

    def get_zone_by_id(self, zone_id: str) -> Optional[ZoneIntent]:
        for z in self.zones:
            if z.zone_id == zone_id:
                return z
        return None

    def get_zone_by_land_use(self, land_use: str) -> List[ZoneIntent]:
        return [z for z in self.zones if z.land_use == land_use]


# ── Tool Helpers ──────────────────────────────────────────────

def _make_result(success: bool, data: Any = None, error: str = "") -> Dict[str, Any]:
    payload: Dict[str, Any] = {"success": success}
    if data is not None:
        payload["data"] = data
    if error:
        payload["error"] = error
    return payload


def _to_tool_message(result: Dict[str, Any], tool_call_id: str) -> ToolMessage:
    return ToolMessage(
        content=json.dumps(result, ensure_ascii=False, default=str),
        tool_call_id=tool_call_id,
    )


# ── LLM Intent Parsing ────────────────────────────────────────

def _parse_reports_to_intent(
    reports: Dict[str, Dict[str, Any]],
    village_name: str,
    gis_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Parse planning reports into structured spatial intent using LLM + zone_schema."""

    from app.agent.gis.prompts import PARSE_AGENT_SYSTEM_PROMPT

    try:
        from app.core.settings import LLM_MODEL
        from langchain_openai import ChatOpenAI
        from app.services.modules.gis.zone_schema import (
            DLBM_TO_ZONE_TYPE,
            ZONE_TYPE_TO_DLBMS,
            get_zone_type_for_dlbm,
        )

        llm = ChatOpenAI(model=LLM_MODEL, temperature=0.2)

        report_texts = _gather_report_texts(reports)
        landuse_hint = _build_landuse_hint(gis_data)

        prompt = f"""{PARSE_AGENT_SYSTEM_PROMPT}

Village: {village_name}
Total zone types available: {sorted(set(DLBM_TO_ZONE_TYPE.values()))}
{landuse_hint}

Planning reports:
{report_texts}

Extract the spatial intent as JSON with zones[], facilities[], axes[], constraints[].
Each zone MUST specify: zone_id, land_use (from available zone types), dlbm, area_ratio.

Output ONLY valid JSON.
"""
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, "content") else str(response)
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
        intent_json = json.loads(text)

        intent = UnifiedSpatialIntent(
            zones=[ZoneIntent(**z) for z in intent_json.get("zones", [])],
            facilities=[FacilityIntent(**f) for f in intent_json.get("facilities", [])],
            axes=[AxisIntent(**a) for a in intent_json.get("axes", [])],
            constraints=[ConstraintIntent(**c) for c in intent_json.get("constraints", [])],
            metadata={"village_name": village_name},
        )

        return _make_result(True, data={
            "intent_json": intent_json,
            "intent": _intent_to_dict(intent),
        })

    except Exception as e:
        logger.error(f"Intent parsing failed: {e}")
        return _make_result(False, error=str(e), data={
            "intent_json": _build_default_intent(village_name),
        })


def _gather_report_texts(reports: Dict[str, Dict[str, Any]]) -> str:
    """Collect dimension summaries from reports."""
    texts = []
    for dim_key, dim_data in reports.items():
        summary = dim_data.get("summary", "")
        if summary:
            texts.append(f"[{dim_key}]\n{summary}")
    return "\n\n".join(texts) if texts else "(no reports available)"


def _build_landuse_hint(gis_data: Optional[Dict[str, Any]]) -> str:
    """Build a hint from current land use GIS data."""
    if not gis_data:
        return ""
    try:
        current = gis_data.get("landuse_current_geojson")
        if not current:
            return ""
        from collections import Counter
        features = current.get("features", [])
        dlbm_counts = Counter(
            f.get("properties", {}).get("DLBM", "?")
            for f in features
        )
        top = dlbm_counts.most_common(10)
        from app.services.modules.gis.zone_schema import DLBM_TO_DLMC, get_zone_type_for_dlbm
        lines = ["Current land use (top DLBM codes):"]
        for dlbm, count in top:
            dlmc = DLBM_TO_DLMC.get(dlbm, str(dlbm))
            zone = get_zone_type_for_dlbm(dlbm)
            lines.append(f"  {dlbm} ({dlmc}) → {zone} ({count} parcels)")
        return "\n".join(lines)
    except Exception:
        return ""


def _build_default_intent(village_name: str) -> Dict[str, Any]:
    """Fallback: build minimal intent from common village patterns."""
    return {
        "zones": [
            {"zone_id": "agriculture", "land_use": "农业用地", "dlbm": "0100", "area_ratio": 0.45, "direction": "periphery"},
            {"zone_id": "housing", "land_use": "居住用地", "dlbm": "2121", "area_ratio": 0.20, "direction": "center"},
            {"zone_id": "ecological", "land_use": "生态绿地", "dlbm": "0300", "area_ratio": 0.25, "direction": "periphery"},
            {"zone_id": "public", "land_use": "公共服务用地", "dlbm": "0800", "area_ratio": 0.05, "direction": "center"},
            {"zone_id": "transport", "land_use": "交通用地", "dlbm": "1000", "area_ratio": 0.05, "direction": "center"},
        ],
        "facilities": [],
        "axes": [{"axis_id": "main", "axis_type": "primary", "direction": "east-west", "label": "主要发展轴"}],
        "constraints": [],
        "metadata": {"village_name": village_name, "is_default": True},
    }


def _intent_to_dict(intent: UnifiedSpatialIntent) -> Dict[str, Any]:
    return {
        "zones": [z.__dict__ for z in intent.zones],
        "facilities": [f.__dict__ for f in intent.facilities],
        "axes": [a.__dict__ for a in intent.axes],
        "constraints": [c.__dict__ for c in intent.constraints],
        "metadata": intent.metadata,
    }


def _safe_enum(enum_cls: type, value: str, default: Any = None) -> Any:
    """Safely convert string to enum value, returning default on failure."""
    try:
        return enum_cls(value)
    except (ValueError, KeyError):
        return default if default is not None else list(enum_cls)[0]


def _dict_to_intent(data: Dict[str, Any]) -> UnifiedSpatialIntent:
    """Backward-compatible: convert dict to UnifiedSpatialIntent."""
    def _ensure_direction(v: Any) -> Direction:
        return v if isinstance(v, Direction) else Direction(v)
    def _ensure_density(v: Any) -> Density:
        return v if isinstance(v, Density) else Density(v)

    return UnifiedSpatialIntent(
        zones=[ZoneIntent(**{**z, "direction": _ensure_direction(z.get("direction", "center")), "density": _ensure_density(z.get("density", "medium"))}) for z in data.get("zones", [])],
        facilities=[FacilityIntent(**f) for f in data.get("facilities", [])],
        axes=[AxisIntent(**{**a, "direction": _ensure_direction(a.get("direction", "east-west"))}) for a in data.get("axes", [])],
        constraints=[ConstraintIntent(**c) for c in data.get("constraints", [])],
        metadata=data.get("metadata", {}),
    )


# ── Tool ──────────────────────────────────────────────────────

@tool
def parse_planning_text(
    reports: Annotated[Dict[str, Dict[str, Any]], InjectedState("reports")],
    village_name: Annotated[str, InjectedState("village_name")],
    gis_data: Annotated[Optional[Dict[str, Any]], InjectedState("gis_data")] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Parse planning reports into structured spatial intent (UnifiedSpatialIntent).

    The intent includes: zones[], facilities[], axes[], constraints[].
    Data is auto-injected from state — no arguments needed.
    """
    result = _parse_reports_to_intent(
        reports=reports,
        village_name=village_name,
        gis_data=gis_data,
    )
    intent_data = result.get("data", {}).get("intent_json", {})
    return Command(update={
        "intent_json": intent_data,
        "intent": result.get("data", {}).get("intent", {}),
        "messages": [_to_tool_message(result, tool_call_id)],
    })
