"""Verified, input-bound classification decisions for unresolved L3 targets.

The provider only proposes a stable ``target_id``/``claim_id`` pair and a
classification code from the candidate set built for this invocation.  The
candidate set is never populated from the complete authoritative dictionary:
if the caller did not provide candidates, there is no decision to make and the
target remains pending.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

from app.contracts.artifacts.classification_ref import (
    ClassificationDecision,
    ClassificationSystem,
    classification_code_names,
)
from app.contracts.llm.decision_contracts import (
    DecisionContext,
    PendingDecision,
    SemanticIssue,
    SemanticValidationOutcome,
    stable_digest,
)
from app.infrastructure.llm.verified_structured import run_verified_structured_decision
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

_BATCH_SIZE = 6
_MAX_ATTEMPTS = 3
_PROMPT_VERSION = "l3-classification-verified-v2"


class PendingClassificationDecision(PendingDecision):
    """A target that cannot be classified without a new proposal or review."""

    target_id: str = Field(min_length=1)
    claim_id: str = ""
    candidate_set_digest: str = Field(min_length=1)


class ClassificationDecisionBatch(list[ClassificationDecision]):
    """Accepted decisions with explicit pending work beside the list API."""

    def __init__(
        self,
        accepted: Sequence[ClassificationDecision] = (),
        *,
        pending: Sequence[PendingDecision] = (),
        candidate_set_digest: str = "",
        attempts: int = 0,
    ) -> None:
        super().__init__(accepted)
        self.pending = list(pending)
        self.candidate_set_digest = candidate_set_digest
        self.attempts = attempts


class _ClassificationTarget(BaseModel):
    """The stable, input-derived context for one target decision."""

    model_config = ConfigDict(extra="forbid", strict=True)

    target_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    claim_ids: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    candidate_codes: tuple[str, ...] = Field(min_length=1)
    name: str = ""
    category: str = ""
    expected_output_kind: str = ""


class _ClassificationProposalItem(BaseModel):
    """Provider proposal before deterministic target/evidence validation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    target_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    status: Literal["resolved", "abstain", "ambiguous"] = "resolved"
    selected_code: str | None = None
    rationale: str = ""

    @model_validator(mode="after")
    def validate_resolution_shape(self) -> "_ClassificationProposalItem":
        if self.status == "resolved" and not self.selected_code:
            raise ValueError("resolved classification requires selected_code")
        if self.status != "resolved" and self.selected_code is not None:
            raise ValueError("abstain/ambiguous classification cannot select a code")
        return self


class _ClassificationProposalBatch(BaseModel):
    """Strict wrapper; its item code enum is generated per invocation."""

    model_config = ConfigDict(extra="forbid", strict=True)


def _strict_string_values(value: Any) -> tuple[str, ...] | None:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return None
    values: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            return None
        values.append(item.strip())
    return tuple(dict.fromkeys(values))


def _candidate_values(raw: Mapping[str, Any]) -> tuple[str, ...] | None:
    """Read only explicit candidate IDs supplied by the current input."""
    if "candidate_codes" in raw:
        return _strict_string_values(raw.get("candidate_codes"))
    if "classification_candidate_codes" in raw:
        return _strict_string_values(raw.get("classification_candidate_codes"))
    if "classification_candidates" in raw:
        candidates = raw.get("classification_candidates")
        if not isinstance(candidates, Sequence) or isinstance(
            candidates, (str, bytes, bytearray)
        ):
            return None
        values: list[str] = []
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                values.append(candidate.strip())
                continue
            if not isinstance(candidate, Mapping):
                return None
            candidate_id = candidate.get("candidate_id", candidate.get("code"))
            if not isinstance(candidate_id, str) or not candidate_id.strip():
                return None
            values.append(candidate_id.strip())
        return tuple(dict.fromkeys(values))
    return None


def _pending(
    *,
    target_id: str,
    claim_id: str,
    reason_code: str,
    candidate_set_digest: str,
    issue_fingerprints: Sequence[str] = (),
    dependency_refs: Sequence[str] = (),
) -> PendingClassificationDecision:
    return PendingClassificationDecision(
        decision_ref=target_id,
        target_id=target_id,
        claim_id=claim_id,
        reason_code=reason_code,
        issue_fingerprints=list(issue_fingerprints),
        dependency_refs=[*dependency_refs, f"candidate_set:{candidate_set_digest}"],
        requires_human_review=True,
        candidate_set_digest=candidate_set_digest,
    )


