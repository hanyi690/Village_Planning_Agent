"""Canonical semantic fingerprints for persisted business artifacts."""

from __future__ import annotations

import hashlib
import json
from typing import Any


_VOLATILE_CONTRACT_FIELDS = {"artifact_id", "created_at"}


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        is_contract = "created_at" in value and any(
            key in value for key in ("schema_version", "context_version", "artifact_id")
        )
        is_provenance = all(
            key in value for key in ("source", "run_id", "module", "timestamp")
        )
        return {
            str(key): _jsonable(item)
            for key, item in value.items()
            if not (
                (is_contract and key in _VOLATILE_CONTRACT_FIELDS)
                or (is_provenance and key == "timestamp")
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


__all__ = ["semantic_checksum", "semantic_payload"]
