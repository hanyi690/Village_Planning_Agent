"""DELIVER review package tests — 8 sections, JSON-serializable."""

import json

from app.agent.deliver.review import build_deliver_review_package
from app.modules.schema.contracts.delivery_manifest_contracts import (
    Deliverable,
    DeliveryGate,
    DeliveryManifest,
    HumanItem,
    TraceabilityEntry,
)
from app.modules.schema.contracts.provenance import Provenance
from app.modules.schema.contracts.workflow_contracts import GateDecision

_SECTIONS = {
    "交付清单",
    "溯源谱系",
    "出口门槛",
    "未决人工项",
    "规划分类缺失",
    "法定成果完整性",
    "Gate 决定",
    "来源追溯",
}


def _gate():
    return GateDecision(stage="deliver", passed=True, feedback_route=None)


def _manifest():
    return DeliveryManifest(
        context_version="v1",
        artifact_id="del-1",
        deliverables=[
            Deliverable(
                deliverable_id="deliverable-0",
                type="gdb_layer",
                path="output/layer_admin_area.geojson",
                format="geojson",
            )
        ],
        traceability=[
            TraceabilityEntry(
                intervention_id="iv-1",
                requirement_id="0",
                candidate_id="cand-1",
                selection_id="BSM001",
                change_id="BSM001",
                planned_ref="BSM001",
                deliverable_id="",
            )
        ],
        pending_human_items=[
            HumanItem(item_id="hi-class-0", description="补充规划分类编码", blocking=True)
        ],
        delivery_gate=DeliveryGate(land_balance_closed=True, zones_complete=True),
        statutory_complete=False,
        statutory_complete_breakdown={
            "delivery_gate": True,
            "no_blocking_items": False,
            "classification_complete": False,
        },
        provenance=Provenance(source="deliver_aggregate", run_id="r1", module="app.agent.deliver.aggregate"),
    )


def test_review_has_8_sections():
    package = build_deliver_review_package(_manifest(), _gate())
    assert set(package.keys()) == _SECTIONS


def test_review_deliverables_section():
    package = build_deliver_review_package(_manifest(), _gate())
    section = package["交付清单"]
    assert isinstance(section, list)
    assert section[0]["deliverable_id"] == "deliverable-0"


def test_review_traceability_section():
    package = build_deliver_review_package(_manifest(), _gate())
    section = package["溯源谱系"]
    assert section[0]["intervention_id"] == "iv-1"
    assert section[0]["planned_ref"] == "BSM001"


def test_review_gate_section():
    package = build_deliver_review_package(_manifest(), _gate())
    section = package["出口门槛"]
    assert section["land_balance_closed"] is True
    assert section["passed"] is True


def test_review_statutory_completeness_section():
    package = build_deliver_review_package(_manifest(), _gate())
    section = package["法定成果完整性"]
    assert section["statutory_complete"] is False
    assert section["breakdown"]["classification_complete"] is False


def test_review_json_serializable():
    package = build_deliver_review_package(_manifest(), _gate())
    json.dumps(package)


def test_review_provenance():
    package = build_deliver_review_package(_manifest(), _gate())
    assert package["来源追溯"]["source"] == "deliver_aggregate"
