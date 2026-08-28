"""Deterministic semantic identity for an EXECUTE materialization plan."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


_PLAN_METADATA_FIELDS = {
    "approved_input_fingerprint",
    "artifact_id",
    "created_at",
    "plan_id",
    "scenario_id",
}


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def execution_plan_semantic_payload(plan: Any) -> dict[str, Any]:
    """Return plan content while excluding mutable artifact/approval metadata."""
    payload = _jsonable(plan)
    if not isinstance(payload, dict):
        raise TypeError("execution plan must serialize to an object")
    return {
        str(key): value
        for key, value in payload.items()
        if key not in _PLAN_METADATA_FIELDS
    }


def execution_plan_semantic_digest(plan: Any) -> str:
    """Hash all deterministic worker/materialization semantics of ``plan``."""
    canonical = json.dumps(
        execution_plan_semantic_payload(plan),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


__all__ = ["execution_plan_semantic_payload", "execution_plan_semantic_digest"]
