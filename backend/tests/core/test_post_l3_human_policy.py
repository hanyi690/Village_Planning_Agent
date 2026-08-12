from app.workflow.root_graph import _human_review_blocking_target_ids


def test_validate_human_items_are_authoritative_when_gate_pending_requests_are_empty():
    target_ids, non_target_blockers = _human_review_blocking_target_ids(
        {
            "validate_gate": {"pending_requests": []},
            "human_review_items": [{
                "request_id": "pr-validate-retry_execute-0",
                "stage": "validate",
                "context": {"target_ids": ["parcel-1", "parcel-2"]},
            }],
        },
        "validate",
    )

    assert target_ids == {"parcel-1", "parcel-2"}
    assert non_target_blockers == 0
