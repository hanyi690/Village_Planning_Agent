"""Typed dispatch boundary for the workflow graph.

The graph may still use legacy stage workers while the migration is in flight,
but every jump is represented as a proposal and is approved by this module
before it can become a LangGraph command.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.schema.contracts.artifact_descriptor import ArtifactDescriptor


class DispatchAction(StrEnum):
    ADVANCE = "advance"
    RETRY = "retry"
    DISPATCH = "dispatch"
    HUMAN_REVIEW = "human_review"
    CONVERSATION = "conversation"
    TOOL = "execute_tools"
    REVISION = "revision"
    TERMINAL = "terminal"


class DispatchDiagnosticCode(StrEnum):
    MALFORMED_PROPOSAL = "MALFORMED_PROPOSAL"
    ILLEGAL_ACTION = "ILLEGAL_ACTION"
    UNAUTHORIZED_STAGE = "UNAUTHORIZED_STAGE"
    MISSING_PARENT_ARTIFACT = "MISSING_PARENT_ARTIFACT"
    INVALID_ARTIFACT_REF = "INVALID_ARTIFACT_REF"
    ATTEMPT_LIMIT_EXCEEDED = "ATTEMPT_LIMIT_EXCEEDED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    INVALID_ATTEMPT = "INVALID_ATTEMPT"
    INVALID_BUDGET = "INVALID_BUDGET"


class DispatchProposal(BaseModel):
    """A model- or stage-produced request to move the workflow cursor."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    allowed_action: str
    target_stage: str
    input_refs: dict[str, str] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    reason: str
    parent_refs: list[str] = Field(default_factory=list)
    source_stage: str = ""
    attempt: int | None = None
    budget: int = 1
    idempotency_key: str = ""
    provenance: dict[str, str] = Field(default_factory=dict)

    @field_validator("allowed_action", "target_stage", "reason")
    @classmethod
    def require_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("dispatch text fields must not be empty")
        return normalized

    @field_validator("input_refs", "provenance")
    @classmethod
    def require_ref_values(cls, value: dict[str, str]) -> dict[str, str]:
        if any(not key.strip() or not ref.strip() for key, ref in value.items()):
            raise ValueError("dispatch references must have non-empty keys and values")
        return value


class DispatchCommand(BaseModel):
    """The only typed command that may be translated into a graph jump."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: str
    target_stage: str
    input_refs: dict[str, ArtifactDescriptor] = Field(default_factory=dict)
    parent_digests: list[str] = Field(default_factory=list)
    attempt: int
    budget: int = 1
    reason: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    idempotency_key: str = ""


class DispatchDiagnostic(BaseModel):
    """Structured rejection information; no rejected jump is silent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: DispatchDiagnosticCode
    source_stage: str = ""
    target_stage: str = ""
    message: str
    details: dict[str, str] = Field(default_factory=dict)
    retryable: bool = False


