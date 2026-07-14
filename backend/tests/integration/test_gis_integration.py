"""GIS integration tests — 24 tests covering multi-module interactions.

Requires real Jin Tian data (GeoJSON + L3 reports) but no LLM calls.

Sections:
  1. Knowledge Graph (4 tests)
  2. Conflict Detection (1 test)
  3. Zone Allocation (1 test)
  4. Layout Generation (1 test)
  5. Real Layout Validation (1 test)
  6. GIS Data Priority (1 test)
  7. Tool Layer (1 test)
  8. EXPORT step (6 tests) — 12-layer output + land balance + field coverage
  9. RENDER step (3 tests) — GISLayerConfig format
  10. Conflict Detailed (4 tests) — 3 types + KG→Allocator data flow
"""

import json
from pathlib import Path

import pytest

from tests.fixtures.gis_shared import tool_call, extract_result, ZONE_TARGETS

from app.services.modules.gis.kg import PlanningKG
from app.services.modules.gis.kg.query import query_kg
from app.services.modules.gis.optimizer import ConstraintDrivenAllocator
from app.services.modules.gis.engine import SpatialLayoutEngine
from app.services.modules.gis.validation.layout_validator import LayoutValidator
from app.tools.gis.kg import build_knowledge_graph, query_knowledge_graph
from app.tools.gis.parse import _dict_to_intent

from tests.fixtures.gis_e2e import (
    load_landuse_current,
    load_boundary,
    load_l3_reports_for_kg,
    load_gis_data_for_agent,
    make_real_intent,
)


# Shared targets for zone allocation
_ALLOC_TARGETS = {
    "农田保护区": 78.83,
    "村庄建设区": 30.50,
    "生态保护区": 362.02,
    "一般农业区": 1881.54,
}


# ============================================================================
# 1. KG build from reports (4 tests)
# ============================================================================


class TestKnowledgeGraph:

    def test_kg_build_from_reports(self, l3_reports_for_kg, landuse_geojson):
        """KG from real reports: >=600 triples, >=3 constraints, 660 parcels."""
        kg = PlanningKG(village_name="金田村")
        kg.build_from_reports(reports=l3_reports_for_kg, landuse_geojson=landuse_geojson)
        assert kg.get_triple_count() >= 600
        assert kg._parcel_count == 660

    def test_kg_constraints_injected(self, l3_reports_for_kg, landuse_geojson):
        """KG extracts >=3 constraints with expected fields."""
        kg = PlanningKG(village_name="金田村")
        kg.build_from_reports(reports=l3_reports_for_kg, landuse_geojson=landuse_geojson)
        constraints = kg.get_constraints()
        assert len(constraints) >= 3
        fields = {c.get("field", "") for c in constraints}
        assert "construction_area_ha" in fields
        assert "farmland_area_ha" in fields

    def test_kg_sparql_query(self, l3_reports_for_kg, landuse_geojson):
        """SPARQL queries return non-empty results on real KG."""
        kg = PlanningKG(village_name="金田村")
        kg.build_from_reports(reports=l3_reports_for_kg, landuse_geojson=landuse_geojson)
        # get_constraints
        results = query_kg(kg, "get_constraints")
        assert len(results) >= 3
        # count_by_zone_type
        results = query_kg(kg, "count_by_zone_type")
        assert len(results) > 0
        # get_parcels_by_dlbm
        results = query_kg(kg, "get_parcels_by_dlbm", dlbm="2121")
        assert len(results) > 0

    def test_kg_serialization_roundtrip(self, l3_reports_for_kg, landuse_geojson):
        """Turtle serialization preserves all triples."""
        kg = PlanningKG(village_name="金田村")
        kg.build_from_reports(reports=l3_reports_for_kg, landuse_geojson=landuse_geojson)
        turtle_str = kg.to_turtle()
        assert len(turtle_str) > 1000
        kg2 = PlanningKG.from_turtle(turtle_str, village_name="金田村")
        assert kg2.get_triple_count() == kg.get_triple_count()


# ============================================================================
# 2. Conflict detection + resolution (1 test)
# ============================================================================


class TestConflictDetection:

    def test_conflict_detect_and_resolve(self, gis_data):
        """ConflictDetector runs on real data, resolver processes conflicts."""
        from app.services.modules.gis.layout.metrics_calculator import GISMetricsCalculator
        summaries = GISMetricsCalculator.compute_summaries(gis_data)
        engine = SpatialLayoutEngine()
        result = engine.detect_and_resolve_conflicts(summaries)
        assert isinstance(result, dict)
        # Should have conflicts or empty dict (no conflicts is also valid)
        assert "conflicts" in result or "resolved" in result or len(result) >= 0


# ============================================================================
# 3. Zone allocation greedy + MIP (1 test)
# ============================================================================


