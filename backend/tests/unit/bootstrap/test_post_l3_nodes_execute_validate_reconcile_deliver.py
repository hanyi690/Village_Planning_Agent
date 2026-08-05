"""Post-L3 chain nodes (execute/validate/reconcile/deliver) tests."""

from types import SimpleNamespace

import pytest

from app.agent.bootstrap.post_l3_nodes import (
    deliver_node,
    execute_node,
    reconcile_node,
    validate_node,
)
from app.agent.bootstrap.post_l3_state import PostL3ChainState
from app.modules.schema.contracts.workflow_contracts import GateDecision


def _pass_gate(stage="validate"):
    return GateDecision(stage=stage, passed=True, feedback_route=None)


def _bundle():
    return SimpleNamespace(
        to_geojson_dict=lambda: {"landuse_current_geojson": {}},
        bundle_parcels=lambda: ["P1"],
        polygons=SimpleNamespace(get=lambda k: []),
    )


def _context():
    return SimpleNamespace(
        bundle=_bundle(),
        constraint_index=None,
        village_anchors=None,
        kg_session_ref="kg-1",
        session_id="s1",
    )


def _planned_state():
    return SimpleNamespace(parcels=[], zones=[], facilities=[], roads=[], axes=[])


@pytest.mark.asyncio
async def test_execute_node_runs_subgraph(monkeypatch):
    changeset = SimpleNamespace(changes=[])
    planned = _planned_state()

    async def fake_graph_ainvoke(exec_dict):
        return {"parcel_changeset": changeset, "layout_configs": [], "allocated_geojson": {}, "execution_errors": []}

    class FakeGraph:
        async def ainvoke(self, d):
            return await fake_graph_ainvoke(d)

    monkeypatch.setattr(
        "app.agent.execute.execute_agent.build_execute_agent_graph",
        lambda: FakeGraph(),
    )
    monkeypatch.setattr(
        "app.agent.execute.planned_state_builder.changeset_to_planned_state",
        lambda changeset, intent: planned,
    )
    state = PostL3ChainState(
        session_id="s1", village_name="金田村", intent=SimpleNamespace(),
        site_selection=SimpleNamespace(), context=_context(),
    )
    out = await execute_node(state)
    assert out["planned_state"] is planned
    assert out["parcel_changeset"] is changeset


@pytest.mark.asyncio
async def test_validate_node_runs_aggregate(monkeypatch):
    report = SimpleNamespace(overall_passed=True)
    gate = _pass_gate("validate")
    monkeypatch.setattr(
        "app.agent.validate.aggregate.validate_aggregate",
        lambda ps, cs, lc, intent, cidx, run_id="": report,
    )
    monkeypatch.setattr(
        "app.agent.validate.gate.evaluate_validate_gate",
        lambda report: gate,
    )
    state = PostL3ChainState(
        planned_state=_planned_state(), intent=SimpleNamespace(), context=_context()
    )
    out = await validate_node(state)
    assert out["validation_report"] is report
    assert out["validate_gate"] is gate
    assert len(out["upstream_gates"]) == 1


@pytest.mark.asyncio
async def test_reconcile_node_runs_aggregate(monkeypatch):
    report = SimpleNamespace(inconsistencies=[])
    gate = _pass_gate("reconcile")
    monkeypatch.setattr(
        "app.agent.reconcile.aggregate.reconcile_aggregate",
        lambda *args, **kwargs: report,
    )
    monkeypatch.setattr(
        "app.agent.reconcile.gate.evaluate_reconcile_gate",
        lambda report: gate,
    )
    state = PostL3ChainState(
        planned_state=_planned_state(),
        intent=SimpleNamespace(),
        context=_context(),
    )
    out = await reconcile_node(state)
    assert out["reconciliation_report"] is report
    assert out["reconcile_gate"] is gate


@pytest.mark.asyncio
async def test_deliver_node_produces_manifest(monkeypatch):
    manifest = SimpleNamespace(statutory_complete=True)
    gate = _pass_gate("deliver")
    monkeypatch.setattr(
        "app.agent.deliver.aggregate.deliver_aggregate",
        lambda ps, vr, rr, ug, er, current_parcels=None, run_id="": manifest,
    )
    monkeypatch.setattr(
        "app.agent.deliver.gate.evaluate_deliver_gate",
        lambda manifest: gate,
    )
    monkeypatch.setattr(
        "app.modules.spatial_ops.output.export_package.export_gdb_package",
        lambda **kwargs: {"status": "completed", "exported_files": ["a.geojson"]},
    )
    state = PostL3ChainState(
        session_id="s1",
        village_name="金田村",
        planned_state=_planned_state(),
        layout_configs=[{"layerType": "planned_project"}],
        validation_report=SimpleNamespace(overall_passed=True),
        reconciliation_report=SimpleNamespace(),
        context=_context(),
    )
    out = await deliver_node(state)
    assert out["delivery_manifest"] is manifest
    assert out["deliver_gate"] is gate
    assert out["export_result"]["status"] == "completed"
    assert len(out["upstream_gates"]) == 1
