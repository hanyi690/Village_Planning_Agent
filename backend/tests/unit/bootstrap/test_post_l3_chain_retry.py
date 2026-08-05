"""Post-L3 chain retry loops + HUMAN route tests (Wave M2)."""

from types import SimpleNamespace

import pytest

from app.agent.bootstrap.post_l3_chain import (
    build_post_l3_chain,
    _route_after_parse,
    _route_after_ground,
    _route_after_select,
    _route_after_validate,
    _route_after_reconcile,
    _route_after_deliver,
)
from app.agent.bootstrap.post_l3_state import PostL3ChainState
from app.modules.schema.contracts.workflow_contracts import GateDecision


def _gate(route, stage="parse"):
    return GateDecision(stage=stage, passed=(route is None), feedback_route=route)


def _state(gate_field, gate, **kwargs):
    return PostL3ChainState(**{gate_field: gate, **kwargs})


# ── Route function tests ──

def test_route_after_parse_pass():
    state = _state("parse_gate", _gate(None))
    assert _route_after_parse(state) == "ground"


def test_route_after_parse_repair_retries():
    state = _state("parse_gate", _gate("REPAIR"), retry_counts={})
    assert _route_after_parse(state) == "parse"


def test_route_after_parse_repair_max_retries_human():
    state = _state("parse_gate", _gate("REPAIR"), retry_counts={"parse": 3}, max_retries=3)
    assert _route_after_parse(state) == "human_end"


def test_route_after_parse_human():
    state = _state("parse_gate", _gate("HUMAN"))
    assert _route_after_parse(state) == "human_end"


def test_route_after_ground_explore_retries():
    state = _state("ground_gate", _gate("EXPLORE", "ground"), retry_counts={})
    assert _route_after_ground(state) == "ground"


def test_route_after_ground_explore_max_retries():
    state = _state("ground_gate", _gate("EXPLORE", "ground"), retry_counts={"ground": 3}, max_retries=3)
    assert _route_after_ground(state) == "human_end"


def test_route_after_select_retry_ground():
    state = _state("select_gate", _gate("RETRY_GROUND", "select"), retry_counts={})
    assert _route_after_select(state) == "ground"


def test_route_after_validate_retry_execute():
    state = _state("validate_gate", _gate("RETRY_EXECUTE", "validate"), retry_counts={})
    assert _route_after_validate(state) == "execute"


def test_route_after_validate_retry_select():
    state = _state("validate_gate", _gate("RETRY_SELECT", "validate"), retry_counts={})
    assert _route_after_validate(state) == "select"


def test_route_after_validate_retry_parse():
    state = _state("validate_gate", _gate("RETRY_PARSE", "validate"), retry_counts={})
    assert _route_after_validate(state) == "parse"


def test_route_after_validate_retry_l3_cannot_loop():
    state = _state("validate_gate", _gate("RETRY_L3", "validate"), retry_counts={})
    assert _route_after_validate(state) == "end"


def test_route_after_reconcile_retry_execute():
    state = _state("reconcile_gate", _gate("RETRY_EXECUTE", "reconcile"), retry_counts={})
    assert _route_after_reconcile(state) == "execute"


def test_route_after_deliver_retry_validate():
    state = _state("deliver_gate", _gate("RETRY_VALIDATE", "deliver"), retry_counts={})
    assert _route_after_deliver(state) == "validate"


def test_route_after_deliver_pass():
    state = _state("deliver_gate", _gate(None, "deliver"))
    assert _route_after_deliver(state) == "end"


# ── Graph compilation test ──

def test_chain_compiles_with_retry():
    graph = build_post_l3_chain()
    assert graph is not None


# ── HUMAN route populates human_review_items ──

@pytest.mark.asyncio
async def test_human_review_node_populates_items(monkeypatch):
    from app.agent.bootstrap.post_l3_nodes import human_review_node
    from app.modules.schema.contracts.workflow_contracts import PendingRequest

    gate = GateDecision(
        stage="parse",
        passed=False,
        feedback_route="HUMAN",
        pending_requests=[
            PendingRequest(
                request_id="pr-1",
                stage="parse",
                request_type="parse_human",
                context={"reason": "HUMAN"},
            ),
        ],
    )
    state = PostL3ChainState(parse_gate=gate, human_review_items=[])
    result = await human_review_node(state)
    assert len(result["human_review_items"]) == 1
    assert result["human_review_items"][0]["request_id"] == "pr-1"
