"""EXECUTE _route_after_execution_review: 3-route conditional (pass / retry / human).

Wave O Task 6: failed execution review after max rounds routes to "human"
(terminal review) instead of the old silent "pass" fallthrough.
"""

from pathlib import Path

from app.agent.execute.execute_agent import (
    _route_after_execution_review,
    build_execute_agent_graph,
)
from app.agent.execute.execute_state import ExecuteAgentState

_EXECUTE_AGENT_PATH = (
    Path(__file__).resolve().parents[3] / "app" / "agent" / "execute" / "execute_agent.py"
)


def _state(**overrides):
    defaults = dict(session_id="s1", validation_result={}, validation_round=0)
    defaults.update(overrides)
    return ExecuteAgentState(**defaults)


def test_route_pass():
    state = _state(validation_result={"passed": True})
    assert _route_after_execution_review(state) == "pass"


def test_route_retry():
    state = _state(validation_result={"passed": False}, validation_round=1)
    assert _route_after_execution_review(state) == "retry"


def test_route_human_after_max_rounds():
    state = _state(validation_result={"passed": False}, validation_round=3)
    assert _route_after_execution_review(state) == "human"


def test_route_human_rounds_above_max():
    state = _state(validation_result={"passed": False}, validation_round=5)
    assert _route_after_execution_review(state) == "human"


def test_route_pass_priority_over_max_rounds():
    state = _state(validation_result={"passed": True}, validation_round=5)
    assert _route_after_execution_review(state) == "pass"


def test_route_no_validation_result():
    assert _route_after_execution_review(_state(validation_result={})) == "retry"


def test_graph_edges_include_human():
    source = _EXECUTE_AGENT_PATH.read_text(encoding="utf-8")
    assert '"human": END' in source
    graph = build_execute_agent_graph()
    assert graph is not None
