"""PARSE Agent subgraph — Think-Then-Format two-phase pattern.

Architecture (LangGraph StateGraph):
  START -> classify_sections -> route_by_section (conditional edges fan-out)
     -> [explore_projects -> format_projects
      | explore_targets -> format_targets
      | extract_regulations | extract_tables]
     -> validate_and_merge -> should_retry? -> END or retry

Key design (v8 — Think-Then-Format):
  - Phase A (explore): thinking=ON, json_schema=OFF, tools=ON
    LLM freely reasons + calls tools (lookup_code, resolve_place, query_village_kg)
    Produces natural language draft + structured code/place mappings
  - Phase B (format): thinking=OFF, json_schema=ON, tools=OFF
    LLM formats draft into strict Pydantic output — guaranteed compatible
  - Separation eliminates "output length limit exceeded" caused by
    qwen3.7-plus thinking mode + json_schema incompatibility

Why this works:
  - qwen3.7-plus thinking mode consumes token budget unpredictably,
    leaving insufficient tokens for json_schema output -> truncation
  - By separating thinking (Phase A) from json_schema (Phase B),
    each call uses a compatible feature set
  - Phase A: max_tokens=8192 (thinking + free text, no JSON constraint)
  - Phase B: max_tokens=4096 (pure JSON output, no thinking tokens)

LangGraph compliance:
  - Tool calling and structured output in SEPARATE nodes (official pattern)
  - No bind_tools() + with_structured_output() anti-pattern
  - Conditional edges fan-out to explore nodes
  - Explore -> Format edges ensure sequential execution within each pair

References:
  [1] LangGraph StateGraph with Pydantic BaseModel state
  [2] LangGraph conditional edges for fan-out routing
  [3] https://help.aliyun.com/zh/model-studio/qwen-structured-output
  [4] Exa search: "thinking mode breaks json_schema in Qwen models"
"""

from __future__ import annotations

import functools
import json
import re
import time
import warnings

# Suppress Pydantic serializer warnings
warnings.filterwarnings("ignore", message="Pydantic serializer")
from typing import Any, Dict, List, Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import StateGraph, END, START

