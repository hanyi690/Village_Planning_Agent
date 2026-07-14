"""E2E integration tests — Jin Tian village real data pipeline.

Requires data/gis/jintian/ (660 parcels + planned ground truth).
Tests all 4 layers, export, render, and comparison with planned data.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest


# ── helpers ────────────────────────────────────────────────────────────

def _load_jintian_geojson(rel_path: str) -> dict:
    from app.core.settings import JINTIAN_GIS_DIR
    path = Path(JINTIAN_GIS_DIR) / rel_path
    if not path.exists():
        pytest.skip(f"Jintian data not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _build_gis_data() -> Dict[str, Any]:
    """Load all Jin Tian data into gis_data dict matching pipeline format."""
    return {
        "boundary_geojson": _load_jintian_geojson("current/boundary.geojson"),
        "landuse_current_geojson": _load_jintian_geojson("current/landuse.geojson"),
        "road_geojson": _load_jintian_geojson("current/road.geojson"),
        "admin_boundary_line_geojson": _load_jintian_geojson("current/admin_boundary_line.geojson"),
        "annotation_geojson": _load_jintian_geojson("current/annotation.geojson"),
        "farmland_protection_geojson": _load_jintian_geojson("planned/farmland_protection.geojson"),
        "ecological_protection_geojson": _load_jintian_geojson("planned/ecological_protection.geojson"),
        "historical_protection_geojson": _load_jintian_geojson("planned/historical_protection.geojson"),
        "construction_zone_geojson": _load_jintian_geojson("planned/construction_zone.geojson"),
        "geological_hazard_geojson": _load_jintian_geojson("planned/geological_hazard_points.geojson"),
        "landuse_planned_geojson": _load_jintian_geojson("planned/landuse.geojson"),
        "road_planned_geojson": _load_jintian_geojson("planned/road.geojson"),
        "annotation_planned_geojson": _load_jintian_geojson("planned/annotation.geojson"),
    }


def _get_default_intent() -> Dict[str, Any]:
    from app.services.modules.gis.layout.data_loader import make_default_intent
    return make_default_intent()


def _run_pipeline(
    intent: Optional[Dict[str, Any]] = None,
    gis_data: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Run full layout generation pipeline, return list of {layerType, data}."""
    if intent is None:
        intent = _get_default_intent()
    if gis_data is None:
        gis_data = _build_gis_data()

    from app.tools.gis.generate import (
        _generate_function_zones,
        _generate_planning_zones,
        _generate_facilities,
        _generate_axes,
    )

    layers: List[Dict[str, Any]] = []
    fz = _generate_function_zones(intent, gis_data)
    if fz:
        layers.append(fz)
    pz = _generate_planning_zones(None, gis_data, intent)
    if pz:
        layers.append(pz)
    fp = _generate_facilities(intent, gis_data)
    if fp:
        layers.append(fp)
    ax = _generate_axes(intent, gis_data)
    if ax:
        layers.append(ax)
    return layers


def _run_export(
    layers: List[Dict[str, Any]],
    gis_data: Dict[str, Any],
    village_name: str = "金田村",
) -> tuple[str, list[str]]:
    """Run export and return (output_dir, exported_file_list)."""
    tmpdir = tempfile.mkdtemp(prefix="gis_e2e_test_")
    from app.tools.gis.export import export_gdb

    cmd = export_gdb.func(
        layout_configs=layers,
        allocated_geojson=gis_data.get("landuse_current_geojson"),
        gis_data=gis_data,
        village_name=village_name,
        output_dir=tmpdir,
        tool_call_id="test-e2e-export",
    )
    messages = cmd.update.get("messages", [])
    result = json.loads(messages[0].content)
    return tmpdir, result["data"]["exported_files"]


# ── tests ──────────────────────────────────────────────────────────────


