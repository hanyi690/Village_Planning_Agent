"""Post-L3 chain nodes (parse/ground/select) tests."""

from types import SimpleNamespace

import pytest

from app.agent.bootstrap.post_l3_nodes import ground_node, parse_node, select_node
from app.agent.bootstrap.post_l3_state import PostL3ChainState
from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
from app.modules.schema.contracts.workflow_contracts import GateDecision


def _pass_gate():
    return GateDecision(stage="parse", passed=True, feedback_route=None)


@pytest.mark.asyncio
async def test_parse_node_compiles_program(monkeypatch):
    program = SimpleNamespace(artifact_id="l3-1", interventions=[])
    result = IntentCompilationResult()
    spec = SimpleNamespace(type="directional")
    gate = _pass_gate()
    monkeypatch.setattr(
        "app.agent.bootstrap.post_l3_nodes.compile_program",
        lambda program, run_id="", context_version="": (result, [spec], gate),
    )
    state = PostL3ChainState(planning_program=program, run_id="r1")
    out = await parse_node(state)
    assert out["intent"] is result
    assert out["specs"] == [spec]
    assert out["parse_gate"] is gate
    assert len(out["upstream_gates"]) == 1


@pytest.mark.asyncio
async def test_ground_node_resolves_specs(monkeypatch):
    grounding = SimpleNamespace(candidates=[], unresolved=[])
    gate = GateDecision(stage="ground", passed=True, feedback_route=None)
    monkeypatch.setattr(
        "app.agent.bootstrap.post_l3_nodes.ground_aggregate",
        lambda specs, context: grounding,
    )
    monkeypatch.setattr(
        "app.agent.bootstrap.post_l3_nodes.evaluate_ground_gate",
        lambda result: gate,
    )
    state = PostL3ChainState(specs=["s1"], context=SimpleNamespace(session_id="r1"))
    out = await ground_node(state)
    assert out["grounding_result"] is grounding
    assert out["ground_gate"] is gate
    assert len(out["upstream_gates"]) == 1


@pytest.mark.asyncio
async def test_select_node_produces_decision(monkeypatch):
    decision = SimpleNamespace(selected_combination=["BSM001"])
    briefs = ["brief-1"]
    gate = GateDecision(stage="select", passed=True, feedback_route=None)
    intent = SimpleNamespace(project_targets=["p1", "p2"])
    monkeypatch.setattr(
        "app.agent.bootstrap.post_l3_nodes.select_aggregate",
        lambda result, intent, context: (decision, briefs),
    )
    monkeypatch.setattr(
        "app.agent.bootstrap.post_l3_nodes.evaluate_select_gate",
        lambda decision, target_count=0: gate,
    )
    state = PostL3ChainState(
        grounding_result=SimpleNamespace(),
        intent=intent,
        context=SimpleNamespace(session_id="r1", bundle=object()),
    )
    out = await select_node(state)
    assert out["site_selection"] is decision
    assert out["land_design_briefs"] == briefs
    assert out["select_gate"] is gate
    assert len(out["upstream_gates"]) == 1
