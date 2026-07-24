"""Run full PARSE Agent pipeline and generate Markdown report.

Usage:
  cd backend
  python -m scripts.run_parse_pipeline --source json
  python -m scripts.run_parse_pipeline --source db
  python -m scripts.run_parse_pipeline --source mineru

Reads:
  - data/gis/jintian/current/*.geojson (GIS data)
  - output/experiments/rag/g1/iter0/layer3_reports.json (planning text, source=json)
  - SQLite dimension_reports (source=db)
  - docs/MinerU_markdown_*村庄规划*.md (source=mineru)

Writes:
  - output/parse_results/{village}_{date}.md (parse report)
  - output/parse_results/{date}/pipeline_trace.json (LLM interaction history + drafts + mappings)
  - output/parse_results/{date}/pipeline_run.json (timing, counts, file index)
  - output/parse_cache/{village}_{source}_{timestamp}.json (PARSE cache for layout pipeline)

Features:
  - Real-time progress output with StepTimer
  - graph.astream() for node-by-node progress
  - flush=True on all prints to prevent stdout overwrite
  - Timing metrics per step and per node
  - Structured JSON trace files for optimization analysis
"""

import asyncio
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

# Ensure UTF-8 output
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "gis" / "jintian"
L3_REPORTS_PATH = PROJECT_ROOT / "output" / "experiments" / "rag" / "g1" / "iter0" / "layer3_reports.json"
OUTPUT_DIR = PROJECT_ROOT / "output" / "parse_results"
PARSE_CACHE_DIR = PROJECT_ROOT / "output" / "parse_cache"


# ── StepTimer utility ──────────────────────────────────────────────


class StepTimer:
    """Context manager that prints step name and elapsed time."""

    def __init__(self, name: str):
        self.name = name
        self.start = None

    def __enter__(self):
        self.start = time.time()
        print(f"\n{'=' * 60}", flush=True)
        print(f"▶ Step: {self.name}", flush=True)
        print(f"{'=' * 60}", flush=True)
        return self

    def __exit__(self, *args):
        elapsed = time.time() - self.start
        print(f"  ⏱ {self.name}: {elapsed:.1f}s", flush=True)


# ── Data loading ───────────────────────────────────────────────────


def load_gis_data() -> dict:
    """Load all current GeoJSON layers."""
    gis_data = {}
    current_dir = DATA_DIR / "current"
    for f in current_dir.glob("*.geojson"):
        key = f.stem + "_geojson"
        try:
            with open(str(f), "r", encoding="utf-8") as fh:
                gis_data[key] = json.load(fh)
        except Exception as e:
            print(f"  [GIS] WARNING: Failed to load {f.name}: {e}", flush=True)

    # Rename landuse key to expected format
    for key in list(gis_data.keys()):
        if "landuse" in key and "landuse_current" not in key:
            gis_data["landuse_current_geojson"] = gis_data.pop(key)
            break

    # Parse annotation.geojson → typed CurrentAnnotation models via ingestion layer
    annotations = []
    ann_warnings = []
    ann_path = current_dir / "annotation.geojson"
    if ann_path.exists():
        from app.modules.gis.schema import ingest_feature
        annotations, ann_warnings = ingest_feature(str(ann_path), "current_annotation")
        print(f"  [GIS] Parsed {len(annotations)} annotations (typed via ingest_feature)", flush=True)
        if ann_warnings:
            print(f"  [GIS] Annotation warnings: {len(ann_warnings)}", flush=True)

    # Parse road.geojson → typed CurrentRoad models via ingestion layer
    roads = []
    road_warnings = []
    road_path = current_dir / "road.geojson"
    if road_path.exists():
        from app.modules.gis.schema import ingest_feature as _ingest_road
        roads, road_warnings = _ingest_road(str(road_path), "current_road")
        print(f"  [GIS] Parsed {len(roads)} roads (typed via ingest_feature)", flush=True)
        if road_warnings:
            print(f"  [GIS] Road warnings: {len(road_warnings)}", flush=True)

    print(f"  [GIS] Loaded {len(gis_data)} layers: {sorted(gis_data.keys())[:5]}...", flush=True)

    # Inject annotation data into gis_data dict for compute_spatial_context
    if annotations:
        ann_features = []
        for ann in annotations:
            feat = {"type": "Feature", "properties": {}, "geometry": getattr(ann, "geometry", {})}
            for attr in ("text", "category", "name", "注记", "分类"):
                val = getattr(ann, attr, None)
                if val:
                    feat["properties"][attr] = val
            ann_features.append(feat)
        gis_data["annotation_geojson"] = {"type": "FeatureCollection", "features": ann_features}
        print(f"  [GIS] Injected {len(ann_features)} annotations into gis_data dict", flush=True)

    return gis_data, annotations, roads