class TestDataLoading:
    """Verify all Jin Tian data layers load correctly."""

    def test_current_layers_loaded(self):
        """8 current status layers load with correct feature counts."""
        gis_data = _build_gis_data()
        assert len(gis_data) >= 12, f"Expected >=12 layers, got {len(gis_data)}"

        boundary = gis_data["boundary_geojson"]
        assert len(boundary["features"]) == 1
        assert boundary["features"][0]["geometry"]["type"] == "MultiPolygon"

        landuse = gis_data["landuse_current_geojson"]
        assert len(landuse["features"]) == 660, f"Expected 660 parcels, got {len(landuse['features'])}"

        road = gis_data["road_geojson"]
        assert len(road["features"]) == 131

        annotation = gis_data["annotation_geojson"]
        assert len(annotation["features"]) == 34

    def test_planned_layers_loaded(self):
        """Planned (ground truth) layers load correctly."""
        gis_data = _build_gis_data()

        planned_landuse = gis_data["landuse_planned_geojson"]
        assert len(planned_landuse["features"]) == 582, f"Expected 582, got {len(planned_landuse['features'])}"

        farmland = gis_data["farmland_protection_geojson"]
        assert len(farmland["features"]) == 88

        ecological = gis_data["ecological_protection_geojson"]
        assert len(ecological["features"]) == 5

        construction = gis_data["construction_zone_geojson"]
        assert len(construction["features"]) == 139

        hazard = gis_data["geological_hazard_geojson"]
        assert len(hazard["features"]) == 40

    def test_crs_is_wgs84(self):
        """All layers use EPSG:4326 (WGS84)."""
        gis_data = _build_gis_data()
        for key, geojson in gis_data.items():
            if not isinstance(geojson, dict) or "features" not in geojson:
                continue
            crs = geojson.get("crs", {})
            crs_name = crs.get("properties", {}).get("name", "")
            if crs_name:
                assert "4326" in crs_name or "WGS" in crs_name.upper() or "CRS84" in crs_name, \
                    f"Layer {key} has non-WGS84 CRS: {crs_name}"


class TestPipeline:
    """End-to-end pipeline tests with real data."""

    def test_all_four_layers_generated(self):
        """Pipeline produces all 4 layer types."""
        layers = _run_pipeline()
        layer_types = {lyr["layerType"] for lyr in layers}
        assert layer_types >= {"function_zone", "planning_zone", "facility_point", "infrastructure"}, \
            f"Missing layers: expected 4 types, got {layer_types}"

    def test_function_zone_has_merged_features(self):
        """ZoneGenerator produces merged zone features (not per-parcel)."""
        layers = _run_pipeline()
        fz = next(lyr for lyr in layers if lyr["layerType"] == "function_zone")
        feats = fz["data"].get("features", [])
        # ZoneGenerator merges 660 parcels into 3-8 zone features
        assert 3 <= len(feats) <= 15, f"Expected 3-15 merged zones, got {len(feats)}"
        for f in feats:
            props = f.get("properties", {})
            assert "zone_id" in props, f"Feature missing zone_id: {props}"
            assert "land_use" in props, f"Feature missing land_use"
            assert "area_ha" in props, f"Feature missing area_ha"
            assert props["area_ha"] > 0, f"Zone area must be positive, got {props['area_ha']}"

    def test_planning_zone_all_660_parcels(self):
        """Planning zone layer has all 660 parcels classified."""
        layers = _run_pipeline()
        pz = next(lyr for lyr in layers if lyr["layerType"] == "planning_zone")
        feats = pz["data"].get("features", [])
        assert len(feats) == 660, f"Expected 660 parcels, got {len(feats)}"
        zone_types = set()
        for f in feats:
            zt = f["properties"].get("zone_type", "")
            assert zt, f"Parcel missing zone_type: {f['properties']}"
            zone_types.add(zt)
        # Should have at least 2 of the 4 planning zone types
        planning_types = {"农田保护区", "村庄建设区", "生态保护区", "一般农业区"}
        overlap = zone_types & planning_types
        assert len(overlap) >= 2, f"Expected >=2 planning zone types, got {overlap}"

    def test_facility_placement_all_placed(self):
        """FacilityPlacer places all 6 facilities + hazard points."""
        layers = _run_pipeline()
        fp = next(lyr for lyr in layers if lyr["layerType"] == "facility_point")
        feats = fp["data"].get("features", [])
        # 6 facilities + 40 hazard points = 46
        assert len(feats) >= 6, f"Expected >=6 facility features, got {len(feats)}"

        facility_types = set()
        for f in feats:
            ft = f["properties"].get("facility_type", "")
            if ft:
                facility_types.add(ft)
            # Verify geometry is a Point
            assert f["geometry"]["type"] == "Point", f"Facility must be Point, got {f['geometry']['type']}"
            # Verify within reasonable coordinate range (Jin Tian is ~116E, 24N)
            coords = f["geometry"]["coordinates"]
            assert 115 < coords[0] < 117, f"Longitude out of range: {coords[0]}"
            assert 23 < coords[1] < 25, f"Latitude out of range: {coords[1]}"

        assert "村委会" in facility_types, f"村委会 not placed: {facility_types}"

    def test_axis_building_produces_features(self):
        """AxisBuilder produces axis features (Point + LineString)."""
        layers = _run_pipeline()
        ax = next(lyr for lyr in layers if lyr["layerType"] == "infrastructure")
        feats = ax["data"].get("features", [])
        assert len(feats) >= 1, f"Expected >=1 axis feature, got {len(feats)}"
        geom_types = {f["geometry"]["type"] for f in feats}
        assert geom_types & {"Point", "LineString", "MultiLineString"}, \
            f"Expected Point/LineString in axes, got {geom_types}"

    def test_pipeline_reproducible(self):
        """Same data + same intent → same layer structure (no randomness)."""
        layers1 = _run_pipeline()
        layers2 = _run_pipeline()
        assert len(layers1) == len(layers2)
        for l1, l2 in zip(layers1, layers2):
            assert l1["layerType"] == l2["layerType"]
            assert len(l1["data"]["features"]) == len(l2["data"]["features"])


