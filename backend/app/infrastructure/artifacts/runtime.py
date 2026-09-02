"""Reference-only workflow state helpers.

The graph stores small references and reloads typed artifacts at stage
boundaries.  This module deliberately has no LangGraph imports so it can be
used by recovery code and tests without importing model/tool registrations.
"""

from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
from typing import Any, Iterable, TypeVar

from pydantic import ValidationError

from app.infrastructure.artifacts import ContentAddressedArtifactRepository, NamedRefConflict
from app.infrastructure.artifacts.fingerprint import semantic_checksum
from app.contracts.artifacts.ref import ArtifactRef as ArtifactDescriptor
from app.infrastructure.paths import run_tmp_root

T = TypeVar("T")

ARTIFACT_SCHEMA_VERSION = "3"

ARTIFACT_KEYS = (
    "data_catalog", "source_snapshot", "normalized_resource", "representation_snapshot", "capability_index", "data_snapshot", "data_stage", "schema_mapping_snapshot", "world_model_snapshot", "world_model_current_snapshot",
    "kg_stage", "evidence_snapshot", "evidence_external_observations", "evidence_gap_ledger", "l1_snapshot", "l2_strategy", "planning_program", "target_projection",
    "grounding_result", "scoped_grounding_problem", "demand_portfolio", "suitability_surface", "portfolio_decision",
    "execution_plan", "execution_result", "parcel_changeset", "spatial_changeset",
    "planned_entity_set", "planned_representation_set", "execution_trace",
    "planned_state", "validation_report", "final_manifest", "delivery_manifest",
    "layout_configs", "render_layers", "delivery_spatial_snapshot", "deferral_ledger",
    "export_result", "render_artifacts", "execution_diagnostics", "kg_layer1",
    "repair_directives", "repair_impact", "global_zone_allocation",
    "planning_scenario", "scenario_set", "approved_execution_input", "validation_certificate", "final_relation_validation",
    "global_site_allocation", "l1_observations", "l1_bindings", "l1_world_projection",
    "source_semantic_classification", "l1_source_index", "l1_observation_snapshot", "l1_binding_snapshot", "l1_final_product", "l1_product_manifest", "data_admission_receipt", "data_admission_gap", "data_remote_admission_receipt", "boundary_scope", "world_model_commit_snapshot", "world_model_commit_receipt", "execution_staging", "staged_parcel_changeset", "staged_spatial_changeset",
    "staged_planned_state", "staged_layout_configs",
    "staged_planned_entity_set", "staged_planned_representation_set", "staged_execution_trace",
    "staged_delivery_spatial_snapshot",
    "solver_subproblem_plan", "solver_readiness",
    "planning_task_graph",
)

_DIMENSION_PRODUCT_KEY = re.compile(r"^l[123]_dimension__[a-z0-9][a-z0-9_-]{0,127}$")
_EVIDENCE_RETRIEVAL_KEY = re.compile(r"^evidence_retrieval__[0-9a-f]{64}$")