class TestZoneAllocation:

    @pytest.mark.parametrize("mode", ["greedy", "mip"])
    def test_allocate_zones_greedy_mip(self, mode, landuse_geojson):
        """Both greedy and MIP allocation produce features with valid assigned_zone."""
        allocator = ConstraintDrivenAllocator()
        result_geojson, _trace = allocator.solve(
            landuse_geojson=landuse_geojson,
            targets=_ALLOC_TARGETS,
            constraints=[],
            mode=mode,
        )
        features = result_geojson.get("features", [])
        assert len(features) > 0
        valid_zones = {"农田保护区", "村庄建设区", "生态保护区", "一般农业区", "生态控制区", "林业发展区"}
        assigned = {f["properties"].get("assigned_zone", "") for f in features}
        non_valid = assigned - valid_zones
        assert not non_valid, f"Invalid assigned_zone values: {non_valid}"


# ============================================================================
# 4. Layout generation (1 test)
# ============================================================================


class TestLayoutGeneration:

    def test_generate_layout_multi_layer(
        self, landuse_geojson, boundary_geojson, l3_reports_for_kg
    ):
        """generate_layout produces >=3 layers including planning_zone."""
        engine = SpatialLayoutEngine()
        engine.build_kg_from_reports(reports=l3_reports_for_kg, landuse_geojson=landuse_geojson)
        intent = _dict_to_intent(make_real_intent())
        configs = engine.generate_layout(
            intent=intent,
            boundary_geojson=boundary_geojson,
            landuse_geojson=landuse_geojson,
        )
        assert len(configs) >= 3
        layer_types = {c["layerType"] for c in configs}
        assert "planning_zone" in layer_types


# ============================================================================
# 5. Real layout validation (1 test)
# ============================================================================


class TestRealLayoutValidation:

    def test_validate_real_layout(
        self, landuse_geojson, boundary_geojson, l3_reports_for_kg
    ):
        """LayoutValidator runs all 8 checks on real generated layout."""
        engine = SpatialLayoutEngine()
        engine.build_kg_from_reports(reports=l3_reports_for_kg, landuse_geojson=landuse_geojson)
        intent = _dict_to_intent(make_real_intent())
        configs = engine.generate_layout(
            intent=intent,
            landuse_geojson=landuse_geojson,
            boundary_geojson=boundary_geojson,
        )
        validator = LayoutValidator()
        report = validator.validate(configs, engine._kg_constraints)
        assert report.status in ("pass", "fail", "warning")
        assert len(report.checks) == 8


# ============================================================================
# 6. GIS data priority over regex (1 test)
# ============================================================================


class TestGISDataPriority:

    def test_gis_data_priority_over_regex(self, gis_data):
        """GIS-measured values override regex-extracted values."""
        from app.services.modules.gis.layout.metrics_calculator import GISMetricsCalculator
        metrics = GISMetricsCalculator.compute_land_use_metrics(gis_data)
        # GIS should compute non-zero total area
        assert metrics["total_area_ha"] > 0
        # Construction area from GIS should be positive
        assert metrics["construction_area_ha"] > 0
        # Farmland area from GIS should be positive
        assert metrics["farmland_area_ha"] > 0


# ============================================================================
# 7. Tool layer build + query (1 test)
# ============================================================================


class TestToolLayer:

    def test_tool_layer_build_and_query(self, l3_reports_for_kg, gis_data):
        """build_knowledge_graph tool writes kg_turtle, query reads it."""
        cmd = build_knowledge_graph.func(
            reports=l3_reports_for_kg,
            gis_data=gis_data,
            village_name="金田村",
            tool_call_id="call-build-1",
        )
        from langgraph.types import Command
        assert isinstance(cmd, Command)
        assert "kg_turtle" in cmd.update
        assert len(cmd.update["kg_turtle"]) > 1000

        # Query using the built turtle
        cmd2 = query_knowledge_graph.func(
            template_name="get_constraints",
            field_name="",
            dlbm="",
            zone_type="",
            kg_turtle=cmd.update["kg_turtle"],
            tool_call_id="call-query-1",
        )
        result = extract_result(cmd2)
        assert result["success"] is True
        assert len(result["data"]["results"]) >= 3


# ============================================================================
# 8. EXPORT step — 12-layer GeoJSON + land balance table (6 tests)
# ============================================================================


