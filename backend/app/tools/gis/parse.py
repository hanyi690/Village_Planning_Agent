"""PARSE tool - pipeline entry for the PARSE Agent.

The primary entry point is parse_planning_text (LangGraph @tool).
All legacy intent functions (resolve_gen_intent, resolve_plan_intent,
parse_text_via_llm, etc.) are DEPRECATED and will be removed in v5.0.
They exist only for backward compat with app.api.gis_test_routes.
New code should use parse_planning_text or directly invoke the PARSE Agent.
"""

from __future__ import annotations

import json
import re
import warnings
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

from app.utils.logger import get_logger
from app.tools.helpers import make_result

logger = get_logger(__name__)


# ============================================================
# Helpers
# ============================================================

_DEPRECATION_MSG = "This function is DEPRECATED and will be removed in v5.0. Use parse_planning_text() or invoke the PARSE Agent directly."


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


def _intent_to_dict(intent) -> Dict[str, Any]:
    """Convert UnifiedSpatialIntent to dict."""
    return {
        "zones": [z.__dict__ for z in intent.zones],
        "facilities": [f.__dict__ for f in intent.facilities],
        "axes": [a.__dict__ for a in intent.axes],
        "constraints": [c.__dict__ for c in intent.constraints],
        "metadata": intent.metadata,
    }


def _dict_to_intent(data: Dict[str, Any]):
    """Convert dict to UnifiedSpatialIntent. Enum conversion handled by _safe_dataclass."""
    from app.modules.schema import (
        UnifiedSpatialIntent, ZoneIntent, FacilityIntent, AxisIntent, ConstraintIntent,
    )
    return UnifiedSpatialIntent(
        zones=[_safe_dataclass(ZoneIntent, z) for z in data.get("zones", [])],
        facilities=[_safe_dataclass(FacilityIntent, f) for f in data.get("facilities", [])],
        axes=[_safe_dataclass(AxisIntent, a) for a in data.get("axes", [])],
        constraints=[_safe_dataclass(ConstraintIntent, c) for c in data.get("constraints", [])],
        metadata=data.get("metadata", {}),
    )


# ============================================================
# GIS-measured constraints + village params (no LLM)
# ============================================================

def _compute_intent_from_gis_internal(
    gis_data: Dict[str, Any],
    village_name: str = "金田村委会",
) -> Dict[str, Any]:
    """Compute spatial intent from actual GIS data (no LLM, no hardcoded values).

    Internal version — no deprecation warning. Used by parse_planning_text fallback.
    """
    from app.tools.gis._analytics.metrics_calculator import GISMetricsCalculator
    from app.modules.schema import get_zone_type_for_dlbm, ZONE_TYPE_TO_DLBMS

    metrics = GISMetricsCalculator.compute_land_use_metrics(gis_data)
    distribution = GISMetricsCalculator.compute_zone_distribution(gis_data)

    zones = []
    for zone_type, area_ratio in sorted(distribution.items(), key=lambda x: -x[1]):
        if area_ratio < 0.001:
            continue
        dlbms = ZONE_TYPE_TO_DLBMS.get(zone_type, [])
        primary_dlbm = dlbms[0] if dlbms else "0100"
        direction = "center" if zone_type in ("居住用地", "公共服务用地", "商业用地") else "periphery"
        zones.append({
            "zone_id": f"z_{zone_type[:2]}",
            "land_use": zone_type,
            "dlbm": primary_dlbm,
            "area_ratio": area_ratio,
            "direction": direction,
            "preserve_existing": True,
        })

    total_ratio = sum(z["area_ratio"] for z in zones)
    if total_ratio > 0 and abs(total_ratio - 1.0) > 0.001:
        for z in zones:
            z["area_ratio"] = round(z["area_ratio"] / total_ratio, 4)

    constraints = []
    if metrics["construction_area_ha"] > 0:
        constraints.append({
            "constraint_id": "c1", "type": "construction_cap",
            "value": metrics["construction_area_ha"], "unit": "公顷",
        })
    if metrics["farmland_area_ha"] > 0:
        constraints.append({
            "constraint_id": "c2", "type": "farmland_min",
            "value": metrics["farmland_area_ha"], "unit": "公顷",
        })
    if metrics["ecological_area_ha"] > 0:
        constraints.append({
            "constraint_id": "c3", "type": "ecological_redline",
            "value": metrics["ecological_area_ha"], "unit": "公顷",
        })

    return {
        "zones": zones,
        "facilities": [],
        "axes": [{"axis_id": "a1", "axis_type": "primary", "direction": "east-west", "label": "主要发展轴"}],
        "constraints": constraints,
        "metadata": {
            "village_name": village_name,
            "source": "gis_data_computed",
            "computed_from": "landuse_current_geojson",
        },
    }


