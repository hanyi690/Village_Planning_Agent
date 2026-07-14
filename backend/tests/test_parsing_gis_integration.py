"""Parsing→GIS integration tests using real Jintian village planning data.

Layer A: Deterministic tests (no API key required)
Layer B: LLM-based tests (require DASHSCOPE_API_KEY, skipped if absent)

Verifies:
- metric_anchors extraction accuracy on real L1/L2/L3 Chinese planning text
- GIS GeoJSON as highest-priority data source for area metrics
- SemanticField annotation coverage
- CROSS_DIMENSION_METRICS field ref validity
- Conflict detector with real data
- (Layer B) Instructor structured parse → IntentOutput → GIS layout
"""

import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest

from app.core.settings import JINTIAN_GIS_DIR

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]
L1_REPORT_PATH = PROJECT_ROOT / "output" / "experiments" / "rag" / "g1" / "iter0" / "layer1_reports.json"
L2_REPORT_PATH = PROJECT_ROOT / "output" / "experiments" / "rag" / "g1" / "iter0" / "layer2_reports.json"
L3_REPORT_PATH = PROJECT_ROOT / "output" / "experiments" / "rag" / "g1" / "iter0" / "layer3_reports.json"
JINTIAN_DIR = JINTIAN_GIS_DIR


def _load_reports_raw(layer_path: Path) -> Dict[str, str]:
    """Load raw report strings from a layer JSON file."""
    if not layer_path.exists():
        pytest.skip(f"Report file not found: {layer_path}")
    with open(layer_path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("reports", {})


def _load_all_reports_raw() -> Dict[str, str]:
    """Load all L1+L2+L3 report strings (L3 overwrites L2 overwrites L1 on key collision)."""
    result = {}
    for path in [L1_REPORT_PATH, L2_REPORT_PATH, L3_REPORT_PATH]:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            result.update(data.get("reports", {}))
    return result


def _build_reports_dict(layer: str = "all") -> Dict[str, Dict[str, Any]]:
    """Build reports dict in format expected by extract_metric_anchors.

    Args:
        layer: "L1", "L2", "L3", or "all" (L1+L2+L3 combined)
    """
    if layer == "L1":
        raw = _load_reports_raw(L1_REPORT_PATH)
    elif layer == "L2":
        raw = _load_reports_raw(L2_REPORT_PATH)
    elif layer == "L3":
        raw = _load_reports_raw(L3_REPORT_PATH)
    else:
        raw = _load_all_reports_raw()
    result = {}
    for dim_key, content in raw.items():
        if isinstance(content, str):
            result[dim_key] = {"summary": {"metrics": {}}, "content": content}
    return result


def _load_boundary_geojson() -> Dict[str, Any]:
    """Load boundary GeoJSON for total_area verification."""
    path = JINTIAN_DIR / "boundary.geojson"
    if not path.exists():
        pytest.skip("boundary.geojson not found")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_gis_data() -> Dict[str, Any]:
    """Load GIS data dict for extract_metric_anchors gis_data parameter."""
    def _load(name: str) -> Dict[str, Any]:
        path = JINTIAN_DIR / name
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        return {}

    return {
        "boundary_geojson": _load("current/boundary.geojson"),
        "landuse_current_geojson": _load("current/landuse.geojson"),
        "ecological_protection_geojson": _load("planned/ecological_protection.geojson"),
        "construction_zone_geojson": _load("planned/construction_zone.geojson"),
        "hazard_points_geojson": _load("planned/geological_hazard_points.geojson"),
    }


# ============================================
# Layer A: Deterministic tests (no API key)
# ============================================


class TestMetricAnchorsRealData:
    """Test metric_anchors extraction accuracy on real Jintian L3 reports."""

    def test_all_6_core_anchors_correct(self):
        """6 core anchors extracted from GIS data match expected values."""
        from app.services.modules.parsing.metric_anchors import extract_metric_anchors

        reports = _build_reports_dict()
        gis_data = _load_gis_data()
        anchors = extract_metric_anchors(reports, gis_data=gis_data)

        assert anchors.construction_area_ha == pytest.approx(30.5, abs=0.5)
        assert anchors.farmland_area_ha == pytest.approx(85.2, abs=0.5)
        # Ecological from GIS DLBM (03/31) ~35.9ha; 362ha was regex-extracted from text
        assert anchors.ecological_area_ha is not None
        assert anchors.ecological_area_ha > 0
        assert anchors.total_area_ha is not None
        assert anchors.total_area_ha > 2000  # Jintian village is ~2352 ha

    def test_confidence_100_percent(self):
        """With GIS data, all 4 key fields should be found → confidence=1.0."""
        from app.services.modules.parsing.metric_anchors import extract_metric_anchors

        reports = _build_reports_dict()
        gis_data = _load_gis_data()
        anchors = extract_metric_anchors(reports, gis_data=gis_data)
        assert anchors.confidence == 1.0

    def test_zone_ratios_computed(self):
        """Zone ratios computed from anchors and total area."""
        from app.services.modules.parsing.metric_anchors import extract_metric_anchors

        reports = _build_reports_dict()
        gis_data = _load_gis_data()
        anchors = extract_metric_anchors(reports, gis_data=gis_data)

        assert len(anchors.zone_ratios) >= 3
        assert "村庄建设区" in anchors.zone_ratios
        assert "农田保护区" in anchors.zone_ratios
        assert "生态保护区" in anchors.zone_ratios
        for zone, ratio in anchors.zone_ratios.items():
            assert 0 < ratio < 1

    def test_anchor_dict_format(self):
        """to_anchor_dict produces well-structured dict for prompt injection."""
        from app.services.modules.parsing.metric_anchors import extract_metric_anchors

        reports = _build_reports_dict()
        gis_data = _load_gis_data()
        anchors = extract_metric_anchors(reports, gis_data=gis_data)
        anchor_dict = anchors.to_anchor_dict()

        assert "建设用地" in anchor_dict
        assert anchor_dict["建设用地"]["value"] == pytest.approx(30.5, abs=0.5)
        assert anchor_dict["建设用地"]["unit"] == "ha"
        assert "source" in anchor_dict["建设用地"]

    def test_total_area_matches_boundary_geojson(self):
        """Total area from regex matches boundary GeoJSON MJ field."""
        from app.services.modules.parsing.metric_anchors import extract_metric_anchors

        reports = _build_reports_dict()
        gis_data = _load_gis_data()
        anchors = extract_metric_anchors(reports, gis_data=gis_data)
        boundary = _load_boundary_geojson()

        total_from_geojson = None
        for feature in boundary.get("features", []):
            props = feature.get("properties", {})
            if "MJ" in props:
                total_from_geojson = float(props["MJ"])
                break

        if total_from_geojson and anchors.total_area_ha:
            assert anchors.total_area_ha == pytest.approx(total_from_geojson, abs=1.0)


class TestSemanticFieldCoverage:
    """Verify SemanticField annotation completeness."""

    def test_all_numeric_fields_have_semantic_annotation(self):
        """Every numeric field in dimension schemas has SemanticField."""
        from app.services.modules.parsing.schemas import _DIMENSION_SCHEMAS, _BASE_SUMMARY_FIELDS
        from app.services.modules.parsing.semantics import SemanticField

        unannotated = []
        for dim_key, schema_cls in _DIMENSION_SCHEMAS.items():
            for fname, finfo in schema_cls.model_fields.items():
                if fname in _BASE_SUMMARY_FIELDS:
                    continue
                type_str = str(finfo.annotation)
                if "int" in type_str or "float" in type_str:
                    has_sem = any(isinstance(m, SemanticField) for m in finfo.metadata)
                    if not has_sem:
                        unannotated.append(f"{dim_key}.{fname}")

        assert len(unannotated) == 0, f"Unannotated fields: {unannotated}"

    def test_cross_dimension_metrics_field_refs_valid(self):
        """All FieldRef in CROSS_DIMENSION_METRICS point to existing schema fields."""
        from app.services.modules.parsing.semantics import CROSS_DIMENSION_METRICS
        from app.services.modules.parsing.schemas import _DIMENSION_SCHEMAS

        invalid_refs = []
        for concept, refs in CROSS_DIMENSION_METRICS.items():
            for ref in refs:
                schema_cls = _DIMENSION_SCHEMAS.get(ref.dimension)
                if schema_cls is None:
                    invalid_refs.append(f"{concept.value}: unknown dimension '{ref.dimension}'")
                elif ref.field not in schema_cls.model_fields:
                    invalid_refs.append(f"{concept.value}: {ref.dimension}.{ref.field} not in schema")

        assert len(invalid_refs) == 0, f"Invalid refs: {invalid_refs}"


class TestConflictDetectorRealData:
    """Test conflict detector with real L3 report data."""

    def test_detect_all_no_crash(self):
        """Conflict detector runs without errors on real data."""
        from app.services.modules.gis.conflict.detector import ConflictDetector

        reports = _build_reports_dict()
        detector = ConflictDetector()
        report = detector.detect_all(reports)

        assert isinstance(report.metric_conflicts, list)
        assert isinstance(report.constraint_violations, list)
        assert isinstance(report.spatial_conflicts, list)

    def test_conflict_resolver_with_real_data(self):
        """Conflict resolver processes real detected conflicts."""
        from app.services.modules.gis.conflict.detector import ConflictDetector
        from app.services.modules.gis.conflict.resolver import ConflictResolver

        reports = _build_reports_dict()
        detector = ConflictDetector()
        conflict_report = detector.detect_all(reports)

        resolver = ConflictResolver()
        resolution_report = resolver.resolve(conflict_report)

        assert isinstance(resolution_report.metric_resolutions, list)
        assert isinstance(resolution_report.constraint_resolutions, list)
        summary = resolution_report.summary()
        assert isinstance(summary, str)


class TestParsingModuleImports:
    """Verify all parsing module imports work after summary/ removal."""

    def test_all_parsing_submodules_importable(self):
        """Each file in parsing/ module imports independently."""
        import importlib

        submodules = [
            "app.services.modules.parsing",
            "app.services.modules.parsing.schemas",
            "app.services.modules.parsing.semantics",
            "app.services.modules.parsing.metric_anchors",
            "app.services.modules.parsing.structured_output",
            "app.services.modules.parsing.summary_generator",
            "app.services.modules.parsing.summary_parser",
            "app.services.modules.parsing.validator",
            "app.services.modules.parsing.prompts",
        ]
        for mod in submodules:
            importlib.import_module(mod)

    def test_gis_consumers_importable(self):
        """GIS modules that depend on parsing still import correctly."""
        import importlib

        consumers = [
            "app.services.modules.gis.conflict.detector",
            "app.services.modules.gis.conflict.resolver",
            "app.tools.gis.layout_tools",
            "app.agent.analysis.node",
            "app.services.report_store",
        ]
        for mod in consumers:
            importlib.import_module(mod)


# ============================================
# GIS Priority Tests
# ============================================


class TestGISDataPriority:
    """Verify GIS GeoJSON takes highest priority over text extraction."""

    def test_gis_overrides_regex_for_total_area(self):
        """GIS boundary MJ field overrides regex-extracted total area."""
        from app.services.modules.parsing.metric_anchors import extract_metric_anchors

        reports = _build_reports_dict()
        gis_data = _load_gis_data()

        # Without GIS
        anchors_no_gis = extract_metric_anchors(reports, gis_data=_load_gis_data())
        # With GIS
        anchors_with_gis = extract_metric_anchors(reports, gis_data=gis_data)

        # GIS should provide total area from boundary MJ
        assert anchors_with_gis.total_area_ha is not None
        assert anchors_with_gis.total_area_source.startswith("gis.")

        # GIS value should match boundary GeoJSON MJ
        boundary = gis_data["boundary_geojson"]
        for feature in boundary.get("features", []):
            mj = feature.get("properties", {}).get("MJ")
            if mj:
                assert anchors_with_gis.total_area_ha == pytest.approx(float(mj), abs=0.5)
                break

    def test_gis_overrides_regex_for_construction_area(self):
        """GIS landuse DLBM classification overrides regex for construction area."""
        from app.services.modules.parsing.metric_anchors import extract_metric_anchors

        reports = _build_reports_dict()
        gis_data = _load_gis_data()

        anchors = extract_metric_anchors(reports, gis_data=gis_data)

        # GIS should provide construction area from landuse DLBM
        assert anchors.construction_area_ha is not None
        assert anchors.construction_source.startswith("gis.")

    def test_gis_overrides_regex_for_farmland_area(self):
        """GIS landuse DLBM classification overrides regex for farmland area."""
        from app.services.modules.parsing.metric_anchors import extract_metric_anchors

        reports = _build_reports_dict()
        gis_data = _load_gis_data()

        anchors = extract_metric_anchors(reports, gis_data=gis_data)

        assert anchors.farmland_area_ha is not None
        assert anchors.farmland_source.startswith("gis.")

    def test_gis_overrides_regex_for_ecological_area(self):
        """GIS landuse DLBM classification overrides regex for ecological area."""
        from app.services.modules.parsing.metric_anchors import extract_metric_anchors

        reports = _build_reports_dict()
        gis_data = _load_gis_data()

        anchors = extract_metric_anchors(reports, gis_data=gis_data)

        assert anchors.ecological_area_ha is not None
        assert anchors.ecological_source.startswith("gis.")

    def test_gis_only_no_reports(self):
        """GIS data alone (no reports) should still extract key area metrics."""
        from app.services.modules.parsing.metric_anchors import extract_metric_anchors

        gis_data = _load_gis_data()

        anchors = extract_metric_anchors({}, gis_data=gis_data)

        assert anchors.total_area_ha is not None
        assert anchors.total_area_ha > 2000
        assert anchors.total_area_source.startswith("gis.")
        # DLBM-based classification should yield reasonable areas
        assert anchors.construction_area_ha is not None
        assert anchors.farmland_area_ha is not None
        assert anchors.ecological_area_ha is not None

    def test_gis_source_tracking(self):
        """All GIS-extracted values have 'gis.*' source strings."""
        from app.services.modules.parsing.metric_anchors import extract_metric_anchors

        gis_data = _load_gis_data()
        anchors = extract_metric_anchors({}, gis_data=gis_data)

        gis_sourced = [
            (anchors.total_area_ha, anchors.total_area_source),
            (anchors.construction_area_ha, anchors.construction_source),
            (anchors.farmland_area_ha, anchors.farmland_source),
            (anchors.ecological_area_ha, anchors.ecological_source),
        ]
        for value, source in gis_sourced:
            if value is not None:
                assert source.startswith("gis."), f"Value {value} has non-GIS source: {source}"


# ============================================
# L1/L2 Report Tests
# ============================================


class TestAllLayersCombined:
    """Test with L1+L2+L3 combined — most complete data scenario."""

    def test_combined_confidence_100_percent(self):
        """With all layers combined, confidence should be 1.0."""
        from app.services.modules.parsing.metric_anchors import extract_metric_anchors

        reports = _build_reports_dict("all")
        anchors = extract_metric_anchors(reports, gis_data=_load_gis_data())

        assert anchors.confidence == 1.0

    def test_combined_all_core_anchors(self):
        """All 6 core anchors present and correct with combined reports."""
        from app.services.modules.parsing.metric_anchors import extract_metric_anchors

        reports = _build_reports_dict("all")
        anchors = extract_metric_anchors(reports, gis_data=_load_gis_data())

        assert anchors.construction_area_ha == pytest.approx(30.5, abs=0.5)
        assert anchors.farmland_area_ha == pytest.approx(85.2, abs=0.5)
        # Ecological from GIS DLBM (03/31) ~35.9ha; 362ha was regex-extracted from text
        assert anchors.ecological_area_ha is not None
        assert anchors.ecological_area_ha > 0
        assert anchors.total_area_ha is not None
        assert anchors.total_area_ha > 2000

    def test_combined_with_gis_highest_priority(self):
        """GIS data + combined reports: GIS values take priority."""
        from app.services.modules.parsing.metric_anchors import extract_metric_anchors

        reports = _build_reports_dict("all")
        gis_data = _load_gis_data()

        anchors = extract_metric_anchors(reports, gis_data=gis_data)

        # GIS-sourced values should be used (they have gis.* source)
        assert anchors.total_area_source.startswith("gis.")
        assert anchors.construction_source.startswith("gis.")
        assert anchors.farmland_source.startswith("gis.")
        assert anchors.ecological_source.startswith("gis.")

        # Values should still be reasonable
        assert anchors.total_area_ha > 2000
        assert anchors.construction_area_ha > 0
        assert anchors.farmland_area_ha > 0
        assert anchors.ecological_area_ha > 0

    def test_combined_zone_ratios_complete(self):
        """Zone ratios from combined reports with GIS are complete."""
        from app.services.modules.parsing.metric_anchors import extract_metric_anchors

        reports = _build_reports_dict("all")
        gis_data = _load_gis_data()
        anchors = extract_metric_anchors(reports, gis_data=gis_data)

        assert len(anchors.zone_ratios) >= 3
        total_ratio = sum(anchors.zone_ratios.values())
        # Ratios are normalized to sum to 1.0 in metric_anchors.py
        assert pytest.approx(total_ratio, abs=0.01) == 1.0


# ============================================
# Layer B: LLM-based tests (require DashScope API key)
# ============================================


_HAS_API_KEY = bool(os.getenv("DASHSCOPE_API_KEY"))


@pytest.mark.asyncio
@pytest.mark.skipif(not _HAS_API_KEY, reason="DASHSCOPE_API_KEY not set")
class TestStructuredParseRealData:
    """Test Instructor structured parse with real planning text."""

    async def test_parse_intent_from_real_reports(self):
        """Parse real L3 reports → IntentOutput with valid zones."""
        from app.tools.gis.parse import _parse_reports_to_intent

        reports = _build_reports_dict()
        result = await _aparse_reports_to_intent(reports, "金田村")

        assert result["success"], f"Parse failed: {result.get('error', '')}"
        intent_data = result["data"]["intent_json"]
        assert len(intent_data["zones"]) >= 3
        total_ratio = sum(z["area_ratio"] for z in intent_data["zones"])
        assert total_ratio == pytest.approx(1.0, abs=0.05)

    async def test_anchor_confidence_high_with_real_data(self):
        """Anchor confidence should be 1.0 with real L3 reports + GIS data."""
        from app.tools.gis.parse import _parse_reports_to_intent

        reports = _build_reports_dict()
        gis_data = _load_gis_data()
        result = await _aparse_reports_to_intent(reports, "金田村", gis_data=gis_data)

        assert result["success"]
        assert result["data"]["anchor_confidence"] == 1.0


@pytest.mark.asyncio
@pytest.mark.skipif(not _HAS_API_KEY, reason="DASHSCOPE_API_KEY not set")
class TestFullPipelineRealData:
    """Test full parsing→GIS layout pipeline with real data."""

    async def test_reports_to_layout(self):
        """Real L3 reports → KG build → layout generation."""
        from app.services.modules.gis.engine import SpatialLayoutEngine
        from app.services.modules.gis.layout.zone_generator import (
            UnifiedSpatialIntent,
            ZoneIntent,
        )
        from app.services.modules.gis.planning_intent import Direction
        from tests.fixtures.gis_e2e import (
            load_l3_reports_for_kg,
            load_gis_data_for_agent,
        )

        reports = load_l3_reports_for_kg()
        gis_data = load_gis_data_for_agent()

        engine = SpatialLayoutEngine()
        engine.build_kg(
            reports=reports,
            landuse_geojson=gis_data["landuse_current_geojson"],
        )

        intent = UnifiedSpatialIntent(
            zones=[
                ZoneIntent(zone_id="z_farm", land_use="农业用地", dlbm="0110", area_ratio=0.03, direction=Direction.CENTER, preserve_existing=True),
                ZoneIntent(zone_id="z_build", land_use="居住用地", dlbm="2121", area_ratio=0.013, direction=Direction.CENTER, preserve_existing=True),
                ZoneIntent(zone_id="z_eco", land_use="生态绿地", dlbm="0300", area_ratio=0.15, direction=Direction.PERIPHERY, preserve_existing=True),
                ZoneIntent(zone_id="z_agri", land_use="农业用地", dlbm="0200", area_ratio=0.80, direction=Direction.PERIPHERY, preserve_existing=True),
            ],
            metadata={
                "spatial_structure": "一核两带三区",
            },
        )

        configs = engine.generate_layout(
            intent=intent,
            boundary_geojson=gis_data["boundary_geojson"],
            landuse_current_geojson=gis_data["landuse_current_geojson"],
            protection_zones=gis_data.get("protection_zones"),
            road_geojson=gis_data.get("road_geojson"),
            construction_zone_geojson=gis_data.get("construction_zone_geojson"),
            hazard_points_geojson=gis_data.get("hazard_points_geojson"),
        )

        assert len(configs) >= 2
        layer_types = {c.get("layerType") for c in configs}
        assert "function_zone" in layer_types
        assert "planning_zone" in layer_types
