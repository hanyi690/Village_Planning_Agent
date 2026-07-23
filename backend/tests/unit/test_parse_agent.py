"""PARSE Agent unit tests — spatial models, spatial context, and parse tools.

Sections:
  1. Spatial Models (8 tests) — Pydantic schema validation
  2. Spatial Context (6 tests) — compute_spatial_context and sub-functions
  3. Parse Tools (4 tests) — lookup_land_use_code, extract helpers
  4. Parse Agent Graph (3 tests) — graph compilation and topology
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_landuse_geojson():
    """Minimal landuse GeoJSON with 3 parcels for testing."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"DLBM": "2121", "DLMC": "宅基地", "BSM": "P001"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[116.04, 24.83], [116.05, 24.83], [116.05, 24.84], [116.04, 24.84], [116.04, 24.83]]],
                },
            },
            {
                "type": "Feature",
                "properties": {"DLBM": "0110", "DLMC": "水田", "BSM": "P002"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[116.05, 24.83], [116.06, 24.83], [116.06, 24.84], [116.05, 24.84], [116.05, 24.83]]],
                },
            },
            {
                "type": "Feature",
                "properties": {"DLBM": "1340", "DLMC": "商品林", "BSM": "P003"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[116.06, 24.83], [116.07, 24.83], [116.07, 24.84], [116.06, 24.84], [116.06, 24.83]]],
                },
            },
        ],
    }


