from __future__ import annotations

from langgraph.types import Send

from app.contracts.artifacts.artifact_descriptor import ArtifactDescriptor
from app.workflow.dispatch import (
    DispatchDiagnosticCode,
    DispatchPolicy,
    DispatchProposal,
    parse_and_evaluate_dispatch,
)
from app.workflow.routing import authorize_route_result
from app.workflow.terminal import TerminalStatus, diagnostic_terminal, terminal_patch


def _descriptor(name: str) -> dict[str, object]:
    digest = "sha256:" + (name.encode().hex() * 64)[:64]
    return ArtifactDescriptor(
        digest=digest,
        descriptor_digest=digest,
        size_bytes=1,
        schema_id=name,
        schema_version="1",
        semantic_digest=digest,
        producer_stage=name,
        run_id="run-1",
        branch_id="main",
    ).model_dump(mode="json")


def test_valid_dispatch_resolves_parent_descriptors_into_command() -> None:
    state = {
        "active_stage": "target_projection",
        "artifact_refs": {"target_projection": _descriptor("target_projection")},
    }
    proposal = DispatchProposal(
        allowed_action="advance",
        target_stage="ground",
        input_refs={"target_projection": state["artifact_refs"]["target_projection"]["digest"]},
        reason="projection passed its gate",
    )

    decision = DispatchPolicy().authorize(proposal, state)

    assert decision.accepted is True
    assert decision.command is not None
    assert decision.command.target_stage == "ground"
    assert decision.command.parent_digests


def test_cross_stage_jump_is_rejected_with_typed_diagnostic() -> None:
    state = {
        "active_stage": "select",
        "artifact_refs": {"target_projection": _descriptor("target_projection")},
    }
    proposal = DispatchProposal(
        allowed_action="advance",
        target_stage="target_projection",
        reason="illegal backward jump",
    )

    decision = DispatchPolicy().authorize(proposal, state)

    assert decision.accepted is False
    assert decision.diagnostic is not None
    assert decision.diagnostic.code == DispatchDiagnosticCode.UNAUTHORIZED_STAGE


def test_missing_parent_and_malformed_proposal_do_not_fall_through() -> None:
    missing = DispatchPolicy().authorize(
        DispatchProposal(allowed_action="advance", target_stage="ground", reason="missing parent"),
        {"active_stage": "target_projection", "artifact_refs": {}},
    )
    malformed = parse_and_evaluate_dispatch(
        {"allowed_action": "advance", "target_stage": "ground", "unexpected": True},
        {},
    )

    assert missing.diagnostic is not None
    assert missing.diagnostic.code == DispatchDiagnosticCode.MISSING_PARENT_ARTIFACT
    assert malformed.diagnostic is not None
    assert malformed.diagnostic.code == DispatchDiagnosticCode.MALFORMED_PROPOSAL


def test_attempt_and_budget_limits_are_typed_rejections() -> None:
    state = {
        "active_stage": "target_projection",
        "retry_counts": {"ground": 2},
        "max_attempts": 2,
        "dispatch_budget_used": 2,
        "max_dispatch_budget": 2,
        "artifact_refs": {"target_projection": _descriptor("target_projection")},
    }
    proposal = DispatchProposal(
        allowed_action="advance",
        target_stage="ground",
        input_refs={"target_projection": "target_projection"},
        reason="over limits",
        budget=1,
    )

    decision = DispatchPolicy(max_attempts=3, max_budget=3).authorize(proposal, state)

    assert decision.diagnostic is not None
    assert decision.diagnostic.code == DispatchDiagnosticCode.ATTEMPT_LIMIT_EXCEEDED


def test_dynamic_send_batch_is_checked_before_graph_dispatch() -> None:
    result = authorize_route_result(
        {"active_stage": "conversation"},
        "conversation",
        [Send("l1_worker", {"dimension_key": "a"})],
    )

    assert result.accepted is True
    assert result.dynamic is True
    assert result.target_stages == ("l1_worker",)


def test_diagnostic_becomes_terminal_only_state_patch() -> None:
    decision = DispatchPolicy().authorize(
        DispatchProposal(allowed_action="teleport", target_stage="deliver", reason="bad action"),
        {"active_stage": "select"},
    )
    assert decision.diagnostic is not None

    result = diagnostic_terminal(decision.diagnostic)
    patch = terminal_patch(result)

    assert result.status == TerminalStatus.DIAGNOSTIC_ONLY
    assert patch["delivery_status"] == "diagnostic_only"
    assert patch["terminal_ref"] == patch["diagnostic_terminal"]