def _prepare_target(
    raw: Any,
    *,
    authoritative_codes: Mapping[str, str],
    candidate_set_digest: str,
) -> tuple[_ClassificationTarget | None, PendingDecision | None]:
    if not isinstance(raw, Mapping):
        return None, PendingDecision(
            decision_ref="classification_input",
            reason_code="invalid_target_record",
            requires_human_review=True,
            dependency_refs=[f"candidate_set:{candidate_set_digest}"],
        )

    target_id = raw.get("target_id")
    if not isinstance(target_id, str) or not target_id.strip():
        return None, PendingDecision(
            decision_ref="classification_input",
            reason_code="missing_target_id",
            requires_human_review=True,
            dependency_refs=[f"candidate_set:{candidate_set_digest}"],
        )
    target_id = target_id.strip()

    claim_values = raw.get("claim_ids", raw.get("claim_refs"))
    claim_ids = _strict_string_values(claim_values)
    if not claim_ids:
        return None, _pending(
            target_id=target_id,
            claim_id="",
            reason_code="missing_claim_id",
            candidate_set_digest=candidate_set_digest,
        )

    evidence_values = _strict_string_values(raw.get("evidence_refs"))
    if evidence_values is None:
        return None, _pending(
            target_id=target_id,
            claim_id=claim_ids[0],
            reason_code="invalid_evidence_refs",
            candidate_set_digest=candidate_set_digest,
        )
    if not evidence_values:
        evidence_values = claim_ids

    candidate_codes = _candidate_values(raw)
    if not candidate_codes:
        return None, _pending(
            target_id=target_id,
            claim_id=claim_ids[0],
            reason_code="candidate_set_empty",
            candidate_set_digest=candidate_set_digest,
        )
    unknown = sorted(set(candidate_codes) - set(authoritative_codes))
    if unknown:
        return None, _pending(
            target_id=target_id,
            claim_id=claim_ids[0],
            reason_code="candidate_set_unknown_id",
            candidate_set_digest=candidate_set_digest,
            dependency_refs=[f"unknown_candidate:{item}" for item in unknown],
        )

    try:
        prepared = _ClassificationTarget(
            target_id=target_id,
            claim_id=claim_ids[0],
            claim_ids=claim_ids,
            evidence_refs=evidence_values,
            candidate_codes=candidate_codes,
            name=raw.get("name", "") if isinstance(raw.get("name", ""), str) else "",
            category=(
                raw.get("category", "")
                if isinstance(raw.get("category", ""), str)
                else ""
            ),
            expected_output_kind=(
                raw.get("expected_output_kind", "")
                if isinstance(raw.get("expected_output_kind", ""), str)
                else ""
            ),
        )
    except Exception:
        return None, _pending(
            target_id=target_id,
            claim_id=claim_ids[0],
            reason_code="invalid_classification_input",
            candidate_set_digest=candidate_set_digest,
        )
    return prepared, None


def _candidate_set_digest(targets: Sequence[_ClassificationTarget]) -> str:
    return stable_digest(
        [
            {
                "target_id": target.target_id,
                "claim_id": target.claim_id,
                "claim_ids": list(target.claim_ids),
                "candidate_codes": list(target.candidate_codes),
            }
            for target in targets
        ]
    )


def _dynamic_proposal_model(candidate_codes: Sequence[str]) -> type[BaseModel]:
    """Build a schema whose code enum is exactly this invocation's candidates."""
    codes = tuple(dict.fromkeys(candidate_codes))
    if not codes:
        raise ValueError("classification proposal requires a non-empty candidate set")
    code_type = Literal.__getitem__(codes)
    item_model = create_model(
        f"ClassificationProposalItem_{stable_digest(codes)[:12]}",
        __base__=_ClassificationProposalItem,
        selected_code=(code_type | None, None),
    )
    return create_model(
        f"ClassificationProposalBatch_{stable_digest(codes)[:12]}",
        __base__=_ClassificationProposalBatch,
        results=(list[item_model], ...),
    )


def _build_code_catalog(
    candidate_codes: Sequence[str],
    authoritative_codes: Mapping[str, str],
) -> str:
    return "\n".join(
        f"{code} {authoritative_codes[code]}"
        for code in sorted(dict.fromkeys(candidate_codes))
    )


def _targets_with_evidence(program: Any) -> list[dict[str, Any]]:
    from app.domain.program.classification import classification_review_targets

    return classification_review_targets(program)


