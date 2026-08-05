"""Wave O: post-L3 chain step_report + artifact persistence tests.

All mocked — no DB, no LLM, no real filesystem writes. Verifies that the
post-L3 nodes record a StepReport via save_step_report and that a failure in
recording does not interrupt chain execution, plus that _persist_artifact
delegates to FilesystemArtifactStore.store and returns an ArtifactRef dict.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.bootstrap.post_l3_nodes import (
    _persist_artifact,
    ground_node,
    parse_node,
    select_node,
)
from app.agent.bootstrap.post_l3_state import PostL3ChainState
from app.modules.schema.contracts.grounding_contracts import GroundingResult
from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
from app.modules.schema.contracts.workflow_contracts import GateDecision


def _pass_gate(stage):
    return GateDecision(stage=stage, passed=True, feedback_route=None)


async def _async_compile(program, run_id="", context_version=""):
    result = IntentCompilationResult()
    spec = SimpleNamespace(type="directional")
    return result, [spec], _pass_gate("parse")


@pytest.mark.asyncio
async def test_parse_node_records_step_report(monkeypatch):
    save_mock = AsyncMock()
    monkeypatch.setattr("app.services.step_report.save_step_report", save_mock)
    monkeypatch.setattr(
        "app.agent.bootstrap.post_l3_nodes.compile_program_async", _async_compile
    )
    state = PostL3ChainState(
        planning_program=SimpleNamespace(artifact_id="l3-1"), run_id="r1"
    )
    out = await parse_node(state)
    assert "intent" in out
    save_mock.assert_awaited_once()
    kwargs = save_mock.call_args.kwargs
    assert kwargs["stage"] == "PARSE"
    assert kwargs["step_name"] == "post_l3:parse"
    assert kwargs["layer"] == 3
    assert kwargs["diagnostics"]["gate_route"] == "PASS"


@pytest.mark.asyncio
async def test_ground_node_records_step_report(monkeypatch):
    save_mock = AsyncMock()
    monkeypatch.setattr("app.services.step_report.save_step_report", save_mock)
    grounding = SimpleNamespace(candidates=["c1"], unresolved=[])
    monkeypatch.setattr(
        "app.agent.bootstrap.post_l3_nodes.ground_aggregate",
        lambda specs, context: grounding,
    )
    monkeypatch.setattr(
        "app.agent.bootstrap.post_l3_nodes.evaluate_ground_gate",
        lambda result: _pass_gate("ground"),
    )
    state = PostL3ChainState(specs=["s1"], context=SimpleNamespace(session_id="r1"))
    out = await ground_node(state)
    assert "grounding_result" in out
    save_mock.assert_awaited_once()
    kwargs = save_mock.call_args.kwargs
    assert kwargs["stage"] == "GROUND"
    assert kwargs["outputs"]["candidates_count"] == 1
    assert kwargs["outputs"]["unresolved_count"] == 0


@pytest.mark.asyncio
async def test_select_node_records_step_report(monkeypatch):
    save_mock = AsyncMock()
    monkeypatch.setattr("app.services.step_report.save_step_report", save_mock)
    decision = SimpleNamespace(selected_combination=["B1"])
    intent = SimpleNamespace(project_targets=["p1", "p2"])
    monkeypatch.setattr(
        "app.agent.bootstrap.post_l3_nodes.select_aggregate",
        lambda result, intent, context: (decision, ["brief-1"]),
    )
    monkeypatch.setattr(
        "app.agent.bootstrap.post_l3_nodes.evaluate_select_gate",
        lambda decision, target_count=0: _pass_gate("select"),
    )
    state = PostL3ChainState(
        grounding_result=SimpleNamespace(),
        intent=intent,
        context=SimpleNamespace(session_id="r1", bundle=object()),
    )
    out = await select_node(state)
    assert "site_selection" in out
    save_mock.assert_awaited_once()
    kwargs = save_mock.call_args.kwargs
    assert kwargs["stage"] == "SELECT"
    assert kwargs["inputs"]["target_count"] == 2


@pytest.mark.asyncio
async def test_step_report_failure_does_not_break_node(monkeypatch):
    async def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.services.step_report.save_step_report", _boom)
    monkeypatch.setattr(
        "app.agent.bootstrap.post_l3_nodes.compile_program_async", _async_compile
    )
    state = PostL3ChainState(
        planning_program=SimpleNamespace(artifact_id="l3-1"), run_id="r1"
    )
    out = await parse_node(state)
    assert out["parse_gate"].passed is True
    assert len(out["specs"]) == 1
    assert len(out["upstream_gates"]) == 1


def test_persist_artifact_stores_and_returns_ref(monkeypatch):
    class FakeStore:
        instances = []

        def __init__(self, base_dir="."):
            self.calls = []
            FakeStore.instances.append(self)

        def store(self, ref, payload):
            self.calls.append((ref, payload))
            return ref

    monkeypatch.setattr("app.services.artifact_store.FilesystemArtifactStore", FakeStore)
    ref_dict = _persist_artifact(
        "r1", "ground", "GroundingResult", GroundingResult(), context_version="v1"
    )
    assert len(FakeStore.instances) == 1
    stored_ref, payload = FakeStore.instances[0].calls[0]
    assert stored_ref.module == "ground"
    assert stored_ref.run_id == "r1"
    assert stored_ref.artifact_id == "ground-r1-v1"
    assert stored_ref.artifact_type == "GroundingResult"
    assert stored_ref.context_version == "v1"
    assert isinstance(payload, dict)
    assert ref_dict["module"] == "ground"
    assert ref_dict["artifact_id"] == "ground-r1-v1"
    assert ref_dict["run_id"] == "r1"
