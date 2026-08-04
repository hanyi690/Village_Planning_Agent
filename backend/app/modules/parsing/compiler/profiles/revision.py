"""REVISION compilation profile.

Wave F Task 5 delivers the full REVISION profile: it applies user-provided
structured revisions (``ParseRevisionRequest.user_revisions``) deterministically
to an ``L3ProgramFragment`` recompiled from the current report content. No LLM
calls; the base fragment is produced by the L3_PLANNING profile and dotted-path
overrides are applied on top.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.modules.schema.contracts.l3_contracts import L3ProgramFragment
from app.modules.schema.contracts.parse_result_contracts import ParseDiagnostic
from app.modules.schema.contracts.parsing_contracts import CompilationProfile, CompilerTrace

from ..diagnostics import collect_diagnostics
from ..instruction_parser import split_content_instruction
from ..provenance import build_fragment_provenance

from .l3_planning import compile_l3_planning


def _apply_dotted_path(obj: Any, path: str, value: Any) -> bool:
    """Apply a dotted-path override (``field.0.subfield``) to ``obj``.

    Supports list-index navigation and attribute setting on Pydantic models,
    e.g. ``interventions.0.scale`` sets ``obj.interventions[0].scale``.
    Returns True when the path resolved and was applied; False when a segment
    cannot be resolved (invalid path).
    """
    if not path:
        return False
    parts = path.split(".")
    target = obj
    for part in parts[:-1]:
        if isinstance(target, list):
            try:
                index = int(part)
            except ValueError:
                return False
            if not (0 <= index < len(target)):
                return False
            target = target[index]
        elif isinstance(target, BaseModel):
            if not hasattr(target, part):
                return False
            target = getattr(target, part)
        elif isinstance(target, dict):
            if part not in target:
                return False
            target = target[part]
        else:
            return False
    last = parts[-1]
    if isinstance(target, list):
        try:
            index = int(last)
        except ValueError:
            return False
        if not (0 <= index < len(target)):
            return False
        target[index] = value
        return True
    if isinstance(target, dict):
        if last not in target:
            return False
        target[last] = value
        return True
    if isinstance(target, BaseModel):
        if not hasattr(target, last):
            return False
        setattr(target, last, value)
        return True
    return False


def compile_revision(
    *,
    revision_request: Any,
    base_result: Any,
    dimension_key: str,
    content: str,
    instruction: str,
    summary: str = "",
    report_id: str = "",
    run_id: str = "",
) -> L3ProgramFragment:
    """Compile a revised L3 fragment by applying user_revisions deterministically.

    The baseline is recompiled from the current report content via the
    L3_PLANNING profile (the most correct reflection of the report), then
    user-provided dotted-path overrides are applied. Unresolvable paths are
    collected as ``SCHEMA_MISMATCH`` error diagnostics and skipped.
    """
    steps: list[str] = []

    base = compile_l3_planning(
        dimension_key=dimension_key,
        content=content,
        instruction=instruction,
        summary=summary,
        report_id=report_id,
        run_id=run_id,
    )
    steps.append("load_base")

    user_revisions = getattr(revision_request, "user_revisions", None) or {}
    schema_mismatches: list[ParseDiagnostic] = []
    for path, value in user_revisions.items():
        path_str = str(path)
        if not _apply_dotted_path(base, path_str, value):
            schema_mismatches.append(
                ParseDiagnostic(
                    diagnostic_id=f"{dimension_key}-schema-mismatch",
                    severity="error",
                    code="SCHEMA_MISMATCH",
                    message=f"revision path not resolvable: {path_str}",
                    field_path=path_str,
                )
            )
    steps.append("apply_user_revisions")

    display, instr_from_content = split_content_instruction(content or "")
    instr = instruction or instr_from_content
    diagnostics = collect_diagnostics(dimension_key, display, instr)
    diagnostics.extend(schema_mismatches)
    steps.append("revalidate")

    return L3ProgramFragment(
        dimension_key=dimension_key,
        interventions=base.interventions,
        dependencies=base.dependencies,
        evidence_gaps=base.evidence_gaps,
        program_issues=base.program_issues,
        omissions=base.omissions,
        diagnostics=diagnostics,
        provenance=build_fragment_provenance(
            dimension_key,
            report_id,
            run_id,
            ["revision"],
            source_module="revision",
        ),
        trace=CompilerTrace(
            profile=CompilationProfile.REVISION,
            steps=steps,
        ),
    )


__all__ = ["compile_revision"]