def compute_intent_from_gis(
    gis_data: Dict[str, Any],
    village_name: str = "金田村委会",
) -> Dict[str, Any]:
    """[DEPRECATED] Compute spatial intent from actual GIS data (no LLM, no hardcoded values).

    DEPRECATED: kept for backward compat with gis_test_routes.
    Use parse_planning_text() or invoke the PARSE Agent directly.
    """
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
    return _compute_intent_from_gis_internal(gis_data, village_name)


def get_village_params(gis_data: Dict[str, Any]) -> Dict[str, str]:
    """[DEPRECATED] Compute village parameters from GIS data."""
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
    from app.tools.gis._analytics.metrics_calculator import GISMetricsCalculator
    from app.modules.schema import DLBM_TO_DLMC

    metrics = GISMetricsCalculator.compute_land_use_metrics(gis_data)
    total_area = str(round(metrics["total_area_ha"], 2))

    zone_areas = metrics.get("zone_areas", {})
    sorted_zones = sorted(zone_areas.items(), key=lambda x: -x[1])
    top_zones = [z for z, _ in sorted_zones[:3]]

    zone_names = {
        "农业用地": "农业用地", "生态绿地": "林地", "居住用地": "居民点",
        "水域": "水域", "交通用地": "交通", "产业用地": "产业",
        "公共服务用地": "公服", "商业用地": "商业",
    }
    descriptions = [zone_names.get(z, z) for z in top_zones]

    if descriptions:
        land_use_description = descriptions[0] + "为主，含" + "、".join(descriptions[1:])
    else:
        land_use_description = "未知"

    return {
        "total_area": total_area,
        "land_use_description": land_use_description,
        "village_name": "金田村委会",
    }


def get_data_summary(gis_data: Dict[str, Any]) -> Dict[str, Any]:
    """[DEPRECATED] Compute summary statistics for loaded data."""
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
    summary: Dict[str, Any] = {}
    for key, geojson in gis_data.items():
        if not isinstance(geojson, dict) or "features" not in geojson:
            continue
        feats = geojson.get("features", [])
        feat_count = len(feats)
        geom_types: Dict[str, int] = {}
        for f in feats:
            gt = f.get("geometry", {}).get("type", "None")
            geom_types[gt] = geom_types.get(gt, 0) + 1
        summary[key] = {"feature_count": feat_count, "geometry_types": geom_types}
    return summary


# ============================================================
# [DEPRECATED] LLM intent parsing (use PARSE Agent instead)
# ============================================================

def _gather_report_texts(reports: Dict[str, Dict[str, Any]]) -> str:
    """[DEPRECATED] Collect dimension summaries from reports."""
    texts = []
    for dim_key, dim_data in reports.items():
        summary = dim_data.get("summary", "")
        if summary:
            texts.append(f"[{dim_key}]\n{summary}")
    return "\n\n".join(texts) if texts else "(no reports available)"