def _issue(
    *,
    context: DecisionContext,
    target_id: str,
    code: str,
    field_path: str,
    message: str,
) -> SemanticIssue:
    return SemanticIssue(
        stage=context.stage,
        code=code,
        severity="error",
        fatal_scope="field" if field_path else "record",
        object_ref=target_id,
        field_path=field_path,
        dependency_refs=[f"candidate_set:{context.candidate_set_digest}"],
        retryable=True,
        repair_kind="classification_proposal",
        message=message,
    )


def _validate_batch(
    context: DecisionContext,
    proposal: Any,
    expected: Mapping[str, _ClassificationTarget],
) -> SemanticValidationOutcome[Any]:
    results = list(getattr(proposal, "results", ()) or ())
    by_target: dict[str, list[Any]] = {}
    issues: list[SemanticIssue] = []
    pending: list[PendingDecision] = []

    for item in results:
        target_id = getattr(item, "target_id", "")
        by_target.setdefault(target_id, []).append(item)
        if target_id not in expected:
            issue = _issue(
                context=context,
                target_id=target_id or "classification_batch",
                code="unknown_target_id",
                field_path="target_id",
                message="proposal target_id is not in the current input candidate set",
            )
            issues.append(issue)
            pending.append(
                PendingDecision(
                    decision_ref=target_id or context.object_type,
                    reason_code="unknown_target_id",
                    issue_fingerprints=[issue.fingerprint],
                    dependency_refs=[f"candidate_set:{context.candidate_set_digest}"],
                    requires_human_review=True,
                )
            )

    accepted: list[Any] = []
    for target_id, target in expected.items():
        items = by_target.get(target_id, [])
        if len(items) == 0:
            code = "missing_target_result"
            issue = _issue(
                context=context,
                target_id=target_id,
                code=code,
                field_path="target_id",
                message="proposal did not return this pending target",
            )
        elif len(items) != 1:
            code = "ambiguous_target_result"
            issue = _issue(
                context=context,
                target_id=target_id,
                code=code,
                field_path="target_id",
                message="multiple proposals were returned for one stable target_id",
            )
        else:
            item = items[0]
            claim_id = getattr(item, "claim_id", "")
            if claim_id not in target.claim_ids:
                code = "unknown_claim_id"
                issue = _issue(
                    context=context,
                    target_id=target_id,
                    code=code,
                    field_path="claim_id",
                    message="proposal claim_id is not bound to this target input",
                )
            elif getattr(item, "status", "") != "resolved":
                code = "classification_ambiguous"
                issue = _issue(
                    context=context,
                    target_id=target_id,
                    code=code,
                    field_path="status",
                    message="provider abstained or marked the target ambiguous",
                )
            elif getattr(item, "selected_code", None) not in target.candidate_codes:
                code = "unknown_candidate_id"
                issue = _issue(
                    context=context,
                    target_id=target_id,
                    code=code,
                    field_path="selected_code",
                    message="selected_code is outside this target's input candidate set",
                )
            else:
                accepted.append(item)
                continue

        issues.append(issue)
        pending.append(
            _pending(
                target_id=target_id,
                claim_id=target.claim_id,
                reason_code=code,
                candidate_set_digest=context.candidate_set_digest,
                issue_fingerprints=[issue.fingerprint],
            )
        )

    return SemanticValidationOutcome(
        accepted=accepted,
        pending=pending,
        issues=issues,
    )


def _prompt(
    batch: Sequence[_ClassificationTarget],
    *,
    candidate_set_digest: str,
    authoritative_codes: Mapping[str, str],
    feedback: Sequence[str],
) -> str:
    candidate_union = [
        code
        for target in batch
        for code in target.candidate_codes
    ]
    lines = [
        {
            "target_id": target.target_id,
            "claim_id": target.claim_id,
            "name": target.name,
            "category": target.category,
            "expected_output_kind": target.expected_output_kind,
            "candidate_ids": list(target.candidate_codes),
            "evidence_refs": list(target.evidence_refs),
        }
        for target in batch
    ]
    return (
        "你只负责当前输入中的规划用地分类。返回 typed schema；不要返回数组位置、候选名称、"
        "默认编码或新增 ID。每个 target_id/claim_id 最多返回一次；有唯一判断时返回稳定的"
        "candidate_id（即 selected_code），没有可靠唯一判断时返回 status=abstain 或 ambiguous。"
        "候选集、引用和闭集 digest 由本次输入决定，不得使用未列出的值。\n"
        f"candidate_set_digest={candidate_set_digest}\n"
        f"candidate_catalog={_build_code_catalog(candidate_union, authoritative_codes)}\n"
        f"pending_targets={json.dumps(lines, ensure_ascii=False, separators=(',', ':'))}\n"
        f"previous_validation_feedback={json.dumps(list(feedback), ensure_ascii=False)}"
    )


