"""Contracts for the L1 dimension registration and bounded-pass cursor."""

from pydantic import ValidationError
import pytest

from app.contracts.domain.l1_contracts import (
    L1DimensionPassState,
    L1Snapshot,
)
from app.domain.assessment.observation_draft import (
    L1RegisterPassOutput,
    L1RegisterRowDraft,
)


def test_register_pass_keeps_rows_in_the_l1_register_projection() -> None:
    output = L1RegisterPassOutput.model_validate({
        "register_rows": [
            {
                "row_id": "l1:digest:current_asset:1:1",
                "ledger_kind": "current_asset",
                "status": "confirmed",
            },
            {
                "row_id": "l1:digest:demand:1:2",
                "ledger_kind": "demand",
                "status": "uncertain",
            },
        ],
    })

    assert [row.ledger_kind for row in output.register_rows] == [
        "current_asset",
        "demand",
    ]
    assert output.register_rows[1].status == "uncertain"


def test_register_draft_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        L1RegisterRowDraft(
            row_id="row-1",
            ledger_kind="current_asset",
            status="invented",
        )


def test_pass_cursor_is_json_round_trippable_and_snapshot_has_dimension_rows() -> None:
    cursor = L1DimensionPassState(
        dimension_key="traffic",
        source_digest="sha256:source",
        pass_name="repair",
        attempt=1,
        max_attempts=2,
        pending_row_ids=["row-2"],
        rejected_row_ids=["row-2"],
        diagnostics=["location_missing"],
        calls_used=2,
        status="running",
    )
    restored = L1DimensionPassState.model_validate_json(cursor.model_dump_json())
    snapshot = L1Snapshot(register_diagnostics_by_dimension={"traffic": ["location_missing"]})

    assert restored.pass_name == "repair"
    assert restored.pending_row_ids == ["row-2"]
    assert snapshot.register_diagnostics_by_dimension["traffic"] == ["location_missing"]
