"""Deterministic fingerprints used by structural workflow gates."""

from __future__ import annotations

from typing import Any

from app.infrastructure.artifacts.fingerprint import semantic_checksum, semantic_payload

def checksum(value: Any) -> str:
    return semantic_checksum(value)


def stable_artifact_refs(refs: dict[str, Any] | None) -> dict[str, Any]:
    """Retain the complete immutable reference fields needed for audit."""
    stable: dict[str, Any] = {}
    for key, ref in sorted((refs or {}).items()):
        if isinstance(ref, dict):
            stable[key] = {
                field: ref.get(field, "")
                for field in (
                    "digest",
                    "descriptor_digest",
                    "schema_id",
                    "schema_version",
                    "semantic_digest",
                    "parent_digests",
                    "run_id",
                    "branch_id",
                )
            }
        else:
            stable[key] = semantic_payload(ref)
    return stable


def _input_fingerprint_view(refs: dict[str, Any]) -> dict[str, Any]:
    """Prefer content checksums; use artifact IDs only when no checksum exists."""
    view: dict[str, Any] = {}
    for key, ref in refs.items():
        if not isinstance(ref, dict):
            view[key] = ref
            continue
        view[key] = {
            "identity": ref.get("descriptor_digest") or "",
            "blob_digest": ref.get("digest") or "",
            "schema_id": ref.get("schema_id", ""),
            "schema_version": ref.get("schema_version", ""),
            "parent_digests": ref.get("parent_digests", {}),
            "branch_id": ref.get("branch_id", ""),
        }
    return view


def canonical_input_checksum(refs: dict[str, Any] | None) -> str:
    return checksum(_input_fingerprint_view(stable_artifact_refs(refs)))


def canonical_output_checksum(output: Any) -> str:
    return checksum(output)


def gate_progress_metadata(
    *,
    input_artifact_refs: dict[str, Any] | None,
    output: Any,
    issues: Any,
    previous_gate: Any = None,
) -> tuple[dict[str, Any], bool]:
    refs = stable_artifact_refs(input_artifact_refs)
    input_checksum = canonical_input_checksum(refs)
    output_checksum = canonical_output_checksum(output)
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


__all__ = ["checksum", "canonical_input_checksum", "canonical_output_checksum", "gate_progress_metadata", "stable_artifact_refs"]
