"""GIS SSE 事件序列验证测试。

验证 SpatialLayoutEngine.full_pipeline 推送的 SSE 事件序列符合设计：
  building_kg → phase0_conflict_detection → phase1_layout_generation
  → generating_function_zone → generating_planning_zone
  → generating_facility_point → generating_development_axis
  → validation_round_N → complete
"""

import json
from unittest.mock import patch

import pytest

from app.services.modules.gis.layout.engine import SpatialLayoutEngine
from app.tools.gis.layout_tools import _dict_to_intent
from tests.fixtures.gis_e2e import (
    load_landuse_current,
    load_boundary,
    load_protection_zones,
    load_l3_reports_for_kg,
    make_real_intent,
)


def _run_pipeline_with_captured_events(session_id: str) -> list:
    """运行 full_pipeline 并捕获所有 SSE send_tool_progress 调用的 stage。"""
    captured_stages = []

    with patch("app.utils.sse_publisher.SSEPublisher.send_tool_progress") as mock_send:
        def capture(session_id, tool_name, stage, progress, message):
            captured_stages.append({
                "session_id": session_id,
                "tool_name": tool_name,
                "stage": stage,
                "progress": progress,
                "message": message,
            })
        mock_send.side_effect = capture

        engine = SpatialLayoutEngine()
        engine.full_pipeline(
            summaries={},
            intent=_dict_to_intent(make_real_intent()),
            boundary_geojson=load_boundary(),
            landuse_current_geojson=load_landuse_current(),
            protection_zones=load_protection_zones(),
            reports=load_l3_reports_for_kg(),
            max_validation_rounds=2,
            session_id=session_id,
        )

    return captured_stages


class TestSSEEventSequence:
    """验证 SSE 事件推送序列。"""

    def test_sse_events_match_expected_order(self):
        """full_pipeline 应按设计顺序推送 SSE 事件。"""
        events = _run_pipeline_with_captured_events("test-sse-seq-123")

        assert len(events) > 0, "应推送至少一个 SSE 事件"

        expected_sequence = [
            "building_kg",
            "phase0_conflict_detection",
            "phase1_layout_generation",
            "generating_function_zone",
            "generating_planning_zone",
            "generating_facility_point",
            "generating_development_axis",
            "validation_round_1",
            "complete",
        ]

        actual_stages = [e["stage"] for e in events]

        for expected in expected_sequence:
            assert expected in actual_stages, \
                f"缺少事件 '{expected}'，实际事件: {actual_stages}"

        expected_prefix = expected_sequence[:7]
        actual_prefix = actual_stages[:7]
        assert actual_prefix == expected_prefix, \
            f"前 7 个事件顺序错误：\n期望: {expected_prefix}\n实际: {actual_prefix}"

        assert actual_stages[-1] == "complete", \
            f"最后事件应为 complete，实际: {actual_stages[-1]}"

        for event in events:
            assert event["session_id"] == "test-sse-seq-123", \
                f"session_id 不匹配：{event['session_id']}"
            assert event["tool_name"] == "gis_layout_engine", \
                f"tool_name 应为 gis_layout_engine，实际: {event['tool_name']}"
            assert isinstance(event["progress"], float), \
                f"progress 应为 float，实际: {type(event['progress'])}"
            assert len(event["message"]) > 0, "message 不应为空"

    def test_sse_no_events_without_session_id(self):
        """session_id 为空时不应推送任何 SSE 事件。"""
        events = _run_pipeline_with_captured_events("")

        assert len(events) == 0, \
            f"空 session_id 不应推送事件，实际推送: {len(events)} 个"

    def test_sse_validation_round_events_count_matches_max_rounds(self):
        """validation_round 事件数应 ≤ max_validation_rounds。"""
        events = _run_pipeline_with_captured_events("test-sse-rounds")
        validation_events = [
            e for e in events if e["stage"].startswith("validation_round_")
        ]

        assert len(validation_events) <= 2, \
            f"validation_round 事件数应 ≤2（max_validation_rounds=2），实际: {len(validation_events)}"
        assert len(validation_events) >= 1, \
            f"应至少有 1 个 validation_round 事件，实际: {len(validation_events)}"

        for event in validation_events:
            round_num = int(event["stage"].split("_")[-1])
            assert 1 <= round_num <= 2, \
                f"validation_round 编号应在 1-2 之间，实际: {round_num}"