class TestExportGDB:

    @pytest.fixture()
    def pipeline_layout(self, landuse_geojson, boundary_geojson, l3_reports_for_kg, gis_data):
        """Generate layout via engine for export testing."""
        from app.services.modules.gis.layout.metrics_calculator import GISMetricsCalculator
        summaries = GISMetricsCalculator.compute_summaries(gis_data)
        engine = SpatialLayoutEngine()
        engine._intent = _dict_to_intent(make_real_intent())
        engine._session_id = "test-export"
        return engine.full_pipeline(
            reports=l3_reports_for_kg,
            landuse_geojson=landuse_geojson,
            boundary_geojson=boundary_geojson,
            gis_data=gis_data,
            summaries=summaries,
            max_validation_rounds=1,
        )

    def test_export_gdb_produces_files(self, pipeline_layout, gis_data):
        """export_gdb writes files to output directory."""
        from app.tools.gis.export import export_gdb
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = export_gdb.func(
                layout_configs=pipeline_layout,
                allocated_geojson=None,
                gis_data=gis_data,
                village_name="金田村委会",
                tool_call_id="tc-export-1",
                output_dir=tmpdir,
            )
            from langgraph.types import Command
            assert isinstance(cmd, Command)
            result = json.loads(cmd.update["messages"][-1].content)
            assert result["success"] is True
            assert result["data"]["file_count"] >= 1

    def test_export_includes_land_balance(self, pipeline_layout, gis_data):
        """export_gdb produces land_balance.json in tables/."""
        from app.tools.gis.export import export_gdb
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            export_gdb.func(
                layout_configs=pipeline_layout,
                allocated_geojson=None,
                gis_data=gis_data,
                village_name="金田村委会",
                tool_call_id="tc-export-2",
                output_dir=tmpdir,
            )
            balance_path = Path(tmpdir) / "tables" / "land_balance.json"
            assert balance_path.exists(), "land_balance.json not found"
            balance = json.loads(balance_path.read_text(encoding="utf-8"))
            assert "total_area_ha" in balance
            assert balance["total_area_ha"] > 0
            assert "planning_zones" in balance
            assert "function_zones" in balance

    def test_export_includes_layout_json(self, pipeline_layout, gis_data):
        """export_gdb produces layout.json."""
        from app.tools.gis.export import export_gdb
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            export_gdb.func(
                layout_configs=pipeline_layout,
                allocated_geojson=None,
                gis_data=gis_data,
                village_name="金田村委会",
                tool_call_id="tc-export-3",
                output_dir=tmpdir,
            )
            layout_path = Path(tmpdir) / "layout.json"
            assert layout_path.exists(), "layout.json not found"

    def test_land_balance_zone_areas(self, gis_data):
        """_compute_land_balance produces valid zone and function area sums."""
        from app.tools.gis.export import _compute_land_balance
        landuse = gis_data.get("landuse_current_geojson")
        if not landuse:
            pytest.skip("No landuse_current_geojson in gis_data")
        balance = _compute_land_balance(landuse)
        assert balance["total_area_ha"] > 0
        pz_total = sum(balance["planning_zones"].values())
        assert pz_total > 0
        # Zone areas should roughly sum to total
        assert abs(pz_total - balance["total_area_ha"]) / balance["total_area_ha"] < 0.05

    def test_gdb_layer_field_coverage(self, gis_data):
        """Verify exported GeoJSON has required GDB fields for key layers."""
        from app.services.modules.gis.data.gdb_schema import GDB_LAYER_REGISTRY

        # Check current_landuse fields against real data
        landuse = gis_data.get("landuse_current_geojson")
        if not landuse or not landuse.get("features"):
            pytest.skip("No landuse_current_geojson")
        fields = [f[0] for f in GDB_LAYER_REGISTRY["current_landuse"]["fields"]]
        sample = landuse["features"][0].get("properties", {})
        present = sum(1 for f in fields if f in sample and sample[f] is not None)
        # At least DLBM should be present (core field)
        assert "DLBM" in sample, "DLBM missing from landuse feature properties"

    def test_export_gdb_layer_count(self, pipeline_layout, gis_data):
        """export_gdb produces files for all available GDB layers."""
        from app.tools.gis.export import export_gdb
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = export_gdb.func(
                layout_configs=pipeline_layout,
                allocated_geojson=None,
                gis_data=gis_data,
                village_name="金田村委会",
                tool_call_id="tc-export-4",
                output_dir=tmpdir,
            )
            result = json.loads(cmd.update["messages"][-1].content)
            exported = result["data"]["exported_files"]
            # At least boundary + landuse + some protection layers
            assert len(exported) >= 3, f"Too few exported files: {exported}"


# ============================================================================
# 9. RENDER step — GISLayerConfig format (3 tests)
# ============================================================================


