from app.domain.ground.gate import evaluate_ground_gate, ground_gate_route
from app.contracts.artifacts.contract_meta import StageIssue
from app.contracts.spatial.grounding_contracts import GroundingResult


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
