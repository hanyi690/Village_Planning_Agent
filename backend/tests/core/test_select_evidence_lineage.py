from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounding_contracts import CandidateSite, GroundingResult
from app.contracts.domain.selection_contracts import SiteSelectionDecision, TargetAssignment
from app.domain.allocation.select_service import _attach_grounding_lineage_to_decision
from app.domain.materialization.plan_builder import build_execution_plan


def test_select_assignment_preserves_grounding_evidence_lineage() -> None:
    site = CandidateSite(
        site_id="site-1",
        source_parcels=["44142621100000009001"],
        target_ref="target-1",
        evidence_refs=["bundle:parcel:44142621100000009001"],
        geometry=CandidateGeometry(
            target_id="target-1",
            kind="polygon",
            role="parcel_candidate",
            wkt="POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))",
            source_bsms=["44142621100000009001"],
            relation_refs=["kg:relation:road-parcel"],
            l1_fact_refs=["l1:fact:road-access"],
            evidence_refs=["kg:relation:road-parcel", "l1:fact:road-access"],
            l1_snapshot_ref="artifact://l1/snapshot-1",
            bundle_snapshot_digest="bundle-digest-1",
        ),
    )
    decision = SiteSelectionDecision(
        target_assignments=[
            TargetAssignment(
                target_id="target-1",
                target_type="site_area",
                status="placed",
                selected_bsm="44142621100000009001",
                expected_output_kind="point",
            )
        ]
    )

    updated = _attach_grounding_lineage_to_decision(
        decision,
        GroundingResult(candidates=[site]),
    )

    assignment = updated.target_assignments[0]
    assert "kg:relation:road-parcel" in assignment.evidence_refs
    assert assignment.relation_refs == ["kg:relation:road-parcel"]
    assert assignment.l1_snapshot_ref == "artifact://l1/snapshot-1"
    assert assignment.bundle_snapshot_digest == "bundle-digest-1"
    assert assignment.target_binding["grounding_lineage"]["candidate_ids"] == [
        site.candidate_id
    ]

    plan = build_execution_plan(
        type(
            "Intent",
            (),
            {
                "site_area_targets": [
                    type(
                        "Target",
                        (),
                        {
                            "target_id": "target-1",
                            "expected_output_kind": "point",
                            "execution_mode": "spatial",
                        },
                    )()
                ],
                "zone_targets": [],
                "custom_zone_targets": [],
                "facilities": [],
                "development_axes": [],
                "road_targets": [],
                "linear_targets": [],
            },
        )(),
        updated,
        [],
        run_id="run-1",
    )
    task = plan.worker_tasks[0]
    assert task.relation_ids == ["kg:relation:road-parcel"]
    assert task.assignment.target_binding["target_id"] == "target-1"
    assert task.assignment.target_binding["expected_output_kind"] == "point"


def test_execution_plan_expands_required_member_selection() -> None:
    intent = type(
        "Intent",
        (),
        {
            "site_area_targets": [
                type(
                    "Target",
                    (),
                    {
                        "target_id": "road-network",
                        "expected_output_kind": "line",
                        "execution_mode": "spatial",
                    },
                )()
            ],
            "zone_targets": [],
            "custom_zone_targets": [],
            "facilities": [],
            "development_axes": [],
            "road_targets": [],
            "linear_targets": [],
        },
    )()
    decision = SiteSelectionDecision(
        scenario_id="scenario:roads",
        target_assignments=[TargetAssignment(
            target_id="road-network",
            target_type="site_area",
            status="placed",
            expected_output_kind="line",
        )],
    )

    plan = build_execution_plan(
        intent,
        decision,
        [],
        scenario_target_selections={
            "road-network": ["road-1", "road-2", "road-3"],
        },
    )

    assert [task.candidate_id for task in plan.worker_tasks] == [
        "road-1",
        "road-2",
        "road-3",
    ]
    assert all(task.candidate_ids == ["road-1", "road-2", "road-3"] for task in plan.worker_tasks)
    assert [task.task_id for task in plan.worker_tasks] == [
        "site_area_footprint:road-network:member:1",
        "site_area_footprint:road-network:member:2",
        "site_area_footprint:road-network:member:3",
    ]