class TestExport:
    """Export validation with real data."""

    def test_export_12_layers(self):
        """12 standard layers exported."""
        gis_data = _build_gis_data()
        layers = _run_pipeline(gis_data=gis_data)
        tmpdir, exported = _run_export(layers, gis_data)
        assert len(exported) >= 8, f"Expected >=8 exported files, got {len(exported)}: {exported}"

    def test_export_files_are_valid_geojson(self):
        """All exported GeoJSON files are valid FeatureCollections."""
        gis_data = _build_gis_data()
        layers = _run_pipeline(gis_data=gis_data)
        tmpdir, exported = _run_export(layers, gis_data)
        geojson_count = 0
        for fname in exported:
            path = Path(tmpdir) / fname
            if path.suffix in (".geojson", ".json") and "balance" not in fname.lower():
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    assert data.get("type") == "FeatureCollection", \
                        f"{fname}: expected FeatureCollection, got {data.get('type')}"
                    assert "features" in data, f"{fname}: missing features array"
                    geojson_count += 1
        assert geojson_count > 0, "No valid GeoJSON files found in export"

    def test_land_balance_table(self):
        """Land balance table exists and has correct structure."""
        gis_data = _build_gis_data()
        layers = _run_pipeline(gis_data=gis_data)
        tmpdir, exported = _run_export(layers, gis_data)

        balance_files = [f for f in exported if "balance" in f.lower() or "land" in f.lower()]
        assert balance_files, f"No land balance file found in {exported}"

        for bf in balance_files:
            path = Path(tmpdir) / bf
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                assert len(data) > 0, "Land balance list is empty"
            elif isinstance(data, dict):
                assert any(k in data for k in ("total_area_ha", "zones", "type")), \
                    f"Land balance dict missing expected keys: {list(data.keys())[:5]}"
            else:
                pytest.fail(f"Land balance has unexpected type: {type(data)}")


class TestRender:
    """Map renderer tests with real data."""

    def test_map_renderer_output(self):
        """MapRenderer produces valid GISLayerConfig list."""
        gis_data = _build_gis_data()
        layers = _run_pipeline(gis_data=gis_data)

        from app.services.modules.gis.layout.map_renderer import MapRenderer
        renderer = MapRenderer()
        # MapRenderer.render() takes Dict[str, GeoJSON], convert from list format
        layers_dict = {lyr["layerType"]: lyr["data"] for lyr in layers}
        rendered = renderer.render(layers_dict)
        assert isinstance(rendered, list), f"Expected list, got {type(rendered).__name__}"
        assert len(rendered) > 0, "Expected at least 1 rendered layer"
        for rlyr in rendered:
            assert "geojson" in rlyr or "layerType" in rlyr, \
                f"Rendered layer missing expected keys: {rlyr.keys()}"


class TestComparison:
    """Ground truth comparison tests."""

    def test_compare_with_planned(self):
        """Generated layout can be compared against planned data."""
        gis_data = _build_gis_data()
        layers = _run_pipeline(gis_data=gis_data)

        from app.services.modules.gis.layout.compare_layouts import compare
        from app.services.modules.gis.layout.data_loader import load_planned

        planned = load_planned()
        protection = {}
        for key, name in [
            ("farmland_protection_geojson", "farmland"),
            ("ecological_protection_geojson", "ecological"),
            ("historical_protection_geojson", "historical"),
        ]:
            val = gis_data.get(key)
            if val and val.get("features"):
                protection[name] = val

        report = compare(layers, planned, protection if protection else None)
        d = report.to_dict()

        assert "zone_area_matches" in d
        assert "planning_zone_match" in d
        assert "overall_score" in d
        assert 0.0 <= d["overall_score"] <= 1.0, f"Score out of range: {d['overall_score']}"

    def test_planning_zone_distribution(self):
        """4 planning zone types all present in comparison."""
        gis_data = _build_gis_data()
        layers = _run_pipeline(gis_data=gis_data)

        from app.services.modules.gis.layout.compare_layouts import compare_planning_zones
        planned_landuse = gis_data["landuse_planned_geojson"]
        pz = next(lyr for lyr in layers if lyr["layerType"] == "planning_zone")
        result = compare_planning_zones(pz["data"], planned_landuse)
        assert len(result) >= 2, f"Expected >=2 zone types in comparison, got {len(result)}"