@pytest.fixture
def sample_boundary_geojson():
    """Minimal boundary GeoJSON."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[116.03, 24.82], [116.08, 24.82], [116.08, 24.85], [116.03, 24.85], [116.03, 24.82]]],
                },
            },
        ],
    }


@pytest.fixture
def sample_gis_data(sample_landuse_geojson, sample_boundary_geojson):
    """Complete GIS data bundle for testing."""
    return {
        "landuse_current_geojson": sample_landuse_geojson,
        "boundary_geojson": sample_boundary_geojson,
        "farmland_protection_geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[116.05, 24.83], [116.06, 24.83], [116.06, 24.84], [116.05, 24.84], [116.05, 24.83]]],
                    },
                },
            ],
        },
    }


# ============================================================================
# 1. Spatial Models (8 tests)
# ============================================================================


class TestSpatialModels:
    """Test spatially-aware Pydantic models."""

    def test_spatial_context_defaults(self):
        """SpatialContext should have sensible defaults."""
        from app.agent.gis.parse.state import SpatialContext

        ctx = SpatialContext()
        assert ctx.parcel_count == 0
        assert ctx.total_area_ha == 0.0
        assert ctx.village_center is None
        assert ctx.natural_villages == []
        assert ctx.spatial_relations == []
        assert ctx.constraint_summary == []
        assert ctx.zone_adjacency == {}

    def test_spatial_anchor_resolution_status(self):
        """SpatialAnchor resolution_status must be one of 3 values."""
        from app.agent.gis.parse.state import SpatialAnchor

        for status in ["anchored", "partial", "unresolved"]:
            anchor = SpatialAnchor(
                reference="Liu village",
                offset="east",
                confidence=0.8,
                resolution_status=status,
            )
            assert anchor.resolution_status == status

    def test_spatial_rule_operations(self):
        """SpatialRule must accept 5 operation types."""
        from app.agent.gis.parse.state import SpatialRule

        for op in ["no_overlap", "buffer_exclusion", "contained_by", "adjacent_to", "distance_within"]:
            rule = SpatialRule(operation=op, subject="construction", object="farmland")
            assert rule.operation == op

    def test_spatial_operation_with_anchor(self):
        """SpatialOperation should accept SpatialAnchor."""
        from app.agent.gis.parse.state import SpatialOperation, SpatialAnchor

        op = SpatialOperation(
            action="create",
            spatial_anchor=SpatialAnchor(
                reference="Liu village",
                offset="east",
                candidate_parcels=["XG-005"],
                confidence=0.8,
                resolution_status="partial",
            ),
            area_sqm=400,
            land_use_name="经营性建设用地",
            source_text="在刘村小组东侧新建400㎡展销中心",
        )
        assert op.action == "create"
        assert op.spatial_anchor.reference == "Liu village"
        assert op.spatial_anchor.candidate_parcels == ["XG-005"]
        assert op.location_desc is None  # No fallback needed when anchor exists

    def test_spatial_constraint_with_rule(self):
        """SpatialConstraint should accept SpatialRule."""
        from app.agent.gis.parse.state import SpatialConstraint, SpatialRule

        constraint = SpatialConstraint(
            type="spatial_constraint",
            spatial_rule=SpatialRule(
                operation="buffer_exclusion",
                subject="产业用地",
                object="居住区",
                distance_m=200,
            ),
            source_text="产业用地与居住区间距不小于200米",
            article_ref="第15条",
        )
        assert constraint.spatial_rule.operation == "buffer_exclusion"
        assert constraint.spatial_rule.distance_m == 200

    def test_spatial_planning_intent_with_targets(self):
        """SpatialPlanningIntent should accept List[ZoneTarget]."""
        from app.agent.gis.parse.state import (
            SpatialPlanningIntent,
            ZoneTarget,
            SpatialPreference,
            AdjacencyRules,
        )

        intent = SpatialPlanningIntent(
            village_name="金田村",
            zone_targets=[
                ZoneTarget(
                    land_use="居住用地",
                    area_ratio=0.35,
                    dlbm="2121",
                    spatial_preference=SpatialPreference(direction="center", reference="村委会"),
                    adjacency_rules=AdjacencyRules(prefer=["公共服务用地"], avoid=["产业用地"]),
                ),
            ],
        )
        assert intent.village_name == "金田村"
        assert len(intent.zone_targets) == 1
        assert intent.zone_targets[0].spatial_preference.direction == "center"
        assert "产业用地" in intent.zone_targets[0].adjacency_rules.avoid

    def test_parse_agent_state_with_spatial_context(self):
        """ParseAgentState should accept SpatialContext."""
        from app.agent.gis.parse.state import ParseAgentState, SpatialContext

        state = ParseAgentState(
            planning_text="规划文本...",
            village_name="金田村",
            spatial_context=SpatialContext(
                parcel_count=660,
                total_area_ha=2396.9,
                village_center=(116.048, 24.829),
            ),
        )
        assert state.spatial_context.parcel_count == 660
        assert state.spatial_context.village_center == (116.048, 24.829)

    def test_section_info_types(self):
        """SectionInfo should accept all 13 section types."""
        from app.agent.gis.parse.state import SectionInfo

        valid_types = [
            "preamble", "target", "regulation", "project_table",
            "land_use_table", "indicator_table", "heritage_table",
            "facility_table", "ecological_table", "spatial_layout",
            "protection", "infrastructure", "governance",
        ]
        for st in valid_types:
            section = SectionInfo(section_id="S01", section_type=st)
            assert section.section_type == st


# ============================================================================
# 2. Spatial Context (6 tests)
# ============================================================================


class TestSpatialContext:
    """Test compute_spatial_context and sub-functions."""

    def test_compute_centroid(self, sample_boundary_geojson):
        """_compute_centroid should return (lon, lat) tuple."""
        from app.modules.gis.spatial_context import _compute_centroid

        center = _compute_centroid(sample_boundary_geojson)
        assert center is not None
        assert len(center) == 2
        assert 110 < center[0] < 120  # Longitude range for Guangdong
        assert 20 < center[1] < 30    # Latitude range for Guangdong

    def test_compute_landuse_distribution(self, sample_landuse_geojson):
        """_compute_landuse_distribution should return sorted land-use entries."""
        from app.modules.gis.spatial_context import _compute_landuse_distribution

        entries = _compute_landuse_distribution(sample_landuse_geojson)
        assert len(entries) > 0
        # Should be sorted by area descending
        for i in range(len(entries) - 1):
            assert entries[i].area_ha >= entries[i + 1].area_ha

    def test_compute_constraint_summary(self, sample_gis_data):
        """_compute_constraint_summary should extract protection zones."""
        from app.modules.gis.spatial_context import _compute_constraint_summary

        summaries = _compute_constraint_summary(sample_gis_data)
        assert len(summaries) >= 1
        # Should have farmland protection
        farm = [s for s in summaries if s.zone_type == "farmland_protection"]
        assert len(farm) == 1
        assert farm[0].rule == "禁止建设"
        assert farm[0].area_ha > 0

    def test_compute_spatial_context_full(self, sample_gis_data):
        """compute_spatial_context should produce complete SpatialContext."""
        from app.modules.gis.spatial_context import compute_spatial_context

        ctx = compute_spatial_context(sample_gis_data)
        assert ctx.parcel_count > 0
        assert ctx.total_area_ha > 0
        assert ctx.village_center is not None
        assert len(ctx.landuse_distribution) > 0
        assert len(ctx.constraint_summary) >= 1

    def test_compute_spatial_context_empty_input(self):
        """compute_spatial_context should handle empty input gracefully."""
        from app.modules.gis.spatial_context import compute_spatial_context

        ctx = compute_spatial_context({})
        assert ctx.parcel_count == 0
        assert ctx.total_area_ha == 0.0
        assert ctx.village_center is None
        assert ctx.natural_villages == []

    def test_compute_spatial_context_jintian(self):
        """compute_spatial_context should work with real jintian test data."""
        from app.modules.gis.spatial_context import compute_spatial_context

        data_dir = Path(__file__).resolve().parents[3] / "data" / "gis" / "jintian" / "current"
        if not data_dir.exists():
            pytest.skip("Jintian test data not available")

        gis_data = {}
        for f in data_dir.glob("*.geojson"):
            key = f.stem + "_geojson"
            with open(f, "r", encoding="utf-8") as fh:
                gis_data[key] = json.load(fh)

        # Rename landuse key to expected format
        for key in list(gis_data.keys()):
            if "landuse" in key and "landuse_current" not in key:
                gis_data["landuse_current_geojson"] = gis_data.pop(key)
                break

        ctx = compute_spatial_context(gis_data)
        assert ctx.parcel_count == 660
        assert ctx.total_area_ha > 2000
        assert ctx.village_center is not None
        assert len(ctx.natural_villages) > 0
        assert len(ctx.spatial_relations) > 0
        assert len(ctx.zone_adjacency) > 0

        # Verify all landuse entries have valid dlbm
        for entry in ctx.landuse_distribution:
            assert entry.dlbm != "", f"Empty DLBM for {entry.name}"
            assert entry.count > 0
            assert entry.area_ha > 0

        # Print detailed results for review
        print(f"\n=== Jintian SpatialContext ===")
        print(f"parcel_count: {ctx.parcel_count}")
        print(f"total_area_ha: {ctx.total_area_ha:.1f}")
        print(f"village_center: {ctx.village_center}")
        print(f"natural_villages: {len(ctx.natural_villages)}")
        print(f"spatial_relations: {len(ctx.spatial_relations)}")
        print(f"zone_adjacency: {len(ctx.zone_adjacency)} zones")
        for v in ctx.natural_villages[:3]:
            print(f"  Village: {v.name}, parcels={len(v.parcel_ids)}, dominant={v.dominant_landuse}, adj={v.adjacent_to}")
        for lu in ctx.landuse_distribution[:5]:
            print(f"  Landuse: {lu.name} ({lu.dlbm}): {lu.count} parcels, {lu.area_ha:.1f} ha, zone={lu.planning_zone}")
        for r in ctx.spatial_relations[:5]:
            print(f"  Relation: {r.subject} {r.relation} {r.object} (conf={r.confidence})")


# ============================================================================
# 3. Parse Tools (4 tests)
# ============================================================================


class TestParseTools:
    """Test PARSE Agent tools."""

    def test_lookup_land_use_code_residential(self):
        """lookup_land_use_code should find '宅基地' codes."""
        from app.tools.gis.lookup import lookup_land_use_code

        result = lookup_land_use_code.invoke({"land_use_name": "宅基地"})
        assert result["success"] is True
        data = result["data"]
        assert data["ghytbm"] == "2121"
        assert data["vne_code"] == "V11"
        assert data["zone_type"] == "居住用地"

    def test_lookup_land_use_code_construction(self):
        """lookup_land_use_code should find '经营性建设用地' codes."""
        from app.tools.gis.lookup import lookup_land_use_code

        result = lookup_land_use_code.invoke({"land_use_name": "经营性建设用地"})
        assert result["success"] is True
        data = result["data"]
        assert data["ghytbm"] != ""
        assert data["zone_type"] != ""

    def test_lookup_land_use_code_not_found(self):
        """lookup_land_use_code should return failure for unknown names."""
        from app.tools.gis.lookup import lookup_land_use_code

        result = lookup_land_use_code.invoke({"land_use_name": "不存在的用地类型XYZ"})
        assert result["success"] is False

    def test_lookup_land_use_code_farmland(self):
        """lookup_land_use_code should find '耕地' codes."""
        from app.tools.gis.lookup import lookup_land_use_code

        result = lookup_land_use_code.invoke({"land_use_name": "耕地"})
        assert result["success"] is True
        data = result["data"]
        assert len(data["dlbm_aliases"]) > 0


# ============================================================================
# 4. Parse Agent Graph (3 tests)
# ============================================================================


class TestParseAgentGraph:
    """Test PARSE Agent StateGraph compilation and topology."""

    def test_graph_compiles(self):
        """PARSE Agent graph should compile without errors."""
        from app.agent.gis.parse.agent import build_parse_agent_graph

        graph = build_parse_agent_graph()
        assert graph is not None

    def test_graph_has_expected_nodes(self):
        """PARSE Agent graph should have expected functional nodes.

        v8 Think-Then-Format: explore + format pairs for projects/targets.
        """
        from app.agent.gis.parse.agent import build_parse_agent_graph

        graph = build_parse_agent_graph()
        node_names = list(graph.get_graph().nodes.keys())
        # Filter out __start__ and __end__
        functional_nodes = [n for n in node_names if not n.startswith("__")]
        assert "classify_sections" in functional_nodes
        assert "extract_regulations" in functional_nodes
        assert "extract_tables" in functional_nodes
        assert "explore_projects" in functional_nodes
        assert "format_projects" in functional_nodes
        assert "explore_targets" in functional_nodes
        assert "format_targets" in functional_nodes
        assert "validate_and_merge" in functional_nodes

    def test_route_by_section_fan_out(self):
        """route_by_section should return node names for fan-out.

        v8 Think-Then-Format: routes to explore_* nodes (fan-out start points).
        """
        from app.agent.gis.parse.agent import route_by_section
        from app.agent.gis.parse.state import ParseAgentState, SectionInfo

        state = ParseAgentState(
            section_map=[
                SectionInfo(section_id="S01", section_type="regulation", content="..."),
                SectionInfo(section_id="S02", section_type="project_table", content="...", has_table=True),
                SectionInfo(section_id="S03", section_type="target", content="..."),
            ],
        )
        targets = route_by_section(state)
        assert len(targets) >= 3  # At least regulation + projects + targets
        assert "extract_regulations" in targets
        assert "explore_projects" in targets
        assert "explore_targets" in targets