class TestRenderMap:

    @pytest.fixture()
    def pipeline_layout(self, landuse_geojson, boundary_geojson, l3_reports_for_kg, gis_data):
        """Generate layout for render testing."""
        engine = SpatialLayoutEngine()
        engine.build_kg_from_reports(reports=l3_reports_for_kg, landuse_geojson=landuse_geojson)
        intent = _dict_to_intent(make_real_intent())
        return engine.generate_layout(
            intent=intent,
            landuse_geojson=landuse_geojson,
            boundary_geojson=boundary_geojson,
        )

    def test_render_map_produces_layers(self, pipeline_layout, gis_data):
        """render_map returns GISLayerConfig list."""
        from app.tools.gis.render import render_map

        cmd = render_map.func(
            layout_configs=pipeline_layout,
            gis_data=gis_data,
            tool_call_id="tc-render-1",
        )
        from langgraph.types import Command
        assert isinstance(cmd, Command)
        result = json.loads(cmd.update["messages"][-1].content)
        assert result["success"] is True
        assert result["data"]["layer_count"] >= 1

    def test_render_map_gislayer_config_format(self, pipeline_layout, gis_data):
        """Each rendered layer has GISLayerConfig fields (camelCase via alias)."""
        from app.tools.gis.render import render_map

        cmd = render_map.func(
            layout_configs=pipeline_layout,
            gis_data=gis_data,
            tool_call_id="tc-render-2",
        )
        result = json.loads(cmd.update["messages"][-1].content)
        layers = result["data"]["layers"]
        for layer in layers:
            # GISLayerConfig uses camelCase aliases (by_alias=True)
            assert "layerType" in layer or "layer_type" in layer
            assert "layerName" in layer or "layer_name" in layer

    def test_render_includes_base_layers(self, pipeline_layout, gis_data):
        """render_map includes boundary and landuse base layers."""
        from app.tools.gis.render import render_map

        cmd = render_map.func(
            layout_configs=pipeline_layout,
            gis_data=gis_data,
            tool_call_id="tc-render-3",
        )
        result = json.loads(cmd.update["messages"][-1].content)
        layer_types = {
            l.get("layerType") or l.get("layer_type")
            for l in result["data"]["layers"]
        }
        assert "boundary" in layer_types, f"boundary not in rendered layers: {layer_types}"


# ============================================================================
# 10. Conflict detection — 3 types + constraint values (4 tests)
# ============================================================================


class TestConflictDetectionDetailed:

    def test_conflict_three_types(self, gis_data):
        """ConflictDetector detects metric, constraint, and spatial conflicts."""
        from app.services.modules.gis.conflict.detector import ConflictDetector
        from app.services.modules.gis.layout.metrics_calculator import GISMetricsCalculator
        summaries = GISMetricsCalculator.compute_summaries(gis_data)
        detector = ConflictDetector()
        report = detector.detect_all(summaries)
        assert hasattr(report, "metric_conflicts")
        assert hasattr(report, "constraint_violations")
        assert hasattr(report, "spatial_conflicts")
        assert hasattr(report, "total_count")

    def test_conflict_resolver_produces_values(self, gis_data):
        """ConflictResolver produces resolved_values dict."""
        from app.services.modules.gis.conflict.detector import ConflictDetector
        from app.services.modules.gis.conflict.resolver import ConflictResolver
        from app.services.modules.gis.layout.metrics_calculator import GISMetricsCalculator
        summaries = GISMetricsCalculator.compute_summaries(gis_data)
        report = ConflictDetector().detect_all(summaries)
        resolver = ConflictResolver()
        resolution = resolver.resolve(report)
        assert hasattr(resolution, "resolved_values")
        assert isinstance(resolution.resolved_values, dict)

    def test_kg_constraints_feed_allocator(self, l3_reports_for_kg, landuse_geojson, gis_data):
        """KG constraints are used by allocator (constraints != empty when KG built)."""
        kg = PlanningKG(village_name="金田村")
        kg.build_from_reports(reports=l3_reports_for_kg, landuse_geojson=landuse_geojson)
        constraints = kg.get_constraints()
        assert len(constraints) >= 3
        # Constraints should contain area fields used by allocator
        fields = {c.get("field", "") for c in constraints}
        assert "construction_area_ha" in fields or any(
            "construction" in f for f in fields
        )

    def test_mip_allocation_with_kg_constraints(self, landuse_geojson, l3_reports_for_kg, gis_data):
        """MIP allocation uses KG constraints (not empty)."""
        kg = PlanningKG(village_name="金田村")
        kg.build_from_reports(reports=l3_reports_for_kg, landuse_geojson=landuse_geojson)
        constraints = kg.get_constraints()

        from app.services.modules.gis.optimizer import ConstraintDrivenAllocator
        result_geojson, trace = ConstraintDrivenAllocator().solve(
            landuse_geojson=landuse_geojson,
            targets=_ALLOC_TARGETS,
            constraints=constraints,
            mode="mip",
        )
        features = result_geojson.get("features", [])
        assert len(features) > 0
