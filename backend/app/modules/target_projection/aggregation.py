"""Deterministic projection from the authoritative planning program.

This stage is deliberately not an LLM parser.  L3 claims are already
structured and the PlanningProgram is assembled by the domain layer.  The
projection only prepares typed spatial references for GROUND and records a
fail-closed gate.
"""

from __future__ import annotations

from app.contracts.l3.l3_contracts import PlanningProgram
from app.contracts.target_projection.parse_result_contracts import (
    CompilationStatus,
    IntentCompilationResult,
)
from app.contracts.ground.spatial_reference_contracts import SpatialReferenceSpec
from app.contracts.workflow.workflow_contracts import GateDecision

from .requirement_compilation import compile_program_deterministic
from .validation import evaluate_target_projection_gate


def project_program(
    program: PlanningProgram,
    *,
    run_id: str = "",
    context_version: str = "",
) -> tuple[IntentCompilationResult, list[SpatialReferenceSpec], GateDecision]:
    result, specs, diagnostics = compile_program_deterministic(
        program,
        run_id=run_id,
        context_version=context_version,
        program_ref=program.artifact_id,
    )
    gate = evaluate_target_projection_gate(
        result,
        run_id=run_id,
        context_version=context_version,
    )
    if gate.passed and result.compilation_status == CompilationStatus.DRAFT:
        result.compilation_status = CompilationStatus.VALIDATED
    if not result.context_version:
        result.context_version = context_version
    return result, specs, gate


async def project_program_async(
    program: PlanningProgram,
    *,
    run_id: str = "",
    context_version: str = "",
) -> tuple[IntentCompilationResult, list[SpatialReferenceSpec], GateDecision]:
    """Async graph adapter; projection itself remains deterministic and pure."""
    return project_program(
        program,
        run_id=run_id,
        context_version=context_version,
    )


__all__ = ["project_program", "project_program_async"]
