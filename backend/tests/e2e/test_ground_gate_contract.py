from app.domain.ground.gate import evaluate_ground_gate, ground_gate_route
from app.contracts.artifacts.contract_meta import StageIssue
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounding_contracts import CandidateSite, GroundingResult


def test_unresolved_target_reference_routes_to_human_with_target_id():
    result = GroundingResult(
        unresolved=[
            StageIssue(
                stage="ground",
                severity="warning",
                code="spatial_reference_unresolved",
                message="村名没有权威空间绑定",
                related_artifact_id="target-facility-1",
            )
        ]
    )

    assert ground_gate_route(result) == "HUMAN"
    gate = evaluate_ground_gate(result)
    assert gate.feedback_route == "HUMAN"
    assert gate.pending_requests[0].context["target_ids"] == ["target-facility-1"]


def test_empty_grounding_without_target_issue_can_explore():
    assert ground_gate_route(GroundingResult()) == "EXPLORE"


def test_legacy_multi_parcel_confidence_routes_to_human_conservatively():
    result = GroundingResult(
        candidates=[
            CandidateSite(
                site_id="legacy-multi",
                target_ref="target-legacy",
                source_parcels=["P-1", "P-2"],
                metrics={"confidence": 0.95},
                geometry=CandidateGeometry(
                    candidate_id="legacy-multi",
                    target_id="target-legacy",
                    kind="polygon",
                    role="execution_geometry",
                    materialization_role="site_footprint",
                    wkt="POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))",
                    source_ref="legacy:geometry",
                    evidence_refs=["legacy:geometry"],
                    confidence=0.95,
                    hard_constraint_status="passed",
                    availability_status="fully_available",
                ),
            )
        ]
    )

    assert ground_gate_route(result) == "HUMAN"
    assert evaluate_ground_gate(result).feedback_route == "HUMAN"
