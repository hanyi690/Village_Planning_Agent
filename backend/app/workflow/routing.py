"""Workflow route adapters that force graph edges through dispatch policy."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from app.workflow.dispatch import (
    DispatchAction,
    DispatchDiagnostic,
    DispatchPolicy,
    DispatchProposal,
    evaluate_dispatch,
)


class RouteAuthorization(BaseModel):
    """Audit result for one conditional edge or a dynamic Send batch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted: bool
    target_stages: tuple[str, ...] = ()
    diagnostic: DispatchDiagnostic | None = None
    dynamic: bool = False


class WorkflowRouting:
    """Small facade used by root graph call sites and focused tests."""

    _WORKER_STAGES: ClassVar[frozenset[str]] = frozenset({"l1_worker", "l2_worker", "l3_worker"})

    @staticmethod
    def proposal(
        state: Mapping[str, object],
        source_stage: str,
        target_stage: str,
        *,
        action: str | None = None,
        reason: str = "root graph transition",
    ) -> DispatchProposal:
        refs = state.get("artifact_refs")
        input_refs: dict[str, str] = {}
        if isinstance(refs, Mapping):
            for key, value in refs.items():
                if isinstance(key, str) and isinstance(value, Mapping):
                    digest = value.get("digest")
                    if isinstance(digest, str) and digest:
                        input_refs[key] = digest
        chosen = action or _action_for_target(target_stage, source_stage)
        return DispatchProposal(
            allowed_action=chosen,
            target_stage=target_stage,
            input_refs=input_refs,
            reason=reason,
            source_stage=source_stage,
            idempotency_key=f"route:{source_stage}:{target_stage}",
        )

    @classmethod
    def authorize(
        cls,
        state: Mapping[str, object],
        source_stage: str,
        target_stage: str,
        *,
        action: str | None = None,
        reason: str = "root graph transition",
        policy: DispatchPolicy | None = None,
    ):
        proposal = cls.proposal(state, source_stage, target_stage, action=action, reason=reason)
        return evaluate_dispatch(proposal, state, policy=policy, source_stage=source_stage)

    @classmethod
    def authorize_result(
        cls,
        state: Mapping[str, object],
        source_stage: str,
        result: object,
        *,
        policy: DispatchPolicy | None = None,
    ) -> RouteAuthorization:
        if isinstance(result, str):
            decision = cls.authorize(state, source_stage, result, policy=policy)
            return RouteAuthorization(
                accepted=decision.accepted,
                target_stages=(result,),
                diagnostic=decision.diagnostic,
            )
        if isinstance(result, Sequence) and not isinstance(result, (str, bytes)):
            targets: list[str] = []
            for item in result:
                target = _send_target(item)
                if target is None:
                    return RouteAuthorization(
                        accepted=False,
                        diagnostic=DispatchDiagnostic(
                            code="MALFORMED_PROPOSAL",
                            source_stage=source_stage,
                            message="dynamic route item has no target stage",
                        ),
                        dynamic=True,
                    )
                decision = cls.authorize(state, source_stage, target, policy=policy)
                if not decision.accepted:
                    return RouteAuthorization(
                        accepted=False,
                        target_stages=tuple(targets + [target]),
                        diagnostic=decision.diagnostic,
                        dynamic=True,
                    )
                targets.append(target)
            return RouteAuthorization(accepted=True, target_stages=tuple(targets), dynamic=True)
        return RouteAuthorization(
            accepted=False,
            diagnostic=DispatchDiagnostic(
                code="MALFORMED_PROPOSAL",
                source_stage=source_stage,
                message="route result is neither a stage nor a Send sequence",
            ),
        )


def authorize_route_result(
    state: Mapping[str, object],
    source_stage: str,
    result: object,
    *,
    policy: DispatchPolicy | None = None,
) -> RouteAuthorization:
    return WorkflowRouting.authorize_result(state, source_stage, result, policy=policy)


def _action_for_target(target_stage: str, source_stage: str) -> str:
    target = target_stage.strip().lower()
    if target in {"__end__", "end_diagnostic"}:
        return DispatchAction.TERMINAL.value
    if target == "human_review" or target == "human_review_prepare":
        return DispatchAction.HUMAN_REVIEW.value
    if target == "execute_tools":
        return DispatchAction.TOOL.value
    if target in WorkflowRouting._WORKER_STAGES:
        return DispatchAction.REVISION.value if source_stage == "revision_dispatch" else DispatchAction.DISPATCH.value
    if target == "conversation":
        return DispatchAction.CONVERSATION.value
    if target == source_stage or target in {"ground", "execute", "select", "target_projection"}:
        return DispatchAction.RETRY.value if target == source_stage else DispatchAction.ADVANCE.value
    return DispatchAction.ADVANCE.value


def _send_target(item: object) -> str | None:
    target = getattr(item, "node", None)
    if isinstance(target, str) and target:
        return target
    if isinstance(item, str) and item:
        return item
    return None


__all__ = ["RouteAuthorization", "WorkflowRouting", "authorize_route_result"]
