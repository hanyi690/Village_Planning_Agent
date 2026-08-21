"""Deterministic projection from the authoritative planning program.

This stage is deliberately not an LLM parser.  L3 claims are already
structured and the PlanningProgram is assembled by the domain layer.  The
projection only prepares typed spatial references for GROUND and records a
fail-closed gate.
"""

from __future__ import annotations

from typing import Any

from app.contracts.domain.l3_contracts import PlanningProgram
from app.contracts.evidence.identity_contracts import (
    EvidenceObservation,
    GroundedEntityBinding,
)
from app.contracts.workflow.parse_result_contracts import (
    CompilationStatus,
    IntentCompilationResult,
)
from app.contracts.spatial.spatial_reference_contracts import SpatialReferenceSpec
from app.contracts.workflow.workflow_contracts import GateDecision

from .compile import compile_program_deterministic
from .gate import evaluate_target_projection_gate


def project_program(
    program: PlanningProgram,
    *,
    run_id: str = "",
    context_version: str = "",
    observations: list[EvidenceObservation] | None = None,
    bindings: list[GroundedEntityBinding] | None = None,
    source_features: dict[str, list[object]] | None = None,
    source_semantic_decisions: dict[str, Any] | None = None,
) -> tuple[IntentCompilationResult, list[SpatialReferenceSpec], GateDecision]:
    result, specs, diagnostics = compile_program_deterministic(
        program,
        run_id=run_id,
        context_version=context_version,
        program_ref=program.artifact_id,
        observations=observations,
        bindings=bindings,
        source_features=source_features,
        source_semantic_decisions=source_semantic_decisions,
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
    observations: list[EvidenceObservation] | None = None,
    bindings: list[GroundedEntityBinding] | None = None,
    source_features: dict[str, list[object]] | None = None,
    source_semantic_decisions: dict[str, Any] | None = None,
) -> tuple[IntentCompilationResult, list[SpatialReferenceSpec], GateDecision]:
    """Async graph adapter; projection itself remains deterministic and pure."""
    return project_program(
        program,
        run_id=run_id,
        context_version=context_version,
        observations=observations,
        bindings=bindings,
        source_features=source_features,
        source_semantic_decisions=source_semantic_decisions,
    )


__all__ = ["project_program", "project_program_async"]
