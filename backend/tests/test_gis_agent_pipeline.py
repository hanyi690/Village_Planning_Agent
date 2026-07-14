"""GIS 双 Agent 全流程集成测试。

验证 PARSE → LAYOUT 双 Agent 编排、state 传递、子图构建。
B 层测试不需要 API Key，A 层测试需要 DASHSCOPE_API_KEY。
"""

import os

import pytest
from langgraph.types import Command

_HAS_API_KEY = bool(os.environ.get("DASHSCOPE_API_KEY"))


# ── B 层：不需要 API Key ──────────────────────────


class TestStateTransformation:
    """验证双 Agent state 传递格式。"""

    def test_parse_tool_returns_command_with_intent_json(self):
        """parse_planning_text 返回 Command 含 intent_json。"""
        from app.tools.gis.parse import parse_planning_text

        cmd = parse_planning_text.func(
            reports={"land_use": {"summary": {"metrics": {}}, "content": "测试"}},
            village_name="测试村",
            gis_data=None,
            tool_call_id="test-123",
        )
        assert isinstance(cmd, Command)
        assert "intent_json" in cmd.update

    def test_parse_state_has_intent_json_field(self):
        from app.agent.gis.parse_state import ParseAgentState

        assert "intent_json" in ParseAgentState.__annotations__

    def test_layout_state_has_intent_field(self):
        from app.agent.gis.layout_state import LayoutAgentState

        assert "intent" in LayoutAgentState.__annotations__

    def test_both_subgraphs_build_without_error(self):
        from app.agent.gis import create_parse_agent_graph, create_layout_agent_graph

        assert create_parse_agent_graph() is not None
        assert create_layout_agent_graph() is not None


class TestParseAgentErrorHandling:
    """错误处理测试。"""

    def test_gis_error_handler_returns_command_goto_conversation(self):
        from app.agent.graph import _gis_error_handler

        cmd = _gis_error_handler({}, Exception("test"))
        assert isinstance(cmd, Command)
        assert cmd.goto == "conversation"


# ── A 层：需要 API Key ────────────────────────────


@pytest.mark.asyncio
@pytest.mark.skipif(not _HAS_API_KEY, reason="DASHSCOPE_API_KEY not set")
class TestParseAgentSubgraph:
    """PARSE Agent 单独执行。"""

    async def test_parse_produces_valid_intent(self, l3_reports_for_kg, gis_data):
        from app.agent.gis import create_parse_agent_graph

        result = await create_parse_agent_graph().ainvoke({
            "session_id": "test-parse",
            "village_name": "金田村",
            "reports": l3_reports_for_kg,
            "summaries": {},
            "gis_data": gis_data,
            "messages": [],
        })
        intent_json = result.get("intent_json", {})
        assert intent_json, "PARSE Agent 未产出 intent_json"
        assert "zones" in intent_json


@pytest.mark.asyncio
@pytest.mark.skipif(not _HAS_API_KEY, reason="DASHSCOPE_API_KEY not set")
class TestLayoutAgentSubgraph:
    """LAYOUT Agent 单独执行（用预构造 intent）。"""

    async def test_layout_produces_layout_configs(self, l3_reports_for_kg, gis_data, real_intent):
        from app.agent.gis import create_layout_agent_graph

        result = await create_layout_agent_graph().ainvoke({
            "session_id": "test-layout",
            "village_name": "金田村",
            "reports": l3_reports_for_kg,
            "summaries": {},
            "gis_data": gis_data,
            "intent": real_intent,
            "kg_turtle": "",
            "kg_constraints": [],
            "layout_configs": [],
            "allocated_geojson": {},
            "allocation_summary": {},
            "messages": [],
        })
        assert len(result.get("layout_configs", [])) >= 1


@pytest.mark.asyncio
@pytest.mark.skipif(not _HAS_API_KEY, reason="DASHSCOPE_API_KEY not set")
class TestDualAgentOrchestration:
    """完整 PARSE → LAYOUT 双 Agent 编排。"""

    async def test_gis_agent_node_full_flow(self):
        from app.agent.graph import gis_agent_node
        from tests.fixtures.gis_e2e import build_gis_agent_state

        state = build_gis_agent_state(
            village_name="金田村",
            session_id="test-full-flow",
        )
        result = await gis_agent_node(state)
        assert "gis_layout_configs" in result
        assert "messages" in result