def _build_landuse_hint(gis_data: Optional[Dict[str, Any]]) -> str:
    """[DEPRECATED] Build a hint from current land use GIS data."""
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
        from app.modules.schema import DLBM_TO_DLMC, get_zone_type_for_dlbm
        lines = ["Current land use (top DLBM codes):"]
        for dlbm, count in top:
            dlmc = DLBM_TO_DLMC.get(dlbm, str(dlbm))
            zone = get_zone_type_for_dlbm(dlbm)
            lines.append(f"  {dlbm} ({dlmc}) -> {zone} ({count} parcels)")
        return "\n".join(lines)
    except Exception:
        return ""


def _build_gis_constraints_for_llm(gis_data: Optional[Dict[str, Any]]) -> str:
    """[DEPRECATED] Build GIS-measured constraints string for LLM prompt injection."""
    if not gis_data:
        return ""
    from app.tools.gis._analytics.metrics_calculator import GISMetricsCalculator
    metrics = GISMetricsCalculator.compute_land_use_metrics(gis_data)
    lines = [
        "## GIS 实测约束（必须遵守）",
        f"- 建设用地面积: {metrics['construction_area_ha']} 公顷（上限）",
        f"- 耕地保有量: {metrics['farmland_area_ha']} 公顷（下限）",
        f"- 生态保护红线: {metrics['ecological_area_ha']} 公顷（下限）",
        f"- 森林覆盖率: {metrics['forest_coverage']}%",
        f"- 水域面积: {metrics['water_area_ha']} 公顷",
        f"- 村域总面积: {metrics['total_area_ha']} 公顷",
        "",
        "以上约束来自 GIS 实测数据，area_ratio 必须与这些面积一致。",
    ]
    return "\n".join(lines)


