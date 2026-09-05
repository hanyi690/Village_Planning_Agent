"""Canonical semantic fingerprints for persisted business artifacts."""

from __future__ import annotations

import hashlib
import json
from typing import Any


_VOLATILE_CONTRACT_FIELDS = {"artifact_id", "created_at"}


def _is_execution_result(value: dict[str, Any]) -> bool:
    """Identify outcome result rows without matching ExecutionPlan tasks."""
    return (
        "task_id" in value
        and "target_id" in value
        and "status" in value
        and "expected_output_kind" in value
        and "output_artifacts" in value
        and "worker_type" not in value
    )


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        is_contract = "created_at" in value and any(
            key in value
            for key in (
                "schema_version",
                "context_version",
                "artifact_id",
                "dataset_ref",
                "snapshot_id",
            )
        )
        is_provenance = all(
            key in value for key in ("source", "run_id", "module", "timestamp")
        )
        is_execution_result = _is_execution_result(value)
        return {
            str(key): _jsonable(item)
            for key, item in value.items()
            if not (
                (is_contract and key in _VOLATILE_CONTRACT_FIELDS)
                or (is_provenance and key == "timestamp")
                or (is_execution_result and key == "task_id")
            )
        }
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def semantic_payload(value: Any) -> Any:
    """Drop volatile contract/provenance metadata while retaining business data."""
    return _jsonable(value)


def semantic_checksum(value: Any) -> str:
    raw = json.dumps(
        semantic_payload(value),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _json_safe_semantic_payload(value: Any) -> Any:
    """Filter a JSON-safe payload without probing every scalar for models.

    Artifact publication already calls ``model_dump(mode="json")`` once in
    the runtime layer.  This narrower walker has the same volatile-field
    policy as ``_jsonable`` and is intentionally private to the JSON-safe
    publication path.
    """

    if isinstance(value, dict):
        is_contract = "created_at" in value and any(
            key in value
            for key in (
                "schema_version",
                "context_version",
                "artifact_id",
                "dataset_ref",
                "snapshot_id",
            )
        )
        is_provenance = all(
            key in value for key in ("source", "run_id", "module", "timestamp")
        )
        is_execution_result = _is_execution_result(value)
        return {
            str(key): _json_safe_semantic_payload(item)
            for key, item in value.items()
            if not (
                (is_contract and key in _VOLATILE_CONTRACT_FIELDS)
                or (is_provenance and key == "timestamp")
                or (is_execution_result and key == "task_id")
            )
        }
    if isinstance(value, list):
        return [_json_safe_semantic_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe_semantic_payload(item) for item in value]
    return value


def semantic_checksum_json(value: Any) -> str:
    """Checksum a value already normalized to JSON-safe primitives."""

    raw = json.dumps(
        _json_safe_semantic_payload(value),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = ["semantic_checksum", "semantic_checksum_json", "semantic_payload"]
