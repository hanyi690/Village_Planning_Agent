"""Deterministic fingerprints used by structural workflow gates."""

from __future__ import annotations

import hashlib
import json
from typing import Any


_VOLATILE_KEYS = {"artifact_id", "created_at", "stored_at"}


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {
            str(key): _jsonable(item)
            for key, item in value.items()
            if key not in _VOLATILE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def checksum(value: Any) -> str:
    raw = json.dumps(
        _jsonable(value),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def stable_artifact_refs(refs: dict[str, Any] | None) -> dict[str, Any]:
    """Retain the complete immutable reference fields needed for audit."""
    stable: dict[str, Any] = {}
    for key, ref in sorted((refs or {}).items()):
        if isinstance(ref, dict):
            stable[key] = {
                field: ref.get(field, "")
                for field in (
                    "artifact_id",
                    "artifact_type",
                    "checksum",
                    "context_version",
                    "context_fingerprint",
                    "revision",
                )
            }
        else:
            stable[key] = _jsonable(ref)
    return stable


def _input_fingerprint_view(refs: dict[str, Any]) -> dict[str, Any]:
    """Prefer content checksums; use artifact IDs only when no checksum exists."""
    view: dict[str, Any] = {}
    for key, ref in refs.items():
        if not isinstance(ref, dict):
            view[key] = ref
            continue
        view[key] = {
            "identity": ref.get("checksum") or ref.get("artifact_id") or "",
            "artifact_type": ref.get("artifact_type", ""),
            "context_version": ref.get("context_version", ""),
            "context_fingerprint": ref.get("context_fingerprint", ""),
            "revision": ref.get("revision", ""),
        }
    return view


def gate_progress_metadata(
    *,
    input_artifact_refs: dict[str, Any] | None,
    output: Any,
    issues: Any,
    previous_gate: Any = None,
) -> tuple[dict[str, Any], bool]:
    refs = stable_artifact_refs(input_artifact_refs)
    input_checksum = checksum(_input_fingerprint_view(refs))
    output_checksum = checksum(output)
    issue_fingerprint = checksum(issues)
    previous = (
        previous_gate.model_dump(mode="json")
        if hasattr(previous_gate, "model_dump")
        else dict(previous_gate or {})
    )
    previous_input = str(previous.get("input_checksum") or "")
    previous_output = str(previous.get("output_checksum") or "")
    previous_issue = str(previous.get("issue_fingerprint") or "")
    has_previous = bool(previous_input or previous_output or previous_issue)
    inputs_changed = None if not has_previous else input_checksum != previous_input
    identical = bool(
        has_previous
        and input_checksum == previous_input
        and output_checksum == previous_output
        and issue_fingerprint == previous_issue
    )
    progress_made = None if not has_previous else not identical
    return {
        "input_artifact_refs": refs,
        "input_checksum": input_checksum,
        "output_checksum": output_checksum,
        "issue_fingerprint": issue_fingerprint,
        "previous_issue_fingerprint": previous_issue,
        "progress_made": progress_made,
        "inputs_changed": inputs_changed,
    }, identical


__all__ = ["checksum", "gate_progress_metadata", "stable_artifact_refs"]