def _decision_from_item(
    item: Any,
    target: _ClassificationTarget,
) -> ClassificationDecision:
    selected_code = item.selected_code
    if item.status != "resolved" or selected_code not in target.candidate_codes:
        raise ValueError("only a verified resolved item can become ClassificationDecision")
    return ClassificationDecision(
        target_id=target.target_id,
        code_system=ClassificationSystem.APPENDIX5,
        candidate_codes=[selected_code],
        selected_code=selected_code,
        decision_mode="llm_l3",
        evidence_refs=list(target.evidence_refs),
        rationale=str(item.rationale or "")[:500],
        status="resolved",
    )


def _deduplicate_pending(items: Sequence[PendingDecision]) -> list[PendingDecision]:
    unique: dict[tuple[str, str], PendingDecision] = {}
    for item in items:
        unique.setdefault((item.decision_ref, item.reason_code), item)
    return list(unique.values())


async def generate_classification_decisions(
    program: Any,
    *,
    llm: Any = None,
    max_targets: int = 200,
) -> ClassificationDecisionBatch:
    """Generate accepted decisions and retain failed target work as pending."""
    if max_targets < 1:
        raise ValueError("max_targets must be positive")

    authoritative_codes = classification_code_names("appendix5") or {}
    raw_targets = _targets_with_evidence(program)
    if not raw_targets:
        return ClassificationDecisionBatch()

    provisional_targets = list(raw_targets[:max_targets])
    preflight_pending: list[PendingDecision] = []
    if len(raw_targets) > max_targets:
        for raw in raw_targets[max_targets:]:
            target_id = raw.get("target_id") if isinstance(raw, Mapping) else None
            if isinstance(target_id, str) and target_id.strip():
                preflight_pending.append(
                    PendingDecision(
                        decision_ref=target_id.strip(),
                        reason_code="classification_target_limit",
                        requires_human_review=True,
                    )
                )

    identity_payload = []
    for raw in provisional_targets:
        identity_payload.append(
            {
                "target_id": raw.get("target_id") if isinstance(raw, Mapping) else None,
                "claim_ids": (
                    raw.get("claim_ids", raw.get("claim_refs"))
                    if isinstance(raw, Mapping)
                    else None
                ),
                "candidate_codes": (
                    raw.get("candidate_codes") if isinstance(raw, Mapping) else None
                ),
                "classification_candidates": (
                    raw.get("classification_candidates")
                    if isinstance(raw, Mapping)
                    else None
                ),
            }
        )
    input_candidate_digest = stable_digest(identity_payload)
    preflight_pending = [
        item.model_copy(
            update={
                "dependency_refs": [
                    *item.dependency_refs,
                    f"candidate_set:{input_candidate_digest}",
                ]
            }
        )
        for item in preflight_pending
    ]

    targets: list[_ClassificationTarget] = []
    seen_ids: set[str] = set()
    for raw in provisional_targets:
        target, pending_item = _prepare_target(
            raw,
            authoritative_codes=authoritative_codes,
            candidate_set_digest=input_candidate_digest,
        )
        if target is None:
            if pending_item is not None:
                preflight_pending.append(pending_item)
            continue
        if target.target_id in seen_ids:
            preflight_pending.append(
                _pending(
                    target_id=target.target_id,
                    claim_id=target.claim_id,
                    reason_code="duplicate_target_id",
                    candidate_set_digest=input_candidate_digest,
                )
            )
            continue
        seen_ids.add(target.target_id)
        targets.append(target)

    # The digest covers the complete current input, including targets that
    # are already pending for an empty or malformed candidate set.
    candidate_digest = input_candidate_digest

    if not targets:
        return ClassificationDecisionBatch(
            pending=_deduplicate_pending(preflight_pending),
            candidate_set_digest=candidate_digest,
        )

    accepted: dict[str, ClassificationDecision] = {}
    pending = list(preflight_pending)
    remaining = list(targets)
    retry_states: dict[tuple[str, ...], Any] = {}
    feedback_by_key: dict[tuple[str, ...], list[str]] = {}
    attempts = 0

    for round_index in range(_MAX_ATTEMPTS):
        if not remaining:
            break
        next_remaining: list[_ClassificationTarget] = []
        for start in range(0, len(remaining), _BATCH_SIZE):
            batch = remaining[start : start + _BATCH_SIZE]
            batch_key = tuple(target.target_id for target in batch)
            batch_codes = [code for target in batch for code in target.candidate_codes]
            model = _dynamic_proposal_model(batch_codes)
            batch_input_digest = stable_digest(
                {
                    "targets": [target.model_dump(mode="json") for target in batch],
                    "candidate_set_digest": candidate_digest,
                }
            )
            context = DecisionContext(
                stage="l3",
                object_type=f"classification_batch:{','.join(batch_key)}",
                input_digest=batch_input_digest,
                candidate_set_digest=candidate_digest,
                prompt_version=_PROMPT_VERSION,
                validator_version="classification-generator-v2",
            )
            feedback = feedback_by_key.get(batch_key, [])
            messages = [
                {
                    "role": "system",
                    "content": "Return only the typed classification proposal for the pending IDs.",
                },
                {
                    "role": "user",
                    "content": _prompt(
                        batch,
                        candidate_set_digest=candidate_digest,
                        authoritative_codes=authoritative_codes,
                        feedback=feedback,
                    ),
                },
            ]

            expected = {target.target_id: target for target in batch}
            attempts += 1
            result = await run_verified_structured_decision(
                decision_context=context,
                proposal_model_factory=lambda _context, proposal_model=model: proposal_model,
                messages=messages,
                semantic_validator=lambda decision_context, proposal: _validate_batch(
                    decision_context,
                    proposal,
                    expected,
                ),
                previous_retry_state=retry_states.get(batch_key),
                llm=llm,
                max_retries=0,
                timeout=180,
                max_tokens=4096,
                allow_content_json_fallback=False,
            )

            accepted_ids: set[str] = set()
            for item in result.accepted:
                target_id = getattr(item, "target_id", "")
                target = expected.get(target_id)
                if target is None or target_id in accepted:
                    continue
                try:
                    accepted[target_id] = _decision_from_item(item, target)
                    accepted_ids.add(target_id)
                except Exception as exc:
                    logger.warning(
                        "[classification_generator] deterministic decision construction failed for %s: %s",
                        target_id,
                        exc,
                    )

            failed = [target for target in batch if target.target_id not in accepted_ids]
            if not failed:
                continue

            feedback = [
                f"{issue.code}:{issue.object_ref}:{issue.field_path}"
                for issue in result.issues
            ]
            feedback.extend(
                f"{item.reason_code}:{item.decision_ref}"
                for item in result.pending
            )
            feedback = list(dict.fromkeys(feedback)) or [
                "verified structured proposal did not produce an accepted item"
            ]
            failure_key = tuple(target.target_id for target in failed)
            if round_index + 1 >= _MAX_ATTEMPTS or result.retry_state.should_stop:
                issue_fingerprints = [issue.fingerprint for issue in result.issues]
                for target in failed:
                    matching = next(
                        (
                            item
                            for item in result.pending
                            if item.decision_ref == target.target_id
                        ),
                        None,
                    )
                    pending_reason = next(
                        (item.reason_code for item in result.pending),
                        "classification_retry_exhausted",
                    )
                    pending.append(
                        _pending(
                            target_id=target.target_id,
                            claim_id=target.claim_id,
                            reason_code=(
                                matching.reason_code
                                if matching is not None
                                else pending_reason
                            ),
                            candidate_set_digest=candidate_digest,
                            issue_fingerprints=(
                                matching.issue_fingerprints
                                if matching is not None
                                else issue_fingerprints
                            ),
                        )
                    )
            else:
                retry_states[failure_key] = result.retry_state
                feedback_by_key[failure_key] = feedback
                next_remaining.extend(failed)

        remaining = next_remaining

    decisions = [
        accepted[target.target_id]
        for target in targets
        if target.target_id in accepted
    ]
    logger.info(
        "[classification_generator] accepted=%d pending=%d targets=%d candidate_set_digest=%s",
        len(decisions),
        len(pending),
        len(raw_targets),
        candidate_digest,
    )
    return ClassificationDecisionBatch(
        decisions,
        pending=_deduplicate_pending(pending),
        candidate_set_digest=candidate_digest,
        attempts=attempts,
    )


__all__ = [
    "ClassificationDecisionBatch",
    "PendingClassificationDecision",
    "generate_classification_decisions",
]
