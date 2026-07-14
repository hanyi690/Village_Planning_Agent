"""Tests for GIS layout tools — Command return structure and intent conversion.

LangGraph 1.2 Command API:
  - Tool returns Command(update={...state_fields..., "messages": [ToolMessage(...)]})
  - LLM-visible content is in ToolMessage.content (JSON string)
  - InjectedState and InjectedToolCallId params are invisible to LLM
"""

import json
import pytest
from langgraph.types import Command
from langchain_core.messages import ToolMessage

from app.tools.gis.kg import build_knowledge_graph, query_knowledge_graph
from app.tools.gis.conflict import detect_conflicts
from app.tools.gis.validate import validate_layout
from app.tools.gis.parse import _make_result, _dict_to_intent, _safe_enum


def _extract_result(command: Command) -> dict:
    """Extract result payload from Command.update["messages"][0].content."""
    assert isinstance(command, Command), f"Expected Command, got {type(command)}"
    messages = command.update.get("messages", [])
    assert len(messages) > 0, "Command.update has no messages"
    assert isinstance(messages[0], ToolMessage), f"Expected ToolMessage, got {type(messages[0])}"
    return json.loads(messages[0].content)


class TestMakeResult:
    def test_success_with_data(self):
        result = _make_result(True, {"key": "value"})
        assert result["success"] is True
        assert result["data"] == {"key": "value"}

    def test_failure_with_error(self):
        result = _make_result(False, error="something failed")
        assert result["success"] is False
        assert result["error"] == "something failed"

    def test_success_no_data(self):
        result = _make_result(True)
        assert result["success"] is True
        assert "data" not in result


class TestSafeEnum:
    def test_valid_value(self):
        from app.services.modules.gis.planning_intent import Direction
        result = _safe_enum(Direction, "north")
        assert result == Direction.NORTH

    def test_invalid_value_uses_default(self):
        from app.services.modules.gis.planning_intent import Direction
        result = _safe_enum(Direction, "invalid_direction")
        assert isinstance(result, Direction)

    def test_invalid_value_uses_custom_default(self):
        from app.services.modules.gis.planning_intent import Direction
        result = _safe_enum(Direction, "invalid", default=Direction.SOUTH)
        assert result == Direction.SOUTH


class TestDictToIntent:
    def test_basic_conversion(self):
        intent_dict = {
            "zones": [
                {
                    "zone_id": "z1",
                    "land_use": "residential",
                    "dlbm": "2122",
                    "area_ratio": 0.3,
                    "direction": "north",
                    "density": "high",
                }
            ],
            "metadata": {"spatial_structure": "一核一带三区"},
        }
        intent = _dict_to_intent(intent_dict)
        assert len(intent.zones) == 1
        assert intent.zones[0].zone_id == "z1"
        assert intent.zones[0].dlbm == "2122"

    def test_empty_zones(self):
        intent_dict = {"zones": [], "metadata": {}}
        intent = _dict_to_intent(intent_dict)
        assert len(intent.zones) == 0

    def test_default_values(self):
        intent_dict = {
            "zones": [{"zone_id": "z1", "land_use": "agriculture"}],
        }
        intent = _dict_to_intent(intent_dict)
        assert intent.zones[0].area_ratio == 0.0
        assert intent.zones[0].preserve_existing is True

    def test_string_direction_converted_to_enum(self):
        intent_dict = {
            "zones": [{"zone_id": "z1", "land_use": "residential", "direction": "south"}],
        }
        intent = _dict_to_intent(intent_dict)
        from app.services.modules.gis.planning_intent import Direction
        assert intent.zones[0].direction == Direction.SOUTH


def _tool_call(name: str, args: dict, call_id: str) -> dict:
    """Build a full ToolCall dict required by InjectedToolCallId.

    LangChain expects 'id' key (not 'tool_call_id'); the value is mapped to
    InjectedToolCallId param inside the tool.
    """
    return {"name": name, "args": args, "type": "tool_call", "id": call_id}


class TestQueryKnowledgeGraphWithoutKG:
    def test_returns_error_when_no_kg(self):
        """query_knowledge_graph should return error when kg_turtle is empty."""
        cmd = query_knowledge_graph.invoke(
            _tool_call(
                "query_knowledge_graph",
                {"template_name": "get_constraints", "kg_turtle": ""},
                "test-call-1",
            )
        )
        parsed = _extract_result(cmd)
        assert parsed["success"] is False
        assert "KG 未构建" in parsed.get("error", "")

    def test_returns_error_for_unknown_template(self):
        cmd = query_knowledge_graph.invoke(
            _tool_call(
                "query_knowledge_graph",
                {"template_name": "nonexistent_template", "kg_turtle": "some_turtle"},
                "test-call-2",
            )
        )
        parsed = _extract_result(cmd)
        assert parsed["success"] is False


class TestValidateLayout:
    def _make_layout(self, slot_offsets=True):
        """Build a valid 4-zone layout. If slot_offsets, zones are non-overlapping."""
        if slot_offsets:
            coords = [
                [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],
                [[[10, 10], [10, 11], [11, 11], [11, 10], [10, 10]]],
                [[[20, 20], [20, 21], [21, 21], [21, 20], [20, 20]]],
                [[[30, 30], [30, 31], [31, 31], [31, 30], [30, 30]]],
            ]
        else:
            coords = [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]] * 4

        zones = [
            ("农田保护区", 80.0, 0),
            ("村庄建设区", 30.0, 1),
            ("生态保护区", 400.0, 2),
            ("一般农业区", 1800.0, 3),
        ]
        features = []
        for name, area, i in zones:
            features.append({
                "type": "Feature",
                "properties": {"assigned_zone": name, "area_ha": area},
                "geometry": {"type": "Polygon", "coordinates": coords[i]},
            })
        return [{"layerType": "planning_zone", "data": {"type": "FeatureCollection", "features": features}}]

    def test_returns_command_with_pass_status(self):
        layout_configs = self._make_layout(slot_offsets=True)
        cmd = validate_layout.invoke(
            _tool_call(
                "validate_layout",
                {"layout_configs": layout_configs, "constraints": []},
                "test-validate-1",
            )
        )
        parsed = _extract_result(cmd)
        assert parsed["success"] is True
        assert parsed["data"]["status"] == "pass"

    def test_command_update_contains_only_messages(self):
        """validate_layout has no state write-back, only messages."""
        layout_configs = self._make_layout(slot_offsets=True)
        cmd = validate_layout.invoke(
            _tool_call(
                "validate_layout",
                {"layout_configs": layout_configs, "constraints": []},
                "test-validate-2",
            )
        )
        assert isinstance(cmd, Command)
        # Only "messages" key in update (no state fields)
        assert set(cmd.update.keys()) == {"messages"}
        # ToolMessage has matching tool_call_id
        msg = cmd.update["messages"][0]
        assert msg.tool_call_id == "test-validate-2"