class DispatchPolicyDecision(BaseModel):
    """Result of deterministic policy evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted: bool
    command: DispatchCommand | None = None
    diagnostic: DispatchDiagnostic | None = None

    @property
    def approved(self) -> bool:
        """Compatibility spelling for callers that call this an approval."""
        return self.accepted


DispatchDecision = DispatchPolicyDecision


class DispatchPolicy(BaseModel):
    """Deterministic allowlist and resource policy for dispatch proposals."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    allowed_actions: frozenset[str] = frozenset(action.value for action in DispatchAction)
    allowed_stages: frozenset[str] = frozenset()
    max_attempts: int = 3
    max_budget: int = 1000000
    required_parent_refs: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    DEFAULT_STAGES: ClassVar[frozenset[str]] = frozenset({
        "bootstrap_context", "conversation", "execute_tools",
        "l1_worker", "l2_worker", "l3_worker", "layer_completion_check",
        "layer_aggregate", "advance_phase", "revision_dispatch",
        "target_projection", "ground", "select", "execute", "validate",
        "reconcile", "deliver", "human_review_prepare", "human_review_publish",
        "human_review_wait", "human_review_apply", "end_diagnostic", "__end__",
    })
    DEFAULT_TRANSITIONS: ClassVar[dict[str, frozenset[str]]] = {
        "bootstrap_context": frozenset({"conversation"}),
        "conversation": frozenset({
            "execute_tools", "target_projection", "l1_worker", "l2_worker",
            "l3_worker", "conversation", "__end__", "end_diagnostic",
        }),
        "execute_tools": frozenset({"conversation", "end_diagnostic"}),
        "l1_worker": frozenset({"layer_completion_check", "end_diagnostic"}),
        "l2_worker": frozenset({"layer_completion_check", "end_diagnostic"}),
        "l3_worker": frozenset({"layer_completion_check", "end_diagnostic"}),
        "layer_completion_check": frozenset({"layer_aggregate", "end_diagnostic"}),
        "layer_aggregate": frozenset({
            "advance_phase", "target_projection", "conversation", "l1_worker",
            "l2_worker", "l3_worker", "human_review_prepare", "__end__",
            "end_diagnostic",
        }),
        "advance_phase": frozenset({
            "l1_worker", "l2_worker", "l3_worker", "target_projection",
            "__end__", "end_diagnostic",
        }),
        "revision_dispatch": frozenset({"l1_worker", "l2_worker", "l3_worker", "__end__", "end_diagnostic"}),
        "target_projection": frozenset({"target_projection", "ground", "human_review_prepare", "end_diagnostic"}),
        "ground": frozenset({"ground", "select", "human_review_prepare", "end_diagnostic"}),
        "select": frozenset({"ground", "execute", "human_review_prepare", "end_diagnostic"}),
        "execute": frozenset({"validate", "end_diagnostic"}),
        "validate": frozenset({
            "reconcile", "execute", "select", "ground", "target_projection",
            "human_review_prepare", "end_diagnostic",
        }),
        "reconcile": frozenset({"deliver", "execute", "human_review_prepare", "end_diagnostic"}),
        "deliver": frozenset({"__end__", "end_diagnostic"}),
        "human_review_prepare": frozenset({"human_review_publish", "end_diagnostic"}),
        "human_review_publish": frozenset({"human_review_wait", "end_diagnostic"}),
        "human_review_wait": frozenset({"human_review_apply", "end_diagnostic"}),
        "human_review_apply": frozenset({
            "advance_phase", "revision_dispatch", "l1_worker", "l2_worker", "l3_worker",
            "target_projection", "ground", "select", "execute", "validate", "reconcile",
            "deliver", "conversation", "human_review_prepare", "__end__", "end_diagnostic",
        }),
    }
    DEFAULT_REQUIRED_PARENTS: ClassVar[dict[str, tuple[str, ...]]] = {
        "target_projection": ("planning_program",),
        "ground": ("target_projection",),
        "select": ("target_projection", "grounding_result"),
        "execute": ("target_projection", "site_selection", "execution_plan"),
        "validate": ("execution_result",),
        "reconcile": (
            "planning_program", "target_projection", "grounding_result", "site_selection",
            "execution_plan", "execution_result",
        ),
        "deliver": ("execution_result", "validation_report", "reconciliation_report", "execution_plan"),
    }

    def authorize(
        self,
        proposal: DispatchProposal,
        state: Mapping[str, object],
        *,
        source_stage: str | None = None,
    ) -> DispatchPolicyDecision:
        source = _normalize_stage(source_stage or proposal.source_stage or _state_stage(state))
        target = _normalize_stage(proposal.target_stage)
        action = proposal.allowed_action.strip().lower()
        if action not in self.allowed_actions:
            return _reject(
                DispatchDiagnosticCode.ILLEGAL_ACTION,
                source,
                target,
                f"dispatch action {proposal.allowed_action!r} is not allowed",
            )
        if target not in (self.allowed_stages or self.DEFAULT_STAGES):
            return _reject(
                DispatchDiagnosticCode.UNAUTHORIZED_STAGE,
                source,
                target,
                f"target stage {target!r} is outside the workflow allowlist",
            )
        if source and target != "__end__" and target not in self.DEFAULT_TRANSITIONS.get(source, frozenset()):
            return _reject(
                DispatchDiagnosticCode.UNAUTHORIZED_STAGE,
                source,
                target,
                f"transition {source!r} -> {target!r} is not allowed",
            )
        if proposal.attempt is not None and proposal.attempt < 1:
            return _reject(DispatchDiagnosticCode.INVALID_ATTEMPT, source, target, "attempt must be positive")
        if proposal.budget < 1:
            return _reject(DispatchDiagnosticCode.INVALID_BUDGET, source, target, "budget must be positive")

        refs = _artifact_refs(state)
        required = self.required_parent_refs.get(target, self.DEFAULT_REQUIRED_PARENTS.get(target, ()))
        resolved: dict[str, ArtifactDescriptor] = {}
        for key in required:
            descriptor = _resolve_ref(key, proposal.input_refs.get(key), refs)
            if descriptor is None:
                return _reject(
                    DispatchDiagnosticCode.MISSING_PARENT_ARTIFACT,
                    source,
                    target,
                    f"required parent artifact {key!r} is missing",
                    details={"parent_ref": key},
                )
            resolved[key] = descriptor
        for key, ref in proposal.input_refs.items():
            descriptor = _resolve_ref(key, ref, refs)
            if descriptor is None:
                return _reject(
                    DispatchDiagnosticCode.INVALID_ARTIFACT_REF,
                    source,
                    target,
                    f"input artifact ref {key!r} cannot be resolved",
                    details={"input_ref": key},
                )
            resolved[key] = descriptor
        parent_digests: list[str] = []
        for parent in proposal.parent_refs:
            descriptor = _resolve_ref(parent, parent, refs)
            if descriptor is None:
                return _reject(
                    DispatchDiagnosticCode.MISSING_PARENT_ARTIFACT,
                    source,
                    target,
                    f"parent artifact {parent!r} is missing",
                    details={"parent_ref": parent},
                )
            resolved.setdefault(parent, descriptor)
        for descriptor in resolved.values():
            if descriptor.digest not in parent_digests:
                parent_digests.append(descriptor.digest)

        attempt = proposal.attempt or (_retry_count(state, target) + 1)
        configured_attempts = state.get("max_attempts")
        if configured_attempts is None and state.get("max_retries") is not None:
            configured_attempts = _state_limit(state, "max_retries", 0) + 1
        max_attempts = _state_limit(
            {"limit": configured_attempts},
            "limit",
            self.max_attempts,
        )
        if attempt > min(max_attempts, self.max_attempts):
            return _reject(
                DispatchDiagnosticCode.ATTEMPT_LIMIT_EXCEEDED,
                source,
                target,
                f"attempt {attempt} exceeds the limit",
                details={"attempt": str(attempt), "limit": str(min(max_attempts, self.max_attempts))},
            )
        used = _state_int(state, "dispatch_budget_used", 0)
        limit = _state_limit(state, "max_dispatch_budget", self.max_budget)
        if used + proposal.budget > min(limit, self.max_budget):
            return _reject(
                DispatchDiagnosticCode.BUDGET_EXCEEDED,
                source,
                target,
                "dispatch budget is exhausted",
                details={"used": str(used), "requested": str(proposal.budget), "limit": str(min(limit, self.max_budget))},
            )
        return DispatchPolicyDecision(
            accepted=True,
            command=DispatchCommand(
                action=action,
                target_stage=target,
                input_refs=resolved,
                parent_digests=parent_digests,
                attempt=attempt,
                budget=proposal.budget,
                reason=proposal.reason,
                evidence_refs=list(proposal.evidence_refs),
                idempotency_key=proposal.idempotency_key,
            ),
        )

    def evaluate(self, proposal: DispatchProposal, state: Mapping[str, object], *, source_stage: str | None = None) -> DispatchPolicyDecision:
        """Alias used by policy-oriented callers."""
        return self.authorize(proposal, state, source_stage=source_stage)


