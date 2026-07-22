"""PARSE Agent tools — structured text extraction, encoding lookup, and pipeline entry.

3 tools for the PARSE Agent subgraph:
  1. extract_structured_text: table text -> structured JSON rows
  2. lookup_land_use_code: land-use name -> GHYTBM standard codes
  3. parse_planning_text: pipeline entry point -> PARSE Agent subgraph

These tools replace the old parse.py single-tool approach.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.utils.logger import get_logger
from app.tools.helpers import make_result

logger = get_logger(__name__)


# ── Tool 1: extract_structured_text ─────────────────────────────────


class TableRow(BaseModel):
    """A single structured table row."""
    pass


class TableExtractionResult(BaseModel):
    """Structured output for table extraction."""
    rows: List[Dict[str, Any]] = []
    column_names: List[str] = []
    confidence: float = 1.0


@tool
async def extract_structured_text(
    section_content: str,
    table_type: str = "general",
) -> Dict[str, Any]:
    """Extract structured rows from table-containing section text.

    Uses LLM with structured output to parse markdown/plain tables
    into List[Dict] row data.

    Args:
        section_content: Text content containing tables
        table_type: Type hint for the table (land_use, indicator, facility, project, general)

    Returns:
        Dict with 'rows', 'column_names', and 'confidence'.
    """
    try:
        from app.core.llm import create_llm, create_flash_llm
        from app.modules.prompts.parse_prompts import EXTRACT_TABLES_PROMPT

        # Use thinking-enabled LLM via factory (includes request_timeout, api_key, streaming)
        # max_tokens=32768 must be >> thinking_budget=2000 (DashScope: max_tokens = thinking + output total)
        # thinking_budget=2000 caps thinking tokens, leaving ~30000 for JSON output
        llm = create_llm(
            temperature=0,
            max_tokens=32768,
            streaming=True,
            extra_body={"enable_thinking": True, "thinking_budget": 2000},
        )

        prompt = EXTRACT_TABLES_PROMPT.format(section_content=section_content)

        # Stage 1: json_schema structured output (qwen3.7-plus supports this natively)
        try:
            structured_llm = llm.with_structured_output(
                TableExtractionResult, method="json_schema"
            )
            result = await structured_llm.ainvoke([
                SystemMessage(content=f"{prompt}\n\nReturn JSON output."),
                HumanMessage(content=section_content),
            ])
            if result is not None:
                return make_result(
                    success=True,
                    data={
                        "rows": result.rows,
                        "column_names": result.column_names,
                        "confidence": result.confidence,
                    },
                )
        except Exception as parse_err:
            logger.debug("[extract_structured_text] Stage 1 failed: %s", parse_err)

        # Stage 2: Raw invoke + manual JSON parse
        raw = None
        try:
            from langchain_core.messages import AIMessage
            raw_response = await llm.ainvoke([
                SystemMessage(content=f"{prompt}\n\nReturn JSON output."),
                HumanMessage(content=section_content),
            ])
            raw = raw_response.content if hasattr(raw_response, 'content') else str(raw_response)

            # Manual JSON extraction
            import re
            json_str = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
            json_str = re.sub(r'\s*```$', '', json_str, flags=re.MULTILINE)

            obj_s = json_str.find('{')
            arr_s = json_str.find('[')
            if arr_s != -1 and (obj_s == -1 or arr_s < obj_s):
                # LLM returned a list — wrap as {"rows": [...]}
                depth, end = 0, arr_s
                for i in range(arr_s, len(json_str)):
                    if json_str[i] == '[': depth += 1
                    elif json_str[i] == ']':
                        depth -= 1
                        if depth == 0: end = i + 1; break
                parsed = json.loads(json_str[arr_s:end])
                result = TableExtractionResult(
                    rows=parsed if isinstance(parsed, list) else [parsed]
                )
            elif obj_s != -1:
                depth, end = 0, obj_s
                for i in range(obj_s, len(json_str)):
                    if json_str[i] == '{': depth += 1
                    elif json_str[i] == '}':
                        depth -= 1
                        if depth == 0: end = i + 1; break
                result = TableExtractionResult.model_validate_json(json_str[obj_s:end])
            else:
                raise parse_err

            return make_result(
                success=True,
                data={
                    "rows": result.rows,
                    "column_names": result.column_names,
                    "confidence": result.confidence,
                },
            )
        except Exception as e2:
            logger.debug("[extract_structured_text] Stage 2 failed: %s", e2)

        # Stage 3: Flash model JSON repair
        if raw:
            try:
                fast_llm = create_flash_llm(temperature=0)
                structured_fast = fast_llm.with_structured_output(
                    TableExtractionResult, method="json_mode"
                )
                result = await structured_fast.ainvoke([
                    SystemMessage(content="你是 JSON 格式修复专家。将以下文本修复为有效 JSON。仅输出 JSON。"),
                    HumanMessage(content=raw[:4000]),
                ])
                if result is not None:
                    return make_result(
                        success=True,
                        data={
                            "rows": result.rows,
                            "column_names": result.column_names,
                            "confidence": result.confidence,
                        },
                    )
            except Exception as e3:
                logger.warning("[extract_structured_text] Stage 3 (flash repair) failed: %s", e3)

        return make_result(success=False, error="All 3 stages failed")
    except Exception as e:
        logger.warning("[extract_structured_text] Failed: %s", e)
        return make_result(success=False, error=str(e))


# ── Tool 2: lookup_land_use_code ────────────────────────────────────


class GHYTBMMatch(BaseModel):
    """A single GHYTBM (planning use code) match entry."""

    ghytbm: str = ""
    ghytmc: str = ""
    zone_type: str = ""
    vne_code: str = ""


class DLBMMatch(BaseModel):
    """A single DLBM (current land-use code) match entry."""

    dlbm: str = ""
    dlmc: str = ""
    zone_type: str = ""


class GHFLBMMatch(BaseModel):
    """A single GHFLBM (planning classification) match entry."""

    ghflbm: str = ""
    ghytbm: str = ""
    ghytmc: str = ""


class LandUseCodeLookup(BaseModel):
    """Typed result for lookup_land_use_code - replaces raw dict.

    Encodes the name -> multi-system-code lookup result as typed models
    so the tool's output structure is guaranteed consistent and validated.
    Serialized via model_dump() into make_result()'s data field.
    """

    ghytbm: str = ""
    ghytmc: str = ""
    ghflbm: str = ""
    vne_code: str = ""
    dlbm_aliases: List[str] = []
    zone_type: str = ""
    candidates_ghytbm: List[GHYTBMMatch] = []
    candidates_dlbm: List[DLBMMatch] = []


@tool
def lookup_land_use_code(land_use_name: str) -> Dict[str, Any]:
    """Look up standard land-use codes for a given land-use name.

    Queries DictionaryCenter YAML dictionaries (dlbm.yaml, ghtybm.yaml).
    Does NOT auto-convert between encoding systems — only returns lookup results
    and candidate suggestions for human confirmation.

    Args:
        land_use_name: Chinese land-use name (e.g., "经营性建设用地", "宅基地")

    Returns:
        Dict with matching codes: ghytbm, ghflbm, vne_code, dlbm_aliases, candidates.
    """
    try:
        from app.modules.gis.schema import (
            GHYTBM_TO_GHYTMC,
            GHYTBM_TO_ZONE_TYPE,
            GHYTBM_TO_VNE,
            GHFLBM_TO_GHYTBMS,
            DLBM_TO_DLMC,
            DLBM_TO_ZONE_TYPE,
        )

        # Search in GHYTBM names (planning use codes) - typed matches
        ghytbm_matches: List[GHYTBMMatch] = []
        for code, name in GHYTBM_TO_GHYTMC.items():
            if land_use_name in name or name in land_use_name:
                ghytbm_matches.append(GHYTBMMatch(
                    ghytbm=code,
                    ghytmc=name,
                    zone_type=GHYTBM_TO_ZONE_TYPE.get(code, ""),
                    vne_code=GHYTBM_TO_VNE.get(code, ""),
                ))

        # Search in DLBM names (current land-use codes) - typed matches
        dlbm_matches: List[DLBMMatch] = []
        for code, name in DLBM_TO_DLMC.items():
            if land_use_name in name or name in land_use_name:
                dlbm_matches.append(DLBMMatch(
                    dlbm=code,
                    dlmc=name,
                    zone_type=DLBM_TO_ZONE_TYPE.get(code, ""),
                ))

        # Search in GHFLBM (planning classification) - typed matches
        ghflbm_matches: List[GHFLBMMatch] = []
        for code, ghytbms in GHFLBM_TO_GHYTBMS.items():
            for ghytbm in ghytbms:
                name = GHYTBM_TO_GHYTMC.get(ghytbm, "")
                if land_use_name in name or name in land_use_name:
                    ghflbm_matches.append(GHFLBMMatch(
                        ghflbm=code,
                        ghytbm=ghytbm,
                        ghytmc=name,
                    ))
                    break

        if not ghytbm_matches and not dlbm_matches:
            lookup = LandUseCodeLookup(
                candidates_ghytbm=ghytbm_matches[:5],
                candidates_dlbm=dlbm_matches[:5],
            )
            return make_result(
                success=False,
                error=f"No code found for '{land_use_name}'",
                data=lookup.model_dump(),
            )

        # Primary match (first GHYTBM match is preferred)
        primary = ghytbm_matches[0] if ghytbm_matches else GHYTBMMatch()
        primary_dlbm = dlbm_matches[0] if dlbm_matches else DLBMMatch()

        lookup = LandUseCodeLookup(
            ghytbm=primary.ghytbm,
            ghytmc=primary.ghytmc,
            ghflbm=ghflbm_matches[0].ghflbm if ghflbm_matches else "",
            vne_code=primary.vne_code,
            dlbm_aliases=[m.dlbm for m in dlbm_matches],
            zone_type=primary.zone_type or primary_dlbm.zone_type,
            candidates_ghytbm=ghytbm_matches[:5],
            candidates_dlbm=dlbm_matches[:5],
        )

        return make_result(success=True, data=lookup.model_dump())
    except Exception as e:
        logger.warning("[lookup_land_use_code] Failed: %s", e)
        return make_result(success=False, error=str(e))


# ── Tool 3: parse_planning_text ─────────────────────────────────────


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
        from app.modules.gis.spatial_context import compute_spatial_context

        # Compute spatial context from GIS data
        spatial_context = compute_spatial_context(gis_data or {})

        # Build KG from GIS data for on-demand spatial queries
        try:
            from app.agent.gis.parse.agent import set_kg_instance
            from app.modules.kg import PlanningKG
            kg = PlanningKG(village_name=village_name)
            if gis_data:
                kg.build_from_reports(
                    reports={},
                    landuse_geojson=gis_data.get("landuse_current_geojson"),
                    gis_data=gis_data,
                )
            set_kg_instance(kg)
            logger.info("[parse_planning_text] KG built: %d triples", kg.get_triple_count())
        except Exception as kg_err:
            logger.warning("[parse_planning_text] KG build skipped: %s", kg_err)

        # Initialize Gazetteer for place name → VillageGroup matching
        try:
            import app.agent.gis.parse.agent as pa
            from app.modules.parsing.gazetteer import PlaceNameResolver
            gazetteer = PlaceNameResolver(spatial_context.natural_villages)
            pa._gazetteer = gazetteer
            logger.info("[parse_planning_text] Gazetteer initialized with %d villages",
                        len(spatial_context.natural_villages))
        except Exception as gz_err:
            logger.warning("[parse_planning_text] Gazetteer init skipped: %s", gz_err)

        # Build and run PARSE Agent subgraph
        from app.agent.gis.parse.agent import build_parse_agent_graph
        from app.agent.gis.parse.state import ParseAgentState, SpatialPlanningIntent

        graph = build_parse_agent_graph()

        input_state = ParseAgentState(
            planning_text=planning_text,
            village_name=village_name,
            spatial_context=spatial_context,
        )

        result = await graph.ainvoke(input_state.model_dump())

        # Extract outputs
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
                    "village_count": len(spatial_context.natural_villages),
                    "relation_count": len(spatial_context.spatial_relations),
                },
            },
        )
    except Exception as e:
        logger.error("[parse_planning_text] Failed: %s", e)
        return make_result(success=False, error=str(e))


__all__ = [
    "extract_structured_text",
    "lookup_land_use_code",
    "parse_planning_text",
]
