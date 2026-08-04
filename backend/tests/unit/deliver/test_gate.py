"""DELIVER gate tests — 3-way route (PASS/RETRY_VALIDATE/HUMAN)."""

from app.agent.deliver.gate import deliver_gate_route, evaluate_deliver_gate
from app.modules.schema.contracts.delivery_manifest_contracts import (
    DeliveryGate,
    DeliveryManifest,
    HumanItem,
)


def _manifest(*, statutory_complete=False, items=None, gate=None):
    return DeliveryManifest(
        statutory_complete=statutory_complete,
        pending_human_items=list(items or []),
        delivery_gate=gate,
    )


def test_gate_passes_when_statutory_complete():
    dm = _manifest(statutory_complete=True, gate=DeliveryGate(land_balance_closed=True))
    assert deliver_gate_route(dm) == "PASS"
    decision = evaluate_deliver_gate(dm)
    assert decision.passed is True
    assert decision.feedback_route is None
    assert decision.pending_requests == []


def test_gate_routes_retry_validate_on_classification_missing():
    dm = _manifest(
        items=[
            HumanItem(item_id="hi-class-0", description="补充规划分类编码", blocking=True)
        ],
        gate=DeliveryGate(land_balance_closed=True),
    )
    assert deliver_gate_route(dm) == "RETRY_VALIDATE"
    decision = evaluate_deliver_gate(dm)
    assert decision.passed is False
    assert decision.feedback_route == "RETRY_VALIDATE"
    assert decision.pending_requests
    assert decision.pending_requests[0].stage == "deliver"


def test_gate_routes_human_on_export_failure():
    dm = _manifest(
        items=[HumanItem(item_id="hi-layers-planned_landuse", blocking=True)],
        gate=DeliveryGate(land_balance_closed=True),
    )
    assert deliver_gate_route(dm) == "HUMAN"


def test_gate_routes_human_on_upstream_unresolved():
    dm = _manifest(
        items=[HumanItem(item_id="hi-upstream-0", blocking=True)],
        gate=DeliveryGate(land_balance_closed=True),
    )
    assert deliver_gate_route(dm) == "HUMAN"


def test_gate_routes_human_on_tie():
    dm = _manifest(
        items=[
            HumanItem(item_id="hi-class-0", blocking=True),
            HumanItem(item_id="hi-layers-planned_landuse", blocking=True),
        ],
        gate=DeliveryGate(land_balance_closed=True),
    )
    assert deliver_gate_route(dm) == "HUMAN"


def test_gate_routes_human_on_gate_failure_no_blocking_item():
    dm = _manifest(
        items=[],
        gate=DeliveryGate(land_balance_closed=False, zones_complete=False),
    )
    assert deliver_gate_route(dm) == "HUMAN"


def test_gate_pending_requests_populated():
    dm = _manifest(
        items=[HumanItem(item_id="hi-class-0", description="补充规划分类编码", blocking=True)],
        gate=DeliveryGate(land_balance_closed=True),
    )
    decision = evaluate_deliver_gate(dm)
    pr = decision.pending_requests[0]
    assert pr.request_id.startswith("pr-deliver-")
    assert pr.request_type == "deliver_retry_validate"
    assert pr.context["reason"] == "RETRY_VALIDATE"
