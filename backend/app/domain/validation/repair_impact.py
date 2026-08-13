"""Compute the earliest safe replay boundary for typed repair directives."""

from __future__ import annotations

from typing import Any

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.workflow.repair_directive_contracts import (
    ArtifactIntegrityIssue,
    RepairDirective,
    RepairDirectiveCompilation,
    RepairDirectiveType,
    RepairEvidenceScope,
    RepairImpactPlan,
)


_REPLAY_STAGES = [
    "L3",
    "TARGET_PROJECTION",
    "GROUND",
    "SELECT",
    "EXECUTE",
    "VALIDATE",
    "RECONCILE",
    "DELIVER",
]

_ARTIFACT_STAGE: dict[str, str] = {
    "l1_snapshot": "L1",
    "l2_strategy": "L2",
    "planning_program": "L3",
    "target_projection": "TARGET_PROJECTION",
    "grounding_result": "GROUND",
    "site_selection": "SELECT",
    "execution_plan": "EXECUTE",
    "execution_result": "EXECUTE",
    "parcel_changeset": "EXECUTE",
    "planned_state": "EXECUTE",
    "validation_report": "VALIDATE",
    "reconciliation_report": "RECONCILE",
    "delivery_manifest": "DELIVER",
}

_STAGE_ORDER = ["L1", "L2", *_REPLAY_STAGES]

_UPSTREAM_ANCHOR = {
    "L3": "l2_strategy",
    "TARGET_PROJECTION": "planning_program",
    "GROUND": "target_projection",
    "SELECT": "grounding_result",
    "EXECUTE": "site_selection",
}


def _stage_index(stage: str) -> int:
    return _STAGE_ORDER.index(stage)


def _directive_stage(directive: RepairDirective) -> str:
    if directive.directive_type in {
        RepairDirectiveType.EXCLUDE_BSMS,
        RepairDirectiveType.REALLOCATE,
    }:
        return "SELECT"
    if directive.directive_type == RepairDirectiveType.REBUILD_GEOMETRY:
        return "EXECUTE"
    if directive.evidence_scope == RepairEvidenceScope.TARGET_CONTRACT:
        return "L3"
    return "GROUND"


def _ref(value: Any) -> ArtifactRef | None:
    if isinstance(value, ArtifactRef):
        return value
    try:
        return ArtifactRef.model_validate(value)
    except Exception:
        return None


def _issue(
    artifact_key: str,
    code: str,
    message: str,
    *,
    parent_key: str | None = None,
    expected: str = "",
    actual: str = "",
) -> ArtifactIntegrityIssue:
    return ArtifactIntegrityIssue(
        artifact_key=artifact_key,
        artifact_stage=_ARTIFACT_STAGE.get(artifact_key, "unknown"),
        code=code,
        parent_key=parent_key,
        expected_checksum=expected,
        actual_checksum=actual,
        message=message,
    )


def _source_checksum_issues(
    compilation: RepairDirectiveCompilation,
    refs: dict[str, Any],
) -> list[ArtifactIntegrityIssue]:
    issues: list[ArtifactIntegrityIssue] = []
    for key, expected in sorted(compilation.source_checksums.items()):
        current = _ref(refs.get(key))
        actual = current.digest if current is not None else ""
        if actual != expected:
            issues.append(
                _issue(
                    key,
                    "source_violation_checksum_changed",
                    "repair directives no longer match the current violation artifact",
                    expected=expected,
                    actual=actual,
                )
            )
    return issues


_CANONICAL_PARENT = {
    "l2_strategy": "l1_snapshot",
    "planning_program": "l2_strategy",
    "target_projection": "planning_program",
    "grounding_result": "target_projection",
    "site_selection": "grounding_result",
}


def _validate_anchor_tree(
    anchor_key: str,
    refs: dict[str, Any],
) -> tuple[list[ArtifactIntegrityIssue], set[str]]:
    issues: list[ArtifactIntegrityIssue] = []
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visited:
            return
        visited.add(key)
        raw = refs.get(key)
        ref = _ref(raw)
        if ref is None:
            issues.append(
                _issue(
                    key,
                    "invalid_artifact_ref" if raw is not None else "missing_parent_artifact",
                    f"artifact {key} is missing or invalid",
                )
            )
            return
        parent_key = _CANONICAL_PARENT.get(key)
        if parent_key is None:
            return
        if not ref.parent_digests:
            issues.append(
                _issue(
                    key,
                    "missing_parent_lineage",
                    f"artifact {key} has no auditable parent checksums",
                )
            )
            return
        expected = str(ref.parent_digests.get(parent_key) or "")
        parent = _ref(refs.get(parent_key))
        if parent is None:
            issues.append(
                _issue(
                    key,
                    "missing_parent_artifact",
                    f"canonical parent {parent_key} is not available",
                    parent_key=parent_key,
                    expected=expected,
                )
            )
            return
        if not expected:
            issues.append(
                _issue(
                    key,
                    "missing_parent_lineage",
                    f"artifact {key} does not declare canonical parent {parent_key}",
                    parent_key=parent_key,
                    actual=parent.digest,
                )
            )
            return
        if parent.digest != expected:
            issues.append(
                _issue(
                    key,
                    "parent_checksum_mismatch",
                    f"canonical parent checksum changed for {parent_key}",
                    parent_key=parent_key,
                    expected=expected,
                    actual=parent.digest,
                )
            )
            return
        visit(parent_key)

    visit(anchor_key)
    return issues, visited


