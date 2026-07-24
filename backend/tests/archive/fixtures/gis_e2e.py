"""GIS end-to-end test fixtures — realistic GeoJSON data for integration tests."""

from typing import Any, Dict

import pytest


# ── Minimal but realistic GeoJSON fixtures ──


@pytest.fixture
def landuse_geojson() -> Dict[str, Any]:
    """Landuse GeoJSON with 6 parcels covering 4 planning zone types."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "DLBM": "0110", "DLMC": "水田", "BSM": "P001",
                    "area_ha": 80.0, "SHAPE_Area": 800000,
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[113.5, 23.5], [113.6, 23.5], [113.6, 23.6], [113.5, 23.6], [113.5, 23.5]]],
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "DLBM": "0210", "DLMC": "果园", "BSM": "P002",
                    "area_ha": 40.0, "SHAPE_Area": 400000,
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[113.6, 23.5], [113.7, 23.5], [113.7, 23.6], [113.6, 23.6], [113.6, 23.5]]],
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "DLBM": "2121", "DLMC": "宅基地", "BSM": "P003",
                    "area_ha": 15.0, "SHAPE_Area": 150000,
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[113.7, 23.5], [113.75, 23.5], [113.75, 23.55], [113.7, 23.55], [113.7, 23.5]]],
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "DLBM": "1340", "DLMC": "有林地", "BSM": "P004",
                    "area_ha": 60.0, "SHAPE_Area": 600000,
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[113.5, 23.6], [113.6, 23.6], [113.6, 23.7], [113.5, 23.7], [113.5, 23.6]]],
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "DLBM": "0120", "DLMC": "旱地", "BSM": "P005",
                    "area_ha": 30.0, "SHAPE_Area": 300000,
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[113.6, 23.6], [113.7, 23.6], [113.7, 23.7], [113.6, 23.7], [113.6, 23.6]]],
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "DLBM": "2030", "DLMC": "村庄道路", "BSM": "P006",
                    "area_ha": 5.0, "SHAPE_Area": 50000,
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[113.75, 23.55], [113.8, 23.55], [113.8, 23.6], [113.75, 23.6], [113.75, 23.55]]],
                },
            },
        ],
    }


@pytest.fixture
def boundary_geojson() -> Dict[str, Any]:
    """Village boundary polygon."""
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"name": "金田村委会"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[113.5, 23.5], [113.8, 23.5], [113.8, 23.7], [113.5, 23.7], [113.5, 23.5]]],
            },
        }],
    }


@pytest.fixture
def protection_zones() -> Dict[str, Dict[str, Any]]:
    """Protection zone GeoJSONs (farmland + ecological)."""
    return {
        "farmland": {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"name": "永久基本农田"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[113.5, 23.5], [113.6, 23.5], [113.6, 23.6], [113.5, 23.6], [113.5, 23.5]]],
                },
            }],
        },
        "ecological": {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"name": "生态保护红线"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[113.5, 23.6], [113.6, 23.6], [113.6, 23.7], [113.5, 23.7], [113.5, 23.6]]],
                },
            }],
        },
    }


@pytest.fixture
def road_geojson() -> Dict[str, Any]:
    """Road network GeoJSON."""
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"name": "村道1号", "type": "village_road"},
            "geometry": {
                "type": "LineString",
                "coordinates": [[113.5, 23.55], [113.8, 23.55]],
            },
        }],
    }


@pytest.fixture
def construction_zone_geojson() -> Dict[str, Any]:
    """Construction boundary GeoJSON."""
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"name": "村庄建设边界"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[113.7, 23.5], [113.8, 23.5], [113.8, 23.6], [113.7, 23.6], [113.7, 23.5]]],
            },
        }],
    }


@pytest.fixture
def hazard_points_geojson() -> Dict[str, Any]:
    """Geological hazard points GeoJSON."""
    return {
        "type": "FeatureCollection",
        "features": [],
    }


@pytest.fixture
def l3_reports_for_kg() -> Dict[str, Dict[str, Any]]:
    """L3 report data for KG building."""
    return {
        "land_use": {
            "content": "金田村总面积230ha，其中耕地110ha，林地60ha，建设用地20ha。",
        },
        "constraints": {
            "content": "基本农田保护面积不低于80ha，生态保护红线面积不低于50ha，建设用地不超过30ha。",
        },
    }


@pytest.fixture
def gis_data(
    landuse_geojson,
    boundary_geojson,
    protection_zones,
    road_geojson,
    construction_zone_geojson,
    hazard_points_geojson,
) -> Dict[str, Any]:
    """Combined GIS data dict for pipeline testing."""
    return {
        "landuse_current_geojson": landuse_geojson,
        "boundary_geojson": boundary_geojson,
        "farmland_protection_geojson": protection_zones["farmland"],
        "ecological_protection_geojson": protection_zones["ecological"],
        "road_geojson": road_geojson,
        "construction_boundary_geojson": construction_zone_geojson,
        "geological_hazard_geojson": hazard_points_geojson,
    }


@pytest.fixture
def real_intent() -> Dict[str, Any]:
    """Planning intent dict for pipeline testing."""
    return {
        "zones": [
            {"zone_id": "Z01", "land_use": "construction", "area_ratio": 0.10, "direction": "center", "density": "medium"},
            {"zone_id": "Z02", "land_use": "farmland", "area_ratio": 0.45, "direction": "north", "density": "low"},
            {"zone_id": "Z03", "land_use": "ecological", "area_ratio": 0.35, "direction": "south", "density": "low"},
            {"zone_id": "Z04", "land_use": "general_agriculture", "area_ratio": 0.10, "direction": "east", "density": "medium"},
        ],
        "facilities": [
            {"facility_id": "F01", "facility_type": "村委会", "target_zone": "construction", "location_hint": "center"},
        ],
        "axes": [
            {"axis_id": "A01", "axis_type": "primary", "direction": "east"},
        ],
        "metadata": {"source": "test_fixture"},
    }
