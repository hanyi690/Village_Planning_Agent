"""PARSE Agent integration tests — real LLM calls with SQLite cache.

Tests the full PARSE Agent pipeline:
  planning text + GIS data → PARSE Agent → SpatialOperation + SpatialConstraint + SpatialPlanningIntent

Uses SQLiteCache so repeated test runs hit cache instead of LLM API.
Run: pytest tests/integration/test_parse_agent_llm.py -v -s

Sections:
  1. Spatial Context from jintian data (1 test)
  2. Full PARSE Agent with LLM (1 test — end-to-end)
  3. Individual node with LLM (3 tests — classify/extract/validate)
"""

import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest

# ── Cache setup ──────────────────────────────────────────────────────

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)
CACHE_DB = CACHE_DIR / "parse_agent_llm_cache.sqlite"


def _setup_llm_cache():
    """Enable SQLite cache for LangChain LLM calls — persists across test runs."""
    try:
        from langchain_community.cache import SQLiteCache
        from langchain_core.globals import set_llm_cache

        set_llm_cache(SQLiteCache(str(CACHE_DB)))
        return True
    except Exception as e:
        print(f"[CACHE] Failed to set up SQLiteCache: {e}")
        return False


# ── Fixture: jintian GIS data ────────────────────────────────────────


@pytest.fixture
def jintian_gis_data():
    """Load all jintian GeoJSON files as gis_data dict."""
    from app.core.settings import JINTIAN_GIS_DIR

    gis_data = {}
    current_dir = JINTIAN_GIS_DIR / "current"
    planned_dir = JINTIAN_GIS_DIR / "planned"

    for geojson_file in current_dir.glob("*.geojson"):
        key = geojson_file.stem + "_geojson"
        with open(geojson_file, "r", encoding="utf-8") as f:
            gis_data[key] = json.load(f)

    for geojson_file in planned_dir.glob("*.geojson"):
        key = geojson_file.stem + "_geojson"
        with open(geojson_file, "r", encoding="utf-8") as f:
            gis_data[key] = json.load(f)

    # Rename landuse key to expected format
    if "landuse_geojson" in gis_data and "landuse_current_geojson" not in gis_data:
        gis_data["landuse_current_geojson"] = gis_data.pop("landuse_geojson")

    print(f"\n[GIS] Loaded {len(gis_data)} layers: {sorted(gis_data.keys())}")
    return gis_data


# ── Fixture: jintian planning text ───────────────────────────────────


