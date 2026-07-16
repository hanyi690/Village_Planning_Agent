"""parse_intent tool — LLM-driven planning text → UnifiedSpatialIntent.

Merges:
  - layout/planning_intent.py  (data models)
  - tools/gis/layout_tools.py  (parse_planning_text @tool logic)
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Annotated

from langchain_core.tools import tool, InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.utils.logger import get_logger
from ._helpers import make_result, to_tool_message

from app.modules.gis.schema.intent import (
    Direction, Density, ZoneIntent, FacilityIntent,
    AxisIntent, ConstraintIntent, UnifiedSpatialIntent,
)

logger = get_logger(__name__)


# ── LLM Intent Parsing ────────────────────────────────────────

def _safe_dataclass(cls, d: Dict[str, Any]):
    """Construct a dataclass from dict, ignoring unknown fields and converting enum values.

    Uses typing.get_type_hints to resolve string annotations (from __future__ annotations).
    """
    import typing
    from enum import Enum
    hints = typing.get_type_hints(cls)
    valid = set(hints.keys())
    filtered = {}
    for k, v in d.items():
        if k not in valid:
            continue
        field_type = hints[k]
        if isinstance(field_type, type) and issubclass(field_type, Enum):
            try:
                filtered[k] = field_type(v)
            except (ValueError, KeyError):
                filtered[k] = v
        else:
            filtered[k] = v
    return cls(**filtered)


def _parse_reports_to_intent(
    reports: Dict[str, Dict[str, Any]],
    village_name: str,
    gis_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Parse planning reports into structured spatial intent using LLM + zone_schema."""

    from app.agent.gis.prompts import PARSE_AGENT_SYSTEM_PROMPT
    from app.modules.gis.data.loader import _build_gis_constraints_for_llm

    try:
        from app.core.settings import LLM_MODEL
        from langchain_openai import ChatOpenAI
        from app.modules.gis.schema import (
            DLBM_TO_ZONE_TYPE,
            ZONE_TYPE_TO_DLBMS,
            get_zone_type_for_dlbm,
        )

        llm = ChatOpenAI(model=LLM_MODEL, temperature=0.2)

        report_texts = _gather_report_texts(reports)
        landuse_hint = _build_landuse_hint(gis_data)
        gis_constraints = _build_gis_constraints_for_llm(gis_data)

        from app.modules.gis.schema.classification import SCHEMA
        prompt = PARSE_AGENT_SYSTEM_PROMPT.format(
            dlbm_class_table=SCHEMA.to_prompt_table(),
        )
        prompt += f"""

Village: {village_name}
Total zone types available: {sorted(set(DLBM_TO_ZONE_TYPE.values()))}
{landuse_hint}

{gis_constraints}

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
            zones=[_safe_dataclass(ZoneIntent, z) for z in intent_json.get("zones", [])],
            facilities=[_safe_dataclass(FacilityIntent, f) for f in intent_json.get("facilities", [])],
            axes=[_safe_dataclass(AxisIntent, a) for a in intent_json.get("axes", [])],
            constraints=[_safe_dataclass(ConstraintIntent, c) for c in intent_json.get("constraints", [])],
            metadata={"village_name": village_name},
        )

        return make_result(True, data={
            "intent_json": intent_json,
            "intent": _intent_to_dict(intent),
        })

    except Exception as e:
        logger.error(f"Intent parsing failed: {e}")
        return make_result(False, error=str(e), data={
            "intent_json": _build_default_intent(village_name, gis_data),
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
        from app.modules.gis.schema import DLBM_TO_DLMC, get_zone_type_for_dlbm
        lines = ["Current land use (top DLBM codes):"]
        for dlbm, count in top:
            dlmc = DLBM_TO_DLMC.get(dlbm, str(dlbm))
            zone = get_zone_type_for_dlbm(dlbm)
            lines.append(f"  {dlbm} ({dlmc}) → {zone} ({count} parcels)")
        return "\n".join(lines)
    except Exception:
        return ""


def _build_default_intent(
    village_name: str,
    gis_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Fallback: build intent from GIS data or minimal empty intent."""
    if gis_data:
        try:
            from app.modules.gis.data.loader import compute_intent_from_gis
            return compute_intent_from_gis(gis_data, village_name)
        except Exception:
            pass
    return {
        "zones": [],
        "facilities": [],
        "axes": [],
        "constraints": [],
        "metadata": {"village_name": village_name, "source": "empty"},
    }


def _intent_to_dict(intent: UnifiedSpatialIntent) -> Dict[str, Any]:
    return {
        "zones": [z.__dict__ for z in intent.zones],
        "facilities": [f.__dict__ for f in intent.facilities],
        "axes": [a.__dict__ for a in intent.axes],
        "constraints": [c.__dict__ for c in intent.constraints],
        "metadata": intent.metadata,
    }


def _dict_to_intent(data: Dict[str, Any]) -> UnifiedSpatialIntent:
    """Convert dict to UnifiedSpatialIntent. Enum conversion handled by _safe_dataclass."""
    return UnifiedSpatialIntent(
        zones=[_safe_dataclass(ZoneIntent, z) for z in data.get("zones", [])],
        facilities=[_safe_dataclass(FacilityIntent, f) for f in data.get("facilities", [])],
        axes=[_safe_dataclass(AxisIntent, a) for a in data.get("axes", [])],
        constraints=[_safe_dataclass(ConstraintIntent, c) for c in data.get("constraints", [])],
        metadata=data.get("metadata", {}),
    )


def parse_text_via_llm(
    text: str,
    village_name: str,
    gis_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Parse planning markdown text into intent via LLM."""
    from app.agent.gis.prompts import format_parse_prompt
    from app.core.settings import LLM_MODEL
    from langchain_openai import ChatOpenAI
    from app.modules.gis.data.loader import (
        _build_gis_constraints_for_llm, get_village_params,
    )
    import re as _re

    if gis_data:
        params = get_village_params(gis_data)
    else:
        params = {"total_area": "未知", "land_use_description": "未知"}

    prompt_text = format_parse_prompt(
        planning_text=text,
        village_name=village_name,
        total_area=params["total_area"],
        current_land_use=params["land_use_description"],
    )

    gis_constraints = _build_gis_constraints_for_llm(gis_data)
    if gis_constraints:
        prompt_text = f"{prompt_text}\n\n{gis_constraints}"

    llm = ChatOpenAI(model=LLM_MODEL, temperature=0, request_timeout=120)
    response = llm.invoke(prompt_text)
    json_match = _re.search(r'```json\s*(.*?)\s*```', response.content, _re.DOTALL)
    if not json_match:
        json_match = _re.search(r'(\{[\s\S]*\})', response.content)
    if json_match:
        intent = json.loads(json_match.group(1))
        if intent.get("zones"):
            zones = intent.get("zones", [])
            total = sum(z.get("area_ratio", 0) for z in zones)
            if abs(total - 1.0) > 0.05 and total > 0:
                for z in zones:
                    z["area_ratio"] = round(z.get("area_ratio", 0) / total, 4)
            return intent
    raise ValueError("LLM failed to produce valid intent JSON")


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
        "messages": [to_tool_message(result, tool_call_id)],
    })
