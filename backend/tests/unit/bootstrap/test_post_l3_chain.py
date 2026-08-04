"""build_post_l3_chain graph factory tests."""

import pytest

from app.agent.bootstrap.post_l3_chain import (
    build_post_l3_chain,
    _route_after_parse,
    _route_after_deliver,
)
from app.agent.bootstrap.post_l3_state import PostL3ChainState
from app.modules.schema.contracts.workflow_contracts import GateDecision


def _gate(route):
    return GateDecision(
        stage="x", passed=(route is None), feedback_route=route
    )


def test_chain_compiles():
    graph = build_post_l3_chain()
    assert graph is not None


def test_route_after_parse_pass():
    state = PostL3ChainState(parse_gate=_gate(None))
    assert _route_after_parse(state) == "ground"


def test_route_after_parse_human():
    state = PostL3ChainState(parse_gate=_gate("HUMAN"))
    assert _route_after_parse(state) == "end"


def test_route_after_deliver_always_end():
    state = PostL3ChainState(deliver_gate=_gate(None))
    assert _route_after_deliver(state) == "end"
    state2 = PostL3ChainState(deliver_gate=_gate("RETRY_VALIDATE"))
    assert _route_after_deliver(state2) == "end"


@pytest.mark.asyncio
async def test_chain_linear_pass_produces_manifest(monkeypatch):
    """Full linear PASS run reaches the deliver node."""
    from app.modules.schema.contracts.delivery_manifest_contracts import DeliveryManifest
    from app.modules.schema.contracts.reconciliation_contracts import ReconciliationReport
    from app.modules.schema.contracts.validation_report_contracts import ValidationReport

    manifest = DeliveryManifest(statutory_complete=True)
    state = PostL3ChainState(
        session_id="s1",
        village_name="金田村",
        planning_program=type("P", (), {"artifact_id": "l3-1", "interventions": []})(),
    )

    captured = {}

    async def fake_parse(state):
        captured["parse"] = True
        return {
            "intent": type("I", (), {"project_targets": [], "road_targets": [], "zone_targets": [], "facilities": []})(),
            "specs": [],
            "parse_gate": _gate(None),
        }

    async def fake_ground(state):
        captured["ground"] = True
        return {
            "grounding_result": type("G", (), {"candidates": [], "unresolved": [], "context_version": ""})(),
            "ground_gate": _gate(None),
        }

    async def fake_select(state):
        captured["select"] = True
        return {
            "site_selection": type("D", (), {"selected_combination": [], "artifact_id": ""})(),
            "land_design_briefs": [],
            "select_gate": _gate(None),
        }

    async def fake_execute(state):
        captured["execute"] = True
        return {
            "planned_state": type("PS", (), {"parcels": [], "zones": [], "facilities": [], "roads": [], "axes": []})(),
            "parcel_changeset": type("CS", (), {"changes": []})(),
            "layout_configs": [],
            "allocated_geojson": {},
            "execution_errors": [],
        }

    async def fake_validate(state):
        captured["validate"] = True
        return {
            "validation_report": ValidationReport(overall_passed=True),
            "validate_gate": _gate(None),
        }

    async def fake_reconcile(state):
        captured["reconcile"] = True
        return {
            "reconciliation_report": ReconciliationReport(),
            "reconcile_gate": _gate(None),
        }

    async def fake_deliver(state):
        captured["deliver"] = True
        return {
            "delivery_manifest": manifest,
            "deliver_gate": _gate(None),
            "export_result": {"status": "completed", "exported_files": []},
        }

    monkeypatch.setattr("app.agent.bootstrap.post_l3_chain.parse_node", fake_parse)
    monkeypatch.setattr("app.agent.bootstrap.post_l3_chain.ground_node", fake_ground)
    monkeypatch.setattr("app.agent.bootstrap.post_l3_chain.select_node", fake_select)
    monkeypatch.setattr("app.agent.bootstrap.post_l3_chain.execute_node", fake_execute)
    monkeypatch.setattr("app.agent.bootstrap.post_l3_chain.validate_node", fake_validate)
    monkeypatch.setattr("app.agent.bootstrap.post_l3_chain.reconcile_node", fake_reconcile)
    monkeypatch.setattr("app.agent.bootstrap.post_l3_chain.deliver_node", fake_deliver)

    graph = build_post_l3_chain()
    final = await graph.ainvoke(state.model_dump())
    assert captured.get("deliver") is True
    assert final["delivery_manifest"] is manifest
    for key in ("parse", "ground", "select", "execute", "validate", "reconcile", "deliver"):
        assert captured.get(key) is True, key
