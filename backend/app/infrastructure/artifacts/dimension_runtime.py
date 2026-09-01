"""CAS helpers for exact per-dimension L1/L2/L3 products."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, TypeVar

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.workflow.dimension_product_contracts import (
    DimensionProductArtifact,
    DimensionProductStatus,
    dimension_product_key,
)
from app.infrastructure.artifacts.fingerprint import semantic_checksum
from app.infrastructure.artifacts.runtime import (
    load_artifact,
    store_artifact,
    validate_artifact_context,
)


_SCHEMA_BY_LAYER = {
    1: "L1DimensionOutput",
    2: "L2DecisionSet",
    3: "PlanningClaimSet",
}

_BASE_INPUT_KEYS_BY_LAYER = {
    1: ("data_stage", "kg_stage", "evidence_snapshot"),
    2: ("l1_snapshot", "evidence_snapshot"),
    3: ("l1_snapshot", "l2_strategy", "evidence_snapshot"),
}

ProductT = TypeVar("ProductT")


def _json_payload(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    if not isinstance(payload, Mapping):
        raise TypeError("dimension product payload must be a typed object")
    return {str(key): item for key, item in payload.items()}


def _input_digests(
    state: Mapping[str, Any],
    *,
    input_keys: Iterable[str],
) -> dict[str, str]:
    result: dict[str, str] = {}
    refs = dict(state.get("artifact_refs") or {})
    for key in tuple(dict.fromkeys(str(item) for item in input_keys)):
        value = refs.get(key)
        if not value:
            raise ValueError(f"typed dimension input artifact ref is missing: {key}")
        descriptor = value if isinstance(value, ArtifactRef) else ArtifactRef.model_validate(value)
        result[str(key)] = descriptor.digest
    return dict(sorted(result.items()))


def persist_dimension_product(
    state: dict[str, Any],
    *,
    layer: int,
    dimension_key: str,
    status: DimensionProductStatus,
    product: Any = None,
    dependency_product_refs: Iterable[str] = (),
    evidence_gap_refs: Iterable[str] = (),
    input_digest: str = "",
    diagnostics: Iterable[str] = (),
) -> tuple[str, dict[str, Any]]:
    """Commit one dimension envelope and return its checkpoint key/ref."""

    key = dimension_product_key(layer, dimension_key)
    schema_id = _SCHEMA_BY_LAYER.get(layer)
    if schema_id is None:
        raise ValueError("dimension product layer must be 1, 2, or 3")
    payload = _json_payload(product)
    normalized_diagnostics = tuple(
        dict.fromkeys(str(item).strip() for item in diagnostics if str(item).strip())
    )
    dependency_keys = tuple(
        dict.fromkeys(
            str(item).strip()
            for item in dependency_product_refs
            if str(item).strip()
        )
    )
    from app.config import get_dimension_config, get_dimension_layer

    config = get_dimension_config(dimension_key)
    if config is None or get_dimension_layer(dimension_key) != layer:
        raise ValueError("dimension product config layer mismatch")
    expected_dependency_keys = configured_dependency_product_keys(config)
    if set(dependency_keys) != set(expected_dependency_keys):
        raise ValueError(
            "typed dimension dependency closure mismatch: "
            f"expected={sorted(expected_dependency_keys)} "
            f"actual={sorted(dependency_keys)}"
        )
    input_keys = tuple(dict.fromkeys([
        *_BASE_INPUT_KEYS_BY_LAYER[layer],
        *dependency_keys,
    ]))
    input_artifact_digests = _input_digests(state, input_keys=input_keys)
    dependency_product_digests = {
        dependency_key: input_artifact_digests[dependency_key]
        for dependency_key in dependency_keys
    }
    gap_refs = tuple(
        dict.fromkeys(str(item).strip() for item in evidence_gap_refs if str(item).strip())
    )
    identity = {
        "layer": layer,
        "dimension_key": dimension_key,
        "status": status,
        "schema": schema_id,
        "product": payload,
        "dependency_product_refs": dependency_keys,
        "dependency_product_digests": dependency_product_digests,
        "evidence_gap_refs": gap_refs,
        "input_digest": str(input_digest or ""),
        "diagnostics": normalized_diagnostics,
    }
    artifact = DimensionProductArtifact(
        context_version=str(state.get("context_version") or ""),
        context_fingerprint=str(state.get("context_fingerprint") or ""),
        artifact_id=f"{key}-{semantic_checksum(identity)[:16]}",
        stage=f"l{layer}",
        layer=layer,
        dimension_key=dimension_key,
        status=status,
        product_schema_id=schema_id,
        product=payload,
        input_artifact_digests=input_artifact_digests,
        dependency_product_refs=dependency_keys,
        dependency_product_digests=dependency_product_digests,
        evidence_gap_refs=gap_refs,
        input_digest=str(input_digest or ""),
        diagnostics=normalized_diagnostics,
    )
    ref = store_artifact(
        state,
        key,
        f"l{layer}_dimension",
        "DimensionProductArtifact",
        artifact,
        parent_keys=input_keys,
    )
    return key, ref


def load_dimension_product(
    state: Mapping[str, Any],
    *,
    layer: int,
    dimension_key: str,
) -> DimensionProductArtifact | None:
    """Reload and context-check the exact checkpoint-selected product."""

    current = dict(state)
    key = dimension_product_key(layer, dimension_key)
    raw_ref = dict(current.get("artifact_refs") or {}).get(key)
    if not raw_ref:
        return None
    descriptor = validate_artifact_context(current, key, raw_ref)
    artifact = load_artifact(current, key, DimensionProductArtifact)
    if artifact is None:
        return None
    if artifact.layer != layer or artifact.dimension_key != dimension_key:
        raise ValueError("dimension product identity does not match its checkpoint key")
    if descriptor.parent_digests != artifact.input_artifact_digests:
        raise ValueError("dimension product descriptor/input digest closure mismatch")
    current_refs = dict(current.get("artifact_refs") or {})
    for input_key, expected_digest in artifact.input_artifact_digests.items():
        current_ref = current_refs.get(input_key)
        if not current_ref:
            raise ValueError(
                f"dimension product input artifact ref is missing: {input_key}"
            )
        input_descriptor = (
            current_ref
            if isinstance(current_ref, ArtifactRef)
            else ArtifactRef.model_validate(current_ref)
        )
        if input_descriptor.digest != expected_digest:
            raise ValueError(
                f"dimension product input digest changed: {input_key}"
            )
    return artifact


def ensure_dimension_product_patch(
    state: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    layer: int,
) -> dict[str, Any]:
    """Persist an explicit incomplete envelope when a worker produced no CAS result."""

    patch = dict(result)
    dimension_key = str(state.get("dimension_key") or "").strip()
    if not dimension_key:
        raise ValueError("dimension worker result has no dimension_key")
    key = dimension_product_key(layer, dimension_key)
    result_refs = dict(patch.get("artifact_refs") or {})
    if result_refs.get(key):
        return patch

    diagnostics: list[str] = []
    for item in patch.get("dimension_failures") or ():
        if isinstance(item, Mapping):
            code = str(item.get("code") or "dimension_worker_incomplete")
            message = str(item.get("message") or item.get("error") or "").strip()
            diagnostics.append(f"{code}: {message}".rstrip())
        else:
            diagnostics.append(str(item).strip())
    for field_name in ("fatal_error", "quality_feedback", "error"):
        value = str(patch.get(field_name) or "").strip()
        if value:
            diagnostics.append(f"{field_name}: {value}")
    if not diagnostics:
        diagnostics.append("dimension worker returned without a completed typed product")
    diagnostics = list(dict.fromkeys(item for item in diagnostics if item))
    diagnostic_text = " ".join(diagnostics).casefold()
    status: DimensionProductStatus = (
        "human_required"
        if patch.get("human_review_items")
        or "requires_human_confirmation" in diagnostic_text
        or "human_required" in diagnostic_text
        else "pending"
    )

    from app.config import get_dimension_config

    config = get_dimension_config(dimension_key)
    dependency_keys = configured_dependency_product_keys(config)
    gap_refs = []
    for item in patch.get("evidence_gap_rows") or ():
        if isinstance(item, Mapping):
            gap_ref = str(item.get("gap_ref") or item.get("gap_id") or "").strip()
            if gap_ref:
                gap_refs.append(gap_ref)
    product_key, product_ref = persist_dimension_product(
        dict(state),
        layer=layer,
        dimension_key=dimension_key,
        status=status,
        dependency_product_refs=dependency_keys,
        evidence_gap_refs=gap_refs,
        input_digest="sha256:" + semantic_checksum({
            "context_version": state.get("context_version", ""),
            "context_fingerprint": state.get("context_fingerprint", ""),
            "dimension_key": dimension_key,
            "dependencies": dependency_keys,
        }),
        diagnostics=diagnostics,
    )
    patch["artifact_refs"] = {**result_refs, product_key: product_ref}
    return patch


def dependency_product_keys(artifacts: Iterable[Any]) -> tuple[str, ...]:
    """Translate dependency records to their typed CAS checkpoint keys."""

    result: list[str] = []
    for item in artifacts:
        layer = int(getattr(item, "layer", 0) or 0)
        dimension = str(getattr(item, "dimension_key", "") or "").strip()
        if layer in {1, 2, 3} and dimension:
            result.append(dimension_product_key(layer, dimension))
    return tuple(dict.fromkeys(result))


def configured_dependency_product_keys(config: Any) -> tuple[str, ...]:
    """Return the exact typed-product keys declared by one dimension config."""

    from app.config import get_dimension_config, get_dimension_layer

    dimensions = tuple(dict.fromkeys([
        *list(getattr(config, "depends_on", ()) or ()),
        *list(getattr(config, "layer_depends_on", ()) or ()),
        *list(getattr(config, "phase_depends_on", ()) or ()),
    ]))
    result: list[str] = []
    for dimension in dimensions:
        dependency = get_dimension_config(str(dimension))
        dependency_layer = get_dimension_layer(str(dimension))
        if dependency_layer not in {1, 2, 3}:
            raise ValueError(f"unknown dependency dimension: {dimension}")
        result.append(dimension_product_key(dependency_layer, str(dimension)))
    return tuple(result)


def load_layer_dimension_products(
    state: Mapping[str, Any],
    *,
    layer: int,
    model_type: type[ProductT],
) -> tuple[dict[str, ProductT], dict[str, str]]:
    """Load the complete configured layer from exact checkpoint CAS refs.

    The returned error table is part of the stage gate input.  Callers must not
    omit its dimensions or replace them with ReportStore ``latest`` rows.
    """

    from app.config.loader import list_dimensions

    current_refs = dict(state.get("artifact_refs") or {})
    products: dict[str, ProductT] = {}
    errors: dict[str, str] = {}
    for config in list_dimensions(layer):
        dimension = str(config.key)
        try:
            artifact = load_dimension_product(
                state,
                layer=layer,
                dimension_key=dimension,
            )
            if artifact is None:
                raise ValueError("typed dimension artifact ref is missing")
            if artifact.status != "completed":
                detail = "; ".join(artifact.diagnostics[:4])
                raise ValueError(
                    f"typed dimension artifact is {artifact.status}: {detail}"
                )
            expected_dependencies = set(configured_dependency_product_keys(config))
            actual_dependencies = set(artifact.dependency_product_refs)
            if actual_dependencies != expected_dependencies:
                raise ValueError(
                    "typed dimension dependency closure mismatch: "
                    f"expected={sorted(expected_dependencies)} "
                    f"actual={sorted(actual_dependencies)}"
                )
            for dependency_key in expected_dependencies:
                raw_ref = current_refs.get(dependency_key)
                if not raw_ref:
                    raise ValueError(
                        f"typed dimension dependency ref is missing: {dependency_key}"
                    )
                descriptor = (
                    raw_ref
                    if isinstance(raw_ref, ArtifactRef)
                    else ArtifactRef.model_validate(raw_ref)
                )
                if artifact.dependency_product_digests.get(dependency_key) != descriptor.digest:
                    raise ValueError(
                        f"typed dimension dependency digest mismatch: {dependency_key}"
                    )
            products[dimension] = model_type.model_validate(artifact.product)
        except Exception as exc:  # aggregate records this as a typed gate issue
            errors[dimension] = f"{type(exc).__name__}: {exc}"
    return products, errors


__all__ = [
    "configured_dependency_product_keys",
    "dependency_product_keys",
    "ensure_dimension_product_patch",
    "load_layer_dimension_products",
    "load_dimension_product",
    "persist_dimension_product",
]