def _build_default_intent(
    village_name: str,
    gis_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """[DEPRECATED] Fallback: build intent from GIS data or minimal empty intent."""
    if gis_data:
        try:
            return _compute_intent_from_gis_internal(gis_data, village_name)
        except Exception:
            pass
    return {
        "zones": [],
        "facilities": [],
        "axes": [],
        "constraints": [],
        "metadata": {"village_name": village_name, "source": "empty"},
    }


def _parse_reports_to_intent(
    reports: Dict[str, Dict[str, Any]],
    village_name: str,
    gis_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """[DEPRECATED] Parse planning reports into structured spatial intent using LLM.

    DEPRECATED: use parse_planning_text() or invoke the PARSE Agent.
    """
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
    from app.agent.gis.prompts import PARSE_AGENT_SYSTEM_PROMPT

    try:
        from app.core.settings import LLM_MODEL
        from langchain_openai import ChatOpenAI
        from app.modules.schema import (
            DLBM_TO_ZONE_TYPE,
            ZONE_TYPE_TO_DLBMS,
            get_zone_type_for_dlbm,
            UnifiedSpatialIntent, ZoneIntent, FacilityIntent, AxisIntent, ConstraintIntent,
            SCHEMA,
        )

        llm = ChatOpenAI(model=LLM_MODEL, temperature=0.2)

        report_texts = _gather_report_texts(reports)
        landuse_hint = _build_landuse_hint(gis_data)
        gis_constraints = _build_gis_constraints_for_llm(gis_data)

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


def parse_text_via_llm(
    text: str,
    village_name: str,
    gis_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """[DEPRECATED] Parse planning markdown text into intent via LLM.

    DEPRECATED: use parse_planning_text() or invoke the PARSE Agent.
    """
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
    from app.agent.gis.prompts import format_parse_prompt
    from app.core.settings import LLM_MODEL
    from langchain_openai import ChatOpenAI

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
    json_match = re.search(r'```json\s*(.*?)\s*```', response.content, re.DOTALL)
    if not json_match:
        json_match = re.search(r'(\{[\s\S]*\})', response.content)
    if json_match:
        intent = json.loads(json_match.group(1))
        if intent.get("zones"):
            zones = intent.get("zones", [])
            total = sum(z.get("area_ratio", 0) for z in zones)
            if abs(total - 1.0) > 0.05 and total > 0:
                for z in zones:
                    z["area_ratio"] = round(z.get("area_ratio", 0) / total, 4)
            return intent
    return _build_default_intent(village_name, gis_data)


# ============================================================
# [DEPRECATED] High-level resolvers (use PARSE Agent instead)
# ============================================================

def resolve_gen_intent(
    village_name: str = "金田村委会",
    gis_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """[DEPRECATED] Gen path: parse intent from planning markdown.

    DEPRECATED: use parse_planning_text() or invoke the PARSE Agent.
    """
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
    try:
        from app.modules.data.documents import load_planning_text
        text = load_planning_text(village_name)
        intent = parse_text_via_llm(text, village_name, gis_data)
        intent.setdefault("metadata", {})["source"] = "planning_markdown_llm"
        logger.info("[resolve_gen_intent] Parsed from planning markdown")
        return intent
    except FileNotFoundError:
        logger.warning("[resolve_gen_intent] No planning markdown found - cannot resolve gen intent")
    except Exception as e:
        logger.warning(f"[resolve_gen_intent] Markdown parsing failed: {e}")

    if gis_data:
        logger.warning("[resolve_gen_intent] DEGRADED: falling back to GIS data computation (no LLM)")
        intent = compute_intent_from_gis(gis_data, village_name)
        intent.setdefault("metadata", {})["source"] = "gis_data_fallback"
        intent["metadata"]["degraded"] = True
        intent["metadata"]["degraded_reason"] = "planning_markdown_not_found_or_llm_failed"
        return intent

    raise ValueError("No planning markdown found for gen intent")


def resolve_plan_intent(
    village_name: str = "金田村委会",
    gis_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """[DEPRECATED] Plan path: parse intent from L3 reports.

    DEPRECATED: use parse_planning_text() or invoke the PARSE Agent.
    """
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
    from app.modules.data.documents import load_l3_reports
    reports = load_l3_reports()
    if reports:
        try:
            result = _parse_reports_to_intent(reports, village_name, gis_data)
            if result.get("success"):
                intent_json = result.get("data", {}).get("intent_json", {})
                if intent_json.get("zones"):
                    intent_json.setdefault("metadata", {})["source"] = "l3_reports_llm"
                    logger.info("[resolve_plan_intent] Parsed from L3 reports")
                    return intent_json
        except Exception as e:
            logger.warning(f"[resolve_plan_intent] L3 reports parsing failed: {e}")

    if gis_data:
        logger.warning("[resolve_plan_intent] DEGRADED: falling back to GIS data computation (no LLM)")
        intent = compute_intent_from_gis(gis_data, village_name)
        intent.setdefault("metadata", {})["source"] = "gis_data_fallback"
        intent["metadata"]["degraded"] = True
        intent["metadata"]["degraded_reason"] = "l3_reports_not_found_or_llm_failed"
        return intent

    raise ValueError("No L3 reports found for plan intent")


# ============================================================
# LangGraph tool: parse_planning_text
# ============================================================

@tool
async def parse_planning_text(
    planning_text: str,
    village_name: str = "",
    gis_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Parse planning text via PARSE Agent subgraph.

    This is the pipeline entry point that runs the full PARSE Agent:
      classify_sections -> route_by_section -> extract_* -> validate_and_merge

    Returns structured output with:
      - operation_sequence: List[SpatialOperation] with spatial anchors
      - constraint_set: List[SpatialConstraint] with spatial rules
      - planning_intent: SpatialPlanningIntent with zone targets and facilities

    Args:
        planning_text: Markdown planning report text
        village_name: Target village name
        gis_data: GIS data bundle for spatial context computation

    Returns:
        Dict with operation_sequence, constraint_set, planning_intent.
    """
    try:
        from app.modules.spatial_ops import compute_context_blocks
        from app.modules.schema.contracts.context_contracts import ContextBlockType as CBT

        # Compute context blocks from GIS data
        gis_bundle = (gis_data or {}).pop("_gis_bundle", None)
        if gis_bundle is not None:
            context_blocks = compute_context_blocks(gis_bundle)
        elif gis_data:
            from app.modules.data.catalog.catalog import DataCatalog
            catalog = DataCatalog()
            bundle = catalog.load_village_bundle(village_name)
            context_blocks = compute_context_blocks(bundle) if bundle else []
        else:
            context_blocks = []

        try:
            from app.modules.kg.manager import get_kg_manager
            manager = get_kg_manager()
            # Prefer typed bundle (v4 path); build one if only raw gis_data available
            kg_bundle = gis_bundle
            if kg_bundle is None and gis_data:
                try:
                    from app.modules.data.catalog.catalog import DataCatalog
                    kg_bundle = DataCatalog().load_village_bundle(village_name)
                except Exception:
                    pass
            if kg_bundle is not None:
                kg, _cache_hit = manager.get_or_build_layer1(
                    village_name, bundle=kg_bundle
                )
                logger.info("[parse_planning_text] KG ready: %d triples", kg.get_triple_count())
        except Exception as kg_err:
            logger.warning("[parse_planning_text] KG build skipped: %s", kg_err)

        # Extract residential cluster data from context blocks for Gazetteer
        residential_clusters = []
        for block in context_blocks:
            if getattr(block, "block_type", None) == CBT.RESIDENTIAL_CLUSTERS:
                residential_clusters = [
                    {"name": v["name"], "center": v.get("center", [0, 0])}
                    for v in block.data.get("villages", [])
                ]
                break

        try:
            import app.agent.gis.parse.agent as pa
            from app.modules.parsing.gazetteer import PlaceNameResolver
            gazetteer = PlaceNameResolver(residential_clusters)
            pa._gazetteer = gazetteer
            logger.info("[parse_planning_text] Gazetteer initialized with %d villages",
                        len(residential_clusters))
        except Exception as gz_err:
            logger.warning("[parse_planning_text] Gazetteer init skipped: %s", gz_err)

        from app.agent.gis.parse.agent import build_parse_agent_graph, set_context_blocks
        from app.agent.gis.parse.state import ParseAgentState, SpatialPlanningIntent

        set_context_blocks(context_blocks)
        graph = build_parse_agent_graph()

        input_state = ParseAgentState(
            planning_text=planning_text,
            village_name=village_name,
            context_blocks=context_blocks,
        )

        result = await graph.ainvoke(input_state.model_dump())

        operation_sequence = result.get("operation_sequence", [])
        constraint_set = result.get("constraint_set", [])
        planning_intent = result.get("planning_intent", SpatialPlanningIntent())
        validation_errors = result.get("validation_errors", [])

        logger.info(
            "[parse_planning_text] Parsed: %d operations, %d constraints, %d errors",
            len(operation_sequence),
            len(constraint_set),
            len(validation_errors),
        )

        return make_result(
            success=True,
            data={
                "operation_sequence": operation_sequence,
                "constraint_set": constraint_set,
                "planning_intent": planning_intent,
                "validation_errors": validation_errors,
                "spatial_context_summary": {
                    "parcel_count": spatial_context.parcel_count,
                    "total_area_ha": spatial_context.total_area_ha,
                    "village_count": len(spatial_context.residential_clusters),
                    "relation_count": len(spatial_context.spatial_relations),
                },
            },
        )
    except Exception as e:
        logger.error("[parse_planning_text] Failed: %s", e)
        return make_result(success=False, error=str(e))


__all__ = [
    # Tool
    "parse_planning_text",
    # LLM intent
    "parse_text_via_llm",
    "_parse_reports_to_intent",
    "resolve_gen_intent",
    "resolve_plan_intent",
    "compute_intent_from_gis",
    "get_village_params",
    "get_data_summary",
    "_dict_to_intent",
    "_intent_to_dict",
]
