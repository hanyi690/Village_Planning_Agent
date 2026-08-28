"""Compile validation findings into closed, target-level repair directives."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.workflow.repair_directive_contracts import (
    RepairDirective,
    RepairDirectiveCompilation,
    RepairDirectiveType,
    RepairEvidenceScope,
    UnresolvedRepairViolation,
)


@dataclass(frozen=True)
class _RepairPolicy:
    directive_type: RepairDirectiveType
    evidence_scope: RepairEvidenceScope | None = None
    required_evidence: tuple[str, ...] = ()
    requires_bsms: bool = False
    rebuild_strategy: str | None = None


_POLICIES: dict[str, _RepairPolicy] = {
    "hard_constraint": _RepairPolicy(RepairDirectiveType.EXCLUDE_BSMS, requires_bsms=True),
    "hard_constraints": _RepairPolicy(RepairDirectiveType.EXCLUDE_BSMS, requires_bsms=True),
    "prohibited_constraint": _RepairPolicy(RepairDirectiveType.EXCLUDE_BSMS, requires_bsms=True),
    "overlap": _RepairPolicy(RepairDirectiveType.REALLOCATE, requires_bsms=True),
    "target_overlap": _RepairPolicy(RepairDirectiveType.REALLOCATE, requires_bsms=True),
    "worker_conflict": _RepairPolicy(RepairDirectiveType.REALLOCATE, requires_bsms=True),
    "authoritative_land_use_conflict": _RepairPolicy(
        RepairDirectiveType.REALLOCATE,
        requires_bsms=True,
    ),
    "topology": _RepairPolicy(
        RepairDirectiveType.REBUILD_GEOMETRY,
        requires_bsms=True,
        rebuild_strategy="repair_invalid_geometry",
    ),
    "topology_validity": _RepairPolicy(
        RepairDirectiveType.REBUILD_GEOMETRY,
        requires_bsms=True,
        rebuild_strategy="repair_invalid_geometry",
    ),
    "topology_gaps": _RepairPolicy(
        RepairDirectiveType.REBUILD_GEOMETRY,
        requires_bsms=True,
        rebuild_strategy="repair_invalid_geometry",
    ),
    "geometry_invalid": _RepairPolicy(
        RepairDirectiveType.REBUILD_GEOMETRY,
        requires_bsms=True,
        rebuild_strategy="repair_invalid_geometry",
    ),
    "continuity": _RepairPolicy(RepairDirectiveType.REALLOCATE, requires_bsms=True),
    "area_conservation": _RepairPolicy(
        RepairDirectiveType.REBUILD_GEOMETRY,
        requires_bsms=True,
        rebuild_strategy="rebuild_from_authoritative_assignments",
    ),
    "road_route_failed": _RepairPolicy(
        RepairDirectiveType.REBUILD_GEOMETRY,
        requires_bsms=True,
        rebuild_strategy="reroute_avoiding_bsms",
    ),
    "road_unresolved": _RepairPolicy(
        RepairDirectiveType.REQUIRE_SOURCE_EVIDENCE,
        evidence_scope=RepairEvidenceScope.TARGET_CONTRACT,
        required_evidence=("road_mode", "road_endpoint_or_existing_segment"),
    ),
    "target_contract_missing": _RepairPolicy(
        RepairDirectiveType.REQUIRE_SOURCE_EVIDENCE,
        evidence_scope=RepairEvidenceScope.TARGET_CONTRACT,
        required_evidence=("typed_target_contract",),
    ),
    "classification_missing": _RepairPolicy(
        RepairDirectiveType.REQUIRE_SOURCE_EVIDENCE,
        evidence_scope=RepairEvidenceScope.TARGET_CONTRACT,
        required_evidence=("authoritative_classification",),
    ),
    "road_anchor_unresolved": _RepairPolicy(
        RepairDirectiveType.REQUIRE_SOURCE_EVIDENCE,
        evidence_scope=RepairEvidenceScope.GROUNDING,
        required_evidence=("road_endpoint_geometry_or_existing_segment",),
    ),
    "grounding_unresolved": _RepairPolicy(
        RepairDirectiveType.REQUIRE_SOURCE_EVIDENCE,
        evidence_scope=RepairEvidenceScope.GROUNDING,
        required_evidence=("grounded_candidate_geometry",),
    ),
    "geometry_unavailable": _RepairPolicy(
        RepairDirectiveType.REQUIRE_SOURCE_EVIDENCE,
        evidence_scope=RepairEvidenceScope.GROUNDING,
        required_evidence=("source_geometry_with_provenance",),
    ),
}


def _values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)] if str(value).strip() else []


def _read(raw: Any, key: str, default: Any = None) -> Any:
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(raw, key, default)


def _target_ids(raw: Any) -> list[str]:
    values: list[str] = []
    for key in (
        "target_id",
        "target_ids",
        "affected_target_ids",
        "project_id",
        "source_project_id",
    ):
        values.extend(_values(_read(raw, key)))
    return sorted(set(values))


def _affected_bsms(raw: Any) -> list[str]:
    values: list[str] = []
    for key in (
        "bsm",
        "bsms",
        "affected_bsms",
        "affected_parcels",
        "overlap_bsms",
    ):
        values.extend(_values(_read(raw, key)))
    return sorted(set(values))


def _evidence_refs(raw: Any) -> list[str]:
    return sorted(set(_values(_read(raw, "evidence_refs"))))


def _violation_code(raw: Any) -> str:
    return str(
        _read(raw, "code")
        or _read(raw, "check_id")
        or _read(raw, "check")
        or ""
    ).strip().lower()


def _violation_id(raw: Any, code: str, index: int) -> str:
    value = str(_read(raw, "violation_id") or _read(raw, "check_id") or "").strip()
    return value or f"{code or 'invalid'}:{index}"


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _source_ref(value: ArtifactRef | dict[str, Any]) -> ArtifactRef | None:
    if isinstance(value, ArtifactRef):
        return value
    try:
        return ArtifactRef.model_validate(value)
    except Exception:
        return None


def _unresolved(
    *,
    violation_id: str,
    code: str,
    target_ids: list[str],
    bsms: list[str],
    reason_code: str,
    message: str,
) -> UnresolvedRepairViolation:
    return UnresolvedRepairViolation(
        violation_id=violation_id,
        code=code or "invalid",
        target_ids=target_ids,
        affected_bsms=bsms,
        reason_code=reason_code,
        message=message,
    )


def compile_repair_directives(
    violations: Iterable[Any],
    *,
    source_artifact_key: str,
    source_artifact_ref: ArtifactRef | dict[str, Any],
) -> RepairDirectiveCompilation:
    """Compile failed findings; one unsupported finding blocks the whole batch.

    The all-or-nothing behavior prevents a caller from applying a convenient
    subset while silently leaving a target-unbound hard failure in place.
    """

    ref = _source_ref(source_artifact_ref)
    raw_items = list(violations or [])
    failed_items = [item for item in raw_items if not bool(_read(item, "passed", False))]
    specific_target_ids = {
        target_id
        for item in failed_items
        if _violation_code(item) != "traceability"
        for target_id in _target_ids(item)
    }
    failed_items = [
        item
        for item in failed_items
        if not (
            _violation_code(item) == "traceability"
            and _target_ids(item)
            and set(_target_ids(item)).issubset(specific_target_ids)
        )
    ]
    if not failed_items:
        return RepairDirectiveCompilation(status="noop")
    if ref is None or not str(source_artifact_key).strip():
        unresolved = [
            _unresolved(
                violation_id=_violation_id(item, _violation_code(item), index),
                code=_violation_code(item),
                target_ids=_target_ids(item),
                bsms=_affected_bsms(item),
                reason_code="invalid_source_artifact",
                message="repair source must be an immutable ArtifactRef",
            )
            for index, item in enumerate(failed_items)
        ]
        return RepairDirectiveCompilation(status="blocked", unresolved=unresolved)

    directives: list[RepairDirective] = []
    unresolved: list[UnresolvedRepairViolation] = []
    for index, raw in enumerate(failed_items):
        code = _violation_code(raw)
        violation_id = _violation_id(raw, code, index)
        targets = _target_ids(raw)
        bsms = _affected_bsms(raw)
        evidence_refs = _evidence_refs(raw)
        policy = _POLICIES.get(code)
        if policy is None:
            unresolved.append(
                _unresolved(
                    violation_id=violation_id,
                    code=code,
                    target_ids=targets,
                    bsms=bsms,
                    reason_code="unsupported_violation",
                    message=f"no deterministic repair policy for violation {code or '<empty>'}",
                )
            )
            continue
        if not targets:
            unresolved.append(
                _unresolved(
                    violation_id=violation_id,
                    code=code,
                    target_ids=[],
                    bsms=bsms,
                    reason_code="missing_target_lineage",
                    message="automatic repair requires affected_target_ids",
                )
            )
            continue
        geometry_evidence_available = bool(
            policy.directive_type == RepairDirectiveType.REBUILD_GEOMETRY
            and evidence_refs
        )
        if policy.requires_bsms and not bsms and not geometry_evidence_available:
            unresolved.append(
                _unresolved(
                    violation_id=violation_id,
                    code=code,
                    target_ids=targets,
                    bsms=[],
                    reason_code="missing_bsm_lineage",
                    message="this repair requires explicit affected BSMs",
                )
            )
            continue

        for target_id in targets:
            payload = {
                "source_artifact_key": source_artifact_key,
                "source_artifact_digest": ref.digest,
                "violation_id": violation_id,
                "code": code,
                "target_id": target_id,
                "affected_bsms": bsms,
                "directive_type": policy.directive_type.value,
                "evidence_scope": policy.evidence_scope.value if policy.evidence_scope else None,
                "required_evidence": list(policy.required_evidence),
                "evidence_refs": evidence_refs,
                "rebuild_strategy": policy.rebuild_strategy,
            }
            fingerprint = _fingerprint(payload)
            directives.append(
                RepairDirective(
                    directive_id=f"repair-{fingerprint[7:23]}",
                    directive_type=policy.directive_type,
                    target_id=target_id,
                    source_violation_ids=[violation_id],
                    source_artifact_key=source_artifact_key,
                    source_artifact_digest=ref.digest,
                    affected_bsms=bsms,
                    exclude_bsms=bsms
                    if policy.directive_type == RepairDirectiveType.EXCLUDE_BSMS
                    else [],
                    evidence_scope=policy.evidence_scope,
                    required_evidence=list(policy.required_evidence),
                    evidence_refs=evidence_refs,
                    rebuild_strategy=policy.rebuild_strategy,
                    reason_code=code,
                    issue_fingerprint=fingerprint,
                )
            )

    if unresolved:
        return RepairDirectiveCompilation(
            status="blocked",
            unresolved=sorted(unresolved, key=lambda item: item.violation_id),
            source_checksums={source_artifact_key: ref.digest},
        )
    if not directives:
        return RepairDirectiveCompilation(status="noop")
    return RepairDirectiveCompilation(
        status="ready",
        directives=sorted(
            directives,
            key=lambda item: (item.target_id, item.directive_type.value, item.directive_id),
        ),
        source_checksums={source_artifact_key: ref.digest},
    )


def compile_validation_report_directives(
    report: Any,
    *,
    source_artifact_key: str,
    source_artifact_ref: ArtifactRef | dict[str, Any],
) -> RepairDirectiveCompilation:
    """Adapter from the existing ``ValidationReport.checks`` collection."""

    checks = _read(report, "checks", []) or []
    failed = [check for check in checks if not bool(_read(check, "passed", False))]
    return compile_repair_directives(
        failed,
        source_artifact_key=source_artifact_key,
        source_artifact_ref=source_artifact_ref,
    )


__all__ = [
    "compile_repair_directives",
    "compile_validation_report_directives",
]
