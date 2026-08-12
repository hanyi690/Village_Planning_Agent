"""Bounded, deterministic validation-adjustment executor (M7).

Pure decision layer: EXECUTE -> VALIDATE -> diagnose -> this executor ->
earliest-affected-stage recompute -> VALIDATE, max 2 rounds. It never invokes
workflow nodes; it returns typed ``ValidationAdjustment`` decisions that a
stage or workflow caller executes, plus a ``AdjustmentExecutionResult`` for
the gate. Deterministic by construction (no RNG, no LLM, no I/O).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, List

import app.evidence.model.base  # noqa: F401  preload breaks evidence<->repair import cycle

from app.contracts.ports.adjustment import ValidationAdjustmentExecutor
from app.contracts.workflow.repair import (
    AdjustmentExecutionResult,
    AdjustmentFailure,
    IterationRecord,
    ValidationAdjustment,
)
from app.contracts.artifacts.artifact_descriptor import ArtifactDescriptor

_LEDGER_KEY = "validation_adjustment_log"
_AUTHORITATIVE_KEY = "parent_digests"
_ARTIFACT_REFS_KEY = "artifact_refs"
_VALIDATE_INPUT_KEYS = {
    "target_projection",
    "site_selection",
    "execution_plan",
    "execution_result",
}

_STAGE_PRIORITY = {
    "EXECUTE": 0,
    "SELECT": 1,
    "GROUND": 2,
    "L3": 3,
    "TARGET_PROJECTION": 4,
}


@dataclass(frozen=True)
class AdjustmentBudget:
    """Bounded repair budget: at most ``max_rounds`` automatic iterations."""

    max_rounds: int = 2

    def exhausted(self, consumed: int) -> bool:
        return consumed >= self.max_rounds


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def issue_fingerprint(
    responsible_stage: str,
    target_refs: List[str],
    bounded_params: dict[str, Any],
) -> str:
    """sha256 over (responsible_stage, sorted target_refs, bounded_params)."""
    payload = json.dumps(
        {
            "responsible_stage": responsible_stage,
            "target_refs": sorted(set(target_refs)),
            "bounded_params": _jsonable(bounded_params),
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_state_map(state: Any, *keys: str) -> dict[str, Any]:
    for key in keys:
        value = None
        if isinstance(state, dict):
            value = state.get(key)
        elif state is not None:
            value = getattr(state, key, None)
        if isinstance(value, dict):
            return dict(value)
    return {}


def _read_ledger(state: Any) -> list[dict[str, Any]]:
    raw = None
    if isinstance(state, dict):
        raw = state.get(_LEDGER_KEY)
    elif state is not None:
        raw = getattr(state, _LEDGER_KEY, None)
    entries = raw if isinstance(raw, list) else []
    result: list[dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, dict):
            result.append(entry)
        elif hasattr(entry, "model_dump"):
            result.append(entry.model_dump(mode="json"))
    return result


def _read_input_refs(state: Any) -> dict[str, ArtifactDescriptor]:
    refs = _read_state_map(state, _ARTIFACT_REFS_KEY)
    validated: dict[str, ArtifactDescriptor] = {}
    for key, value in sorted(refs.items()):
        if key not in _VALIDATE_INPUT_KEYS:
            continue
        if isinstance(value, ArtifactDescriptor):
            validated[key] = value
            continue
        if isinstance(value, dict):
            try:
                validated[key] = ArtifactDescriptor(**value)
            except Exception:
                continue
    return validated


def _authoritative_digests(state: Any) -> dict[str, str]:
    merged = _read_state_map(state, _AUTHORITATIVE_KEY)
    for key, ref in (state.get(_ARTIFACT_REFS_KEY, {}) if isinstance(state, dict) else {}).items():
        if isinstance(ref, dict):
            digest = ref.get("digest", "")
        else:
            digest = getattr(ref, "digest", "") or ""
        if digest:
            merged.setdefault(str(key), str(digest))
    return merged


def _parent_checksum(input_refs: dict[str, ArtifactDescriptor]) -> str:
    parts = []
    for key, ref in sorted(input_refs.items()):
        parent_digests = ref.parent_digests if isinstance(ref, ArtifactDescriptor) else {}
        parts.append([str(key), json.dumps(parent_digests, sort_keys=True, default=str)])
    if not parts:
        return "none"
    raw = json.dumps(parts, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parent_digest_conflict(state: Any, input_refs: dict[str, ArtifactDescriptor]) -> str | None:
    authoritative = _authoritative_digests(state)
    for key, ref in sorted(input_refs.items()):
        parent_digests = ref.parent_digests if isinstance(ref, ArtifactDescriptor) else {}
        for parent_name, declared in parent_digests.items():
            current = authoritative.get(str(parent_name))
            if current and str(current) != str(declared):
                return f"{key}.{parent_name}"
    return None


def _latest_ledger_status(ledger: list[dict[str, Any]], fingerprint: str) -> str | None:
    for entry in reversed(ledger):
        if entry.get("issue_fingerprint") == fingerprint:
            if entry.get("status") in ("reverted", "applied", "failed", "rejected"):
                return str(entry["status"])
            return "reverted" if entry.get("reverted") else "applied"
    return None


def _oscillating(fingerprint: str, ledger: list[dict[str, Any]]) -> bool:
    return _latest_ledger_status(ledger, fingerprint) == "reverted"


class BoundedAdjustmentExecutor(ValidationAdjustmentExecutor):
    """Pure executor producing bounded, deduplicated adjustment decisions."""

    def __init__(self, budget: AdjustmentBudget | None = None) -> None:
        self.budget = budget or AdjustmentBudget(max_rounds=2)

    async def plan(self, state: object, report: object) -> list[ValidationAdjustment]:
        """Return typed adjustment decisions the caller may execute (empty = none)."""
        if not isinstance(report, dict) and not hasattr(report, "checks"):
            return []
        ledger = _read_ledger(state)
        failed = [
            check
            for check in (getattr(report, "checks", None) or [])
            if not getattr(check, "passed", False)
        ]
        seen = {entry.get("issue_fingerprint") for entry in ledger}
        round_no = len(ledger) + 1
        candidates: list[ValidationAdjustment] = []
        for check in failed:
            candidate = self._candidate_from_check(state, check, round_no)
            if candidate.issue_fingerprint in seen:
                continue
            if _parent_digest_conflict(state, candidate.input_refs) is not None:
                continue
            if _oscillating(candidate.issue_fingerprint, ledger):
                continue
            candidates.append(candidate)
        candidates.sort(
            key=lambda c: (
                _STAGE_PRIORITY.get(c.responsible_stage, 99),
                c.issue_fingerprint,
            )
        )
        return candidates

    async def apply(self, state: object, report: object) -> AdjustmentExecutionResult:
        """Apply the bounded decision for this round; caller recomputes on 'applied'."""
        if report is None or (not isinstance(report, dict) and not hasattr(report, "checks")):
            return _result(
                "rejected",
                AdjustmentFailure(
                    code="unresolved",
                    message="no validation report available for repair",
                ),
            )
        if getattr(report, "overall_passed", False):
            return AdjustmentExecutionResult(status="noop")
        ledger = _read_ledger(state)
        decisions = await self.plan(state, report)
        if decisions and not self.budget.exhausted(len(ledger)):
            chosen = decisions[0]
            return self._applied_result(ledger, report, chosen)
        if self.budget.exhausted(len(ledger)):
            return _result(
                "human_required",
                AdjustmentFailure(
                    code="budget_exceeded",
                    message=f"automatic repair budget exhausted after {len(ledger)} rounds",
                ),
            )
        if self._has_oscillation(state, report, ledger):
            return _result(
                "human_required",
                AdjustmentFailure(
                    code="unresolved",
                    message="oscillation detected (same adjustment applied then reverted); rollback to pre-repair state",
                ),
            )
        if self._all_repeated(state, report, ledger):
            return _result(
                "human_required",
                AdjustmentFailure(
                    code="unresolved",
                    message="issue fingerprint repeats; no new adjustment available",
                ),
            )
        return _result(
            "human_required",
            AdjustmentFailure(
                code="unresolved",
                message="no adjustable issue; request HUMAN review",
            ),
        )

    def _applied_result(
        self,
        ledger: list[dict[str, Any]],
        report: object,
        chosen: ValidationAdjustment,
    ) -> AdjustmentExecutionResult:
        failed_check_ids = [
            str(getattr(check, "check_id", "") or "")
            for check in (getattr(report, "checks", None) or [])
            if not getattr(check, "passed", False) and getattr(check, "check_id", "")
        ]
        iteration = IterationRecord(
            iteration=len(ledger) + 1,
            issue_fingerprint=chosen.issue_fingerprint,
            parent_checksum=_parent_checksum(chosen.input_refs),
            adjustment_refs=[chosen.adjustment_id],
            affected_target_refs=chosen.affected_target_refs,
            before_check_refs=failed_check_ids,
            after_check_refs=[],
            spatial_diff_ref=None,
            output_checksum=chosen.issue_fingerprint,
        )
        return AdjustmentExecutionResult(
            status="applied",
            output_refs=chosen.input_refs,
            iteration=iteration,
        )

    def _has_oscillation(
        self,
        state: object,
        report: object,
        ledger: list[dict[str, Any]],
    ) -> bool:
        failed = [
            check
            for check in (getattr(report, "checks", None) or [])
            if not getattr(check, "passed", False)
        ]
        for check in failed:
            candidate = self._candidate_from_check(state, check, len(ledger) + 1)
            if _oscillating(candidate.issue_fingerprint, ledger):
                return True
        return False

    def _all_repeated(self, state: object, report: object, ledger: list[dict[str, Any]]) -> bool:
        failed = [
            check
            for check in (getattr(report, "checks", None) or [])
            if not getattr(check, "passed", False)
        ]
        for check in failed:
            candidate = self._candidate_from_check(state, check, len(ledger) + 1)
            if candidate.issue_fingerprint not in {e.get("issue_fingerprint") for e in ledger}:
                return False
        return bool(failed)

    def _candidate_from_check(
        self,
        state: object,
        check: Any,
        round_no: int,
    ) -> ValidationAdjustment:
        check_id = str(getattr(check, "check_id", "") or "")
        stage = str(getattr(check, "responsible_stage", "EXECUTE") or "EXECUTE")
        target_refs = sorted(
            {
                str(ref)
                for ref in list(getattr(check, "affected_target_ids", None) or [])
                + list(getattr(check, "affected_parcels", None) or [])
                if ref
            }
        )
        bounded = {
            "check_id": check_id,
            "adjustment_type": "relax",
            "expected_value": getattr(check, "expected_value", None),
            "actual_value": getattr(check, "actual_value", None),
            "reason": str(getattr(check, "fix_suggestion", "") or ""),
        }
        fp = issue_fingerprint(stage, target_refs, bounded)
        input_refs = _read_input_refs(state)
        return ValidationAdjustment(
            adjustment_id=f"adj-{round_no}-{fp[:12]}",
            responsible_stage=stage,
            affected_target_refs=target_refs,
            input_refs=input_refs,
            evidence_refs=[],
            bounded_params=bounded,
            issue_fingerprint=fp,
            idempotency_key=f"adj:{fp}",
        )


def _result(status: str, failure: AdjustmentFailure) -> AdjustmentExecutionResult:
    return AdjustmentExecutionResult(status=status, failure=failure)


__all__ = [
    "AdjustmentBudget",
    "BoundedAdjustmentExecutor",
    "issue_fingerprint",
]
