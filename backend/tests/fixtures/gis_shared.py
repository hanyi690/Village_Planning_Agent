"""Shared constants, helpers, and fixture factories for GIS tests.

Eliminates duplication across test files:
  - Zone targets (was hardcoded 3x)
  - tool_call / extract_result (was duplicated 2x)
  - Zone feature / layout builders (was duplicated 2x)
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

ZONE_TARGETS: Dict[str, float] = {
    "农田保护区": 1200.0,
    "村庄建设区": 30.0,
    "生态保护区": 350.0,
    "一般农业区": 770.0,
}

REQUIRED_ZONE_TYPES: List[str] = [
    "农田保护区",
    "村庄建设区",
    "生态保护区",
    "一般农业区",
]

PROTECTION_DLBM_IN_CONSTRUCTION: List[str] = ["0110", "0120"]

# Non-overlapping polygon coordinates for zone features
_ZONE_OFFSETS = [
    [[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]],
    [[10, 10], [10, 11], [11, 11], [11, 10], [10, 10]],
    [[20, 20], [20, 21], [21, 21], [21, 20], [20, 20]],
    [[30, 30], [30, 31], [31, 31], [31, 30], [30, 30]],
]

# ---------------------------------------------------------------------------
# Tool-call helpers (for LangGraph Command-based tool tests)
# ---------------------------------------------------------------------------


def tool_call(name: str, args: dict, call_id: str = "tc1") -> dict:
    """Build a ToolCall dict for InjectedToolCallId-based tools."""
    return {"name": name, "args": args, "type": "tool_call", "id": call_id}


def extract_result(command) -> dict:
    """Extract result payload from Command.update['messages']."""
    from langgraph.types import Command
    from langchain_core.messages import ToolMessage

    assert isinstance(command, Command), f"Expected Command, got {type(command)}"
    messages = command.update.get("messages", [])
    assert len(messages) > 0, "Command.update has no messages"
    assert isinstance(messages[0], ToolMessage), f"Expected ToolMessage, got {type(messages[0])}"
    return json.loads(messages[0].content)


# ---------------------------------------------------------------------------
# Zone feature / layout builders (for validator tests)
# ---------------------------------------------------------------------------


def make_zone_feature(
    zone_type: str,
    area_ha: float,
    dlbm: str = "",
    current_zone: str = "",
    slot: int = 0,
) -> Dict[str, Any]:
    """Build a planning_zone feature with assigned_zone and area_ha."""
    return {
        "type": "Feature",
        "properties": {
            "assigned_zone": zone_type,
            "zone_type": zone_type,
            "area_ha": area_ha,
            "DLBM": dlbm,
            "current_zone_type": current_zone,
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [_ZONE_OFFSETS[slot % len(_ZONE_OFFSETS)]],
        },
    }


def make_planning_zone_config(features: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a planning_zone layer config from feature list."""
    return {
        "layerType": "planning_zone",
        "data": {"type": "FeatureCollection", "features": features},
    }


def make_valid_4zone_layout() -> List[Dict[str, Any]]:
    """A layout with all 4 required zones and sufficient area, non-overlapping."""
    return [
        make_planning_zone_config([
            make_zone_feature("农田保护区", 80.0, "0110", slot=0),
            make_zone_feature("村庄建设区", 30.0, "2122", slot=1),
            make_zone_feature("生态保护区", 400.0, "1340", slot=2),
            make_zone_feature("一般农业区", 1800.0, "0200", slot=3),
        ])
    ]


class MockAdjacencyGraph:
    """Minimal adjacency graph for testing."""

    def __init__(self, adjacency_dict: Dict[str, set]):
        self.adjacency_dict = adjacency_dict