def _issue_boundary(issue: ArtifactIntegrityIssue) -> str | None:
    stage = issue.artifact_stage
    return stage if stage in _REPLAY_STAGES[:5] else None


def analyze_repair_impact(
    compilation: RepairDirectiveCompilation,
    artifact_refs: dict[str, Any],
) -> RepairImpactPlan:
    """Return a replay plan without invoking or mutating any workflow stage."""

    refs = dict(artifact_refs or {})
    checksums = {
        key: ref.digest
        for key, value in sorted(refs.items())
        if (ref := _ref(value)) is not None
    }
    if compilation.status == "noop":
        return RepairImpactPlan(
            status="noop",
            artifact_checksums=checksums,
            reason="validation snapshot contains no failed repairable violations",
        )
    if compilation.status == "blocked":
        return RepairImpactPlan(
            status="blocked",
            artifact_checksums=checksums,
            affected_target_ids=sorted(
                {target for item in compilation.unresolved for target in item.target_ids}
            ),
            reason="repair compilation is unresolved; automatic replay is forbidden",
        )

    source_issues = _source_checksum_issues(compilation, refs)
    if source_issues:
        return RepairImpactPlan(
            status="blocked",
            artifact_checksums=checksums,
            affected_target_ids=sorted({item.target_id for item in compilation.directives}),
            directive_ids=sorted({item.directive_id for item in compilation.directives}),
            integrity_issues=source_issues,
            reason="source violation checksum changed; directives must be recompiled",
        )

    requested = min(
        (_directive_stage(item) for item in compilation.directives),
        key=_stage_index,
    )
    boundary = requested
    all_issues: list[ArtifactIntegrityIssue] = []

    while True:
        anchor_key = _UPSTREAM_ANCHOR[boundary]
        anchor_stage = _ARTIFACT_STAGE[anchor_key]
        if anchor_key not in refs:
            issue = _issue(
                anchor_key,
                "missing_upstream_anchor",
                f"cannot replay {boundary} without {anchor_key}",
            )
            all_issues.append(issue)
            if anchor_stage not in _UPSTREAM_ANCHOR:
                return RepairImpactPlan(
                    status="blocked",
                    artifact_checksums=checksums,
                    affected_target_ids=sorted({item.target_id for item in compilation.directives}),
                    directive_ids=sorted({item.directive_id for item in compilation.directives}),
                    integrity_issues=all_issues,
                    reason="L1/L2 replay anchor is unavailable; automatic L3 replay is unsafe",
                )
            boundary = anchor_stage
            continue

        integrity, _ = _validate_anchor_tree(anchor_key, refs)
        if not integrity:
            break
        known_issues = {
            (
                item.artifact_key,
                item.code,
                item.parent_key,
                item.expected_checksum,
                item.actual_checksum,
            )
            for item in all_issues
        }
        all_issues.extend(
            issue
            for issue in integrity
            if (
                issue.artifact_key,
                issue.code,
                issue.parent_key,
                issue.expected_checksum,
                issue.actual_checksum,
            )
            not in known_issues
        )
        candidate_stages = [stage for issue in integrity if (stage := _issue_boundary(issue))]
        if not candidate_stages:
            return RepairImpactPlan(
                status="blocked",
                artifact_checksums=checksums,
                affected_target_ids=sorted({item.target_id for item in compilation.directives}),
                directive_ids=sorted({item.directive_id for item in compilation.directives}),
                integrity_issues=all_issues,
                reason="artifact lineage is invalid before TARGET_PROJECTION",
            )
        earlier = min(candidate_stages, key=_stage_index)
        if _stage_index(earlier) >= _stage_index(boundary):
            return RepairImpactPlan(
                status="blocked",
                artifact_checksums=checksums,
                affected_target_ids=sorted({item.target_id for item in compilation.directives}),
                directive_ids=sorted({item.directive_id for item in compilation.directives}),
                integrity_issues=all_issues,
                reason="artifact lineage cannot establish an earlier safe checkpoint",
            )
        boundary = earlier

    rerun = _REPLAY_STAGES[_REPLAY_STAGES.index(boundary) :]
    reusable = sorted(
        (
            key
            for key in refs
            if key in _ARTIFACT_STAGE
            and _stage_index(_ARTIFACT_STAGE[key]) < _stage_index(boundary)
        ),
        key=lambda key: (_stage_index(_ARTIFACT_STAGE[key]), key),
    )
    invalidated = sorted(
        (
            key
            for key in refs
            if key in _ARTIFACT_STAGE
            and _ARTIFACT_STAGE[key] in _REPLAY_STAGES
            and _stage_index(_ARTIFACT_STAGE[key]) >= _stage_index(boundary)
        ),
        key=lambda key: (_stage_index(_ARTIFACT_STAGE[key]), key),
    )
    reason = f"directive boundary={requested}; checksum-safe replay boundary={boundary}"
    return RepairImpactPlan(
        status="ready",
        earliest_invalid_stage=boundary,
        rerun_stages=rerun,
        reusable_artifact_keys=reusable,
        invalidated_artifact_keys=invalidated,
        affected_target_ids=sorted({item.target_id for item in compilation.directives}),
        directive_ids=sorted({item.directive_id for item in compilation.directives}),
        artifact_checksums=checksums,
        integrity_issues=all_issues,
        reason=reason,
    )


__all__ = ["analyze_repair_impact"]