from app.agent.gis.parse.state import (
    ParseAgentState,
    SectionInfo,
    SpatialAnchor,
    SpatialConstraint,
    SpatialOperation,
    SpatialPlanningIntent,
    SpatialRule,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

MAX_PARSE_ROUNDS = 2

# Global Gazetteer instance
_gazetteer: Any = None

# Global SpatialContext for annotation-based Tier 0 place resolution.
# Set by run_parse_pipeline / _parse_intent_node before PARSE graph runs.
_current_spatial_context: Any = None


def set_spatial_context(ctx: Any) -> None:
    """Store the active SpatialContext so resolve_place can use Tier 0 matching.

    Tier 0 uses annotation-derived village/facility anchors (precise coordinates)
    before falling back to the gazetteer's fuzzy/Tianditu matching.
    """
    global _current_spatial_context
    _current_spatial_context = ctx


def _log_llm_call(node: str, phase: str, system_msg: str, user_msg: str,
                  response_content: str, tool_calls: list, elapsed: float,
                  codes: dict = None, draft_len: int = 0,
                  thinking_content: str = "", tool_results: list = None) -> dict:
    """Append a structured LLM call trace entry and return it.

    Returns the trace dict so callers can collect it without referencing
    the mutable global list.
    """
    entry = {
        "node": node,
        "phase": phase,
        "timestamp": time.time(),
        "system_prompt": system_msg,
        "user_prompt": user_msg,
        "response_content": response_content[:8000] if response_content else "",
        "response_len": len(response_content) if response_content else 0,
        "thinking_content": thinking_content[:4000] if thinking_content else "",
        "tool_calls": [{"name": tc.get("name", ""), "args": str(tc.get("args", {}))[:300]}
                       for tc in (tool_calls or [])],
        "tool_results": tool_results or [],
        "tool_call_count": len(tool_calls) if tool_calls else 0,
        "elapsed_s": elapsed,
        "codes_extracted": codes or {},
        "draft_length": draft_len,
    }
    return entry


def _extract_thinking(response) -> str:
    """Extract thinking content from LLM response.

    qwen3.7-plus puts thinking in:
      - response.additional_kwargs["thinking"]
      - or within hesitation tags in response.content
    """
    # Try additional_kwargs first (official qwen thinking API)
    if hasattr(response, "additional_kwargs"):
        thinking = response.additional_kwargs.get("thinking", "")
        if thinking:
            return thinking if isinstance(thinking, str) else str(thinking)

    # Fallback: extract from content between thinking tags
    content = getattr(response, "content", "") or ""
    match = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
    if match:
        return match.group(1).strip()

    return ""


def _get_current_parse_kg() -> Any:
    """Get current KG instance for PARSE agent tool queries.

    Delegates to KGManager.get_any_kg() — returns the most recently
    registered session KG or a cached Layer 1 KG. Returns None if no KG is available.
    """
    from app.modules.kg.manager import get_kg_manager
    return get_kg_manager().get_any_kg()


# ── Tool execution ────────────────────────────────────────────────────


async def _execute_tool_call(tool_name: str, tool_args: dict) -> str:
    """Execute a tool call and return JSON string."""
    import json as _json

    # KG queries
    if tool_name in ("query_village_kg", "find_village_by_name"):
        kg_instance = _get_current_parse_kg()
        if kg_instance is None:
            return _json.dumps({"error": "KG not initialized"})
        from app.modules.kg.query import query_kg
        try:
            template_name = tool_args.get("template_name", "")
            params = {k: v for k, v in tool_args.items() if k != "template_name"}
            results = query_kg(kg_instance, template_name, **params)
            return _json.dumps(results, ensure_ascii=False, default=str)
        except Exception as e:
            logger.warning("[PARSE] KG query failed: %s", e)
            return _json.dumps({"error": str(e)})

    # Code lookup
    if tool_name == "lookup_code":
        land_use_name = tool_args.get("land_use_name", "")
        if not land_use_name:
            return _json.dumps({"error": "missing land_use_name"})
        try:
            from app.tools.gis.lookup import lookup_land_use_code
            result = lookup_land_use_code.invoke({"land_use_name": land_use_name})
            return _json.dumps(result, ensure_ascii=False, default=str)
        except Exception as e:
            return _json.dumps({"error": str(e)}, ensure_ascii=False)

    # Place name -> VillageGroup matching
    if tool_name == "resolve_place":
        place_name = tool_args.get("place_name", "")
        if not place_name:
            return _json.dumps({"error": "missing place_name"})

        # Tier 0: annotation village anchors (precise coordinates from GIS)
        if _current_spatial_context is not None:
            # Check annotation_villages first (most precise)
            for ann_v in getattr(_current_spatial_context, "annotation_villages", []):
                ann_name = getattr(ann_v, "name", "")
                if ann_name and (place_name in ann_name or ann_name in place_name):
                    return _json.dumps({
                        "name": ann_name,
                        "center": list(getattr(ann_v, "center", (0, 0))),
                        "parcel_ids": getattr(ann_v, "parcel_ids", []),
                        "confidence": 0.95,
                        "method": "annotation_village_exact",
                    }, ensure_ascii=False)
            # Check natural_villages (may have been merged with annotation names)
            for nv in getattr(_current_spatial_context, "natural_villages", []):
                nv_name = getattr(nv, "name", "")
                if nv_name and (place_name in nv_name or nv_name in place_name):
                    return _json.dumps({
                        "name": nv_name,
                        "center": list(getattr(nv, "center", (0, 0))),
                        "parcel_ids": getattr(nv, "parcel_ids", []),
                        "confidence": 0.9,
                        "method": "natural_village_match",
                    }, ensure_ascii=False)
            # Check facility_anchors (e.g. "村委会", "小学")
            for fa in getattr(_current_spatial_context, "facility_anchors", []):
                fa_name = getattr(fa, "name", "")
                fa_type = getattr(fa, "facility_type", "")
                if fa_name and (place_name in fa_name or fa_name in place_name):
                    return _json.dumps({
                        "name": fa_name,
                        "center": list(getattr(fa, "center", (0, 0))),
                        "facility_type": fa_type,
                        "confidence": 0.9,
                        "method": "facility_anchor_exact",
                    }, ensure_ascii=False)
                if fa_type and place_name in fa_type:
                    return _json.dumps({
                        "name": fa_name,
                        "center": list(getattr(fa, "center", (0, 0))),
                        "facility_type": fa_type,
                        "confidence": 0.85,
                        "method": "facility_type_match",
                    }, ensure_ascii=False)

        # Tier 1: Gazetteer (Tianditu geocode + fuzzy match)
        global _gazetteer
        if _gazetteer is None:
            return _json.dumps({"error": "Gazetteer not initialized"})
        try:
            result = _gazetteer.resolve(place_name)
            return _json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return _json.dumps({"error": str(e)}, ensure_ascii=False)

    return _json.dumps({"error": f"Unknown tool: {tool_name}"}, ensure_ascii=False)


# ── LangChain tool definitions (schema only — execution via _execute_tool_call) ──

from langchain_core.tools import tool as _langchain_tool


@_langchain_tool
def query_village_kg(template_name: str, **params) -> str:
    """Query village planning knowledge graph for spatial information.

    Available templates (use these EXACT names):
    — Spatial distribution:
      count_by_zone_type, count_by_vne, count_by_planning_zone,
      get_three_zones, get_three_lines
    — Parcel queries:
      get_village_parcels, get_parcels_by_dlbm, get_parcels_by_zone_type,
      get_parcel_detail (bsm=...), get_parcel_neighbors (bsm=...),
      get_parcels_near_point (min_lon, max_lon, min_lat, max_lat)
    — Facilities & infrastructure:
      get_facility_locations, get_facilities_by_type,
      get_road_network, get_water_bodies, get_village_anchors
    — Constraints & protection:
      get_constraints, get_constraint_by_field, check_protected_parcels,
      get_protected_parcels_detail, get_zone_restrictions
    — Planning:
      get_designated_zones, get_all_projects, get_indicators

    Args:
        template_name: SPARQL template name (must match EXACTLY)
        **params: Optional filter params (dlbm, zone_type, bsm, etc.)
    """
    return "Tool called — execution handled by agent loop."


@_langchain_tool
def lookup_code(land_use_name: str) -> str:
    """Query land-use name to standard GHYTBM code.

    Example: lookup_code('宅基地') -> {"ghytbm":"2121","zone_type":"居住用地"}
    Do NOT guess codes — always use this tool.
    """
    import json as _json
    try:
        from app.tools.gis.lookup import lookup_land_use_code
        result = lookup_land_use_code.invoke({"land_use_name": land_use_name})
        return _json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return _json.dumps({"error": str(e), "land_use_name": land_use_name}, ensure_ascii=False)


@_langchain_tool
def resolve_place(place_name: str) -> str:
    """Resolve place name to GIS anchor + parcel IDs.

    Resolution tiers (highest confidence first):
      Tier 0: annotation village anchors (precise GIS coordinates, conf=0.95)
      Tier 0.5: facility anchors from annotation.geojson (conf=0.9)
      Tier 1: Tianditu geocode + nearest VillageGroup
      Tier 2: fuzzy substring match (conf=0.5)

    Example: resolve_place('八社村') -> {name, center, parcel_ids, confidence, method}
    Do NOT guess parcel IDs — always use this tool.
    """
    return "Tool called — execution handled by agent loop."


# ── LLM helpers ──────────────────────────────────────────────────────


@functools.lru_cache(maxsize=4)
def _get_llm(enable_thinking: bool = True, thinking_budget: int = 2000):
    """Get LLM instance — cached (max 4 configurations: thinking on/off × budgets).

    Phase A (explore): thinking=ON, max_tokens=8192
    Phase B (format): thinking=OFF, max_tokens=16384
    """
    from app.core.llm import create_llm

    extra_body = {}
    if enable_thinking:
        extra_body["enable_thinking"] = True
        extra_body["thinking_budget"] = thinking_budget
        max_tokens = 8192  # thinking + free text (no JSON constraint)
    else:
        max_tokens = 16384  # JSON output — large schemas need headroom

    return create_llm(
        temperature=0,
        max_tokens=max_tokens,
        streaming=True,
        extra_body=extra_body,
    )


def _extract_mappings(result_str: str, code_mappings: dict, place_mappings: dict):
    """Extract code and place mappings from tool result JSON (not regex)."""
    try:
        data = json.loads(result_str)
        # Handle nested {"data": {...}} wrapper
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
            inner = data["data"]
        elif isinstance(data, dict):
            inner = data
        elif isinstance(data, list):
            # SPARQL results: [{zone_type, count, total_area}, ...]
            # Don't extract codes from list results, but log they were seen
            logger.debug("[mappings] list result (%d items) — not extractable as code/place", len(data))
            return
        else:
            logger.debug("[mappings] unhandled type=%s", type(data).__name__)
            return

        # lookup_code result: has ghytbm + ghytmc
        if "ghytbm" in inner and "ghytmc" in inner:
            name = inner.get("ghytmc", "")
            code = inner.get("ghytbm", "")
            if name and code:
                code_mappings[name] = code
                logger.debug("[mappings] code: %s -> %s", name, code)

        # resolve_place result: has village_name
        if "village_name" in inner and inner.get("village_name"):
            place_name = inner.get("name", "")
            if place_name:
                place_mappings[place_name] = {
                    "village_name": inner["village_name"],
                    "parcel_ids": inner.get("parcel_ids", []),
                    "confidence": inner.get("confidence", 0),
                }
                logger.debug("[mappings] place: %s -> %s", place_name, inner["village_name"])

        # Also check candidates for additional code mappings
        # Typed path (Phase 3): candidates_ghytbm list from LandUseCodeLookup
        for candidates_key in ("candidates_ghytbm", "candidates_dlbm"):
            for m in inner.get(candidates_key, []) or []:
                if isinstance(m, dict) and "ghytbm" in m and "ghytmc" in m:
                    name2 = m.get("ghytmc", "")
                    code2 = m.get("ghytbm", "")
                    if name2 and code2:
                        code_mappings[name2] = code2
        # Backward compat: old candidates dict format
        candidates = inner.get("candidates", {})
        if isinstance(candidates, dict):
            for match_list in candidates.values():
                if isinstance(match_list, list):
                    for m in match_list:
                        if isinstance(m, dict) and "ghytbm" in m and "ghytmc" in m:
                            name2 = m.get("ghytmc", "")
                            code2 = m.get("ghytbm", "")
                            if name2 and code2:
                                code_mappings[name2] = code2

        # Handle error results (e.g., KG not initialized)
        if "error" in inner:
            logger.debug("[mappings] tool error: %s", inner.get("error", "")[:80])
    except (json.JSONDecodeError, TypeError, AttributeError) as e:
        logger.debug("[mappings] parse failed: %s", e)


async def _format_structured(llm, schema_cls, messages: list) -> object | None:
    """Two-stage structured output — NO thinking mode.

    Stage 1: json_schema (thinking=OFF, guaranteed compatible)
    Stage 2: json_object fallback (simpler, more reliable)

    Note: trace data is returned via _trace_llm_calls.append() side-effect.
    See _log_llm_call().
    """
    schema_name = schema_cls.__name__

    # Compute input length for logging
    input_len = sum(len(m.content) if hasattr(m, "content") else 0 for m in messages)

    # Stage 1: json_schema
    try:
        structured = llm.with_structured_output(schema_cls, method="json_schema")
        result = await structured.ainvoke(messages)
        if result is not None:
            print(f"    OK {schema_name} (json_schema) input={input_len}chars", flush=True)
            return result
    except Exception as e:
        err_msg = str(e)
        snippet = err_msg[:150]
        print(f"    S1 fail {schema_name}: {snippet}", flush=True)
        logger.warning("[format] S1 %s failed (input=%d chars): %s", schema_name, input_len, snippet)

    # Stage 2: json_object + manual parse
    try:
        raw = await llm.ainvoke(messages)
        text = raw.content if hasattr(raw, "content") else str(raw)
        logger.info("[format] S2 raw output: %d chars for %s", len(text), schema_name)
        # Try json_object mode
        structured = llm.with_structured_output(schema_cls, method="json_mode")
        result = await structured.ainvoke([
            SystemMessage(content="Output valid JSON matching the schema."),
            HumanMessage(content=text[:8000]),
        ])
        if result is not None:
            # Log what we got
            field_sizes = {}
            for fname in schema_cls.model_fields:
                val = getattr(result, fname, None)
                if isinstance(val, list):
                    field_sizes[fname] = len(val)
                elif val is not None:
                    field_sizes[fname] = 1
            logger.info("[format] S2 %s OK — fields: %s", schema_name, field_sizes)
            print(f"    OK {schema_name} (json_mode) — {field_sizes}", flush=True)
            return result
    except Exception as e:
        err_msg = str(e)
        print(f"    S2 fail {schema_name}: {err_msg[:150]}", flush=True)
        logger.warning("[format] S2 %s failed: %s", schema_name, err_msg)

    print(f"    FAIL {schema_name} (input={input_len}chars)", flush=True)
    return None


# ── Node 1: classify_sections ────────────────────────────────────────


async def classify_sections_node(state: ParseAgentState) -> dict:
    """Classify document sections — hybrid: keyword (70%) + LLM fallback (30%)."""
    from app.modules.parsing.markdown_parser import split_by_headers, detect_table
    from app.modules.parsing.section_classifier import classify_section, needs_llm_fallback

    # Step 1: deterministic header-based splitting
    raw_sections = split_by_headers(state.planning_text[:12000])
    if not raw_sections:
        raw_sections = [{"title": "Full document", "content": state.planning_text[:8000], "level": 0}]

    # Step 2: keyword-based classification + table detection
    classified = []
    low_conf = []
    for i, rs in enumerate(raw_sections):
        section_type, score = classify_section(rs["title"], rs["content"])
        has_table = detect_table(rs["content"])

        if needs_llm_fallback(section_type, score):
            low_conf.append({"index": i, **rs, "keyword_type": section_type})

        classified.append(SectionInfo(
            section_id=f"S{i + 1:02d}",
            title=rs["title"],
            section_type=section_type,
            content=rs["content"],
            has_table=has_table,
        ))

    # Step 3: LLM fallback only for low-confidence sections
    if low_conf:
        logger.info("[PARSE:classify] %d/%d sections -> LLM fallback",
                     len(low_conf), len(raw_sections))
        try:
            from pydantic import BaseModel as _BM, Field as _Field

            class _FallbackItem(_BM):
                index: int = 0
                section_type: str = ""

            class _FallbackResult(_BM):
                items: list[_FallbackItem] = _Field(default_factory=list)

            llm = _get_llm(enable_thinking=True, thinking_budget=1000)
            from app.modules.parsing.section_classifier import build_fallback_prompt

            prompt = build_fallback_prompt(low_conf)
            messages = [
                SystemMessage(content="You are a village plan document classifier. Output section_type for each."),
                HumanMessage(content=prompt),
            ]
            fb_result = await _format_structured(llm, _FallbackResult, messages)
            if fb_result and fb_result.items:
                for item in fb_result.items:
                    if 0 <= item.index < len(classified):
                        classified[item.index].section_type = item.section_type or classified[item.index].section_type
        except Exception as e:
            logger.warning("[PARSE:classify] LLM fallback failed: %s", e)

    logger.info("[PARSE:classify] %d sections (keyword + LLM hybrid)", len(classified))
    return {
        "section_map": classified,
        "parse_strategy": "full",
    }


# ── Routing: route_by_section (conditional edges fan-out) ─────────────


def route_by_section(state: ParseAgentState) -> List[str]:
    """Fan-out: route to explore/extract nodes based on section types."""
    targets = []
    seen = set()

    for section in state.section_map:
        st = section.section_type

        if st in ("regulation", "protection") and "extract_regulations" not in seen:
            targets.append("extract_regulations")
            seen.add("extract_regulations")
        if st in ("project_table", "land_use_table", "facility_table", "infrastructure") and "explore_projects" not in seen:
            targets.append("explore_projects")
            seen.add("explore_projects")
        if st in ("indicator_table", "target", "spatial_layout") and "explore_targets" not in seen:
            targets.append("explore_targets")
            seen.add("explore_targets")
        if section.has_table and "extract_tables" not in seen:
            targets.append("extract_tables")
            seen.add("extract_tables")

    # Default: at least explore targets
    if not targets:
        targets.append("explore_targets")

    logger.info("[PARSE:route] Routing to: %s", targets)
    return targets


# ── Helper ────────────────────────────────────────────────────────────


def _get_sections_text(state: ParseAgentState, *section_types: str) -> str:
    """Get combined text of sections matching any of the given types."""
    texts = []
    for s in state.section_map:
        if s.section_type in section_types:
            texts.append(s.content)
    return "\n\n".join(texts) if texts else state.planning_text[:8000]


# ── Node 2a: extract_regulations ──────────────────────────────────────


async def extract_regulations_node(state: ParseAgentState) -> dict:
    """Extract spatial constraints — hybrid: regex (70%) + LLM fallback (30%).

    Phase 3: Injects YAML control rule categories into LLM fallback prompt
    for better coverage of the 6 standard regulation categories.
    """
    from pydantic import BaseModel as _BM

    from app.modules.parsing.regulation_extractor import extract_regulations_regex

    # Load control rule categories from YAML (Phase 3 paradigm alignment)
    try:
        from app.modules.schema.encodings.dicts.rule_loader import get_rule_loader
        loader = get_rule_loader()
        control_rules_block = loader.format_control_rules_for_prompt()
    except Exception:
        control_rules_block = ""

    sections_text = _get_sections_text(state, "regulation", "protection")
    all_constraints: list[SpatialConstraint] = []

    # Step 1: deterministic regex extraction — convert dicts to typed
    matched, unmatched = extract_regulations_regex(sections_text)
    for m in matched:
        try:
            all_constraints.append(SpatialConstraint.model_validate(m))
        except Exception:
            # Fallback: set source_text at minimum
            all_constraints.append(SpatialConstraint(
                type="spatial_constraint",
                source_text=str(m.get("source_text", "")),
                article_ref=str(m.get("article_ref", "")),
            ))

    # Step 2: LLM fallback for unmatched lines
    if unmatched:
        logger.info("[PARSE:regulations] Regex=%d -> LLM fallback=%d lines",
                     len(matched), len(unmatched))
        try:
            class _RegFallbackResult(_BM):
                constraints: List[SpatialConstraint] = []

            llm = _get_llm(enable_thinking=True, thinking_budget=1000)
            unmatched_text = "\n".join(f"- {line}" for line in unmatched[:30])
            messages = [
                SystemMessage(content=(
                    "Extract SpatialConstraint from unmatched regulation text.\n"
                    "Classify each constraint into one of the standard categories:\n"
                    f"{control_rules_block}"
                )),
                HumanMessage(content=f"Unmatched rules:\n{unmatched_text}"),
            ]
            fb_result = await _format_structured(llm, _RegFallbackResult, messages)
            if fb_result:
                # Already typed SpatialConstraint instances — no model_dump()
                all_constraints.extend(fb_result.constraints)
        except Exception as e:
            logger.warning("[PARSE:regulations] LLM fallback failed: %s", e)

    logger.info("[PARSE:regulations] %d constraints (regex + LLM hybrid)", len(all_constraints))
    return {"raw_constraints": all_constraints}


# ── Node 2b: extract_tables ──────────────────────────────────────────


async def extract_tables_node(state: ParseAgentState) -> dict:
    """Extract structured data from table sections — schema-informed, zero LLM.

    Phase 4: Infers table schema from headers and maps rows to typed models
    (PlanningIndicatorTable, List[ZoneTarget], List[FacilityTarget]).
    Unmatched tables remain as raw dicts.
    """
    from app.modules.parsing.markdown_parser import parse_markdown_tables
    from app.modules.parsing.table_schema_inference import (
        infer_and_map_table,
        TableSchemaType,
    )

    table_sections = [s for s in state.section_map if s.has_table]
    all_rows = []
    typed_results: Dict[str, Any] = {}  # schema_type -> typed model(s)

    for section in table_sections:
        tables = parse_markdown_tables(section.content)
        for table in tables:
            headers = table.get("headers", [])
            rows = table.get("rows", [])

            # Try schema-informed extraction
            schema_type, typed = infer_and_map_table(headers, rows)

            if typed is not None:
                key = f"{schema_type.value}_{section.section_id}"
                # Merge with existing results of same type
                if key in typed_results:
                    existing = typed_results[key]
                    if isinstance(existing, list) and isinstance(typed, list):
                        existing.extend(typed)
                    elif hasattr(existing, "indicators") and hasattr(typed, "indicators"):
                        existing.indicators.extend(typed.indicators)
                else:
                    typed_results[key] = typed
                continue

            # Fallback: raw dict for unmatched tables
            for row in rows:
                if not row or all(c == "" for c in row):
                    continue
                row_dict = dict(zip(headers, row)) if headers else {"data": row}
                row_dict["_section_id"] = section.section_id
                row_dict["_section_type"] = section.section_type
                all_rows.append(row_dict)

    typed_count = sum(
        len(v.indicators) if hasattr(v, "indicators") else len(v) if isinstance(v, list) else 1
        for v in typed_results.values()
    )
    logger.info(
        "[PARSE:tables] Schema-informed: %d typed, %d raw rows (0 LLM)",
        typed_count, len(all_rows),
    )
    return {"raw_tables": {"rows": all_rows, "typed": typed_results}}
# ── Shared explore helper (Phase A — Think + Tools) ───────────────────


async def _explore_with_tools(
    state: ParseAgentState,
    node_name: str,
    section_types: tuple,
    explore_prompt: str,
    summary_prompt: str,
    draft_key: str,
    code_key: str,
    place_key: str,
    trace_key: str,
    initial_code_mappings: Dict[str, str] = None,
    initial_place_mappings: Dict[str, dict] = None,
) -> dict:
    """Shared Phase A: ReAct with tools -> forced summary -> draft.

    Args:
        node_name: Node identifier for logging (e.g. "explore_projects").
        section_types: Tuple of section_type strings to filter.
        explore_prompt: System prompt for the ReAct exploration phase.
        summary_prompt: System prompt for the forced summary phase.
        draft_key: State field name for the draft result (e.g. "draft_operations").
        code_key: State field name for code mappings (e.g. "code_mappings_projects").
        place_key: State field name for place mappings (e.g. "place_mappings_projects").
        initial_code_mappings: Seed mappings from prior state (targets reuse these).
        initial_place_mappings: Seed mappings from prior state.
    """
    node_traces: list = []

    llm = _get_llm(enable_thinking=True, thinking_budget=800)
    sections = [s for s in state.section_map if s.section_type in section_types]

    if not sections:
        logger.warning("[PARSE:%s] No relevant sections", node_name)
        return {draft_key: "", code_key: {}, place_key: {}, trace_key: []}

    sections_text = "\n\n---\n\n".join(s.content[:1500] for s in sections[:5])
    print(f"    [{node_name}] {len(sections)} sections merged -> {len(sections_text)} chars", flush=True)

    # Phase A1: ReAct with tools
    explore_llm = llm.bind_tools([lookup_code, resolve_place, query_village_kg])
    messages = [
        SystemMessage(content=explore_prompt),
        HumanMessage(content=sections_text[:5000]),
    ]

    code_mappings: Dict[str, str] = dict(initial_code_mappings or {})
    place_mappings: Dict[str, dict] = dict(initial_place_mappings or {})
    total_tool_calls = 0

    for _round in range(2):
        t0 = time.time()
        response = await explore_llm.ainvoke(messages)
        elapsed = time.time() - t0
        messages.append(response)

        thinking = _extract_thinking(response)
        resp_content = response.content if hasattr(response, "content") else ""
        tool_calls_raw = response.tool_calls if hasattr(response, "tool_calls") else []

        # Execute tool calls and collect results
        tool_results_list = []
        if tool_calls_raw:
            total_tool_calls += len(tool_calls_raw)
            print(f"    [{node_name}] tools round {_round+1}: {len(tool_calls_raw)} calls", flush=True)
            for tc in tool_calls_raw[:5]:
                result_str = await _execute_tool_call(tc.get("name", ""), tc.get("args", {}))
                messages.append(ToolMessage(content=str(result_str), tool_call_id=tc["id"]))
                _extract_mappings(result_str, code_mappings, place_mappings)
                tool_results_list.append({
                    "name": tc.get("name", ""),
                    "args": tc.get("args", {}),
                    "result": result_str[:2000],
                })

        # Log this ReAct round
        node_traces.append(_log_llm_call(
            node=node_name,
            phase=f"react_round_{_round+1}",
            system_msg=explore_prompt if _round == 0 else "",
            user_msg=sections_text[:5000] if _round == 0 else "(continuation with tool results)",
            response_content=resp_content,
            tool_calls=tool_calls_raw,
            elapsed=elapsed,
            codes=code_mappings,
            thinking_content=thinking,
            tool_results=tool_results_list,
        ))

        if not tool_calls_raw:
            break

    # Phase A2: Force summary WITHOUT tools
    code_list = "\n".join(f"  {n} -> {c}" for n, c in list(code_mappings.items())[:20])
    print(f"    [{node_name}] writing summary ({len(code_mappings)} codes)...", flush=True)

    summary_user_prompt = (
        f"Code mappings (MUST USE):\n{code_list or '(none)'}\n\n"
        f"Original text:\n{sections_text[:4000]}"
    )

    summary_llm = _get_llm(enable_thinking=True, thinking_budget=400)
    t0 = time.time()
    summary_resp = await summary_llm.ainvoke([
        SystemMessage(content=summary_prompt),
        HumanMessage(content=summary_user_prompt),
    ])
    summary_elapsed = time.time() - t0
    summary_thinking = _extract_thinking(summary_resp)

    draft = summary_resp.content if hasattr(summary_resp, "content") else ""
    if draft and len(draft) > 50:
        preview = draft[:200].replace("\n", " ")
        print(f"    [{node_name}] draft: {len(draft)} chars - {preview}...", flush=True)
    else:
        last_msg = messages[-1] if messages else None
        if last_msg and hasattr(last_msg, "content") and last_msg.content:
            draft = last_msg.content
        print(f"    [{node_name}] fallback draft: {len(draft)} chars", flush=True)

    # Log summary call
    node_traces.append(_log_llm_call(
        node=node_name,
        phase="summary",
        system_msg=summary_prompt,
        user_msg=summary_user_prompt,
        response_content=draft,
        tool_calls=[],
        elapsed=summary_elapsed,
        codes=code_mappings,
        draft_len=len(draft),
        thinking_content=summary_thinking,
    ))

    logger.info("[PARSE:%s] draft=%d chars, %d codes, %d places, %d tool calls",
                 node_name, len(draft), len(code_mappings), len(place_mappings), total_tool_calls)

    return {draft_key: draft, code_key: code_mappings, place_key: place_mappings, trace_key: node_traces}


# ── Node 2c: explore_projects (Phase A - Think + Tools) ────────────────


async def explore_projects_node(state: ParseAgentState) -> dict:
    """Phase A: Think + Explore -> tools -> forced summary -> draft."""
    return await _explore_with_tools(
        state,
        node_name="explore_projects",
        section_types=("project_table", "land_use_table", "facility_table", "infrastructure"),
        explore_prompt=(
            "You are a village plan project analyst.\n"
            "Step 1: Use lookup_code to query GHYTBM codes for ALL land_use_names in the text.\n"
            "Step 2: Use resolve_place to query GIS anchors for ALL place names.\n"
            "Step 3: Use query_village_kg for spatial context:\n"
            "  - query_village_kg('get_village_anchors') to find village coordinates\n"
            "  - query_village_kg('get_facilities_by_type') for existing facility locations\n"
            "  - query_village_kg('get_road_network') for road connectivity\n"
            "  - query_village_kg('get_protected_parcels_detail') for constraint zones\n"
            "  - query_village_kg('get_parcels_near_point', min_lon=..., max_lon=..., min_lat=..., max_lat=...) for nearby parcels\n"
            "Call tools for ALL entities, then STOP when done."
        ),
        summary_prompt=(
            "You are a village plan project summarizer.\n"
            "Based on the tool results above, write a COMPREHENSIVE project list.\n"
            "EVERY project must be on its own line in this format:\n"
            "  [action] project_name | code=XXXX | area=Xsqm | location=... | source=\"...\"\n"
            "Where XXXX is the 4-digit GHYTBM number from lookup_code (e.g. 2121, 1100, 2124).\n"
            "Do NOT write 'GHYTBM=' - just the 4-digit number. Do NOT guess. Write at least 1500 characters."
        ),
        draft_key="draft_operations",
        code_key="code_mappings_projects",
        place_key="place_mappings_projects",
        trace_key="llm_trace_projects",
    )


# ── Node 2c2: format_projects (Phase B — json_schema) ──────────────────


# ── Post-format fixers: auto-correct codes + fill anchors (no LLM) ─────


def _extract_literal_values(model_cls, field_name: str) -> str:
    """Extract allowed Literal values from a Pydantic model field as a comma string.

    Returns empty string if the field is not a Literal type.
    """
    import typing as _typing
    try:
        field = model_cls.model_fields.get(field_name)
        if field is None:
            return ""
        annotation = field.annotation
        args = _typing.get_args(annotation)
        # Literal[...] returns the literal values; Optional[Literal[...]] also works
        literals = [str(a) for a in args if a is not type(None)]
        return ", ".join(literals)
    except Exception:
        return ""


def _schema_constraints_block() -> str:
    """Build a Schema Constraints block listing valid Literal enum values.

    Injects the allowed values for SpatialOperation/SpatialConstraint/ZoneTarget
    fields so the LLM produces schema-compliant output in the free-text draft phase.
    """
    from app.agent.gis.parse.state import (
        SpatialOperation, SpatialConstraint, ZoneTarget, FacilityTarget,
    )
    lines = ["[Schema Constraints — output MUST use ONLY these values]"]

    action_vals = _extract_literal_values(SpatialOperation, "action")
    conf_vals = _extract_literal_values(SpatialOperation, "confidence_level")
    if action_vals:
        lines.append(f"- SpatialOperation.action: [{action_vals}]")
    if conf_vals:
        lines.append(f"- SpatialOperation.confidence_level: [{conf_vals}]")

    ctype_vals = _extract_literal_values(SpatialConstraint, "type")
    prio_vals = _extract_literal_values(SpatialConstraint, "priority")
    if ctype_vals:
        lines.append(f"- SpatialConstraint.type: [{ctype_vals}]")
    if prio_vals:
        lines.append(f"- SpatialConstraint.priority: [{prio_vals}]")

    density_vals = _extract_literal_values(ZoneTarget, "density")
    if density_vals:
        lines.append(f"- ZoneTarget.density: [{density_vals}]")
        lines.append("- ZoneTarget.vne_code: must start with V, N, or E (e.g. V11, V21, E1)")

    status_vals = _extract_literal_values(FacilityTarget, "status")
    if status_vals:
        lines.append(f"- FacilityTarget.status: [{status_vals}]")

    lines.append("")
    return "\n".join(lines)


def _auto_correct_code(
    ops: List[SpatialOperation],
    code_mappings: dict,
) -> List[SpatialOperation]:
    """Post-format: correct invalid GHYTBM codes from deterministic mappings.

    LLM sometimes outputs wrong codes even with the mapping table.
    This runs pure-Python correction before validate_and_merge catches errors.
    """
    if not ops:
        return ops
    try:
        from app.modules.schema import GHYTBM_TO_GHYTMC
        valid_codes = set(GHYTBM_TO_GHYTMC.keys())
    except ImportError:
        logger.debug("[auto_correct] GHYTBM_TO_GHYTMC not available")
        return ops

    corrected = 0
    for op in ops:
        code = op.land_use_code or ""
        if code and code not in valid_codes:
            # Try to match project_name against code_mappings (name -> code)
            best_code = ""
            pname = (op.project_name or "").strip()
            if pname:
                for name, mapped_code in code_mappings.items():
                    if mapped_code and mapped_code in valid_codes:
                        if name in pname or pname in name:
                            best_code = mapped_code
                            break
            if best_code:
                op.land_use_code = best_code
                corrected += 1
            else:
                logger.debug("[auto_correct] no mapping for code=%s project=%s", code, pname[:30])

    if corrected:
        logger.info("[PARSE:auto_correct] Fixed %d GHYTBM codes", corrected)
    return ops


def _auto_fill_spatial_anchor(
    ops: List[SpatialOperation],
    place_mappings: dict,
) -> List[SpatialOperation]:
    """Post-format: auto-fill spatial_anchor from deterministic place mappings.

    LLM often leaves spatial_anchor empty or with low confidence.
    Fill from resolve_place tool results (place_mappings).
    """
    if not ops:
        return ops

    filled = 0
    for op in ops:
        anchor = op.spatial_anchor
        if anchor is not None and anchor.confidence >= 0.3:
            continue  # Already has a good anchor

        # Match against place_mappings (place_name -> {village_name, parcel_ids, confidence})
        search_text = f"{(op.project_name or '')} {(op.location_desc or '')}"
        for place_name, info in place_mappings.items():
            if place_name in search_text:
                op.spatial_anchor = SpatialAnchor(
                    reference=place_name,
                    candidate_parcels=list(info.get("parcel_ids", [])),
                    confidence=float(info.get("confidence", 0.5)),
                    resolution_status="anchored",
                )
                filled += 1
                break

    if filled:
        logger.info("[PARSE:auto_fill] Filled %d spatial anchors", filled)
    return ops


async def format_projects_node(state: ParseAgentState) -> dict:
    """Phase B: Format draft into structured Pydantic — NO thinking, NO tools.

    thinking=OFF, json_schema=ON, tools=OFF
    Pure formatting task — guaranteed compatible.
    """
    from pydantic import BaseModel as _BM

    class ProjectExtractionResult(_BM):
        operations: List[SpatialOperation] = []

    if not state.draft_operations:
        logger.warning("[PARSE:format_projects] No draft — skipping")
        return {"raw_operations": []}

    # Build mapping tables for format prompt
    code_table = "\n".join(f"  {name} -> GHYTBM={code}" for name, code in state.code_mappings_projects.items())
    place_table = "\n".join(
        f"  {name} -> village={info.get('village_name', '')}, parcels={str(info.get('parcel_ids', []))[:80]}"
        for name, info in state.place_mappings_projects.items()
    )

    format_llm = _get_llm(enable_thinking=False)
    schema_block = _schema_constraints_block()
    messages = [
        SystemMessage(content=(
            "You are a JSON formatter. Convert the following project summary into SpatialOperation objects.\n"
            "STRICTLY use the code/place mappings provided — do NOT invent codes.\n"
            "Each operation must have: action, project_name, land_use_code (from mapping),\n"
            "area_sqm, location_desc, source_text.\n\n"
            f"{schema_block}"
        )),
        HumanMessage(content=(
            f"[Code Mapping Table — MUST USE]\n{code_table or '(none)'}\n\n"
            f"[Place Mapping Table — MUST USE]\n{place_table or '(none)'}\n\n"
            f"[Project Draft]\n{state.draft_operations}"
        )),
    ]

    result = await _format_structured(format_llm, ProjectExtractionResult, messages)
    if result is not None:
        # result.operations are already List[SpatialOperation] — store typed, not dicts
        ops = list(result.operations)
        logger.info("[PARSE:format_projects] %d operations", len(ops))

        # Phase 5 (P2): post-format auto-correction (no LLM)
        ops = _auto_correct_code(ops, dict(state.code_mappings_projects))
        ops = _auto_fill_spatial_anchor(ops, dict(state.place_mappings_projects))

        return {"raw_operations": ops}
    return {"raw_operations": []}
# ── Node 2d: explore_targets (Phase A - Think + Tools) ────────────────


async def explore_targets_node(state: ParseAgentState) -> dict:
    """Phase A: Think + Explore -> tools -> forced summary -> draft."""
    # Inject YAML planning targets into prompt (Phase 3 paradigm alignment)
    try:
        from app.modules.schema.encodings.dicts.rule_loader import get_rule_loader
        loader = get_rule_loader()
        targets_block = loader.format_targets_for_prompt()
        categories_block = loader.format_categories_for_prompt()
        zone_mapping_block = loader.format_zone_mapping_for_prompt()
        yaml_context = f"\n{targets_block}\n{categories_block}\n{zone_mapping_block}"
    except Exception:
        yaml_context = ""

    return await _explore_with_tools(
        state,
        node_name="explore_targets",
        section_types=("target", "indicator_table", "spatial_layout"),
        explore_prompt=(
            "You are a village plan target analyst.\n"
            "Step 1: Use lookup_code to get GHYTBM codes for ALL land_use names.\n"
            "Step 2: Use query_village_kg to understand spatial distribution:\n"
            "  - query_village_kg('count_by_zone_type') for land distribution by zone\n"
            "  - query_village_kg('count_by_vne') for VNE classification summary\n"
            "  - query_village_kg('get_three_zones') for 三区（生态/农业/建设）summary\n"
            "  - query_village_kg('get_three_lines') for 三线 boundary information\n"
            "  - query_village_kg('get_village_anchors') for natural village coordinates\n"
            "  - query_village_kg('get_designated_zones') for zone mapping\n"
            "Step 3: Use resolve_place for ANY location names mentioned in the text.\n"
            "Call ALL relevant tools, then STOP when done."
            f"{yaml_context}"
        ),
        summary_prompt=(
            "You are a village plan target summarizer.\n"
            "Based on the tool results above, write a COMPREHENSIVE target summary.\n"
            "Include EVERY zone_target (land_use + GHYTBM code + area_ratio),\n"
            "EVERY facility (type/status/location), and EVERY development axis.\n"
            "Use codes from tool results. Do NOT guess. Write at least 1500 characters."
        ),
        draft_key="draft_targets",
        code_key="code_mappings_targets",
        place_key="place_mappings_targets",
        trace_key="llm_trace_targets",
        initial_code_mappings=dict(state.code_mappings_targets),
        initial_place_mappings=dict(state.place_mappings_targets),
    )


# ── Node 2d2: format_targets (Phase B — json_schema) ──────────────────


async def format_targets_node(state: ParseAgentState) -> dict:
    """Phase B: Format targets draft into SpatialPlanningIntent — NO thinking."""
    if not state.draft_targets:
        logger.warning("[PARSE:format_targets] No draft — skipping")
        return {"raw_targets": SpatialPlanningIntent()}

    code_table = "\n".join(f"  {name} -> GHYTBM={code}" for name, code in state.code_mappings_targets.items())

    # Load YAML-driven structural constraints (Phase 3 gap fix)
    try:
        from app.modules.schema.encodings.dicts.rule_loader import get_rule_loader
        loader = get_rule_loader()
        mandatory_block = loader.format_mandatory_indicators_for_prompt()
        valid_lu_block = loader.format_valid_land_uses_for_prompt()
        vne_block = loader.format_vne_mapping_for_prompt()
    except Exception:
        mandatory_block = valid_lu_block = vne_block = ""

    schema_block = _schema_constraints_block()
    format_llm = _get_llm(enable_thinking=False)
    messages = [
        SystemMessage(content=(
            "You are a JSON formatter. Convert the following target summary into SpatialPlanningIntent.\n"
            "STRICTLY use the code mapping table for dlbm fields — do NOT invent codes.\n"
            "zone_targets.area_ratio values must sum to ~1.0.\n\n"
            f"{schema_block}\n"
            f"{mandatory_block}\n"
            f"{valid_lu_block}\n"
            f"{vne_block}"
        )),
        HumanMessage(content=(
            f"[Code Mapping Table — MUST USE]\n{code_table or '(none)'}\n\n"
            f"[Target Draft]\n{state.draft_targets}"
        )),
    ]

    result = await _format_structured(format_llm, SpatialPlanningIntent, messages)
    if result is not None:
        result.village_name = state.village_name
        logger.info("[PARSE:format_targets] %d zones, %d facilities, %d axes",
                     len(result.zone_targets), len(result.facilities), len(result.development_axes))
        # Store typed SpatialPlanningIntent, not model_dump()
        return {"raw_targets": result}
    return {"raw_targets": SpatialPlanningIntent()}


# ── Typed table merge helper (Phase 4) ──────────────────────────────────


def _merge_typed_tables_into_intent(
    intent: SpatialPlanningIntent,
    typed_tables: Dict[str, Any],
) -> SpatialPlanningIntent:
    """Merge typed table extraction results into SpatialPlanningIntent.

    Tables extracted with schema inference (PlanningIndicatorTable, List[ZoneTarget],
    List[FacilityTarget]) are merged into the LLM-derived intent, filling gaps
    that the LLM may have missed.

    Priority: LLM-derived values are preserved if present; table values fill gaps.
    """
    from app.agent.gis.parse.state import (
        PlanningIndicatorTable,
        ZoneTarget,
        FacilityTarget,
    )

    for key, value in typed_tables.items():
        if value is None:
            continue

        # PlanningIndicatorTable → fill intent.indicator_table
        if isinstance(value, PlanningIndicatorTable):
            if intent.indicator_table is None:
                intent.indicator_table = value
            else:
                # Merge: add indicators not already present (by code)
                existing_codes = {ind.code for ind in intent.indicator_table.indicators}
                for ind in value.indicators:
                    if ind.code and ind.code not in existing_codes:
                        intent.indicator_table.indicators.append(ind)

        # List[ZoneTarget] → supplement intent.zone_targets
        elif isinstance(value, list) and value and isinstance(value[0], ZoneTarget):
            existing_lu = {zt.land_use for zt in intent.zone_targets if zt.land_use}
            for zt in value:
                if zt.land_use and zt.land_use not in existing_lu:
                    intent.zone_targets.append(zt)
                    existing_lu.add(zt.land_use)

        # List[FacilityTarget] → supplement intent.facilities
        elif isinstance(value, list) and value and isinstance(value[0], FacilityTarget):
            existing_types = {f.type for f in intent.facilities if f.type}
            for ft in value:
                if ft.type and ft.type not in existing_types:
                    intent.facilities.append(ft)
                    existing_types.add(ft.type)

    return intent


# ── Node 3: validate_and_merge ────────────────────────────────────────


async def validate_and_merge_node(state: ParseAgentState) -> dict:
    """Validate extraction results and merge into final output."""
    from pydantic import BaseModel as _BM

    from app.modules.prompts.parse_prompts import (
        VALIDATE_AND_MERGE_PROMPT,
        format_spatial_context_for_prompt,
    )

    new_round = state.parse_round + 1

    # Check if all extractions are empty
    # typed: SpatialPlanningIntent is always truthy, check content instead
    has_any_data = (
        len(state.raw_operations) > 0
        or len(state.raw_constraints) > 0
        or bool(state.raw_targets.zone_targets)
        or bool(state.raw_targets.facilities)
        or bool(state.raw_targets.development_axes)
    )

    if not has_any_data:
        logger.warning("[PARSE:validate] All extractions empty — fallback to spatial context")
        constraints_from_ctx: List[SpatialConstraint] = []
        for c in state.spatial_context.constraint_summary:
            constraints_from_ctx.append(SpatialConstraint(
                type="spatial_constraint",
                priority="mandatory",
                source_text=f"{c.zone_type}: {c.rule}",
                spatial_rule=SpatialRule(
                    operation="contained_by",
                    subject="construction",
                    object=c.zone_type,
                ),
            ))
        return {
            "operation_sequence": [],
            "constraint_set": constraints_from_ctx,
            "planning_intent": SpatialPlanningIntent(village_name=state.village_name),
            "validation_errors": ["All LLM extractions failed"],
            "is_valid": False,
            "parse_round": new_round,
        }

    class MergedResult(_BM):
        operation_sequence: List[SpatialOperation] = []
        constraint_set: List[SpatialConstraint] = []
        planning_intent: SpatialPlanningIntent = SpatialPlanningIntent()
        validation_errors: List[str] = []
        is_valid: bool = False

    # ── Deterministic validations (4 checks — no LLM) ──
    det_errors: List[str] = []

    # 1. Area ratio sum check
    zone_targets = state.raw_targets.zone_targets
    if zone_targets:
        total = sum(zt.area_ratio for zt in zone_targets)
        if abs(total - 1.0) > 0.05 and total > 0:
            det_errors.append(f"Area ratios sum to {total:.1%} (expected ~100%)")

    # 2. Encoding validity
    try:
        from app.modules.schema import GHYTBM_TO_GHYTMC
        valid_ghytbms = set(GHYTBM_TO_GHYTMC.keys())
        for op in state.raw_operations:
            code = op.land_use_code or ""
            if code and code not in valid_ghytbms:
                det_errors.append(f"Invalid GHYTBM code: {code}")
    except ImportError:
        pass

    # 3. Low-confidence spatial anchors
    for op in state.raw_operations:
        anchor = op.spatial_anchor
        if anchor is not None and anchor.confidence < 0.3:
            det_errors.append(f"Low anchor confidence for {op.project_name or '?'}")

    # 4. Required source_text field
    for i, op in enumerate(state.raw_operations):
        if not op.source_text:
            det_errors.append(f"Operation #{i + 1} missing source_text")
    for i, c in enumerate(state.raw_constraints):
        if not c.source_text:
            det_errors.append(f"Constraint #{i + 1} missing source_text")

    # ── LLM validation (thinking OFF — no reasoning needed) ──
    format_llm = _get_llm(enable_thinking=False)
    spatial_ctx_text = format_spatial_context_for_prompt(state.spatial_context, detail_level="standard")

    # No more [:3000] truncation — format phase already produced compact JSON
    operations_json = json.dumps(
        [o.model_dump() for o in state.raw_operations], ensure_ascii=False, default=str
    )
    constraints_json = json.dumps(
        [c.model_dump() for c in state.raw_constraints], ensure_ascii=False, default=str
    )
    intent_json = json.dumps(
        state.raw_targets.model_dump(), ensure_ascii=False, default=str
    )

    prompt = VALIDATE_AND_MERGE_PROMPT.format(
        spatial_context=spatial_ctx_text,
        operation_count=len(state.raw_operations),
        operations_json=operations_json,
        constraint_count=len(state.raw_constraints),
        constraints_json=constraints_json,
        intent_json=intent_json,
    )

    messages = [
        SystemMessage(content="Validate and merge village plan extraction results. Output JSON."),
        HumanMessage(content=prompt),
    ]

    result = await _format_structured(format_llm, MergedResult, messages)
    if result is not None:
        all_errors = det_errors + list(result.validation_errors)

        # Phase 4: Merge typed table extractions into planning_intent
        merged_intent = result.planning_intent
        typed_tables = (state.raw_tables or {}).get("typed", {})
        if typed_tables:
            merged_intent = _merge_typed_tables_into_intent(merged_intent, typed_tables)

        logger.info(
            "[PARSE:validate] Merged: %d ops, %d constraints, valid=%s, errors=%d",
            len(result.operation_sequence), len(result.constraint_set),
            result.is_valid, len(all_errors),
        )
        return {
            "operation_sequence": list(result.operation_sequence),
            "constraint_set": list(result.constraint_set),
            "planning_intent": merged_intent,
            "validation_errors": all_errors,
            "is_valid": result.is_valid and len(det_errors) == 0,
            "parse_round": new_round,
        }

    # Fallback
    logger.warning("[PARSE:validate] Merge returned None — using raw results")
    return {
        "operation_sequence": state.raw_operations,
        "constraint_set": state.raw_constraints,
        "planning_intent": state.raw_targets,
        "validation_errors": det_errors + ["Merge validation failed"],
        "is_valid": False,
        "parse_round": new_round,
    }


# ── Routing: should_retry ─────────────────────────────────────────────


def should_retry(state: ParseAgentState) -> str:
    """Determine if PARSE should retry validation or end."""
    if state.is_valid:
        return "end"
    if state.parse_round >= MAX_PARSE_ROUNDS:
        return "end"
    if not state.validation_errors:
        return "end"
    if (
        not state.raw_operations
        and not state.raw_constraints
        and not state.raw_targets.zone_targets
        and not state.raw_targets.facilities
    ):
        return "end"
    logger.info("[PARSE:retry] Round %d — retrying", state.parse_round)
    return "retry"


# ── Graph builder ──────────────────────────────────────────────────────


def build_parse_agent_graph():
    """Build the PARSE Agent StateGraph (Think-Then-Format pattern).

    Returns a compiled LangGraph graph that takes ParseAgentState as input
    and produces operation_sequence + constraint_set + planning_intent.
    """
    builder = StateGraph(ParseAgentState)

    # Add nodes
    builder.add_node("classify_sections", classify_sections_node)
    builder.add_node("explore_projects", explore_projects_node)
    builder.add_node("format_projects", format_projects_node)
    builder.add_node("explore_targets", explore_targets_node)
    builder.add_node("format_targets", format_targets_node)
    builder.add_node("extract_regulations", extract_regulations_node)
    builder.add_node("extract_tables", extract_tables_node)
    builder.add_node("validate_and_merge", validate_and_merge_node)

    # Entry point
    builder.add_edge(START, "classify_sections")

    # Fan-out from classify_sections
    builder.add_conditional_edges("classify_sections", route_by_section)

    # Explore -> Format chains (Think-Then-Format)
    builder.add_edge("explore_projects", "format_projects")
    builder.add_edge("explore_targets", "format_targets")

    # All converge to validate_and_merge
    builder.add_edge("format_projects", "validate_and_merge")
    builder.add_edge("format_targets", "validate_and_merge")
    builder.add_edge("extract_regulations", "validate_and_merge")
    builder.add_edge("extract_tables", "validate_and_merge")

    # Retry loop or end
    builder.add_conditional_edges(
        "validate_and_merge",
        should_retry,
        {"retry": "classify_sections", "end": END},
    )

    graph = builder.compile()
    logger.info("[PARSE Agent] Graph compiled (Think-Then-Format v8)")
    return graph


__all__ = ["build_parse_agent_graph", "query_village_kg", "lookup_code", "resolve_place"]
