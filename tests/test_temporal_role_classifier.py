from __future__ import annotations

import pytest

from app.contracts.data.temporal_role_contracts import (
    SourceTemporalRoleDecision,
    TemporalRoleProposal,
    TemporalRoleProposalBatch,
)
from app.data.ingestion.temporal_role_classifier import (
    build_temporal_role_input,
    classify_temporal_role_async,
)
from app.infrastructure.structured_runtime.contracts import (
    StructuredConsensusResult,
    StructuredPassResult,
)


@pytest.mark.asyncio
async def test_same_role_with_different_valid_reasons_is_consensus(
    monkeypatch: pytest.MonkeyPatch,
):
    row = build_temporal_role_input(
        source_ref="upload:fixture",
        declared_channel="planning_control",
        resource_kind="markdown",
        filename="input.md",
        parsed_text="请提供本次规划约束。",
    )
    outputs = (
        TemporalRoleProposalBatch(proposals=(TemporalRoleProposal(
            profile_ref=row.profile_ref,
            selected_role="planning_control",
            reason_code="requested_future_action",
            confidence=0.85,
        ),)),
        TemporalRoleProposalBatch(proposals=(TemporalRoleProposal(
            profile_ref=row.profile_ref,
            selected_role="planning_control",
            reason_code="hard_constraint",
            confidence=0.82,
        ),)),
    )
    consensus = StructuredConsensusResult(
        status="completed",
        passes=tuple(
            StructuredPassResult(
                pass_number=index,
                status="completed",
                typed_output=value,
            )
            for index, value in enumerate(outputs, start=1)
        ),
        completed_pass_count=2,
        contract_key="data.temporal_role",
    )
    monkeypatch.setattr(
        "app.infrastructure.structured_runtime.consensus.run_structured_consensus",
        lambda *args, **kwargs: _return(consensus),
    )

    result = await classify_temporal_role_async(row)

    assert result.status == "accepted"
    assert result.selected_role == "planning_control"
    assert result.reason_code == "hard_constraint"
    assert result.provider_pass_count == 2


async def _return(value):
    return value
