"""Shared GIS test fixtures — reusable helpers for unit and integration tests."""

from typing import Any, Dict, List, Optional


# ── Constants ──

ZONE_TARGETS = {
    "农田保护区": 100.0,
    "一般农业区": 200.0,
    "村庄建设区": 50.0,
    "生态保护区": 150.0,
}

REQUIRED_ZONE_TYPES = {"村庄建设区", "生态保护区", "一般农业区"}


# ── Helpers ──

def make_zone_feature(
    zone_type: str,
    area_ha: float,
    dlbm: str = "",
    current_zone_type: str = "",
    slot: int = 0,
) -> Dict[str, Any]:
    """Create a single planning_zone feature dict."""
    props: Dict[str, Any] = {
        "assigned_zone": zone_type,
        "zone_type": zone_type,
        "area_ha": area_ha,
        "DLBM": dlbm,
    }
    if current_zone_type:
        props["current_zone_type"] = current_zone_type
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
        },
        "properties": props,
    }


def make_planning_zone_config(
    features: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Create a planning_zone layer config dict."""
    return {
        "layerType": "planning_zone",
        "data": {
            "type": "FeatureCollection",
            "features": features,
        },
    }


def make_valid_4zone_layout() -> List[Dict[str, Any]]:
    """Create a valid 4-zone layout that passes completeness checks."""
    return [make_planning_zone_config([
        make_zone_feature("农田保护区", 100.0, "0110"),
        make_zone_feature("一般农业区", 200.0, "0210"),
        make_zone_feature("村庄建设区", 50.0, "2121"),
        make_zone_feature("生态保护区", 150.0, "1340"),
    ])]


class MockAdjacencyGraph:
    """Mock adjacency graph for testing adjacency_compatibility check."""

    def __init__(self, adjacency_dict: Dict[str, set]):
        self.adjacency_dict = adjacency_dict
