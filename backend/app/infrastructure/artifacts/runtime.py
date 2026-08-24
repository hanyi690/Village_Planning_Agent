"""Reference-only workflow state helpers.

The graph stores small references and reloads typed artifacts at stage
boundaries.  This module deliberately has no LangGraph imports so it can be
used by recovery code and tests without importing model/tool registrations.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, TypeVar

from pydantic import ValidationError

from app.infrastructure.artifacts import ContentAddressedArtifactRepository, NamedRefConflict
from app.infrastructure.artifacts.fingerprint import semantic_checksum
from app.contracts.artifacts.artifact_descriptor import ArtifactDescriptor
from app.infrastructure.paths import run_tmp_root

T = TypeVar("T")

ARTIFACT_SCHEMA_VERSION = "3"

ARTIFACT_KEYS = (
    "l1_snapshot", "l2_strategy", "planning_program", "target_projection",
    "grounding_result", "scoped_grounding_problem", "demand_portfolio", "suitability_surface", "portfolio_decision",
    "execution_plan", "execution_result", "parcel_changeset",
    "planned_state", "validation_report", "reconciliation_report", "delivery_manifest",
    "layout_configs", "render_layers", "delivery_spatial_snapshot", "deferral_ledger",
    "export_result", "render_artifacts", "execution_diagnostics", "kg_layer1",
    "repair_directives", "repair_impact", "global_zone_allocation",
    "planning_scenario", "scenario_set", "approved_execution_input", "validation_certificate", "final_relation_validation",
    "global_site_allocation", "grounded_anchors", "l1_observations", "l1_bindings",
    "source_semantic_classification", "l1_source_index", "execution_staging", "staged_parcel_changeset",
    "staged_planned_state", "staged_layout_configs",
)


class ArtifactReplayError(ValueError):
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


def _parent_digests(
    refs: dict[str, Any],
    *,
    exclude_key: str,
    exclude_keys: set[str] | frozenset[str] = frozenset(),
) -> dict[str, str]:
    parents: dict[str, str] = {}
    for parent_key, parent_ref in refs.items():
        if parent_key == exclude_key or parent_key in exclude_keys or not parent_ref:
            continue
        digest = _ref_value(parent_ref, "digest")
        if not digest:
            raise ArtifactReplayError(f"artifact {parent_key} is not an ArtifactDescriptor")
        parents[str(parent_key)] = digest
    return parents


def _repository(base_dir: str | Path | None = None) -> ContentAddressedArtifactRepository:
    if base_dir is None or str(base_dir) == ".run-tmp":
        base_dir = run_tmp_root()
    return ContentAddressedArtifactRepository(base_dir)


def _descriptor(ref: Any, key: str) -> ArtifactDescriptor:
    try:
        return ref if isinstance(ref, ArtifactDescriptor) else ArtifactDescriptor.model_validate(ref)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ArtifactReplayError(f"artifact {key} is not an ArtifactDescriptor") from exc


def validate_artifact_refs_branch(state: dict[str, Any]) -> str:
    """Fail closed when a checkpoint carries refs from mixed branches.

    A checkpoint cursor and its artifact refs form one immutable replay input.
    Copying blobs into a new branch is safe only after every referenced
    descriptor has been proven to belong to the cursor's run and branch.
    """

    run_id = str(state.get("run_id") or state.get("session_id") or "")
    expected_branch = str(state.get("branch_id") or "main")
    refs = dict(state.get("artifact_refs") or {})
    branches: dict[str, str] = {}
    for key, raw_ref in refs.items():
        ref = _descriptor(raw_ref, str(key))
        if run_id and ref.run_id != run_id:
            raise ArtifactReplayError(
                f"artifact {key} belongs to a different run"
            )
        branch = str(ref.branch_id or "").strip()
        if not branch:
            raise ArtifactReplayError(
                f"artifact {key} has no branch identity"
            )
        branches[str(key)] = branch

    unique_branches = sorted(set(branches.values()))
    if unique_branches and (
        len(unique_branches) != 1 or unique_branches[0] != expected_branch
    ):
        details = ", ".join(
            f"{key}={branch}" for key, branch in sorted(branches.items())
        )
        raise ArtifactReplayError(
            "artifact refs span branches: "
            f"state={expected_branch!r}; refs={details}"
        )
    return expected_branch


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
    *, attempt: int = 1, base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Persist an artifact idempotently and return its JSON reference."""
    if key not in ARTIFACT_KEYS:
        raise ValueError(f"unknown artifact key: {key}")
    run_id = state.get("run_id") or state.get("session_id", "")
    if str(state.get("artifact_schema_version") or ARTIFACT_SCHEMA_VERSION) != ARTIFACT_SCHEMA_VERSION:
        raise ArtifactReplayError("artifact state uses an unsupported schema version")
    context = context_ref_for(state)
    current_refs = dict(state.get("artifact_refs") or {})
    validate_artifact_refs_branch(state)
    branch_id = str(state.get("branch_id") or "main")
    if payload is None:
        raise ArtifactReplayError(
            f"artifact {key} cannot persist a null payload"
        )
    payload_json = _jsonable(payload)
    parent_digests = _parent_digests(
        current_refs,
        exclude_key=key,
        exclude_keys={f"{module}_gate"},
    )
    repository = _repository(base_dir)
    existing_ref = current_refs.get(key)
    if existing_ref:
        # ContractMeta/provenance timestamps are deliberately excluded by
        # semantic_checksum. Replaying the same stage with an equivalent
        # business payload must therefore reuse the existing immutable
        # descriptor instead of creating a new blob solely because
        # ``created_at`` or a provenance timestamp was regenerated.
        try:
            existing = _descriptor(existing_ref, key)
            if (
                existing.schema_id == artifact_type
                and existing.schema_version == ARTIFACT_SCHEMA_VERSION
                and existing.parent_digests == dict(sorted(parent_digests.items()))
                and existing.semantic_digest
                == f"sha256:{semantic_checksum(payload)}"
            ):
                return existing.model_dump(mode="json")
        except (ArtifactReplayError, ValueError, TypeError):
            # The normal CAS path below emits the precise replay error for a
            # malformed or stale descriptor; do not silently adopt it here.
            pass
    try:
        descriptor = repository.put_json(
            payload_json,
            schema_id=artifact_type,
            schema_version=ARTIFACT_SCHEMA_VERSION,
            producer_stage=module,
            run_id=run_id,
            branch_id=branch_id,
            parent_digests=parent_digests,
            provenance={
                "artifact_key": key,
                "context_ref": context,
                "context_fingerprint": str(state.get("context_fingerprint", "")),
                "attempt": attempt,
            },
        )
        expected = None
        if current_refs.get(key):
            expected = _descriptor(current_refs[key], key).descriptor_digest
        repository.compare_and_set_named_ref(
            run_id, branch_id, key, descriptor,
            expected_descriptor_digest=expected,
        )
    except NamedRefConflict as exc:
        # Two legitimate paths reach here:
        # 1. A stage committed the blob + named ref before its LangGraph
        #    checkpoint was committed; retrying the same node must adopt that
        #    exact result (identical payload -> identical content digest).
        # 2. A crash-replay re-executes a stage that already committed the key
        #    and produces a NEW revision (e.g. deferral_ledger revised by
        #    EXECUTE and VALIDATE, or a re-run of EXECUTE after a crash).  In a
        #    single-process replay the named ref is only stale relative to the
        #    checkpoint, so adopt the new descriptor as the latest revision via
        #    a compare-and-set against the repository's current ref.
        existing = repository.get_named_ref(run_id, branch_id, key)
        if (
            existing is not None
            and existing.schema_id == artifact_type
            and existing.schema_version == ARTIFACT_SCHEMA_VERSION
            and existing.parent_digests == dict(sorted(parent_digests.items()))
            and repository.get_json(existing) == payload_json
        ):
            return existing.model_dump(mode="json")
        if existing is not None:
            try:
                repository.compare_and_set_named_ref(
                    run_id, branch_id, key, descriptor,
                    expected_descriptor_digest=existing.descriptor_digest,
                )
            except NamedRefConflict:
                raise ArtifactReplayError(
                    f"artifact {key} named ref changed during replay"
                ) from exc
            return descriptor.model_dump(mode="json")
        raise ArtifactReplayError(f"artifact {key} named ref changed during replay") from exc
    return descriptor.model_dump(mode="json")