def load_planning_text() -> str:
    """Load L3 reports as combined planning text."""
    if not L3_REPORTS_PATH.exists():
        print(f"  [TEXT] L3 reports not found at {L3_REPORTS_PATH}", flush=True)
        return ""

    with open(str(L3_REPORTS_PATH), "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception as e:
            print(f"  [TEXT] WARNING: Failed to parse L3 reports JSON: {e}", flush=True)
            return ""

    reports = data.get("reports", {})
    if not reports:
        print("  [TEXT] No reports in L3 file", flush=True)
        return ""

    sections = []
    for dim_key, content in reports.items():
        if isinstance(content, dict):
            text = content.get("content", content.get("summary", ""))
        else:
            text = str(content)
        if text:
            sections.append(f"## {dim_key}\n\n{text}")

    combined = "\n\n".join(sections)
    print(f"  [TEXT] Combined planning text: {len(combined)} chars from {len(reports)} dimensions", flush=True)
    return combined


# ── DB / MinerU data loaders ──────────────────────────────────────


def load_l3_from_db() -> Tuple[Dict, str]:
    """Load 12 L3 dimension reports from SQLite -> combined planning text.

    Queries the latest session with layer=3 from dimension_reports table,
    then combines all 12 dimension contents into a single planning text.
    """
    try:
        from app.database.engine import get_db_path
        db_path = get_db_path()
    except Exception as e:
        print(f"  [DB] Cannot get DB path: {e}", flush=True)
        return {}, ""

    if not Path(str(db_path)).exists():
        print(f"  [DB] Database not found: {db_path}", flush=True)
        return {}, ""

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT session_id FROM dimension_reports WHERE layer=3 "
            "ORDER BY generated_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            print("  [DB] No L3 reports in database", flush=True)
            return {}, ""

        session_id = row["session_id"]
        cur = conn.execute(
            "SELECT dimension_key, content, summary FROM dimension_reports "
            "WHERE session_id=? AND layer=3", (session_id,)
        )
        rows = cur.fetchall()
    except Exception as e:
        print(f"  [DB] WARNING: SQL query failed: {e}", flush=True)
        return {}, ""
    finally:
        conn.close()

    reports: Dict[str, Any] = {}
    sections: list = []
    for r in rows:
        dk = r["dimension_key"]
        content = r["content"] or ""
        summary_text = r["summary"] or ""
        parsed = json.loads(summary_text) if summary_text else {}
        text = content or parsed.get("text_summary", "")
        reports[dk] = {"summary": parsed, "content": text}
        if text:
            sections.append(f"## {dk}\n\n{text}")

    combined = "\n\n".join(sections)
    print(
        f"  [DB] Loaded {len(rows)} dimensions from session {session_id[:16]}..., "
        f"{len(combined)} chars",
        flush=True,
    )
    return reports, combined


def load_mineru_text() -> Tuple[str, str]:
    """Load planning text from MinerU markdown file in docs/.

    Returns:
        (file_path, text_content)
    """
    docs_dir = PROJECT_ROOT / "docs"
    candidates = sorted(
        docs_dir.glob("MinerU_markdown_*村庄规划*文本*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        print("  [MINERU] No MinerU markdown found in docs/", flush=True)
        return "", ""

    text = candidates[0].read_text(encoding="utf-8")
    print(f"  [MINERU] Loaded: {candidates[0].name}, {len(text)} chars", flush=True)
    return str(candidates[0]), text


# ── PARSE result cache ────────────────────────────────────────────


def _serialize_for_cache(obj: Any) -> Any:
    """Recursively serialize Pydantic models to dicts for JSON caching."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, list):
        return [_serialize_for_cache(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _serialize_for_cache(v) for k, v in obj.items()}
    return obj


def save_parse_cache(result: Dict, village_name: str, source: str = "") -> Path:
    """Save PARSE results to cache file for layout pipeline consumption."""
    PARSE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    source_tag = f"_{source}" if source else ""
    cache_path = PARSE_CACHE_DIR / f"{village_name}{source_tag}_{timestamp}.json"

    with open(str(cache_path), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    file_size_kb = cache_path.stat().st_size / 1024
    ops_count = len(result.get("operation_sequence", []))
    cs_count = len(result.get("constraint_set", []))
    print(
        f"  [CACHE] Saved PARSE cache: {cache_path} ({file_size_kb:.1f} KB, "
        f"ops={ops_count}, constraints={cs_count})",
        flush=True,
    )
    return cache_path


# ── Pipeline execution with streaming progress ─────────────────────


def _summarize_node_output(node_name: str, output: dict) -> str:
    """Create a one-line summary of node output for progress display."""
    summaries = {
        "classify_sections": lambda o: f"{len(o.get('section_map', []))} sections",
        "extract_regulations": lambda o: f"{len(o.get('raw_constraints', []))} constraints",
        "extract_tables": lambda o: f"{len(o.get('raw_tables', {}).get('rows', []))} rows",
        "explore_projects": lambda o: f"draft={len(o.get('draft_operations', ''))} chars, {len(o.get('code_mappings_projects', {}))} codes",
        "format_projects": lambda o: f"{len(o.get('raw_operations', []))} operations",
        "explore_targets": lambda o: f"draft={len(o.get('draft_targets', ''))} chars, {len(o.get('code_mappings_targets', {}))} codes",
        "format_targets": lambda o: f"targets extracted",
        "validate_and_merge": lambda o: f"valid={o.get('is_valid', False)}, {len(o.get('validation_errors', []))} errors",
    }
    summarizer = summaries.get(node_name, lambda o: "done")
    try:
        return summarizer(output)
    except Exception:
        return "done"


async def _run_parse_graph_with_progress(graph, input_state) -> tuple:
    """Run PARSE graph with statistical progress + structured trace log.

    Returns (result_dict, trace_log) where trace_log is a list of per-node dicts.
    """
    result = {}
    trace_log: list = []  # Structured trace for report generation
    active_nodes = {}  # {node_name: float} — start time
    node_tokens = {}   # {node_name: int}
    last_status_time = 0

    trace_log: list = []  # Structured trace for reporter
    print("  ▶ PARSE Agent 开始执行...", flush=True)

    async for chunk in graph.astream(
        input_state.model_dump(),
        stream_mode=["updates", "messages"],
        version="v2",
    ):
        if chunk["type"] == "updates":
            for node_name, node_output in chunk["data"].items():
                summary = _summarize_node_output(node_name, node_output)
                elapsed = time.time() - active_nodes.pop(node_name, time.time())
                tokens = node_tokens.pop(node_name, 0)
                print(f"  ✅ {node_name}: {summary} ({elapsed:.0f}s, {tokens}t)", flush=True)
                if isinstance(node_output, dict):
                    result.update(node_output)
                # Append structured trace entry
                trace_entry = _build_trace_entry(node_name, node_output, elapsed, tokens)
                trace_log.append(trace_entry)

        elif chunk["type"] == "messages":
            msg_chunk, metadata = chunk["data"]
            node = metadata.get("langgraph_node", "")
            if not node:
                continue

            if node not in active_nodes:
                active_nodes[node] = time.time()
                node_tokens[node] = 0
                print(f"  ⏳ {node} 开始...", flush=True)

            if msg_chunk.content:
                node_tokens[node] = node_tokens.get(node, 0) + 1

            # Print status every 15 seconds (not every token)
            now = time.time()
            if now - last_status_time >= 15:
                parts = []
                for name in sorted(active_nodes.keys()):
                    t = node_tokens.get(name, 0)
                    s = now - active_nodes[name]
                    parts.append(f"{name}: {s:.0f}s ({t}t)")
                print(f"  🔄 {', '.join(parts)}", flush=True)
                last_status_time = now

    print("  ✅ PARSE Agent 执行完毕", flush=True)
    return result, trace_log


def _build_trace_entry(node_name: str, node_output: dict, elapsed: float, tokens: int) -> dict:
    """Build a structured trace entry from node output.

    Captures:
      - Full draft content (not truncated) for explore nodes
      - LLM call traces (system/user prompts, thinking, tool calls + results)
      - Code/place mappings
    """
    entry = {
        "node": node_name,
        "elapsed_s": elapsed,
        "tokens": tokens,
        "status": "ok",
        "summary": _summarize_node_output(node_name, node_output),
    }

    # Extract LLM trace data from node output
    # Per-node keys (Phase 2 fix for parallel fan-out InvalidUpdateError)
    llm_trace = (node_output.get("llm_trace_projects", [])
                 + node_output.get("llm_trace_targets", [])
                 + node_output.get("llm_trace", []))  # backward compat
    if llm_trace:
        entry["llm_calls"] = llm_trace

    # Extract draft content for explore nodes (full content, not truncated)
    if "draft_operations" in node_output:
        draft = node_output["draft_operations"]
        entry["draft_length"] = len(draft)
        entry["draft_full"] = draft[:5000] if draft else ""
        entry["draft_preview"] = draft[:600] if draft else ""
        entry["codes_extracted"] = len(node_output.get("code_mappings_projects", {}))
        entry["code_mappings"] = node_output.get("code_mappings_projects", {})
        entry["place_mappings"] = node_output.get("place_mappings_projects", {})
    elif "draft_targets" in node_output:
        draft = node_output["draft_targets"]
        entry["draft_length"] = len(draft)
        entry["draft_full"] = draft[:5000] if draft else ""
        entry["draft_preview"] = draft[:600] if draft else ""
        entry["codes_extracted"] = len(node_output.get("code_mappings_targets", {}))
        entry["code_mappings"] = node_output.get("code_mappings_targets", {})
        entry["place_mappings"] = node_output.get("place_mappings_targets", {})
    elif "raw_operations" in node_output:
        ops = node_output["raw_operations"]
        entry["format_result"] = f"{len(ops)} operations"
    elif "raw_targets" in node_output:
        targets = node_output["raw_targets"]
        if isinstance(targets, dict):
            zones = len(targets.get("zone_targets", []))
            facilities = len(targets.get("facilities", []))
        else:
            # Typed SpatialPlanningIntent (Phase 2+)
            zones = len(getattr(targets, "zone_targets", []))
            facilities = len(getattr(targets, "facilities", []))
        entry["format_result"] = f"{zones} zones + {facilities} facilities"
    elif "raw_tables" in node_output:
        rows = node_output["raw_tables"].get("rows", [])
        entry["draft_preview"] = f"{len(rows)} table rows"
    elif "raw_constraints" in node_output:
        entry["draft_preview"] = f"{len(node_output['raw_constraints'])} constraints"
    elif "section_map" in node_output:
        entry["draft_preview"] = f"{len(node_output['section_map'])} sections"
    elif "validation_errors" in node_output:
        errors = node_output.get("validation_errors", [])
        entry["draft_preview"] = "; ".join(str(e)[:120] for e in errors[:5])

    return entry


# ── Main pipeline ──────────────────────────────────────────────────


SAMPLE_PLANNING_TEXT = """
## 产业发展规划

第12条 在刘村小组东侧、晒谷场北边空地，新建400㎡农产品展销中心，用地性质为经营性建设用地。

## 空间管制规则

第6条 耕地保有量不低于78.83公顷，基本农田保护面积不低于71.5公顷。
第8条 现状村道拓宽为6米规划道路，沿东西向主干道布局。
第15条 产业用地与居住区间距不小于200米。

## 建设项目安排

1. 新建农产品展销中心，建筑面积400㎡，位于刘村小组东侧
2. 改造村委会办公楼，保留现有功能
3. 新建公共停车场，位于村口交通节点

## 规划目标

- 规划人口1850人
- 村庄建设用地规模30.5公顷
- 耕地保有量86.5公顷
- 生态用地占比不低于15%
"""


async def run_pipeline(source: str = "json", text_path: str = ""):
    """Run the full PARSE Agent pipeline.

    Args:
        source: Planning text source — "json" (L3 reports file), "db" (SQLite),
                "mineru" (docs/ markdown), "text" (custom file)
        text_path: Path to custom text file (only used when source="text")
    """
    total_start = time.time()

    # Step 1: Load data
    with StepTimer("加载数据"):
        gis_data, annotations, roads = load_gis_data()

        # Load planning text by source
        planning_text = ""
        if source == "db":
            _reports, planning_text = load_l3_from_db()
            if not planning_text:
                print("  [ERROR] DB 中无 L3 规划数据", flush=True)
                return
        elif source == "mineru":
            _fp, planning_text = load_mineru_text()
            if not planning_text:
                print("  [ERROR] 未找到 MinerU markdown 文件", flush=True)
                return
        elif source == "text" and text_path:
            p = Path(text_path)
            if p.exists():
                planning_text = p.read_text(encoding="utf-8")
                print(f"  [TEXT] Loaded custom text: {p.name}, {len(planning_text)} chars", flush=True)
            else:
                print(f"  [ERROR] Text file not found: {text_path}", flush=True)
                return
        else:  # "json"
            planning_text = load_planning_text()

        if not planning_text:
            print("  [WARN] 无规划文本，使用示例文本", flush=True)
            planning_text = SAMPLE_PLANNING_TEXT

    # Step 2: Compute spatial context
    with StepTimer("计算空间上下文"):
        from app.modules.gis.spatial_context import compute_spatial_context

        spatial_context = compute_spatial_context(gis_data)
        print(f"  parcels: {spatial_context.parcel_count}", flush=True)
        print(f"  total_area: {spatial_context.total_area_ha:.1f} ha", flush=True)
        print(f"  villages: {len(spatial_context.natural_villages)}", flush=True)
        print(f"  relations: {len(spatial_context.spatial_relations)}", flush=True)
        print(f"  constraints: {len(spatial_context.constraint_summary)}", flush=True)
        print(f"  zone_adjacency: {len(spatial_context.zone_adjacency)} zones", flush=True)

    # Step 3: Run PARSE Agent
    with StepTimer("运行 PARSE Agent"):
        from app.agent.gis.parse.agent import build_parse_agent_graph, set_spatial_context
        import app.agent.gis.parse.agent as pa
        from app.agent.gis.parse.state import ParseAgentState
        from app.modules.kg import PlanningKG
        from app.modules.parsing.gazetteer import PlaceNameResolver

        # Build KG for on-demand spatial queries
        kg_summary = {"triple_count": 0, "parcel_count": 0, "facility_count": 0, "road_count": 0, "village_count": 0}
        typed_parcels = None  # Typed parcels from ingestion layer (schema-injection path)
        try:
            from app.modules.gis.schema import ingest_current_landuse
            landuse_path = DATA_DIR / "current" / "landuse.geojson"
            if landuse_path.exists():
                typed_parcels, _parcel_warnings = ingest_current_landuse(str(landuse_path))
                print(f"  [GIS] Ingested {len(typed_parcels)} parcels (typed via ingest_current_landuse)", flush=True)
        except Exception as ingest_err:
            print(f"  [GIS] Typed ingestion skipped: {ingest_err}", flush=True)

        try:
            kg = PlanningKG(village_name="金田村")
            if gis_data:
                landuse = gis_data.get("landuse_current_geojson")
                # Prefer typed parcels (schema-injection) over raw GeoJSON (legacy)
                if typed_parcels:
                    kg.build_from_reports(reports={}, parcels=typed_parcels, gis_data=gis_data)
                else:
                    kg.build_from_reports(reports={}, landuse_geojson=landuse, gis_data=gis_data)
            # Inject annotation facilities + village names
            if annotations:
                kg.add_annotations(annotations)
            if roads:
                kg.add_roads(roads)
            # Register with KGManager for PARSE agent tool queries
            from app.modules.kg.manager import get_kg_manager
            get_kg_manager().register_session("parse_pipeline", kg)
            kg_summary = {
                "triple_count": kg.get_triple_count(),
                "parcel_count": kg._parcel_count if hasattr(kg, "_parcel_count") else kg.get_parcel_count(),
                "facility_count": len(annotations) if annotations else 0,
                "road_count": len(roads) if roads else 0,
                "village_count": len(spatial_context.natural_villages),
            }
            print(f"  [KG] Built: {kg.get_triple_count()} triples + annotations/roads", flush=True)
        except Exception as kg_err:
            print(f"  [KG] Build failed: {type(kg_err).__name__}: {kg_err}", flush=True)

        # Initialize Gazetteer for place name → VillageGroup matching
        gazetteer = PlaceNameResolver(spatial_context.natural_villages)
        pa._gazetteer = gazetteer
        pa.set_spatial_context(spatial_context)
        print(f"  [Gazetteer] Initialized with {len(spatial_context.natural_villages)} villages", flush=True)
        print(
            f"  [Annotation] {len(spatial_context.facility_anchors)} facility anchors, "
            f"{len(spatial_context.annotation_villages)} village name anchors",
            flush=True,
        )

        graph = build_parse_agent_graph()
        input_state = ParseAgentState(
            planning_text=planning_text[:12000],
            village_name="金田村",
            spatial_context=spatial_context,
        )
        if len(planning_text) > 12000:
            print(f"  [WARN] Planning text truncated: {len(planning_text)} -> 12000 chars", flush=True)

        try:
            result, trace_log = await _run_parse_graph_with_progress(graph, input_state)
        except Exception as e:
            import traceback
            print(f"  ❌ PARSE Agent 失败: {e}", flush=True)
            traceback.print_exc()
            print("  从空间上下文生成基本报告", flush=True)
            result = {}
            trace_log = [{"node": "ERROR", "elapsed_s": 0, "tokens": 0, "status": "fail",
                          "summary": str(e), "draft_preview": traceback.format_exc()[:500]}]

    # Step 4: Extract results
    operation_sequence = result.get("operation_sequence", [])
    constraint_set = result.get("constraint_set", [])
    planning_intent = result.get("planning_intent", {})
    validation_errors = result.get("validation_errors", [])
    is_valid = result.get("is_valid", False)
    section_map = result.get("section_map", [])
    # Log extraction completeness
    missing_keys = [k for k in ["operation_sequence", "constraint_set", "planning_intent",
                                 "validation_errors", "section_map"] if k not in result]
    if missing_keys:
        print(f"  [WARN] PARSE result missing keys: {missing_keys}", flush=True)
    print(
        f"  [EXTRACT] ops={len(operation_sequence)}, constraints={len(constraint_set)}, "
        f"errors={len(validation_errors)}, valid={is_valid}",
        flush=True,
    )

    # Step 5: Display results
    print(f"\n{'=' * 60}", flush=True)
    print("PARSE Agent 结果摘要", flush=True)
    print(f"{'=' * 60}", flush=True)

    print(f"\n--- 段落分类 ({len(section_map)}) ---", flush=True)
    for s in section_map:
        st = s.get("section_type", "?") if isinstance(s, dict) else s.section_type
        title = s.get("title", "") if isinstance(s, dict) else s.title
        print(f"  [{st}] {title}", flush=True)

    print(f"\n--- 操作序列 ({len(operation_sequence)}) ---", flush=True)
    for i, op in enumerate(operation_sequence[:20]):
        action = op.get("action", "?") if isinstance(op, dict) else op.action
        land_use = op.get("land_use_name", "") if isinstance(op, dict) else getattr(op, "land_use_name", "")
        area = op.get("area_sqm") if isinstance(op, dict) else getattr(op, "area_sqm", None)
        code = op.get("land_use_code", "") if isinstance(op, dict) else getattr(op, "land_use_code", "")
        area_info = f", {area}sqm" if area else ""
        code_info = f" ({code})" if code else ""
        print(f"  {i+1}. [{action}] {land_use}{code_info}{area_info}", flush=True)
    if len(operation_sequence) > 20:
        print(f"  ...还有 {len(operation_sequence) - 20} 条操作", flush=True)

    print(f"\n--- 约束集 ({len(constraint_set)}) ---", flush=True)
    for i, c in enumerate(constraint_set[:10]):
        ctype = c.get("type", "?") if isinstance(c, dict) else c.type
        priority = c.get("priority", "") if isinstance(c, dict) else getattr(c, "priority", "")
        value = c.get("value", "") if isinstance(c, dict) else getattr(c, "value", "")
        val_info = f", value={value}" if value else ""
        print(f"  {i+1}. [{ctype}] priority={priority}{val_info}", flush=True)
    if len(constraint_set) > 10:
        print(f"  ...还有 {len(constraint_set) - 10} 条约束", flush=True)

    print(f"\n--- 规划意图 ---", flush=True)
    if isinstance(planning_intent, dict):
        zone_targets = planning_intent.get("zone_targets", [])
        facilities = planning_intent.get("facilities", [])
        axes = planning_intent.get("development_axes", [])
    else:
        # Typed SpatialPlanningIntent (Phase 2+)
        zone_targets = getattr(planning_intent, "zone_targets", [])
        facilities = getattr(planning_intent, "facilities", [])
        axes = getattr(planning_intent, "development_axes", [])
    print(f"  zone_targets: {len(zone_targets)}", flush=True)
    for zt in zone_targets:
        lu = zt.get("land_use", "?") if isinstance(zt, dict) else zt.land_use
        ratio = zt.get("area_ratio", 0) if isinstance(zt, dict) else zt.area_ratio
        dlbm = zt.get("dlbm", "") if isinstance(zt, dict) else getattr(zt, "dlbm", "")
        code_info = f" ({dlbm})" if dlbm else ""
        print(f"    {lu}{code_info}: {ratio:.1%}", flush=True)
    print(f"  facilities: {len(facilities)}", flush=True)
    print(f"  development_axes: {len(axes)}", flush=True)

    print(f"\n--- 校验 ---", flush=True)
    print(f"  is_valid: {is_valid}", flush=True)
    if validation_errors:
        for err in validation_errors[:5]:
            print(f"  error: {err}", flush=True)

    # Step 6: Generate report — ALWAYS, even on failure
    with StepTimer("生成 Markdown 报告"):
        from app.utils.parse_reporter import generate_parse_report

        total_elapsed = time.time() - total_start

        try:
            report_path = generate_parse_report(
                village_name="金田村",
                spatial_context=spatial_context,
                operation_sequence=operation_sequence,
                constraint_set=constraint_set,
                planning_intent=planning_intent,
                validation_errors=validation_errors,
                is_valid=is_valid,
                section_map=section_map,
                timing_info={
                    "total_seconds": total_elapsed,
                    "model": "qwen3.7-plus",
                    "structured_output_method": "Think-Then-Format v11",
                },
                pipeline_trace=trace_log,
                kg_summary=kg_summary,
            )
            print(f"  [REPORT] Generated: {report_path}", flush=True)
            print(f"  [REPORT] Full path: {report_path.resolve()}", flush=True)
        except Exception as report_err:
            # Fallback: minimal report on crash
            import traceback as _tb
            fallback_path = OUTPUT_DIR / f"金田村_{datetime.now().strftime('%Y-%m-%d')}_FALLBACK.md"
            fail_text = f"""# PARSE Agent 报告 (降级)
> 状态: ❌ 报告生成失败
> 错误: {report_err}
> Traceback: {_tb.format_exc()[:2000]}
"""
            fallback_path.write_text(fail_text, encoding="utf-8")
            print(f"  [REPORT] Fallback generated: {fallback_path}", flush=True)

    # Step 7: Save PARSE result to cache for layout pipeline consumption
    try:
        parse_cache_data = {
            "village_name": "金田村",
            "timestamp": datetime.now().isoformat(),
            "source": source,
            "spatial_context": _serialize_for_cache(spatial_context),
            "operation_sequence": _serialize_for_cache(operation_sequence),
            "constraint_set": _serialize_for_cache(constraint_set),
            "planning_intent": _serialize_for_cache(planning_intent),
            "validation_errors": _serialize_for_cache(validation_errors),
            "section_map": _serialize_for_cache(section_map),
            "kg_summary": kg_summary,
            "is_valid": is_valid,
        }
        save_parse_cache(parse_cache_data, "金田村", source=source)
    except Exception as cache_err:
        print(f"  [CACHE] Failed to save PARSE cache: {cache_err}", flush=True)

    # Step 8: Save structured trace file for optimization analysis
    try:
        trace_dir = OUTPUT_DIR / datetime.now().strftime('%Y-%m-%d')
        trace_dir.mkdir(parents=True, exist_ok=True)

        # 8a: pipeline_trace.json — full LLM interaction history
        trace_path = trace_dir / "pipeline_trace.json"
        trace_data = {
            "village_name": "金田村",
            "timestamp": datetime.now().isoformat(),
            "source": source,
            "trace_log": _serialize_for_cache(trace_log),
        }
        trace_path.write_text(
            json.dumps(trace_data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"  [TRACE] Saved: {trace_path} ({trace_path.stat().st_size / 1024:.1f} KB)", flush=True)

        # 8b: pipeline_run.json — single-file index of all outputs
        run_path = trace_dir / "pipeline_run.json"
        run_data = {
            "village_name": "金田村",
            "timestamp": datetime.now().isoformat(),
            "source": source,
            "is_valid": is_valid,
            "timing": {
                "total_seconds": total_elapsed,
                "model": "qwen3.7-plus",
                "structured_output_method": "Think-Then-Format v11",
            },
            "counts": {
                "operations": len(operation_sequence),
                "constraints": len(constraint_set),
                "zone_targets": len(
                    planning_intent.get("zone_targets", [])
                    if isinstance(planning_intent, dict)
                    else getattr(planning_intent, "zone_targets", [])
                ),
                "validation_errors": len(validation_errors),
                "sections": len(section_map),
            },
            "kg_summary": kg_summary,
            "output_files": {
                "report": str(OUTPUT_DIR / f"金田村_{datetime.now().strftime('%Y-%m-%d')}.md"),
                "trace": str(trace_path),
                "cache": str(PARSE_CACHE_DIR / f"金田村_{source}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"),
            },
        }
        run_path.write_text(
            json.dumps(run_data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"  [RUN] Saved: {run_path}", flush=True)
    except Exception as trace_err:
        print(f"  [TRACE] Failed to save trace files: {trace_err}", flush=True)
    total_elapsed = time.time() - total_start
    print(f"\n{'=' * 60}", flush=True)
    print(f"⏱ 总耗时: {total_elapsed:.1f}s", flush=True)
    print(f"{'=' * 60}", flush=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run PARSE Agent pipeline")
    parser.add_argument(
        "--source",
        choices=["json", "db", "mineru", "text"],
        default="json",
        help="Planning text source (default: json)",
    )
    parser.add_argument(
        "--text",
        type=str,
        default="",
        help="Path to custom planning text file (only with --source text)",
    )
    args = parser.parse_args()

    asyncio.run(run_pipeline(source=args.source, text_path=args.text))
