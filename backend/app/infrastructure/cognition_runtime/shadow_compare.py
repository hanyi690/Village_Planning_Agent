"""Deterministic V1/V2 comparison for Context Runtime shadow mode.

The comparator never compares geometry payloads or treats BSM strings as
world-model identities.  It compares source-lineage keyed candidate sets and
leaves stage-specific dimensions as explicit failures until a stage supplies
those results.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import Any

from app.contracts.cognition.shadow_diff import (
    CognitionShadowDiff,
    ShadowDiffItem,
    ShadowStageObservation,
)


def _value(item: Any, key: str, default: Any = "") -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _entity_refs(kg: Any, source_feature_ref: str) -> tuple[str, ...]:
    finder = getattr(kg, "find_entities", None)
    if not callable(finder):
        return ()
    try:
        rows = finder(source_feature_id=source_feature_ref, source_feature_ref=source_feature_ref, limit=64)
    except TypeError:
        try:
            rows = finder(source_feature_id=source_feature_ref, limit=64)
        except Exception:
            return ()
    except Exception:
        return ()
    refs = {
        str(_value(row, "entity_ref", "") or "").strip()
        for row in (rows or ())
        if str(_value(row, "entity_ref", "") or "").strip()
    }
    return tuple(sorted(refs))


def _status(v1_refs: tuple[str, ...], v2_refs: tuple[str, ...]) -> str:
    if v1_refs == v2_refs:
        return "match"
    if v1_refs and not v2_refs:
        return "v1_only"
    if v2_refs and not v1_refs:
        return "v2_only"
    return "conflict"


def build_shadow_diff(
    *,
    session_id: str,
    v1_kg: Any,
    v2_world_model: Any,
    source_features: Iterable[Any] = (),
    v1_snapshot_ref: str = "",
    v1_snapshot_digest: str = "",
) -> CognitionShadowDiff:
    """Build a source-lineage keyed diff at context bootstrap time."""

    source_ids = sorted(
        {
            str(_value(feature, "source_feature_ref", "") or "").strip()
            for feature in source_features
            if str(_value(feature, "source_feature_ref", "") or "").strip()
        }
    )
    v1_all: set[str] = set()
    v2_all: set[str] = set()
    lineage_conflicts = 0
    for source_id in source_ids:
        v1_refs = _entity_refs(v1_kg, source_id)
        v2_refs = _entity_refs(v2_world_model, source_id)
        v1_all.update(v1_refs)
        v2_all.update(v2_refs)
        if v1_refs and v2_refs and len(v1_refs) != len(v2_refs):
            lineage_conflicts += 1

    entity_status = _status(tuple(sorted(v1_all)), tuple(sorted(v2_all)))
    items = [
        ShadowDiffItem(
            dimension="entity_candidates",
            status=entity_status,
            v1_refs=tuple(sorted(v1_all)),
            v2_refs=tuple(sorted(v2_all)),
            details=f"source_features={len(source_ids)}",
        ),
        ShadowDiffItem(
            dimension="source_lineage",
            status="conflict" if lineage_conflicts else "match",
            details=f"lineage_conflicts={lineage_conflicts}",
        ),
    ]
    for dimension in ("selected_entity", "selected_representation", "ambiguity", "constraint_result"):
        items.append(
            ShadowDiffItem(
                dimension=dimension,
                status="failure",
                details="stage result not supplied at context bootstrap",
            )
        )
    status = "match" if all(item.status == "match" for item in items) else "different"
    return CognitionShadowDiff(
        session_id=session_id,
        v1_snapshot_ref=v1_snapshot_ref,
        v1_snapshot_digest=v1_snapshot_digest,
        v2_snapshot_ref=str(getattr(v2_world_model, "snapshot_ref", "") or ""),
        v2_snapshot_digest=str(getattr(v2_world_model, "snapshot_digest", "") or ""),
        items=tuple(items),
        status=status,
    )


def persist_shadow_diff(diff: CognitionShadowDiff) -> str:
    """Persist one immutable shadow diff and update its session named ref."""

    from app.infrastructure.artifacts.repository import ContentAddressedArtifactRepository
    from app.infrastructure.paths import run_tmp_root

    run_id = "shadow-" + hashlib.sha256(
        diff.session_id.encode("utf-8")
    ).hexdigest()[:32]
    repository = ContentAddressedArtifactRepository(run_tmp_root() / "world_model_cas")
    current = repository.get_named_ref(run_id, "main", "shadow_diff")
    descriptor = repository.put_json(
        diff.model_dump(mode="json"),
        schema_id="cognition_shadow_diff",
        schema_version="1.0",
        producer_stage="COGNITION",
        run_id=run_id,
        branch_id="main",
        parent_digests={
            key: value
            for key, value in {
                "v1_snapshot": diff.v1_snapshot_digest,
                "v2_snapshot": diff.v2_snapshot_digest,
            }.items()
            if value
        },
        provenance={"session_id": diff.session_id, "diff_digest": diff.digest},
    )
    repository.compare_and_set_named_ref(
        run_id,
        "main",
        "shadow_diff",
        descriptor,
        expected_descriptor_digest=current.descriptor_digest if current else None,
    )
    return descriptor.descriptor_digest


def record_shadow_stage(
    *,
    session_id: str,
    stage: str,
    dimension_key: str,
    v1_refs: Iterable[str] = (),
    v2_refs: Iterable[str] = (),
    details: str = "",
    v1_available: bool = True,
    v2_available: bool = True,
) -> str:
    """Append one bounded V1/V2 stage observation to the CAS diff.

    Shadow mode may execute different stage implementations, so this helper
    records an explicit comparison (or ``failure`` when one side is absent)
    without copying LLM text, geometries, or full stage artifacts.
    """
    from app.infrastructure.artifacts.repository import ContentAddressedArtifactRepository
    from app.infrastructure.paths import run_tmp_root

    run_id = "shadow-" + hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
    repository = ContentAddressedArtifactRepository(run_tmp_root() / "world_model_cas")
    current = repository.get_named_ref(run_id, "main", "shadow_diff")
    if current is None:
        return ""
    current_payload = repository.get_json(current)
    # JSON CAS blobs encode tuples as arrays; normalize them before the strict
    # contract validator so a later stage can safely append to the diff.
    if isinstance(current_payload, dict):
        for key in ("items", "stage_observations"):
            rows = current_payload.get(key) or []
            normalized = []
            for row in rows:
                if isinstance(row, dict):
                    row = dict(row)
                    row["v1_refs"] = tuple(row.get("v1_refs") or ())
                    row["v2_refs"] = tuple(row.get("v2_refs") or ())
                normalized.append(row)
            current_payload[key] = tuple(normalized)
    diff = CognitionShadowDiff.model_validate(current_payload)
    left = tuple(sorted({str(value).strip() for value in v1_refs if str(value).strip()}))
    right = tuple(sorted({str(value).strip() for value in v2_refs if str(value).strip()}))
    status = _status(left, right) if v1_available and v2_available else "failure"
    observation = ShadowStageObservation(
        stage=str(stage or "UNKNOWN"),
        dimension_key=str(dimension_key or ""),
        status=status,
        v1_refs=left,
        v2_refs=right,
        details=str(details or ""),
    )
    observations = tuple(
        item
        for item in diff.stage_observations
        if not (item.stage == observation.stage and item.dimension_key == observation.dimension_key)
    ) + (observation,)
    next_diff = CognitionShadowDiff(
        session_id=diff.session_id,
        v1_snapshot_ref=diff.v1_snapshot_ref,
        v1_snapshot_digest=diff.v1_snapshot_digest,
        v2_snapshot_ref=diff.v2_snapshot_ref,
        v2_snapshot_digest=diff.v2_snapshot_digest,
        items=diff.items,
        stage_observations=observations,
        status="match" if all(item.status == "match" for item in diff.items) and all(item.status == "match" for item in observations) else "different",
    )
    return persist_shadow_diff(next_diff)


__all__ = ["build_shadow_diff", "persist_shadow_diff", "record_shadow_stage"]
