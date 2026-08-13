"""plan_builder deferral-lift regression tests.

A HUMAN deferral is a point-in-time decision.  When a later GROUND/SELECT
revision provides resolution evidence (candidate parcels / selected BSM /
anchors / road endpoints), the target must be lifted back into worker_tasks.
Targets without evidence stay deferred.
"""
from __future__ import annotations

from app.contracts.artifacts.deferral_contracts import (
    DeferralLedger,
    HumanDeferralDecision,
    TargetDeferral,
)
from app.contracts.artifacts.classification_ref import (
    ClassificationDecision,
    ClassificationSystem,
)
from app.contracts.workflow.parse_contracts import ZoneTarget, RoadTarget
from app.domain.materialization.plan_builder import build_execution_plan


def _decision(target_id: str) -> ClassificationDecision:
    return ClassificationDecision(
        target_id=target_id,
        code_system=ClassificationSystem.GBT21010,
        candidate_codes=["1207"],
        selected_code="1207",
        evidence_refs=["human-review:test"],
        status="resolved",
    )


def _deferral_ledger(*target_ids: str) -> DeferralLedger:
    return DeferralLedger(entries=tuple(
        TargetDeferral(
            target_id=tid,
            reason="validate_structural_failure",
            decision=HumanDeferralDecision(decision_id=f"review-{tid}"),
        )
        for tid in target_ids
    ))


def test_deferred_zone_with_only_grounded_parcels_stays_deferred_until_global_select():
    zone = ZoneTarget(
        target_id="zone-grounded",
        zone_id="zone-grounded",
        land_use="A01",
        candidate_bsms=["P001", "P002"],
        classification_decision=_decision("zone-grounded"),
    )
    intent = type("Intent", (), {"zone_targets": [zone]})()
    selection = type("Selection", (), {"target_assignments": []})()
    plan = build_execution_plan(
        intent, selection, [],
        deferral_ledger=_deferral_ledger("zone-grounded"),
    )
    assert plan.worker_tasks == []
    assert [task.target_id for task in plan.deferred_tasks] == ["zone-grounded"]


def test_deferred_zone_without_evidence_stays_deferred():
    zone = ZoneTarget(
        target_id="zone-empty",
        zone_id="zone-empty",
        land_use="A01",
        candidate_bsms=[],
        classification_decision=_decision("zone-empty"),
    )
    intent = type("Intent", (), {"zone_targets": [zone]})()
    selection = type("Selection", (), {"target_assignments": []})()
    plan = build_execution_plan(
        intent, selection, [],
        deferral_ledger=_deferral_ledger("zone-empty"),
    )
    assert plan.worker_tasks == []
    assert [task.target_id for task in plan.deferred_tasks] == ["zone-empty"]


def test_deferred_road_with_proxy_endpoints_stays_deferred():
    road = RoadTarget(
        target_id="road-lift",
        road_level="村道",
        width_m=4.0,
        connects=["村北", "村南"],
        start_anchor=(113.0, 23.0),
        end_anchor=(113.01, 23.01),
        candidate_bsms=["P003", "P004"],
    )
    intent = type("Intent", (), {"road_targets": [road]})()
    selection = type("Selection", (), {"target_assignments": []})()
    plan = build_execution_plan(
        intent, selection, [],
        deferral_ledger=_deferral_ledger("road-lift"),
    )
    assert plan.worker_tasks == []
    assert [task.target_id for task in plan.deferred_tasks] == ["road-lift"]
