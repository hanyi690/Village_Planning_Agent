"""PARSE merge node - deterministic patch merger + revalidation.

Wave F applies deterministic patches (ADD / UPDATE / REMOVE / MERGE) to a
deep copy of the compile result, revalidates, and records a trace step. No
LLM calls, no I/O. Mirrors the dotted-path approach of
``profiles/revision.py`` without importing from it (bridge isolation).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.modules.schema.contracts.parse_result_contracts import (
    CompilationPatch,
    CompilationStatus,
    IntentCompilationResult,
    ParseDiagnostic,
    PatchOperation,
)


def _is_supported_path(path: str) -> bool:
    """Only deterministic paths reachable on the compile result are supported."""
    if not path:
        return False
    if path in ("project_requirements", "spatial_reference_specs"):
        return True
    return path.startswith("typed_intent.")


def _resolve_parent(obj: Any, path: str) -> tuple[Any, str] | None:
    """Resolve the parent object + final segment of a dotted path.

    Supports ``field``, ``field.index`` and ``field.index.subfield``
    navigation through lists and Pydantic models via getattr. Returns None
    when a segment cannot be resolved (invalid path).
    """
    if not path:
        return None
    parts = path.split(".")
    target = obj
    for part in parts[:-1]:
        if isinstance(target, list):
            try:
                index = int(part)
            except ValueError:
                return None
            if not (0 <= index < len(target)):
                return None
            target = target[index]
        elif isinstance(target, BaseModel):
            if not hasattr(target, part):
                return None
            target = getattr(target, part)
        else:
            return None
    return target, parts[-1]


def _apply_update(obj: Any, path: str, value: Any) -> bool:
    parent, last = _resolve_parent(obj, path)
    if parent is None:
        return False
    if isinstance(parent, BaseModel):
        if not hasattr(parent, last):
            return False
        setattr(parent, last, value)
        return True
    if isinstance(parent, list):
        try:
            index = int(last)
        except ValueError:
            return False
        if not (0 <= index < len(parent)):
            return False
        parent[index] = value
        return True
    return False


def _apply_append(obj: Any, path: str, value: Any) -> bool:
    parent, last = _resolve_parent(obj, path)
    if parent is None:
        return False
    if isinstance(parent, BaseModel):
        if not hasattr(parent, last):
            return False
        field = getattr(parent, last)
        if not isinstance(field, list):
            return False
        field.append(value)
        return True
    if isinstance(parent, list):
        try:
            index = int(last)
        except ValueError:
            return False
        if not (0 <= index < len(parent)):
            return False
        field = parent[index]
        if not isinstance(field, list):
            return False
        field.append(value)
        return True
    return False


def _apply_remove(obj: Any, path: str, value: Any) -> bool:
    parent, last = _resolve_parent(obj, path)
    if parent is None:
        return False
    if isinstance(parent, BaseModel):
        if not hasattr(parent, last):
            return False
        field = getattr(parent, last)
        if not isinstance(field, list) or value is None:
            return False
        new_field = [item for item in field if item != value]
        setattr(parent, last, new_field)
        return len(new_field) != len(field)
    if isinstance(parent, list):
        try:
            index = int(last)
        except ValueError:
            return False
        if not (0 <= index < len(parent)):
            return False
        del parent[index]
        return True
    return False


def apply_patches(
    result: IntentCompilationResult,
    patches: list[CompilationPatch],
    *,
    run_id: str = "",
) -> IntentCompilationResult:
    """Apply deterministic patches to a deep copy and revalidate.

    Unsupported or unresolvable paths are skipped and recorded as
    ``SCHEMA_MISMATCH`` error diagnostics. The original result is left
    untouched (Pydantic v2 ``model_copy(deep=True)``).
    """
    copy = result.model_copy(deep=True)
    for index, patch in enumerate(patches):
        path = patch.field_path
        applied = True
        if not _is_supported_path(path):
            applied = False
        elif patch.operation == PatchOperation.ADD:
            applied = _apply_append(copy, path, patch.after)
        elif patch.operation == PatchOperation.MERGE:
            applied = _apply_append(copy, path, patch.after)
        elif patch.operation == PatchOperation.UPDATE:
            applied = _apply_update(copy, path, patch.after)
        elif patch.operation == PatchOperation.REMOVE:
            applied = _apply_remove(
                copy,
                path,
                patch.after if patch.after is not None else patch.before,
            )
        else:
            applied = False
        if not applied:
            copy.diagnostics.append(
                ParseDiagnostic(
                    diagnostic_id=f"parse-schema-mismatch-{index}",
                    severity="error",
                    code="SCHEMA_MISMATCH",
                    message=f"patch path not resolvable: {path}",
                    field_path=path,
                )
            )
        copy.patches.append(patch)

    has_errors = any(d.severity == "error" for d in copy.diagnostics)
    copy.compilation_status = (
        CompilationStatus.NEEDS_REPAIR if has_errors else CompilationStatus.VALIDATED
    )
    copy.trace.steps.append(
        {
            "step": "apply_patches",
            "patches": len(patches),
            "status": copy.compilation_status.value,
        }
    )
    return copy


__all__ = ["apply_patches"]