@pytest.fixture
def jintian_planning_text():
    """Load L3 reports as combined planning text."""
    from app.core.settings import PROJECT_ROOT

    l3_path = PROJECT_ROOT / "output" / "experiments" / "rag" / "g1" / "iter0" / "layer3_reports.json"
    if not l3_path.exists():
        pytest.skip("L3 reports not found at {l3_path}")

    with open(l3_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    reports = data.get("reports", {})
    if not reports:
        pytest.skip("No reports in L3 file")

    # Combine all dimensions into single planning text
    sections = []
    for dim_key, content in reports.items():
        if isinstance(content, dict):
            text = content.get("content", content.get("summary", ""))
        else:
            text = str(content)
        if text:
            sections.append(f"## {dim_key}\n\n{text}")

    combined = "\n\n".join(sections)
    print(f"\n[TEXT] Combined planning text: {len(combined)} chars from {len(reports)} dimensions")
    return combined


# ============================================================================
# 1. Spatial Context from jintian data
# ============================================================================


class TestSpatialContextJintian:
    """Test compute_spatial_context with real jintian GIS data."""

    def test_spatial_context_jintian_detailed(self, jintian_gis_data):
        """Compute and display spatial context from jintian data."""
        from app.agent.gis.spatial_context import compute_spatial_context

        ctx = compute_spatial_context(jintian_gis_data)

        # ── Detailed output ──
        print(f"\n{'='*60}")
        print(f"金田村 SpatialContext 详细解析结果")
        print(f"{'='*60}")
        print(f"地块总数: {ctx.parcel_count}")
        print(f"总面积: {ctx.total_area_ha:.1f} ha")
        print(f"村中心: {ctx.village_center}")
        print(f"建设边界: {ctx.construction_boundary_ha:.1f} ha")

        print(f"\n--- 地类分布 ({len(ctx.landuse_distribution)} 类) ---")
        for lu in ctx.landuse_distribution:
            print(f"  {lu.name} ({lu.dlbm}): {lu.count} 块, {lu.area_ha:.1f} ha, 分区={lu.planning_zone}")

        print(f"\n--- 自然村落锚点 ({len(ctx.natural_villages)} 个) ---")
        for v in ctx.natural_villages:
            print(
                f"  {v.name}: 中心={v.center}, 地块数={len(v.parcel_ids)}, "
                f"主地类={v.dominant_landuse}, 邻接={v.adjacent_to}"
            )

        print(f"\n--- 空间关系 ({len(ctx.spatial_relations)} 条) ---")
        for r in ctx.spatial_relations[:10]:
            print(f"  {r.subject} --[{r.relation}]--> {r.object} (conf={r.confidence:.1f}, src={r.source})")
        if len(ctx.spatial_relations) > 10:
            print(f"  ... and {len(ctx.spatial_relations) - 10} more")

        print(f"\n--- 约束概要 ({len(ctx.constraint_summary)} 条) ---")
        for c in ctx.constraint_summary:
            print(f"  {c.zone_type}: {c.rule}, 面积={c.area_ha:.1f} ha, 重叠={c.overlaps_with}")

        print(f"\n--- 分区邻接 ({len(ctx.zone_adjacency)} 个) ---")
        for zone, neighbors in ctx.zone_adjacency.items():
            print(f"  {zone}: 邻接 {', '.join(neighbors)}")

        # ── Assertions ──
        assert ctx.parcel_count > 500, f"Expected >500 parcels, got {ctx.parcel_count}"
        assert ctx.total_area_ha > 2000
        assert ctx.village_center is not None
        assert len(ctx.landuse_distribution) >= 5


# ============================================================================
# 2. Full PARSE Agent with LLM
# ============================================================================


class TestParseAgentLLM:
    """Test PARSE Agent with real LLM calls (cached)."""

    @pytest.mark.asyncio
    async def test_full_parse_pipeline(self, jintian_planning_text, jintian_gis_data):
        """Run full PARSE Agent pipeline: text + GIS → operations + constraints + intent."""
        _setup_llm_cache()

        from app.agent.gis.parse_agent import build_parse_agent_graph
        from app.agent.gis.schema.parse_state import ParseAgentState
        from app.agent.gis.spatial_context import compute_spatial_context

        # Step 1: Compute spatial context
        spatial_context = compute_spatial_context(jintian_gis_data)
        print(f"\n[Step1] SpatialContext: {spatial_context.parcel_count} parcels, "
              f"{len(spatial_context.natural_villages)} villages, "
              f"{len(spatial_context.spatial_relations)} relations")

        # Step 2: Build and run PARSE Agent
        graph = build_parse_agent_graph()
        input_state = ParseAgentState(
            planning_text=jintian_planning_text[:12000],
            village_name="金田村",
            spatial_context=spatial_context,
        )

        print(f"\n[Step2] Running PARSE Agent graph (may hit cache)...")
        result = await graph.ainvoke(input_state.model_dump())

        # Step 3: Display results
        operation_sequence = result.get("operation_sequence", [])
        constraint_set = result.get("constraint_set", [])
        planning_intent = result.get("planning_intent", {})
        validation_errors = result.get("validation_errors", [])
        is_valid = result.get("is_valid", False)
        section_map = result.get("section_map", [])

        print(f"\n{'='*60}")
        print(f"金田村 PARSE Agent 解析结果")
        print(f"{'='*60}")

        # Sections
        print(f"\n--- 文档分段 ({len(section_map)} 段) ---")
        for s in section_map:
            st = s.get("section_type", "?") if isinstance(s, dict) else s.section_type
            title = s.get("title", "") if isinstance(s, dict) else s.title
            has_table = s.get("has_table", False) if isinstance(s, dict) else s.has_table
            table_mark = "📊" if has_table else ""
            print(f"  [{st}] {title} {table_mark}")

        # Operations
        print(f"\n--- 操作序列 ({len(operation_sequence)} 条) ---")
        for i, op in enumerate(operation_sequence):
            action = op.get("action", "?") if isinstance(op, dict) else op.action
            source = op.get("source_text", "") if isinstance(op, dict) else op.source_text
            source_short = (source[:60] + "...") if len(source) > 60 else source
            anchor = op.get("spatial_anchor") if isinstance(op, dict) else getattr(op, "spatial_anchor", None)
            land_use = op.get("land_use_name", "") if isinstance(op, dict) else getattr(op, "land_use_name", "")
            area = op.get("area_sqm") if isinstance(op, dict) else getattr(op, "area_sqm", None)
            confidence = op.get("confidence", 0) if isinstance(op, dict) else getattr(op, "confidence", 0)

            anchor_info = ""
            if anchor:
                if isinstance(anchor, dict):
                    ref = anchor.get("reference", "")
                    offset = anchor.get("offset", "")
                    status = anchor.get("resolution_status", "")
                    candidates = anchor.get("candidate_parcels", [])
                else:
                    ref = anchor.reference
                    offset = anchor.offset or ""
                    status = anchor.resolution_status
                    candidates = anchor.candidate_parcels
                anchor_info = f" → [{status}] {ref} {offset}"
                if candidates:
                    anchor_info += f" (候选: {candidates[:3]})"

            area_info = f", {area}㎡" if area else ""
            lu_info = f", 用途={land_use}" if land_use else ""
            print(f"  {i+1}. [{action}]{lu_info}{area_info} conf={confidence:.1f}")
            print(f"     来源: {source_short}")
            if anchor_info:
                print(f"     锚定: {anchor_info}")

        # Constraints
        print(f"\n--- 约束集 ({len(constraint_set)} 条) ---")
        for i, c in enumerate(constraint_set):
            ctype = c.get("type", "?") if isinstance(c, dict) else c.type
            source = c.get("source_text", "") if isinstance(c, dict) else c.source_text
            source_short = (source[:60] + "...") if len(source) > 60 else source
            priority = c.get("priority", "") if isinstance(c, dict) else getattr(c, "priority", "")
            spatial_rule = c.get("spatial_rule") if isinstance(c, dict) else getattr(c, "spatial_rule", None)

            rule_info = ""
            if spatial_rule:
                if isinstance(spatial_rule, dict):
                    operation = spatial_rule.get("operation", "")
                    subject = spatial_rule.get("subject", "")
                    obj = spatial_rule.get("object", "")
                    dist = spatial_rule.get("distance_m")
                else:
                    operation = spatial_rule.operation
                    subject = spatial_rule.subject
                    obj = spatial_rule.object
                    dist = spatial_rule.distance_m
                dist_info = f", {dist}m" if dist else ""
                rule_info = f" → {operation}({subject}, {obj}{dist_info})"

            print(f"  {i+1}. [{ctype}] priority={priority}")
            print(f"     来源: {source_short}")
            if rule_info:
                print(f"     规则: {rule_info}")

        # Planning Intent
        zone_targets = planning_intent.get("zone_targets", [])
        facilities = planning_intent.get("facilities", [])
        axes = planning_intent.get("development_axes", [])
        print(f"\n--- 规划意图 ---")
        print(f"  分区目标: {len(zone_targets)} 个")
        for zt in zone_targets:
            lu = zt.get("land_use", "?") if isinstance(zt, dict) else zt.land_use
            ratio = zt.get("area_ratio", 0) if isinstance(zt, dict) else zt.area_ratio
            pref = zt.get("spatial_preference") if isinstance(zt, dict) else getattr(zt, "spatial_preference", None)
            pref_info = ""
            if pref:
                direction = pref.get("direction", "") if isinstance(pref, dict) else getattr(pref, "direction", None)
                reference = pref.get("reference", "") if isinstance(pref, dict) else getattr(pref, "reference", None)
                if direction or reference:
                    pref_info = f", 偏好: {direction} (ref={reference})"
            print(f"    {lu}: {ratio:.1%}{pref_info}")
        print(f"  设施需求: {len(facilities)} 个")
        for ft in facilities:
            ftype = ft.get("type", "?") if isinstance(ft, dict) else ft.type
            status = ft.get("status", "?") if isinstance(ft, dict) else ft.status
            hint = ft.get("location_hint", "") if isinstance(ft, dict) else getattr(ft, "location_hint", "")
            anchor = ft.get("anchor_village", "") if isinstance(ft, dict) else getattr(ft, "anchor_village", "")
            anchor_info = f", 锚定={anchor}" if anchor else ""
            print(f"    {ftype}: {status}, 位置={hint}{anchor_info}")
        print(f"  发展轴: {len(axes)} 个")
        for at in axes:
            direction = at.get("direction", "?") if isinstance(at, dict) else at.direction
            ref = at.get("reference_feature", "") if isinstance(at, dict) else at.reference_feature
            connects = at.get("connects", []) if isinstance(at, dict) else at.connects
            connects_info = f", 连接={connects}" if connects else ""
            print(f"    {direction}: {ref}{connects_info}")

        # Validation
        print(f"\n--- 校验结果 ---")
        print(f"  is_valid: {is_valid}")
        if validation_errors:
            print(f"  errors ({len(validation_errors)}):")
            for err in validation_errors:
                print(f"    - {err}")

        # ── Assertions ──
        assert len(section_map) > 0, "Should classify at least 1 section"
        assert len(operation_sequence) > 0 or len(constraint_set) > 0 or len(zone_targets) > 0, \
            "Should extract at least operations, constraints, or zone targets"


# ============================================================================
# 3. Individual LLM nodes
# ============================================================================


class TestParseNodesLLM:
    """Test individual PARSE Agent nodes with real LLM (cached)."""

    @pytest.mark.asyncio
    async def test_classify_sections_node(self, jintian_planning_text, jintian_gis_data):
        """Test classify_sections node with LLM."""
        _setup_llm_cache()

        from app.agent.gis.parse_agent import classify_sections_node
        from app.agent.gis.schema.parse_state import ParseAgentState
        from app.agent.gis.spatial_context import compute_spatial_context

        spatial_context = compute_spatial_context(jintian_gis_data)
        state = ParseAgentState(
            planning_text=jintian_planning_text[:8000],
            village_name="金田村",
            spatial_context=spatial_context,
        )

        result = await classify_sections_node(state)
        sections = result.get("section_map", [])

        print(f"\n--- classify_sections 结果 ({len(sections)} 段) ---")
        for s in sections:
            if isinstance(s, dict):
                print(f"  [{s.get('section_type', '?')}] {s.get('title', '')} (table={s.get('has_table', False)})")
            else:
                print(f"  [{s.section_type}] {s.title} (table={s.has_table})")

        assert len(sections) > 0, "Should classify at least 1 section"

    @pytest.mark.asyncio
    async def test_extract_projects_node(self, jintian_planning_text, jintian_gis_data):
        """Test extract_projects node with LLM."""
        _setup_llm_cache()

        from app.agent.gis.parse_agent import extract_projects_node
        from app.agent.gis.schema.parse_state import ParseAgentState, SectionInfo
        from app.agent.gis.spatial_context import compute_spatial_context

        spatial_context = compute_spatial_context(jintian_gis_data)
        state = ParseAgentState(
            planning_text=jintian_planning_text,
            village_name="金田村",
            spatial_context=spatial_context,
            section_map=[
                SectionInfo(
                    section_id="S01",
                    title="产业规划与项目安排",
                    section_type="project_table",
                    content=jintian_planning_text[:6000],
                    has_table=True,
                ),
            ],
        )

        result = await extract_projects_node(state)
        operations = result.get("raw_operations", [])

        print(f"\n--- extract_projects 结果 ({len(operations)} 条操作) ---")
        for i, op in enumerate(operations):
            action = op.get("action", "?")
            land_use = op.get("land_use_name", "")
            area = op.get("area_sqm")
            source = op.get("source_text", "")[:80]
            anchor = op.get("spatial_anchor")
            anchor_info = ""
            if anchor:
                ref = anchor.get("reference", "")
                offset = anchor.get("offset", "")
                status = anchor.get("resolution_status", "")
                candidates = anchor.get("candidate_parcels", [])
                anchor_info = f" → [{status}] {ref} {offset} (候选: {candidates[:3]})"
            print(f"  {i+1}. [{action}] {land_use} {area}㎡")
            print(f"     来源: {source}")
            if anchor_info:
                print(f"     锚定: {anchor_info}")

        # Even if no operations extracted (depends on LLM), should not crash
        assert isinstance(operations, list)

    @pytest.mark.asyncio
    async def test_lookup_code_integration(self):
        """Test lookup_land_use_code with various village planning terms."""
        from app.tools.gis.parse_tools import lookup_land_use_code

        terms = ["宅基地", "经营性建设用地", "耕地", "生态林", "水域", "道路交通"]
        print(f"\n--- lookup_land_use_code 集成测试 ---")

        for term in terms:
            result = lookup_land_use_code.invoke({"land_use_name": term})
            if result["success"]:
                data = result["data"]
                print(f"  ✅ {term}: GHYTBM={data['ghytbm']}, VNE={data['vne_code']}, "
                      f"分区={data['zone_type']}, DLBM候选={data['dlbm_aliases'][:3]}")
            else:
                print(f"  ❌ {term}: 未找到编码")

        # At least residential and farmland should work
        assert lookup_land_use_code.invoke({"land_use_name": "宅基地"})["success"]
        assert lookup_land_use_code.invoke({"land_use_name": "耕地"})["success"]


class TestEncodingValidation:
    """Encoding validation tests — verify GHYTBM code correctness."""

    def test_ghytbm_codes_all_valid(self):
        """All appendix5 GHYTBM codes should be in GHYTBM_TO_GHYTMC."""
        from app.modules.gis.schema import GHYTBM_TO_GHYTMC

        known_codes = {
            "1100", "1200", "1340", "1350", "1400", "1500", "1510",
            "2100", "2121", "2122", "2123", "2124", "2125", "2126",
            "2200", "2270", "2310", "2320", "2130", "3100", "3200",
        }
        for code in known_codes:
            assert code in GHYTBM_TO_GHYTMC, f"GHYTBM code {code} not found"

    def test_zone_type_coverage(self):
        """All GHYTBM codes should have zone_type mapping."""
        from app.modules.gis.schema import GHYTBM_TO_ZONE_TYPE, GHYTBM_TO_GHYTMC

        for code in GHYTBM_TO_GHYTMC:
            zone = GHYTBM_TO_ZONE_TYPE.get(code, "")
            assert zone, f"GHYTBM {code} ({GHYTBM_TO_GHYTMC[code]}) has no zone_type"

    def test_vne_coverage(self):
        """All GHYTBM codes should have VNE mapping."""
        from app.modules.gis.schema import GHYTBM_TO_VNE, GHYTBM_TO_GHYTMC

        for code in GHYTBM_TO_GHYTMC:
            vne = GHYTBM_TO_VNE.get(code, "")
            assert vne, f"GHYTBM {code} ({GHYTBM_TO_GHYTMC[code]}) has no VNE code"
