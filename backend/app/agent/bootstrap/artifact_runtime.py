"""Reference-only workflow state helpers.

The graph stores small references and reloads typed artifacts at stage
boundaries.  This module deliberately has no LangGraph imports so it can be
used by recovery code and tests without importing model/tool registrations.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, TypeVar

from app.modules.ports.artifact_store import ArtifactRef
from app.services.artifact_fingerprint import semantic_checksum
from app.services.artifact_store import FilesystemArtifactStore

T = TypeVar("T")

ARTIFACT_KEYS = (
    "l1_snapshot", "l2_strategy", "planning_program", "intent_compilation",
    "grounding_result", "site_selection", "execution_plan", "execution_outcome", "parcel_changeset",
    "planned_state", "validation_report", "reconciliation_report", "delivery_manifest",
    "allocated_geojson", "render_layers", "deferral_ledger",
)


class ArtifactReplayError(RuntimeError):
    """Raised when a replay cannot prove artifact identity."""


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def payload_checksum(payload: Any) -> str:
    raw = json.dumps(_jsonable(payload), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _ref_value(ref: Any, field: str, default: str = "") -> str:
    if isinstance(ref, dict):
        return str(ref.get(field) or default)
    return str(getattr(ref, field, default) or default)


def _parent_checksums(refs: dict[str, Any], *, exclude_key: str) -> dict[str, str]:
    parents: dict[str, str] = {}
    for parent_key, parent_ref in refs.items():
        if parent_key == exclude_key or not parent_ref:
            continue
        revision = _ref_value(parent_ref, "revision", "v1")
        checksum = _ref_value(parent_ref, "checksum") or _ref_value(parent_ref, "semantic_checksum")
        parents[str(parent_key)] = f"{revision}:{checksum}"
    return parents


def context_ref_for(state: dict[str, Any]) -> dict[str, Any]:
    """Return the stable context reference carried by a workflow state."""
    ref = state.get("context_ref")
    if isinstance(ref, dict) and ref.get("session_id") and ref.get("version"):
        return ref
    return {
        "session_id": state.get("session_id", ""),
        "version": str(state.get("context_version", "")),
    }


def store_artifact(
    state: dict[str, Any], key: str, module: str, artifact_type: str, payload: Any,
    *, attempt: int = 1,
) -> dict[str, Any]:
    """Persist an artifact idempotently and return its JSON reference."""
    if key not in ARTIFACT_KEYS:
        raise ValueError(f"unknown artifact key: {key}")
    run_id = state.get("run_id") or state.get("session_id", "")
    context = context_ref_for(state)
    current_refs = dict(state.get("artifact_refs") or {})
    parent_refs = {
        parent_key: parent_ref
        for parent_key, parent_ref in current_refs.items()
        if parent_key != key
    }
    parent_checksums = _parent_checksums(current_refs, exclude_key=key)
    input_fingerprint = payload_checksum({
        "key": key, "context": context, "attempt": attempt,
        "parents": parent_refs,
    })
    artifact_id = f"{key}-{run_id}-{input_fingerprint[:16]}"
    fingerprint = str(state.get("context_fingerprint", ""))
    ref = ArtifactRef(
        context_version=str(context.get("version", "")),
        context_fingerprint=fingerprint,
        artifact_id=artifact_id,
        module=module, run_id=run_id, artifact_type=artifact_type, revision="v1",
        parent_checksums=parent_checksums,
    )
    store = FilesystemArtifactStore()
    payload_json = _jsonable(payload)
    try:
        existing = store.read_manifest(ref)
    except FileNotFoundError:
        existing = None
    if existing is not None:
        existing_payload = store.retrieve(ref)
        if payload_checksum(existing_payload) != payload_checksum(payload_json):
            if semantic_checksum(existing_payload) != semantic_checksum(payload_json):
                raise ArtifactReplayError(
                    f"non-deterministic replay for {key}: {artifact_id} checksum changed"
                )
        if existing.get("context_fingerprint") and fingerprint and existing.get("context_fingerprint") != fingerprint:
            raise ArtifactReplayError(f"artifact {key} existing fingerprint mismatch")
        ref.checksum = str(existing.get("checksum", ""))
        ref.semantic_checksum = str(
            existing.get("semantic_checksum") or semantic_checksum(existing_payload)
        )
        ref.parent_checksums = {
            str(parent_key): str(parent_value)
            for parent_key, parent_value in (existing.get("parent_checksums") or parent_checksums).items()
        }
        return ref.model_dump(mode="json")
    store.store(ref, payload_json)
    return ref.model_dump(mode="json")


def load_artifact(state: dict[str, Any], key: str, model: type[T] | None = None) -> T | dict[str, Any] | None:
    """Load and validate a typed artifact from refs; return None when absent."""
    refs = state.get("artifact_refs") or {}
    ref_data = refs.get(key)
    if not ref_data:
        legacy = {
            "planning_program": "l3_program_ref", "grounding_result": "grounding_result_ref",
            "site_selection": "site_selection_ref", "parcel_changeset": "parcel_changeset_ref",
            "planned_state": "planned_state_ref", "validation_report": "validation_report_ref",
            "reconciliation_report": "reconciliation_report_ref",
        }
        ref_data = state.get(legacy.get(key, ""))
    if not ref_data:
        return None
    ref = ArtifactRef(**ref_data) if isinstance(ref_data, dict) else ref_data
    context = context_ref_for(state)
    if ref.run_id != (state.get("run_id") or state.get("session_id", "")):
        raise ArtifactReplayError(f"artifact {key} belongs to a different run")
    if str(ref.context_version) != str(context.get("version", "")):
        raise ArtifactReplayError(f"artifact {key} has a different context version")
    state_fingerprint = str(state.get("context_fingerprint", ""))
    ref_fingerprint = str(getattr(ref, "context_fingerprint", ""))
    if ref_fingerprint and state_fingerprint and ref_fingerprint != state_fingerprint:
        raise ArtifactReplayError(f"artifact {key} fingerprint mismatch")
    payload = FilesystemArtifactStore().retrieve(ref)
    manifest = FilesystemArtifactStore().read_manifest(ref)
    manifest_fingerprint = str(manifest.get("context_fingerprint", ""))
    if manifest_fingerprint and state_fingerprint and manifest_fingerprint != state_fingerprint:
        raise ArtifactReplayError(f"artifact {key} manifest fingerprint mismatch")
    if manifest.get("artifact_type") != ref.artifact_type:
        raise ArtifactReplayError(f"artifact {key} type metadata mismatch")
    stored_checksum = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    legacy_checksum = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    if manifest.get("checksum") not in {stored_checksum, legacy_checksum}:
        raise ArtifactReplayError(f"artifact {key} checksum mismatch")
    if ref.checksum and manifest.get("checksum") != ref.checksum:
        raise ArtifactReplayError(f"artifact {key} reference checksum mismatch")
    stored_semantic = semantic_checksum(payload)
    manifest_semantic = str(manifest.get("semantic_checksum") or stored_semantic)
    if manifest_semantic != stored_semantic:
        raise ArtifactReplayError(f"artifact {key} semantic checksum mismatch")
    if ref.semantic_checksum and manifest_semantic != ref.semantic_checksum:
        raise ArtifactReplayError(f"artifact {key} reference semantic checksum mismatch")
    if model is not None:
        return model(**payload)
    return payload


def migrate_legacy_artifacts(state: dict[str, Any]) -> dict[str, Any]:
    """Build the unified map from one legacy checkpoint without copying payloads."""
    refs = dict(state.get("artifact_refs") or {})
    legacy = {
        "planning_program": "l3_program_ref", "grounding_result": "grounding_result_ref",
        "site_selection": "site_selection_ref", "parcel_changeset": "parcel_changeset_ref",
        "planned_state": "planned_state_ref", "validation_report": "validation_report_ref",
        "reconciliation_report": "reconciliation_report_ref",
    }
    for key, field in legacy.items():
        if key not in refs and isinstance(state.get(field), dict) and state[field].get("artifact_id"):
            refs[key] = state[field]
    return refs
