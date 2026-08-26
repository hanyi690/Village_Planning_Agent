from app.domain.validation.closed_set import (
    CandidateDescriptor,
    select_closed_set_candidate,
    validate_exact_batch_membership,
)


def _candidates() -> list[CandidateDescriptor]:
    return [
        CandidateDescriptor(candidate_id="facility-1", kind="facility", label="卫生室"),
        CandidateDescriptor(candidate_id="facility-2", kind="facility", label="文化室"),
    ]


def test_selects_stable_id_and_digest_is_order_independent() -> None:
    first = select_closed_set_candidate(
        decision_id="d1",
        candidates=_candidates(),
        proposed_candidate_id="facility-2",
        abstain_allowed=True,
    )
    second = select_closed_set_candidate(
        decision_id="d1",
        candidates=list(reversed(_candidates())),
        proposed_candidate_id="facility-2",
        abstain_allowed=True,
    )
    assert first.status == "selected"
    assert first.selected_candidate_id == "facility-2"
    assert first.candidate_set_digest == second.candidate_set_digest


def test_unknown_id_never_falls_back_to_first_candidate() -> None:
    result = select_closed_set_candidate(
        decision_id="d2",
        candidates=_candidates(),
        proposed_candidate_id="3",
        abstain_allowed=True,
    )
    assert result.status == "abstain"
    assert result.selected_candidate_id is None


def test_missing_proposal_can_be_ambiguous_when_abstain_is_forbidden() -> None:
    result = select_closed_set_candidate(
        decision_id="d3",
        candidates=_candidates(),
        proposed_candidate_id=None,
        abstain_allowed=False,
    )
    assert result.status == "ambiguous"


def test_duplicate_candidate_ids_are_ambiguous() -> None:
    candidates = _candidates() + [CandidateDescriptor(candidate_id="facility-1", kind="facility")]
    result = select_closed_set_candidate(
        decision_id="d4",
        candidates=candidates,
        proposed_candidate_id="facility-1",
        abstain_allowed=True,
    )
    assert result.status == "ambiguous"


def test_exact_batch_membership_rejects_missing_extra_and_duplicates() -> None:
    result = validate_exact_batch_membership(
        ["a", "b"],
        ["a", "a", "c"],
    )
    assert result.accepted is False
    assert result.missing_ids == ("b",)
    assert result.extra_ids == ("c",)
    assert result.duplicate_ids == ("a",)