def evaluate_dispatch(
    proposal: DispatchProposal,
    state: Mapping[str, object],
    *,
    policy: DispatchPolicy | None = None,
    source_stage: str | None = None,
) -> DispatchPolicyDecision:
    return (policy or DispatchPolicy()).authorize(proposal, state, source_stage=source_stage)


def parse_and_evaluate_dispatch(
    raw_proposal: Mapping[str, object],
    state: Mapping[str, object],
    *,
    policy: DispatchPolicy | None = None,
    source_stage: str | None = None,
) -> DispatchPolicyDecision:
    try:
        proposal = DispatchProposal.model_validate(raw_proposal)
    except Exception as exc:
        diagnostic = DispatchDiagnostic(
            code=DispatchDiagnosticCode.MALFORMED_PROPOSAL,
            source_stage=_normalize_stage(source_stage or _state_stage(state)),
            message="dispatch proposal failed validation",
            details={"error": str(exc)},
        )
        return DispatchPolicyDecision(accepted=False, diagnostic=diagnostic)
    return evaluate_dispatch(proposal, state, policy=policy, source_stage=source_stage)


def _reject(
    code: DispatchDiagnosticCode,
    source: str,
    target: str,
    message: str,
    *,
    details: dict[str, str] | None = None,
) -> DispatchPolicyDecision:
    return DispatchPolicyDecision(
        accepted=False,
        diagnostic=DispatchDiagnostic(
            code=code,
            source_stage=source,
            target_stage=target,
            message=message,
            details=details or {},
        ),
    )


