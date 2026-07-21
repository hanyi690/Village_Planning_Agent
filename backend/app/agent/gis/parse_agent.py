"""PARSE Agent subgraph — semi-structured ReAct for spatially-aware text parsing.

Architecture (LangGraph StateGraph):
  START -> classify_sections -> route_by_section (conditional edges fan-out)
     -> [extract_regulations | extract_tables | extract_projects | extract_targets]
     -> validate_and_merge -> should_retry? -> END or retry

Key design:
  - Deterministic skeleton ensures step completeness
  - LLM nodes use three-stage structured output (json_schema -> manual -> flash repair)
  - qwen3.7-plus supports thinking + json_schema simultaneously (verified 2026-07-21)
  - Conditional edges fan-out to extract nodes (all see full state)
  - SpatialContext injection with detail_level (minimal/standard/full) to control token budget
  - Max 2 retry rounds for validation failures

Structured output strategy (3 stages):
  Stage 1: llm.with_structured_output(method="json_schema") — qwen3.7-plus
           natively supports thinking + json_schema simultaneously (verified).
           json_schema guarantees both valid JSON AND schema conformance.
  Stage 2: Raw invoke + manual JSON extraction + Pydantic validation
  Stage 3: qwen3.5-flash JSON repair (method="json_mode", no thinking)

Token budget management:
  - max_tokens NOT set: avoids JSON truncation in thinking mode
    (DashScope docs: "Do not set max_tokens when structured output is enabled")
  - thinking_budget=2000: caps thinking tokens (default=65536 for qwen3.7-plus)
  - detail_level: spatial_context injection scaled per node need
    minimal (~500 chars) for classify, standard (~4KB) for extract, full (~12KB) for validate

References:
  [1] LangGraph StateGraph with Pydantic BaseModel state
  [2] LangGraph conditional edges for fan-out routing
  [3] https://help.aliyun.com/zh/model-studio/qwen-structured-output
  [4] https://docs.qwencloud.com/developer-guides/text-generation/structured-output

Note on routing:
  Using conditional_edges (returning list of node names) instead of Send API,
  so all extract nodes receive the full ParseAgentState — this gives them
  access to spatial_context, planning_text, and section_map without
  passing per-section sub-state.
"""

from __future__ import annotations

import json
import warnings

# Suppress Pydantic serializer warnings from with_structured_output(include_raw=True)
# These fire when the model returns parsed Pydantic instances inside dicts
warnings.filterwarnings("ignore", message="Pydantic serializer")
from typing import Any, Dict, List, Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END, START

