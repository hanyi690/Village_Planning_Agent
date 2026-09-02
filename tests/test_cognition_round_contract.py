import pytest

from app.contracts.cognition_round import CognitionRound, requirement_set_digest
from app.contracts.evidence.requirement_contracts import EvidenceRequirement
from app.workflow.cognition_context import open_cognition_round


def _requirement(statement: str = "road R1 exists") -> EvidenceRequirement:
    return EvidenceRequirement(
        requirement_id="req-1",
        statement=statement,
        kind="claim",
        policy_ref="road_identity.v1",
    )


def _state() -> dict[str, str]:
    return {
        "run_id": "workflow-1",
        "branch_id": "main",
        "world_model_snapshot_ref": "world-model://session-1/1/wm-1",
        "world_model_snapshot_digest": "wm-1",
        "world_model_epoch": "1",
    }


def test_workflow_round_factory_is_deterministic_and_pins_parent():
    requirement = _requirement()

    first = open_cognition_round(_state(), (requirement,))
    second = open_cognition_round(_state(), (requirement,))

    assert first == second
    assert first.round_id.startswith("cognition-round:")
    assert first.wm_epoch == "1"
    assert first.parent_world_model_snapshot_ref == _state()["world_model_snapshot_ref"]
    assert first.parent_world_model_snapshot_digest == "wm-1"
    assert first.requirement_set_digest == requirement_set_digest((requirement,))
    assert first.proposal_fingerprint == ""
    assert first.status == "open"


def test_round_changes_when_requirement_set_or_parent_changes():
    first = open_cognition_round(_state(), (_requirement(),))
    changed_requirement = open_cognition_round(
        _state(),
        (_requirement("road R2 exists"),),
    )
    changed_parent = open_cognition_round(
        {
            **_state(),
            "world_model_snapshot_digest": "wm-2",
        },
        (_requirement(),),
    )

    assert changed_requirement.round_id != first.round_id
    assert changed_parent.round_id != first.round_id
    assert changed_parent.parent_world_model_snapshot_digest == "wm-2"


def test_closed_round_requires_frozen_proposal_fingerprint():
    round_contract = open_cognition_round(_state(), (_requirement(),))

    with pytest.raises(ValueError, match="closed cognition round"):
        CognitionRound.model_validate({
            **round_contract.model_dump(mode="json"),
            "status": "frozen",
        })

    frozen = round_contract.freeze("sha256:" + "a" * 64)
    assert frozen.status == "frozen"
    assert frozen.proposal_fingerprint == "sha256:" + "a" * 64
    assert frozen.freeze(frozen.proposal_fingerprint) == frozen

    with pytest.raises(ValueError, match="already frozen"):
        frozen.freeze("sha256:" + "b" * 64)


def test_round_rejects_malformed_proposal_fingerprints():
    with pytest.raises(ValueError, match="proposal_fingerprint"):
        round_contract = open_cognition_round(_state(), (_requirement(),))
        round_contract.freeze("sha256:not-a-digest")