def load_artifact(
    state: dict[str, Any], key: str, model: type[T] | None = None,
    *, base_dir: str | Path | None = None,
) -> T | dict[str, Any] | None:
    """Load and validate a typed artifact from refs; return None when absent."""
    refs = state.get("artifact_refs") or {}
    ref_data = refs.get(key)
    if not ref_data:
        return None
    ref = _descriptor(ref_data, key)
    context = context_ref_for(state)
    if ref.run_id != (state.get("run_id") or state.get("session_id", "")):
        raise ArtifactReplayError(f"artifact {key} belongs to a different run")
    if ref.branch_id != str(state.get("branch_id") or "main"):
        raise ArtifactReplayError(f"artifact {key} belongs to a different branch")
    if ref.schema_id == "":
        raise ArtifactReplayError(f"artifact {key} has no schema identity")
    repository = _repository(base_dir)
    payload = repository.get_json(ref)
    if payload is None:
        raise ArtifactReplayError(
            f"artifact {key} contains a null payload"
        )
    if model is not None:
        try:
            return model.model_validate(payload)
        except ValidationError:
            # JSON artifacts encode datetimes and other standard scalar
            # values as strings.  Preserve strict validation first, then use
            # Pydantic's explicit non-strict coercion for durable replay.
            return model.model_validate(payload, strict=False)
    return payload