from app.agent.gis.schema.parse_state import (
    ParseAgentState,
    SectionClassificationResult,
    SectionInfo,
    SpatialConstraint,
    SpatialOperation,
    SpatialPlanningIntent,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

MAX_PARSE_ROUNDS = 2

# Global KG instance — set by parse_planning_text before running the graph
_kg_instance: Any = None

# Global Gazetteer instance — set by parse_planning_text before running the graph
_gazetteer: Any = None


def set_kg_instance(kg) -> None:
    """Set the global KG instance for PARSE Agent tool queries."""
    global _kg_instance
    _kg_instance = kg


async def _execute_tool_call(tool_name: str, tool_args: dict) -> str:
    """Execute a tool call and return JSON string. Delegates by tool name.

    Supports:
      - query_village_kg / find_village_by_name → KG SPARQL query
      - lookup_code → DictionaryCenter code lookup
    """
    import json as _json

    # KG queries
    if tool_name in ("query_village_kg", "find_village_by_name"):
        global _kg_instance
        if _kg_instance is None:
            return _json.dumps({"error": "KG not initialized"})
        from app.modules.gis.kg.query import query_kg
        try:
            template_name = tool_args.get("template_name", "")
            params = {k: v for k, v in tool_args.items() if k != "template_name"}
            results = query_kg(_kg_instance, template_name, **params)
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
            from app.tools.gis.parse_tools import lookup_land_use_code
            result = lookup_land_use_code.invoke({"land_use_name": land_use_name})
            return _json.dumps(result, ensure_ascii=False, default=str)
        except Exception as e:
            return _json.dumps({"error": str(e)}, ensure_ascii=False)

    # Place name → VillageGroup matching
    if tool_name == "resolve_place":
        place_name = tool_args.get("place_name", "")
        if not place_name:
            return _json.dumps({"error": "missing place_name"})
        global _gazetteer
        if _gazetteer is None:
            return _json.dumps({"error": "Gazetteer not initialized"})
        try:
            result = _gazetteer.resolve(place_name)
            return _json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return _json.dumps({"error": str(e)}, ensure_ascii=False)

    return _json.dumps({"error": f"Unknown tool: {tool_name}"}, ensure_ascii=False)


# KG query tool — bound to extract nodes for on-demand spatial queries
from langchain_core.tools import tool as _langchain_tool


@_langchain_tool
def query_village_kg(template_name: str, **params) -> str:
    """Query village planning knowledge graph for spatial information.

    Use this to check constraints (construction caps, farmland minimums),
    count parcels by zone type, query zone restrictions, get land-use
    distribution, find adjacent parcels, and look up indicator values.

    Available templates: get_constraints, get_constraint_by_field,
    get_parcels_by_dlbm, get_parcels_by_zone_type, count_by_zone_type,
    get_zone_restrictions, get_indicators, get_adjacent_parcels,
    get_all_projects, get_designated_zones, count_entity_types,
    get_facility_serve_areas, get_parcels_by_facility,
    get_regulation_impacts, get_road_network, get_water_bodies,
    get_project_indicators, check_protected_parcels.

    Args:
        template_name: SPARQL template to query (see list above)
        **params: Optional filter params (dlbm, zone_type, field_name, etc.)
    """
    return "Tool called — execution handled by agent loop."


@_langchain_tool
def lookup_code(land_use_name: str) -> str:
    """查询土地利用名称→标准编码。输入中文名称如'宅基地'，返回 GHYTBM/DLBM/zone_type。

    示例: lookup_code('经营性建设用地') → {"ghytbm":"2124","zone_type":"产业用地"}
    不要自己猜编码，使用此工具查询。
    """
    import json as _json
    try:
        from app.tools.gis.parse_tools import lookup_land_use_code
        result = lookup_land_use_code.invoke({"land_use_name": land_use_name})
        return _json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return _json.dumps({"error": str(e), "land_use_name": land_use_name}, ensure_ascii=False)


@_langchain_tool
def resolve_place(place_name: str) -> str:
    """地名→GIS锚点查询。输入中文地名（如'园寨''田坑'社前'），返回最近VillageGroup+地块列表。

    示例: resolve_place('园寨') → {village_name:'VillageGroup_1', parcel_ids:[...], confidence:0.8, method:'geocode'}
    用于将规划文本中的自然村名映射到GIS数据中的地块锚点。不要自己猜地块BSM。
    """
    import json as _json
    global _gazetteer
    if _gazetteer is None:
        return _json.dumps({"error": "Gazetteer not initialized"}, ensure_ascii=False)
    try:
        result = _gazetteer.resolve(place_name)
        return _json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return _json.dumps({"error": str(e), "name": place_name}, ensure_ascii=False)


async def _invoke_structured(
    llm, schema_cls, messages: list,
    tools: Optional[list] = None,
    kg_executor: Optional[callable] = None,
    max_tool_rounds: int = 3,
) -> object | None:
    """Three-stage structured output with optional KG tool-calling ReAct loop.

    Stage 1: json_schema with thinking + optional tools
             qwen3.7-plus supports thinking + json_schema + tools (verified).
             If tools provided, runs ReAct loop: LLM calls tool → execute → re-invoke.
    Stage 2: Raw invoke + manual JSON extraction + Pydantic validation
    Stage 3: qwen3.5-flash JSON repair (method="json_mode", no thinking)

    Args:
        llm: ChatOpenAI instance with thinking enabled
        schema_cls: Pydantic model for structured output
        messages: List of LangChain messages
        tools: Optional list of LangChain tools for KG queries
        kg_executor: Optional function to execute tool calls (needed for ReAct loop)
        max_tool_rounds: Max ReAct loop iterations (default 3)

    Ref: https://help.aliyun.com/zh/model-studio/qwen-structured-output
    Ref: https://docs.qwencloud.com/developer-guides/text-generation/structured-output
    """
    raw = None
    schema_name = schema_cls.__name__
    has_tools = bool(tools)

    # Stage 1: json_schema with thinking + optional tools
    label = f"⏳ {schema_name} (json_schema{' + tools' if has_tools else ''})"
    print(f"    {label}", flush=True)
    try:
        kwargs = {"method": "json_schema"}
        if has_tools:
            kwargs["tools"] = tools
            kwargs["strict"] = True
            kwargs["include_raw"] = True

        structured_llm = llm.with_structured_output(schema_cls, **kwargs)
        result = await structured_llm.ainvoke(messages)

        # Handle include_raw result (tools mode)
        if has_tools and isinstance(result, dict):
            raw_msg = result.get("raw")
            parsed = result.get("parsed")

            # ReAct loop: LLM called a tool → execute → feed back → re-invoke
            tool_round = 0
            while (tool_round < max_tool_rounds
                   and raw_msg
                   and hasattr(raw_msg, "tool_calls")
                   and raw_msg.tool_calls
                   and parsed is None):
                tool_round += 1
                print(f"    🔧 [PARSE] ReAct round {tool_round}: {len(raw_msg.tool_calls)} tool call(s)", flush=True)

                # Execute tool calls
                from langchain_core.messages import AIMessage, ToolMessage
                messages.append(raw_msg)  # Append assistant message with tool_calls
                for tc in raw_msg.tool_calls[:5]:  # Limit to 5 parallel calls
                    tool_name = tc.get("name", "")
                    tool_args = tc.get("args", {})
                    print(f"      → {tool_name}({str(tool_args)[:80]})", flush=True)
                    try:
                        if kg_executor:
                            tool_result = await kg_executor(tool_name, tool_args)
                        else:
                            tool_result = f"Tool {tool_name} not available (no executor)"
                        messages.append(ToolMessage(content=str(tool_result), tool_call_id=tc["id"]))
                    except Exception as te:
                        logger.warning("[PARSE] Tool call failed: %s: %s", tool_name, te)
                        messages.append(ToolMessage(
                            content=f"Error: {te}", tool_call_id=tc["id"]
                        ))

                # Re-invoke with tool results
                result = await structured_llm.ainvoke(messages)
                raw_msg = result.get("raw") if isinstance(result, dict) else None
                parsed = result.get("parsed") if isinstance(result, dict) else result

            if parsed is not None:
                if tool_round:
                    print(f"    ✅ {schema_name}: kg tools ×{tool_round}", flush=True)
                else:
                    print(f"    ✅ {schema_name}", flush=True)
                return parsed
            elif tool_round >= max_tool_rounds:
                logger.warning("[PARSE] ReAct loop exceeded max rounds (%d)", max_tool_rounds)
                raw = raw_msg.content if raw_msg and hasattr(raw_msg, "content") else None
            else:
                raw = raw_msg.content if raw_msg and hasattr(raw_msg, "content") else None
        elif not has_tools and result is not None:
            print(f"    ✅ {schema_name}", flush=True)
            return result
    except Exception as e:
        print(f"    ⚠️  S1→S2 {schema_name}: {e!s:.80s}", flush=True)

    # Stage 2: Raw invoke + manual JSON parse
    print(f"    ⏳ {schema_name} (manual retry)", flush=True)
    try:
        from langchain_core.messages import AIMessage
        response = await llm.ainvoke(messages)
        if isinstance(response, AIMessage):
            raw = response.content
        else:
            raw = str(response)

        parsed = _extract_and_parse_json(raw)
        if parsed is not None:
            if isinstance(parsed, list):
                parsed = _wrap_list_as_object(parsed, schema_cls)
            print(f"    ✅ {schema_name} (manual)", flush=True)
            return schema_cls.model_validate(parsed)
    except Exception as e:
        print(f"    ⚠️  S2→S3 {schema_name}: {e!s:.80s}", flush=True)

    # Stage 3: Flash repair
    if raw:
        print(f"    ⏳ {schema_name} (flash repair)", flush=True)
        try:
            fast_llm = _get_fast_llm()
            repair_messages = [
                SystemMessage(
                    content="你是 JSON 格式修复专家。将以下文本修复为有效 JSON。仅输出 JSON。"
                ),
                HumanMessage(content=raw[:4000]),
            ]
            structured_fast = fast_llm.with_structured_output(
                schema_cls, method="json_mode"
            )
            result = await structured_fast.ainvoke(repair_messages)
            if result is not None:
                print(f"    ✅ {schema_name} (flash)", flush=True)
                return result
        except Exception as e:
            print(f"    ❌ S3 {schema_name}: {e!s:.80s}", flush=True)

    print(f"    ❌ {schema_name}: all failed", flush=True)
    logger.warning("[PARSE] All 3 stages failed for %s", schema_cls.__name__)
    return None


def _extract_and_parse_json(text: str) -> object | None:
    """Extract and parse JSON from LLM response text.

    Handles: markdown code fences, mixed prose+JSON, nested braces/brackets.
    """
    import re

    json_str = text
    # Strip markdown code fences
    json_str = re.sub(r'^```(?:json)?\s*', '', json_str, flags=re.MULTILINE)
    json_str = re.sub(r'\s*```$', '', json_str, flags=re.MULTILINE)

    # Find first { or [
    obj_start = json_str.find('{')
    arr_start = json_str.find('[')

    if obj_start == -1 and arr_start == -1:
        return None

    # Try parsing as object first
    if obj_start != -1 and (arr_start == -1 or obj_start < arr_start):
        end = _find_matching_brace(json_str, obj_start, '{', '}')
        if end is not None:
            candidate = json_str[obj_start:end]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
    else:
        end = _find_matching_brace(json_str, arr_start, '[', ']')
        if end is not None:
            candidate = json_str[arr_start:end]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

    return None


def _find_matching_brace(text: str, start: int, open_char: str, close_char: str) -> int | None:
    """Find the position after the matching closing brace/bracket."""
    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return i + 1
    return None


def _wrap_list_as_object(parsed: list, schema_cls) -> dict:
    """Wrap a bare list into the schema's first list-type field.

    E.g. LLM returns [{...}, {...}] instead of {"rows": [{...}, {...}]}
    """
    for fname, finfo in schema_cls.model_fields.items():
        ann = finfo.annotation
        if hasattr(ann, '__origin__') and ann.__origin__ is list:
            return {fname: parsed}
    # Fallback: wrap under generic key
    return {"items": parsed}


def _get_llm(enable_thinking: bool = True, thinking_budget: int = 2000):
    """Get LLM instance with thinking enabled by default.

    Uses create_llm() factory to ensure proper api_key, base_url,
    request_timeout (180s), and streaming=True for token-level events.

    Key DashScope constraints (verified by testing 2026-07-21):
    - max_tokens MUST be > thinking_budget (DashScope requirement).
      Set to 32768 (32K) because DashScope treats max_tokens as the TOTAL
      limit for thinking + output combined. Even with thinking_budget=2000,
      the API may consume more thinking tokens than budgeted, so max_tokens
      must be high enough to accommodate both. 32K gives plenty of headroom
      for complex PARSE schemas like SpatialPlanningIntent (~5-8K output).
    - thinking_budget caps thinking tokens (qwen3.7-plus default=65536).
      2000 is sufficient for classification/extraction tasks.
    - qwen3.7-plus supports thinking + json_schema simultaneously (verified).

    Ref: https://help.aliyun.com/zh/model-studio/qwen-structured-output
    """
    from app.core.llm import create_llm

    extra_body = {}
    if enable_thinking:
        extra_body["enable_thinking"] = True
        extra_body["thinking_budget"] = thinking_budget

    return create_llm(
        temperature=0,
        max_tokens=32768,  # Must be >> thinking_budget (DashScope: max_tokens = thinking + output total)
        streaming=True,
        extra_body=extra_body,
    )


def _get_fast_llm():
    """Get fast LLM for JSON repair (Stage 3 fallback).

    Uses create_flash_llm() which configures DashScope API credentials
    and request_timeout automatically.
    """
    from app.core.llm import create_flash_llm

    return create_flash_llm(temperature=0)


# ── Node 1: classify_sections ───────────────────────────────────────


async def classify_sections_node(state: ParseAgentState) -> dict:
    """Classify document sections — hybrid: keyword (70%) + LLM fallback (30%).

    Uses split_by_headers() + classify_section() for high-confidence sections.
    Low-confidence sections (score < 2) are routed to LLM for re-classification.
    """
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
            # Use keyword hint as placeholder — LLM will refine
            section_type = section_type  # keep as hint

        classified.append(SectionInfo(
            section_id=f"S{i + 1:02d}",
            title=rs["title"],
            section_type=section_type,
            content=rs["content"],
            has_table=has_table,
        ))

    # Step 3: LLM fallback only for low-confidence sections
    if low_conf:
        logger.info("[PARSE:classify] %d/%d sections → LLM fallback",
                     len(low_conf), len(raw_sections))
        try:
            llm = _get_llm()
            from app.modules.parsing.section_classifier import build_fallback_prompt
            from pydantic import BaseModel as _BM, Field as _Field

            class _FallbackItem(_BM):
                index: int = 0
                section_type: str = ""

            class _FallbackResult(_BM):
                items: list[_FallbackItem] = _Field(default_factory=list)

            prompt = build_fallback_prompt(low_conf)
            messages = [
                SystemMessage(content="你是村庄规划文档结构分类器。输出每个段落的 section_type。"),
                HumanMessage(content=prompt),
            ]
            fb_result = await _invoke_structured(llm, _FallbackResult, messages)
            if fb_result and fb_result.items:
                for item in fb_result.items:
                    idx = item.index
                    llm_type = item.section_type
                    if 0 <= idx < len(classified):
                        classified[idx].section_type = llm_type or classified[idx].section_type
        except Exception as e:
            logger.warning("[PARSE:classify] LLM fallback failed: %s — using keywords", e)

    logger.info("[PARSE:classify] %d sections (keyword + LLM hybrid)", len(classified))
    return {
        "section_map": classified,
        "parse_strategy": "full",
    }


# ── Routing: route_by_section (conditional edges fan-out) ────────────


def route_by_section(state: ParseAgentState) -> List[str]:
    """Fan-out: route to extract nodes based on section types.

    Returns list of node names. LangGraph runs them in parallel.
    All extract nodes receive full state (spatial_context, section_map, etc.).
    """
    targets = []
    seen = set()

    for section in state.section_map:
        st = section.section_type

        if st in ("regulation", "protection") and "extract_regulations" not in seen:
            targets.append("extract_regulations")
            seen.add("extract_regulations")
        elif st in ("project_table", "land_use_table", "facility_table", "infrastructure") and "extract_projects" not in seen:
            targets.append("extract_projects")
            seen.add("extract_projects")
        elif st in ("indicator_table", "target", "spatial_layout") and "extract_targets" not in seen:
            targets.append("extract_targets")
            seen.add("extract_targets")
        elif section.has_table and "extract_tables" not in seen:
            targets.append("extract_tables")
            seen.add("extract_tables")

    # Default: at least extract targets
    if not targets:
        targets.append("extract_targets")

    logger.info("[PARSE:route] Routing to: %s", targets)
    return targets


# ── Helper: get relevant sections text ───────────────────────────────


def _get_sections_text(state: ParseAgentState, *section_types: str) -> str:
    """Get combined text of sections matching any of the given types."""
    texts = []
    for s in state.section_map:
        if s.section_type in section_types:
            texts.append(s.content)
    return "\n\n".join(texts) if texts else state.planning_text[:6000]


# ── Node 2a: extract_regulations ────────────────────────────────────


async def extract_regulations_node(state: ParseAgentState) -> dict:
    """Extract spatial constraints — hybrid: regex (70%) + LLM fallback (30%).

    Runs deterministic regex patterns first via extract_regulations_regex().
    Unmatched lines are batch-sent to LLM with minimal prompt — no spatial
    context injection needed since the patterns handle common cases.
    """
    from pydantic import BaseModel as _BM

    from app.modules.parsing.regulation_extractor import extract_regulations_regex

    sections_text = _get_sections_text(state, "regulation", "protection")
    all_constraints: list[dict] = []

    # Step 1: deterministic regex extraction
    matched, unmatched = extract_regulations_regex(sections_text)
    all_constraints.extend(matched)

    # Step 2: LLM fallback for unmatched lines (batch, minimal prompt)
    if unmatched:
        logger.info("[PARSE:regulations] Regex=%d → LLM fallback=%d lines",
                     len(matched), len(unmatched))
        try:
            class _RegFallbackResult(_BM):
                constraints: List[SpatialConstraint] = []

            llm = _get_llm()
            unmatched_text = "\n".join(f"- {line}" for line in unmatched[:30])
            messages = [
                SystemMessage(content="你是村庄规划管制规则提取器。从以下未匹配文本中提取 SpatialConstraint。"),
                HumanMessage(content=f"未匹配规则文本:\n{unmatched_text}"),
            ]
            fb_result = await _invoke_structured(llm, _RegFallbackResult, messages)
            if fb_result:
                all_constraints.extend([c.model_dump() for c in fb_result.constraints])
        except Exception as e:
            logger.warning("[PARSE:regulations] LLM fallback failed: %s", e)

    logger.info("[PARSE:regulations] Extracted %d constraints (regex + LLM hybrid)",
                 len(all_constraints))
    return {"raw_constraints": all_constraints}


# ── Node 2b: extract_tables ─────────────────────────────────────────


async def extract_tables_node(state: ParseAgentState) -> dict:
    """Extract structured data from table sections — deterministic, zero LLM.

    Uses parse_markdown_tables() to parse pipe-delimited markdown tables
    directly, eliminating the 3K-5K token LLM call per table.
    """
    from app.modules.parsing.markdown_parser import parse_markdown_tables

    table_sections = [s for s in state.section_map if s.has_table]
    all_rows = []
    for section in table_sections:
        tables = parse_markdown_tables(section.content)
        for table in tables:
            headers = table.get("headers", [])
            for row in table.get("rows", []):
                if not row or all(c == "" for c in row):
                    continue
                row_dict = dict(zip(headers, row)) if headers else {"data": row}
                row_dict["_section_id"] = section.section_id
                row_dict["_section_type"] = section.section_type
                all_rows.append(row_dict)

    logger.info("[PARSE:tables] Deterministic: %d table rows (0 LLM)", len(all_rows))
    return {"raw_tables": {"rows": all_rows}}


# ── Node 2c: extract_projects ───────────────────────────────────────


async def _explore_draft_format(
    state: ParseAgentState,
    *,
    section_types: tuple[str, ...],
    explore_tools: list,
    explore_system_prompt: str,
    draft_system_prompt: str,
    draft_prompt_template: str,
    format_system_prompt: str,
    schema_cls: type,
    log_label: str,
    post_process: callable = lambda r: r,
) -> tuple[object | None, str]:
    """Three-round shared extraction: tool exploration → draft → flash format.

    Round 1: thinking LLM + tools (3 rounds of ReAct)
    Round 2: thinking LLM produces free-text draft
    Round 3: flash model formats draft into structured Pydantic output
    """
    from langchain_core.messages import AIMessage, ToolMessage

    llm = _get_llm()
    sections_text = _get_sections_text(state, *section_types)

    # ── Round 1: Free exploration with tools ──
    explore_msgs = [
        SystemMessage(content=explore_system_prompt),
        HumanMessage(content=sections_text[:6000]),
    ]
    explore_llm = llm.bind_tools(explore_tools)
    tool_results: list[str] = []
    for _round in range(3):
        response = await explore_llm.ainvoke(explore_msgs)
        explore_msgs.append(response)
        if not hasattr(response, "tool_calls") or not response.tool_calls:
            break
        for tc in response.tool_calls[:8]:
            tool_name = tc.get("name", "")
            tool_args = tc.get("args", {})
            result_str = await _execute_tool_call(tool_name, tool_args)
            explore_msgs.append(ToolMessage(content=str(result_str), tool_call_id=tc["id"]))
            tool_results.append(f"[{tool_name}(...): {result_str[:200]}]")

    tools_summary = "\n".join(tool_results[:30])
    logger.info("[PARSE:%s] Round 1 done: %d tool results", log_label, len(tool_results))

    # ── Round 2: Free-text draft from thinking LLM ──
    draft_prompt = draft_prompt_template.format(
        tools_summary=tools_summary[:3000],
        sections_text=sections_text[:6000],
    )
    draft_response = await llm.ainvoke([
        SystemMessage(content=draft_system_prompt),
        HumanMessage(content=draft_prompt),
    ])
    draft_text = draft_response.content if hasattr(draft_response, "content") else str(draft_response)
    logger.info("[PARSE:%s] Round 2 draft: %d chars", log_label, len(draft_text))

    # ── Round 3: Flash model formats draft into Pydantic ──
    flash_llm = _get_fast_llm()
    result = await _invoke_structured(flash_llm, schema_cls, [
        SystemMessage(content=format_system_prompt),
        HumanMessage(content=draft_text[:6000]),
    ])
    return post_process(result), log_label


async def extract_projects_node(state: ParseAgentState) -> dict:
    """Extract spatial operations — three-round: tools → draft → flash format."""
    from pydantic import BaseModel as _BM

    class ProjectExtractionResult(_BM):
        operations: List[SpatialOperation] = []

    result, _ = await _explore_draft_format(
        state,
        section_types=("project_table", "land_use_table", "facility_table", "infrastructure"),
        explore_tools=[lookup_code, resolve_place, query_village_kg],
        explore_system_prompt=(
            "你是村庄规划项目分析助手。对于以下文本中的每个项目，请用工具查询：\n"
            "1. 用 lookup_code 查询每种出现的 land_use_name 的 GHYTBM 编码\n"
            "2. 用 resolve_place 查询每个位置描述中地名的 GIS 锚点\n"
        ),
        draft_system_prompt="你是村庄规划项目提取器。严格使用工具返回的编码和地名，不要自己编造。",
        draft_prompt_template=(
            "基于以下原始文本和工具查询结果，用自然语言列出所有项目，每项写明：\n"
            "action、project_name、land_use_code（必须使用工具查询返回的 ghytbm 编码）、\n"
            "area_sqm、location_desc、source_text、village_name（来自resolve_place结果）、\n"
            "parcel_ids（来自resolve_place结果）、confidence。\n\n"
            "工具查询结果:\n{tools_summary}\n\n"
            "原始文本:\n{sections_text}"
        ),
        format_system_prompt="你是 JSON 格式化器。将以下项目列表严格转换为指定 schema。使用文本中的编码和地名值。",
        schema_cls=ProjectExtractionResult,
        log_label="projects",
    )
    if result is not None:
        ops = [o.model_dump() for o in result.operations]
        logger.info("[PARSE:projects] Extracted %d operations", len(ops))
        return {"raw_operations": ops}
    return {"raw_operations": []}


# ── Node 2d: extract_targets ────────────────────────────────────────


async def extract_targets_node(state: ParseAgentState) -> dict:
    """Extract planning targets — three-round: tools → draft → flash format."""
    result, _ = await _explore_draft_format(
        state,
        section_types=("target", "indicator_table", "spatial_layout"),
        explore_tools=[lookup_code, query_village_kg, resolve_place],
        explore_system_prompt=(
            "你是村庄规划目标分析助手。请用工具查询以下信息：\n"
            "1. lookup_code: 查询 land_use 对应的 GHYTBM 编码\n"
            "2. query_village_kg(template_name='count_by_zone_type'): 查询地类分布\n"
            "3. query_village_kg(template_name='get_designated_zones'): 查询分区邻接\n"
        ),
        draft_system_prompt="你是村庄规划目标提取器。严格使用工具返回的编码，不要自己编造。",
        draft_prompt_template=(
            "基于以下原始文本和工具查询结果，用自然语言列出所有规划目标，包括：\n"
            "分区目标(land_use + dlbm编码 + area_ratio)、设施(type/status/location_hint)、\n"
            "发展轴(direction/reference_feature/connects)。\n"
            "dlbm 必须使用工具查询返回的 ghytbm 编码，不要自己编造。\n\n"
            "工具查询结果:\n{tools_summary}\n\n"
            "原始文本:\n{sections_text}"
        ),
        format_system_prompt="你是 JSON 格式化器。将以下规划目标列表严格转换为指定 schema。",
        schema_cls=SpatialPlanningIntent,
        log_label="targets",
        post_process=lambda r: (setattr(r, "village_name", state.village_name), r)[1] if r is not None else None,
    )
    if result is not None:
        logger.info(
            "[PARSE:targets] Extracted %d zones, %d facilities, %d axes",
            len(result.zone_targets),
            len(result.facilities),
            len(result.development_axes),
        )
        return {"raw_targets": result.model_dump()}
    return {"raw_targets": {}}


# ── Node 3: validate_and_merge ──────────────────────────────────────


async def validate_and_merge_node(state: ParseAgentState) -> dict:
    """Validate extraction results and merge into final output.

    If all LLM extractions failed (empty raw results), skip LLM validation
    and directly pass through whatever spatial context provides.
    """
    from pydantic import BaseModel as _BM

    from app.modules.prompts.parse_prompts import (
        VALIDATE_AND_MERGE_PROMPT,
        format_spatial_context_for_prompt,
    )

    # Increment parse round
    new_round = state.parse_round + 1

    # Check if all extractions are empty — if so, skip LLM validation
    has_any_data = (
        len(state.raw_operations) > 0
        or len(state.raw_constraints) > 0
        or bool(state.raw_targets)
    )

    if not has_any_data:
        logger.warning("[PARSE:validate] All extractions empty — generating from spatial context")
        # Build minimal results from spatial context
        constraints_from_ctx = []
        for c in state.spatial_context.constraint_summary:
            constraints_from_ctx.append({
                "type": "spatial_constraint",
                "priority": "mandatory",
                "source_text": f"{c.zone_type}: {c.rule}",
                "spatial_rule": {
                    "operation": "contained_by",
                    "subject": "construction",
                    "object": c.zone_type,
                },
            })

        return {
            "operation_sequence": [],
            "constraint_set": constraints_from_ctx,
            "planning_intent": {"village_name": state.village_name},
            "validation_errors": ["All LLM extractions failed — using spatial context fallback"],
            "is_valid": False,
            "parse_round": new_round,
        }

    class MergedResult(_BM):
        operation_sequence: List[SpatialOperation] = []
        constraint_set: List[SpatialConstraint] = []
        planning_intent: SpatialPlanningIntent = SpatialPlanningIntent()
        validation_errors: List[str] = []
        is_valid: bool = False

    # ── Deterministic validations (4 of 6 checks — no LLM) ──
    det_errors: List[str] = []

    # 1. Area ratio sum check
    if state.raw_targets:
        zone_targets = state.raw_targets.get("zone_targets", [])
        if zone_targets:
            total = sum(zt.get("area_ratio", 0) for zt in zone_targets)
            if abs(total - 1.0) > 0.05 and total > 0:
                det_errors.append(f"Area ratios sum to {total:.1%} (expected ~100%)")

    # 2. Encoding validity via DictionaryCenter
    try:
        from app.modules.gis.schema import GHYTBM_TO_GHYTMC
        valid_ghytbms = set(GHYTBM_TO_GHYTMC.keys())
        for op in state.raw_operations:
            code = op.get("land_use_code", "")
            if code and code not in valid_ghytbms:
                det_errors.append(f"Invalid GHYTBM code: {code}")
    except ImportError:
        pass

    # 3. Low-confidence spatial anchors
    for op in state.raw_operations:
        anchor = op.get("spatial_anchor", {})
        if isinstance(anchor, dict) and anchor.get("confidence", 1.0) < 0.3:
            det_errors.append(f"Low anchor confidence for {op.get('project_name', '?')}")

    # 4. Required source_text field
    for i, op in enumerate(state.raw_operations):
        if not op.get("source_text"):
            det_errors.append(f"Operation #{i + 1} missing source_text")
    for i, c in enumerate(state.raw_constraints):
        if not c.get("source_text"):
            det_errors.append(f"Constraint #{i + 1} missing source_text")

    # ── LLM only for semantic checks (constraint completeness, dedup) ──
    llm = _get_llm()
    spatial_ctx_text = format_spatial_context_for_prompt(state.spatial_context, detail_level="standard")

    operations_json = json.dumps(state.raw_operations, ensure_ascii=False, default=str)[:3000]
    constraints_json = json.dumps(state.raw_constraints, ensure_ascii=False, default=str)[:3000]
    intent_json = json.dumps(state.raw_targets, ensure_ascii=False, default=str)[:3000]

    prompt = VALIDATE_AND_MERGE_PROMPT.format(
        spatial_context=spatial_ctx_text,
        operation_count=len(state.raw_operations),
        operations_json=operations_json,
        constraint_count=len(state.raw_constraints),
        constraints_json=constraints_json,
        intent_json=intent_json,
    )

    messages = [
        SystemMessage(content="你是村庄规划数据校验与合并器。请按 JSON 格式输出。"),
        HumanMessage(content=prompt),
    ]

    result = await _invoke_structured(llm, MergedResult, messages)
    if result is not None:
        all_errors = det_errors + list(result.validation_errors)
        logger.info(
            "[PARSE:validate] Merged: %d ops, %d constraints, valid=%s, errors=%d (det=%d, llm=%d)",
            len(result.operation_sequence),
            len(result.constraint_set),
            result.is_valid,
            len(all_errors),
            len(det_errors),
            len(result.validation_errors),
        )
        return {
            "operation_sequence": [o.model_dump() for o in result.operation_sequence],
            "constraint_set": [c.model_dump() for c in result.constraint_set],
            "planning_intent": result.planning_intent.model_dump(),
            "validation_errors": all_errors,
            "is_valid": result.is_valid and len(det_errors) == 0,
            "parse_round": new_round,
        }

    # Fallback: _invoke_structured returned None
    logger.warning("[PARSE:validate] Merge returned None — using raw results")
    return {
        "operation_sequence": state.raw_operations,
        "constraint_set": state.raw_constraints,
        "planning_intent": state.raw_targets,
        "validation_errors": det_errors + ["Merge validation failed — using raw extraction results"],
        "is_valid": False,
        "parse_round": new_round,
    }


# ── Routing: should_retry ───────────────────────────────────────────


def should_retry(state: ParseAgentState) -> str:
    """Determine if PARSE should retry validation or end."""
    if state.is_valid:
        return "end"
    if state.parse_round >= MAX_PARSE_ROUNDS:
        logger.info("[PARSE:retry] Max rounds reached (%d) — ending", state.parse_round)
        return "end"
    if len(state.validation_errors) == 0:
        return "end"
    # If all extractions are empty, no point retrying
    if not state.raw_operations and not state.raw_constraints and not state.raw_targets:
        logger.info("[PARSE:retry] All extractions empty — ending without retry")
        return "end"
    logger.info("[PARSE:retry] Round %d — retrying (errors: %s)", state.parse_round, state.validation_errors[:3])
    return "retry"


# ── Graph builder ────────────────────────────────────────────────────


def build_parse_agent_graph():
    """Build the PARSE Agent StateGraph.

    Returns a compiled LangGraph graph that takes ParseAgentState as input
    and produces operation_sequence + constraint_set + planning_intent.
    """
    builder = StateGraph(ParseAgentState)

    # Add nodes
    builder.add_node("classify_sections", classify_sections_node)
    builder.add_node("extract_regulations", extract_regulations_node)
    builder.add_node("extract_tables", extract_tables_node)
    builder.add_node("extract_projects", extract_projects_node)
    builder.add_node("extract_targets", extract_targets_node)
    builder.add_node("validate_and_merge", validate_and_merge_node)

    # Entry point
    builder.add_edge(START, "classify_sections")

    # Fan-out from classify_sections via conditional edges
    # route_by_section returns list of node names — LangGraph runs them in parallel
    builder.add_conditional_edges("classify_sections", route_by_section)

    # All extract nodes converge to validate_and_merge
    builder.add_edge("extract_regulations", "validate_and_merge")
    builder.add_edge("extract_tables", "validate_and_merge")
    builder.add_edge("extract_projects", "validate_and_merge")
    builder.add_edge("extract_targets", "validate_and_merge")

    # Retry loop or end
    builder.add_conditional_edges(
        "validate_and_merge",
        should_retry,
        {"retry": "classify_sections", "end": END},
    )

    graph = builder.compile()
    logger.info("[PARSE Agent] Graph compiled successfully")
    return graph


__all__ = ["build_parse_agent_graph", "set_kg_instance", "query_village_kg", "lookup_code", "resolve_place"]