def _known_artifact_key(key: str) -> bool:
    return (
        key in ARTIFACT_KEYS
        or _DIMENSION_PRODUCT_KEY.fullmatch(key) is not None
        or _EVIDENCE_RETRIEVAL_KEY.fullmatch(key) is not None
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


def _repository(
    base_dir: str | Path | None = None,
    *,
    state: dict[str, Any] | None = None,
) -> ContentAddressedArtifactRepository:
    """Resolve CAS storage from the checkpoint before process environment.

    Artifact descriptors are immutable, but their blobs still need a storage
    root.  A resumed process may have a different cwd or environment, so a
    state-carried root is authoritative whenever the caller did not provide an
    explicit test/replay directory.  Older checkpoints without the field keep
    the historical ``run_tmp_root`` fallback.
    """

    if base_dir is None or str(base_dir) == ".run-tmp":
        state_root = str((state or {}).get("artifact_root") or "").strip()
        base_dir = Path(state_root).resolve() if state_root else run_tmp_root()
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


def validate_artifact_context(
    state: dict[str, Any], key: str, ref: Any,
) -> ArtifactDescriptor:
    """Validate that an artifact was produced from this frozen cognition context.

    ``context_version`` alone is not sufficient once a session can contain
    multiple DATA or World-Model snapshots.  ``store_artifact`` copies the
    bounded ``context_ref`` into provenance; stage facades call this helper
    after reloading an upstream artifact so a stale snapshot fails closed.
    Empty expected values remain compatible with old checkpoints, while a
    non-empty current authority value must be present and equal on the
    artifact.  Large catalogs/graphs are never loaded by this check.
    """
    descriptor = _descriptor(ref, key)
    expected = context_ref_for(state)
    actual = descriptor.provenance.get("context_ref")
    if not isinstance(actual, dict):
        raise ArtifactReplayError(f"artifact {key} has no context provenance")
    # Context authority grows monotonically along the pipeline.  DATA produces
    # the DATA axis, KG consumes DATA and produces the World-Model axis, while
    # EVIDENCE and later stages consume both.  Comparing a DATA/KG artifact
    # against a World Model that did not exist until a later stage makes every
    # valid upstream checkpoint stale by construction.
    producer_stage = str(descriptor.producer_stage or "").strip().casefold()
    base_fields = ("session_id", "version")
    data_fields = (
        "snapshot_digest",
        "data_snapshot_digest",
        "data_resource_catalog_digest",
    )
    world_model_fields = (
        "world_model_mode",
        "world_model_snapshot_ref",
        "world_model_snapshot_digest",
        "world_model_shadow_snapshot_ref",
        "world_model_shadow_snapshot_digest",
    )
    fields = (*base_fields, *data_fields)
    if producer_stage not in {"data", "kg", "cognition"}:
        fields = (*fields, *world_model_fields)
    for field in fields:
        expected_value = str(expected.get(field) or "").strip()
        if not expected_value:
            continue
        actual_value = str(actual.get(field) or "").strip()
        if actual_value != expected_value:
            raise ArtifactReplayError(
                f"artifact {key} context authority mismatch: {field}"
            )
    return descriptor


def validate_artifact_context_with_l1_transition(
    state: dict[str, Any],
    key: str,
    ref: Any,
) -> ArtifactDescriptor:
    """Validate a base-context artifact through the exact L1 WM transition.

    L1 identity GROUND advances only the World Model axis.  DATA, KG,
    EVIDENCE and the original L1 snapshot remain immutable products of the
    parent authority.  This helper is deliberately narrow: it first performs
    the normal validation and permits the parent context only when a current,
    CAS-backed ``L1WorldProjectionSnapshot`` proves the exact artifact is in
    its source closure.  It never weakens ``validate_artifact_context``.
    """

    try:
        return validate_artifact_context(state, key, ref)
    except ArtifactReplayError as original_error:
        refs = dict(state.get("artifact_refs") or {})
        projection_raw = refs.get("l1_world_projection")
        current_world_raw = refs.get("world_model_current_snapshot")
        if not projection_raw or not current_world_raw:
            raise original_error

        from app.contracts.cognition.stage_contracts import (
            L1WorldProjectionSnapshot,
        )

        projection_ref = validate_artifact_context(
            state,
            "l1_world_projection",
            projection_raw,
        )
        current_world_ref = validate_artifact_context(
            state,
            "world_model_current_snapshot",
            current_world_raw,
        )
        projection = load_artifact(
            state,
            "l1_world_projection",
            L1WorldProjectionSnapshot,
        )
        if projection is None:
            raise original_error
        if (
            projection.resulting_world_model_artifact_ref.descriptor_digest
            != current_world_ref.descriptor_digest
            or projection.resulting_world_model_artifact_ref.digest
            != current_world_ref.digest
        ):
            raise ArtifactReplayError(
                "L1 World projection/current World Model identity mismatch"
            )
        current_context = context_ref_for(state)
        for field in (
            "session_id",
            "version",
            "snapshot_digest",
            "data_snapshot_digest",
            "data_resource_catalog_digest",
            "world_model_mode",
            "world_model_snapshot_ref",
            "world_model_snapshot_digest",
        ):
            expected_value = str(
                projection.resulting_context_ref.get(field) or ""
            ).strip()
            actual_value = str(current_context.get(field) or "").strip()
            if expected_value and actual_value != expected_value:
                raise ArtifactReplayError(
                    f"L1 World projection resulting context mismatch: {field}"
                )
        if (
            projection.resulting_world_model_snapshot_ref
            != str(current_context.get("world_model_snapshot_ref") or "")
            or projection.resulting_world_model_snapshot_digest
            != str(current_context.get("world_model_snapshot_digest") or "")
        ):
            raise ArtifactReplayError(
                "L1 World projection is not authoritative for current context"
            )

        descriptor = _descriptor(ref, key)
        allowed: dict[str, ArtifactDescriptor] = {
            "l1_snapshot": projection.l1_snapshot_artifact_ref,
            "l1_observations": projection.observation_artifact_ref,
            "l1_bindings": projection.binding_artifact_ref,
            "world_model_snapshot": (
                projection.source_world_model_artifact_ref
            ),
        }
        l1_parent_digest = str(
            projection.l1_snapshot_artifact_ref.parent_digests.get(key)
            or ""
        )
        exact = allowed.get(key)
        exact_identity = bool(
            exact is not None
            and exact.descriptor_digest == descriptor.descriptor_digest
            and exact.digest == descriptor.digest
            and exact.semantic_digest == descriptor.semantic_digest
        )
        ancestor_identity = bool(
            l1_parent_digest and l1_parent_digest == descriptor.digest
        )
        if not exact_identity and not ancestor_identity:
            raise original_error
        actual_context = descriptor.provenance.get("context_ref")
        if not isinstance(actual_context, dict):
            raise ArtifactReplayError(
                f"artifact {key} has no source context provenance"
            )
        for field in (
            "session_id",
            "version",
            "snapshot_digest",
            "data_snapshot_digest",
            "data_resource_catalog_digest",
            "world_model_mode",
            "world_model_snapshot_ref",
            "world_model_snapshot_digest",
        ):
            expected_value = str(
                projection.source_context_ref.get(field) or ""
            ).strip()
            if not expected_value:
                continue
            if str(actual_context.get(field) or "").strip() != expected_value:
                raise ArtifactReplayError(
                    f"artifact {key} source transition mismatch: {field}"
                )
        return descriptor


def validate_l1_world_projection_transition(state: dict[str, Any]) -> Any:
    """Reload and prove the complete base→child L1 cognition transition."""

    from app.contracts.cognition.snapshot import SessionWorldModelSnapshot
    from app.contracts.cognition.stage_contracts import (
        L1WorldProjectionSnapshot,
    )

    refs = dict(state.get("artifact_refs") or {})
    required_keys = (
        "world_model_snapshot",
        "world_model_current_snapshot",
        "l1_snapshot",
        "l1_observations",
        "l1_bindings",
        "l1_world_projection",
    )
    missing = [key for key in required_keys if not refs.get(key)]
    if missing:
        raise ArtifactReplayError(
            "L1 World projection inputs are missing: " + ", ".join(missing)
        )
    projection_ref = validate_artifact_context(
        state,
        "l1_world_projection",
        refs["l1_world_projection"],
    )
    current_ref = validate_artifact_context(
        state,
        "world_model_current_snapshot",
        refs["world_model_current_snapshot"],
    )
    projection = load_artifact(
        state,
        "l1_world_projection",
        L1WorldProjectionSnapshot,
    )
    current_snapshot = load_artifact(
        state,
        "world_model_current_snapshot",
        SessionWorldModelSnapshot,
    )
    if projection is None or current_snapshot is None:
        raise ArtifactReplayError("L1 World projection cannot be reloaded")
    expected_parents = {
        key: _descriptor(refs[key], key).digest
        for key in required_keys
        if key != "l1_world_projection"
    }
    if projection_ref.parent_digests != dict(sorted(expected_parents.items())):
        raise ArtifactReplayError(
            "L1 World projection parent closure is not exact"
        )

    exact_pairs = (
        (
            projection.source_world_model_artifact_ref,
            _descriptor(
                refs["world_model_snapshot"],
                "world_model_snapshot",
            ),
        ),
        (
            projection.resulting_world_model_artifact_ref,
            current_ref,
        ),
        (
            projection.l1_snapshot_artifact_ref,
            _descriptor(refs["l1_snapshot"], "l1_snapshot"),
        ),
        (
            projection.observation_artifact_ref,
            _descriptor(refs["l1_observations"], "l1_observations"),
        ),
        (
            projection.binding_artifact_ref,
            _descriptor(refs["l1_bindings"], "l1_bindings"),
        ),
    )
    for frozen, active in exact_pairs:
        if any(
            getattr(frozen, field) != getattr(active, field)
            for field in (
                "descriptor_digest",
                "digest",
                "semantic_digest",
            )
        ):
            raise ArtifactReplayError(
                "L1 World projection artifact identity mismatch"
            )
    if (
        projection.resulting_world_model_snapshot_ref
        != current_snapshot.snapshot_ref
        or projection.resulting_world_model_snapshot_digest
        != current_snapshot.graph_digest
        or projection.resulting_world_model_version
        != current_snapshot.version
        or current_snapshot.parent_snapshot_ref
        != projection.source_world_model_snapshot_ref
        or current_snapshot.parent_snapshot_digest
        != projection.source_world_model_snapshot_digest
    ):
        raise ArtifactReplayError(
            "L1 World projection child snapshot lineage mismatch"
        )
    current_context = context_ref_for(state)
    for field in (
        "session_id",
        "version",
        "snapshot_digest",
        "data_snapshot_digest",
        "data_resource_catalog_digest",
        "world_model_mode",
        "world_model_snapshot_ref",
        "world_model_snapshot_digest",
    ):
        expected_value = str(
            projection.resulting_context_ref.get(field) or ""
        ).strip()
        if expected_value and str(
            current_context.get(field) or ""
        ).strip() != expected_value:
            raise ArtifactReplayError(
                f"L1 World projection current authority mismatch: {field}"
            )
    return projection


def store_artifact(
    state: dict[str, Any], key: str, module: str, artifact_type: str, payload: Any,
    *,
    attempt: int = 1,
    base_dir: str | Path | None = None,
    parent_keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Persist an artifact idempotently and return its JSON reference."""
    if not _known_artifact_key(key):
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
    selected_refs = current_refs
    if parent_keys is not None:
        required_parent_keys = tuple(dict.fromkeys(str(item) for item in parent_keys))
        missing_parent_keys = [
            parent_key
            for parent_key in required_parent_keys
            if not current_refs.get(parent_key)
        ]
        if missing_parent_keys:
            raise ArtifactReplayError(
                "artifact input refs are missing: " + ", ".join(missing_parent_keys)
            )
        selected_refs = {
            parent_key: current_refs[parent_key]
            for parent_key in required_parent_keys
        }
    parent_digests = _parent_digests(
        selected_refs,
        exclude_key=key,
        exclude_keys={f"{module}_gate"},
    )
    repository = _repository(base_dir, state=state)
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
            and existing.semantic_digest
            == f"sha256:{semantic_checksum(payload)}"
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
    repository = _repository(base_dir, state=state)
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


def load_embedded_artifact(
    state: dict[str, Any], descriptor_data: dict[str, Any] | None,
    model: type[T] | None = None,
    *, base_dir: str | Path | None = None,
) -> T | dict[str, Any] | None:
    """Load an exact child artifact referenced by a root artifact."""
    if not descriptor_data:
        return None
    ref = _descriptor(descriptor_data, "embedded_child")
    run_id = state.get("run_id") or state.get("session_id", "")
    if ref.run_id != run_id or ref.branch_id != str(state.get("branch_id") or "main"):
        raise ArtifactReplayError("embedded child artifact belongs to a different run or branch")
    payload = _repository(base_dir, state=state).get_json(ref)
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
    repository = _repository(base_dir, state=state)
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
