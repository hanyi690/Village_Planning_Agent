from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.infrastructure.structured_runtime.contracts import (
    StructuredConsensusResult,
    StructuredPassResult,
)


def test_structured_pass_result_is_frozen_and_keeps_reasoning_as_metadata():
    result = StructuredPassResult(
        pass_number=1,
        status="completed",
        typed_output={"value": "ok"},
        reasoning_present=True,
        reasoning_channel="provider_split",
        reasoning_length=42,
        reasoning_digest="sha256:reasoning",
    )

    assert result.typed_output == {"value": "ok"}
    assert result.reasoning_length == 42
    assert "reasoning" not in result.typed_output
    with pytest.raises(ValidationError):
        result.pass_number = 2


def test_consensus_rejects_unknown_fields_and_tracks_pass_counts():
    result = StructuredConsensusResult(
        status="provider_failed",
        passes=(StructuredPassResult(
            pass_number=1,
            status="provider_failed",
            failure_code="TIMEOUT",
        ),),
        provider_failure_count=1,
        contract_key="data.temporal_role",
    )

    assert result.provider_failure_count == 1
    with pytest.raises(ValidationError):
        StructuredConsensusResult(status="completed", unexpected=True)
