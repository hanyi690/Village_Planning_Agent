from pathlib import Path

from app.modules.evidence.proposals import (
    build_evidence_proposals,
    to_cognition_assertion_proposals,
)

from test_evidence_proposals import _requirement, _result


def test_evidence_proposal_compiler_has_no_world_model_writer_dependency():
    source = Path("backend/app/modules/evidence/proposals.py").read_text(encoding="utf-8")

    assert "WorldModelCommitPort" not in source
    assert "commit_assertion_transaction" not in source
    assert "world_model_store" not in source


def test_cognition_conversion_does_not_mutate_the_evidence_batch():
    result = _result(_requirement("identity"))
    batch = build_evidence_proposals(
        result,
        round_id="round-1",
        wm_epoch="wm-7",
        parent_world_model_digest="wm-7",
    )
    before = batch.model_dump(mode="json")

    to_cognition_assertion_proposals(batch)

    assert batch.model_dump(mode="json") == before


def test_absence_proposal_can_cross_the_cognition_contract_boundary():
    result = _result(
        _requirement("claim", metadata={"predicate": "exists"}),
        conclusion_kind="absence",
        candidates=(),
        claims=(),
        facts=(),
    )
    batch = build_evidence_proposals(
        result,
        round_id="round-1",
        wm_epoch="wm-7",
        parent_world_model_digest="wm-7",
    )

    assertion = to_cognition_assertion_proposals(batch)[0]

    assert assertion.value is False
    assert assertion.object_ref == ""
