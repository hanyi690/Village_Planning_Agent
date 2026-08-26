"""Focused tests for semantic spatial drafts and runtime-owned selection."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.contracts.spatial.spatial_reference_contracts import (
    CandidateSelectionProposal,
    SpatialQueryDraft,
    compile_spatial_query_draft,
    spatial_candidate_descriptor,
    spatial_candidate_input_digest,
    validate_spatial_candidate_proposal,
)


def _descriptors():
    return [
        spatial_candidate_descriptor(
            {"candidate_id": "feature:one", "canonical_name": "甲", "role": "facility"},
            kind="facility",
        ),
        spatial_candidate_descriptor(
            {"candidate_id": "feature:two", "canonical_name": "乙", "role": "facility"},
            kind="facility",
        ),
    ]


def test_query_draft_has_no_runtime_fields_and_compiler_adds_them():
    draft = SpatialQueryDraft(
        type="attributive",
        semantic_terms=["学校"],
        retrieval_scopes=["facilities"],
    )
    assert "target_id" not in draft.model_dump()
    with pytest.raises(ValidationError):
        SpatialQueryDraft.model_validate({
            "type": "attributive",
            "target_id": "forged-target",
        })
    with pytest.raises(ValidationError):
        SpatialQueryDraft.model_validate({
            "type": "attributive",
            "attr_filter": {"source_feature_id": "forged-feature"},
        })
    with pytest.raises(ValidationError):
        SpatialQueryDraft.model_validate({
            "type": "attributive",
            "reference": {
                "kind": "place_name",
                "filter": {"source_snapshot_ref": "forged-snapshot"},
            },
        })

    runtime = compile_spatial_query_draft(
        draft,
        spec_id="spec:1",
        target_id="target:1",
        source_snapshot_ref="snapshot:1",
        source_snapshot_digest="sha256:snapshot",
        materialization_role="site_footprint",
    )
    assert runtime.target_id == "target:1"
    assert runtime.source_snapshot_ref == "snapshot:1"
    assert runtime.materialization_role == "site_footprint"


def test_candidate_selection_requires_stable_id_and_exact_input_digest():
    candidates = _descriptors()
    digest = spatial_candidate_input_digest(
        decision_id="decision:1",
        query_text="甲设施",
        candidates=candidates,
    )
    decision = validate_spatial_candidate_proposal(
        decision_id="decision:1",
        query_text="甲设施",
        candidates=candidates,
        proposal=CandidateSelectionProposal(
            status="selected",
            selected_candidate_id="feature:two",
            input_digest=digest,
        ),
    )
    assert decision.status == "selected"
    assert decision.selected_candidate_id == "feature:two"
    assert decision.exact_membership.accepted
    assert decision.input_digest == digest

    mismatch = validate_spatial_candidate_proposal(
        decision_id="decision:1",
        query_text="甲设施",
        candidates=candidates,
        proposal={
            "status": "selected",
            "selected_candidate_id": "feature:two",
            "input_digest": "wrong",
        },
    )
    assert mismatch.status == "ambiguous"
    assert "digest" in mismatch.reason


def test_candidate_selection_rejects_index_payload_and_unknown_id():
    candidates = _descriptors()
    with pytest.raises(ValidationError):
        CandidateSelectionProposal.model_validate({
            "candidate_index": 1,
            "status": "selected",
            "selected_candidate_id": None,
            "input_digest": "x",
        })

    digest = spatial_candidate_input_digest(
        decision_id="decision:2",
        query_text="设施",
        candidates=candidates,
    )
    decision = validate_spatial_candidate_proposal(
        decision_id="decision:2",
        query_text="设施",
        candidates=candidates,
        proposal=CandidateSelectionProposal(
            status="selected",
            selected_candidate_id="feature:missing",
            input_digest=digest,
        ),
    )
    assert decision.status == "ambiguous"
    assert decision.selected_candidate_id is None


def test_candidate_selection_supports_explicit_abstain():
    candidates = _descriptors()
    digest = spatial_candidate_input_digest(
        decision_id="decision:3",
        query_text="设施",
        candidates=candidates,
    )
    decision = validate_spatial_candidate_proposal(
        decision_id="decision:3",
        query_text="设施",
        candidates=candidates,
        proposal=CandidateSelectionProposal(
            status="abstain",
            selected_candidate_id=None,
            input_digest=digest,
        ),
    )
    assert decision.status == "abstain"


def test_duplicate_runtime_candidate_ids_are_ambiguous():
    candidates = _descriptors()
    candidates[1] = candidates[0].model_copy(update={"label": "乙"})
    digest = spatial_candidate_input_digest(
        decision_id="decision:4",
        query_text="设施",
        candidates=candidates,
    )
    decision = validate_spatial_candidate_proposal(
        decision_id="decision:4",
        query_text="设施",
        candidates=candidates,
        proposal=CandidateSelectionProposal(
            status="selected",
            selected_candidate_id="feature:one",
            input_digest=digest,
        ),
    )
    assert decision.status == "ambiguous"
    assert not decision.exact_membership.accepted