def _normalize_stage(value: str) -> str:
    normalized = value.strip().lower()
    aliases = {
        "target-projection": "target_projection",
        "human_review": "human_review_prepare",
        "human-review": "human_review_prepare",
        "end": "__end__",
        "end_diagnostic": "end_diagnostic",
    }
    return aliases.get(normalized, normalized)


def _state_stage(state: Mapping[str, object]) -> str:
    for key in ("active_stage", "current_stage", "paused_stage", "phase"):
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _artifact_refs(state: Mapping[str, object]) -> dict[str, ArtifactDescriptor]:
    raw = state.get("artifact_refs")
    if not isinstance(raw, Mapping):
        return {}
    resolved: dict[str, ArtifactDescriptor] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        try:
            resolved[key] = value if isinstance(value, ArtifactDescriptor) else ArtifactDescriptor.model_validate(value)
        except Exception:
            continue
    return resolved


def _resolve_ref(key: str, supplied: str | None, refs: Mapping[str, ArtifactDescriptor]) -> ArtifactDescriptor | None:
    if key in refs and (supplied is None or supplied == key or supplied == refs[key].digest):
        return refs[key]
    if supplied:
        if supplied in refs:
            return refs[supplied]
        for descriptor in refs.values():
            if descriptor.digest == supplied:
                return descriptor
    return None


def _retry_count(state: Mapping[str, object], stage: str) -> int:
    for key in ("retry", "retry_counts"):
        raw = state.get(key)
        if isinstance(raw, Mapping):
            value = raw.get(stage, 0)
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                return 0
    return 0


def _state_int(state: Mapping[str, object], key: str, default: int) -> int:
    value = state.get(key)
    try:
        return default if value is None else max(0, int(value))
    except (TypeError, ValueError):
        return default


def _state_limit(state: Mapping[str, object], key: str, default: int) -> int:
    value = state.get(key)
    try:
        return max(0, int(value)) if value is not None else default
    except (TypeError, ValueError):
        return default


__all__ = [
    "DispatchAction", "DispatchCommand", "DispatchDecision", "DispatchDiagnostic",
    "DispatchDiagnosticCode", "DispatchPolicy", "DispatchPolicyDecision", "DispatchProposal",
    "evaluate_dispatch", "parse_and_evaluate_dispatch",
]