def load_artifact_descriptor(
    state: dict[str, Any], descriptor_data: dict[str, Any] | None,
    model: type[T] | None = None,
    *, base_dir: str | Path | None = None,
) -> T | dict[str, Any] | None:
    """Load an exact child artifact descriptor embedded in a root artifact."""
    if not descriptor_data:
        return None
    ref = _descriptor(descriptor_data, "embedded_child")
    run_id = state.get("run_id") or state.get("session_id", "")
    if ref.run_id != run_id or ref.branch_id != str(state.get("branch_id") or "main"):
        raise ArtifactReplayError("embedded child artifact belongs to a different run or branch")
    payload = _repository(base_dir).get_json(ref)
    if payload is None:
        raise ArtifactReplayError("embedded child artifact contains a null payload")
    if model is not None:
        return model(**payload)
    return payload


def fork_artifact_refs(
    state: dict[str, Any],
    branch_id: str,
    *,
    base_dir: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Copy immutable descriptors into a new branch while reusing blobs."""
    branch = str(branch_id or "").strip()
    if not branch:
        raise ValueError("branch_id is required for an artifact fork")
    validate_artifact_refs_branch(state)
    run_id = state.get("run_id") or state.get("session_id", "")
    refs = dict(state.get("artifact_refs") or {})
    repository = _repository(base_dir)
    forked: dict[str, dict[str, Any]] = {}
    for key, raw_ref in refs.items():
        ref = _descriptor(raw_ref, key)
        if ref.run_id != run_id:
            raise ArtifactReplayError(f"artifact {key} belongs to a different run")
        payload = repository.get_json(ref)
        descriptor = repository.put_json(
            payload,
            schema_id=ref.schema_id,
            schema_version=ref.schema_version,
            producer_stage=ref.producer_stage,
            run_id=run_id,
            branch_id=branch,
            parent_digests=dict(ref.parent_digests),
            provenance={
                **dict(ref.provenance),
                "forked_from_descriptor_digest": ref.descriptor_digest,
            },
        )
        repository.compare_and_set_named_ref(
            run_id,
            branch,
            key,
            descriptor,
            expected_descriptor_digest=None,
        )
        forked[key] = descriptor.model_dump(mode="json")
    return forked
