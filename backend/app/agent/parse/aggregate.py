"""Top-level PARSE aggregate - orchestration + public API.

Wave F: COMPILE mode is fully deterministic. REPAIR/REVISE modes are
structurally wired (route + gate + revision profile) but the LLM patch path
is uninvoked - ambiguous/low-confidence results route to NEEDS_REVIEW.
"""
from __future__ import annotations

from typing import Any

from app.modules.ports.artifact_store import ArtifactRef
from app.modules.schema.contracts.l3_contracts import PlanningProgram
from app.modules.schema.contracts.parse_result_contracts import (
    CompilationPatch,
    CompilationStatus,
    IntentCompilationResult,
    ParseMode,
    ParseRevisionRequest,
)
from app.modules.schema.contracts.review_contracts import (
    ArtifactRefLite,
    ReviewPackage,
    ReviewStatus,
)
from app.modules.schema.contracts.spatial_reference_contracts import SpatialReferenceSpec
from app.modules.schema.contracts.workflow_contracts import GateDecision
from app.services.artifact_store import FilesystemArtifactStore
from app.services.review_package import write_review_package
from app.utils.logger import get_logger

from .compile_node import compile_program_deterministic
from .gate_node import evaluate_parse_gate
from .llm_patch import generate_llm_patches
from .merge_node import apply_patches
from .review import build_parse_review_package
from .route_node import route_compilation

logger = get_logger(__name__)


def _coerce_specs(
    raw: list[Any],
) -> list[SpatialReferenceSpec]:
    """Coerce spatial_reference_specs entries to SpatialReferenceSpec objects."""
    specs: list[SpatialReferenceSpec] = []
    for entry in raw:
        if isinstance(entry, SpatialReferenceSpec):
            specs.append(entry)
        elif isinstance(entry, dict):
            specs.append(SpatialReferenceSpec(**entry))
    return specs


def compile_program(
    program: PlanningProgram,
    *,
    run_id: str = "",
    context_version: str = "",
    mode: ParseMode = ParseMode.COMPILE,
    revision_request: ParseRevisionRequest | None = None,
    base_result: IntentCompilationResult | None = None,
    patches: list[CompilationPatch] | None = None,
) -> tuple[IntentCompilationResult, list[SpatialReferenceSpec], GateDecision]:
    """Run the top-level PARSE pipeline: compile -> route -> gate.

    COMPILE mode is deterministic (no LLM). REPAIR/REVISE modes start from
    ``base_result`` (or a fresh deterministic compile) and apply deterministic
    patches; the LLM patch route stays uninvoked in Wave F so ambiguous results
    route to NEEDS_REVIEW.
    """
    if mode == ParseMode.COMPILE:
        result, specs, diags = compile_program_deterministic(
            program,
            run_id=run_id,
            context_version=context_version,
            program_ref=program.artifact_id,
        )
        specs = _coerce_specs(result.spatial_reference_specs)
    else:
        if base_result is not None:
            base = base_result
        else:
            base, _, _ = compile_program_deterministic(
                program,
                run_id=run_id,
                context_version=context_version,
                program_ref=program.artifact_id,
            )
        result = apply_patches(base, patches or [], run_id=run_id)
        specs = _coerce_specs(result.spatial_reference_specs)
        diags = result.diagnostics

    route = route_compilation(result, diags)
    if route in ("llm_patch", "human_review"):
        result.compilation_status = CompilationStatus.NEEDS_REVIEW

    gate_decision = evaluate_parse_gate(
        result, run_id=run_id, context_version=context_version
    )

    if gate_decision.passed and result.compilation_status == CompilationStatus.DRAFT:
        result.compilation_status = CompilationStatus.VALIDATED

    if not result.context_version:
        result.context_version = context_version

    return result, specs, gate_decision


async def compile_program_async(
    program: PlanningProgram,
    *,
    run_id: str = "",
    context_version: str = "",
    mode: ParseMode = ParseMode.COMPILE,
    revision_request: ParseRevisionRequest | None = None,
    base_result: IntentCompilationResult | None = None,
    patches: list[CompilationPatch] | None = None,
) -> tuple[IntentCompilationResult, list[SpatialReferenceSpec], GateDecision]:
    """Async top-level PARSE pipeline with the LLM patch route activated.

    Mirrors ``compile_program`` but when routing decides ``llm_patch`` the LLM
    patch path is actually invoked: generate -> apply -> re-route. Only
    ``human_review`` (or a failed/empty LLM patch attempt) routes to
    NEEDS_REVIEW. ``compile_program`` (sync) is kept unchanged for callers
    that cannot await.
    """
    if mode == ParseMode.COMPILE:
        result, specs, diags = compile_program_deterministic(
            program,
            run_id=run_id,
            context_version=context_version,
            program_ref=program.artifact_id,
        )
        specs = _coerce_specs(result.spatial_reference_specs)
    else:
        if base_result is not None:
            base = base_result
        else:
            base, _, _ = compile_program_deterministic(
                program,
                run_id=run_id,
                context_version=context_version,
                program_ref=program.artifact_id,
            )
        result = apply_patches(base, patches or [], run_id=run_id)
        specs = _coerce_specs(result.spatial_reference_specs)
        diags = result.diagnostics

    route = route_compilation(result, diags)
    if route == "llm_patch":
        generated = await generate_llm_patches(result, diags, program)
        if generated:
            result = apply_patches(result, generated, run_id=run_id)
            specs = _coerce_specs(result.spatial_reference_specs)
            diags = result.diagnostics
            route = route_compilation(result, diags)
        else:
            route = "human_review"
    if route == "human_review":
        result.compilation_status = CompilationStatus.NEEDS_REVIEW

    gate_decision = evaluate_parse_gate(
        result, run_id=run_id, context_version=context_version
    )

    if gate_decision.passed and result.compilation_status == CompilationStatus.DRAFT:
        result.compilation_status = CompilationStatus.VALIDATED

    if not result.context_version:
        result.context_version = context_version

    return result, specs, gate_decision


def _load_program(state: dict[str, Any], base_dir: str) -> PlanningProgram:
    """Resolve the PlanningProgram from state (object, or artifact via store)."""
    program = state.get("planning_program")
    if isinstance(program, PlanningProgram):
        return program

    ref_data = state.get("l3_program_ref")
    if isinstance(ref_data, dict):
        store = FilesystemArtifactStore(base_dir=base_dir)
        ref = ArtifactRef(**ref_data)
        payload = store.retrieve(ref)
        return PlanningProgram(**payload)

    if program is not None:
        return PlanningProgram(**program)

    logger.warning("[parse_aggregate] no planning_program found in state")
    return PlanningProgram()


def _content_to_review_package(
    content: dict[str, Any],
    artifact_ref: ArtifactRef,
    run_id: str,
) -> ReviewPackage:
    """Wrap the parse review content dict into a persisted ReviewPackage."""
    meta = content["metadata"]
    summary_lines = [
        f"# PARSE 审查包 (artifact={meta['artifact_id']})",
        "",
        f"**状态:** {meta['compilation_status']}",
    ]
    summary = content.get("编译摘要", {})
    summary_lines.append(
        f"**模式:** {summary.get('mode', '')} | "
        f"**干预数:** {summary.get('intervention_count', 0)} | "
        f"**spec 数:** {summary.get('spec_count', 0)}"
    )
    summary_lines.append("")
    summary_lines.append("## 编译诊断")
    for diag in content.get("编译诊断", []):
        summary_lines.append(
            f"- [{diag.get('severity', '')}] {diag.get('code', '')}: "
            f"{diag.get('message', '')}"
        )
    if not content.get("编译诊断"):
        summary_lines.append("- (无)")
    summary_lines.append("")
    summary_lines.append("## Gate 决定")
    gate = content.get("Gate 决定", {})
    summary_lines.append(
        f"**passed:** {gate.get('passed')} | "
        f"**feedback_route:** {gate.get('feedback_route')}"
    )

    return ReviewPackage(
        run_id=run_id,
        module="parse",
        summary_md="\n".join(summary_lines),
        artifact_ref=ArtifactRefLite(
            artifact_id=artifact_ref.artifact_id,
            module=artifact_ref.module,
            run_id=artifact_ref.run_id,
            artifact_type=artifact_ref.artifact_type,
            revision=artifact_ref.revision,
        ),
        trace_json=content.get("profile trace", {}),
        status=ReviewStatus.AWAITING_REVIEW,
    )


async def parse_aggregate(
    state: dict[str, Any],
    *,
    base_dir: str = ".run-tmp",
) -> dict[str, Any]:
    """PARSE state-graph node: compile -> persist artifact -> review package."""
    run_id = state.get("run_id", state.get("session_id", ""))
    context_version = state.get("context_version", "")

    program = _load_program(state, base_dir)

    mode_raw = state.get("parse_mode", "compile")
    mode = ParseMode(mode_raw) if not isinstance(mode_raw, ParseMode) else mode_raw

    result, specs, gate_decision = await compile_program_async(
        program,
        run_id=run_id,
        context_version=context_version,
        mode=mode,
    )

    artifact_id = f"parse-{run_id}-v1"
    result.artifact_id = artifact_id

    artifact_store = FilesystemArtifactStore(base_dir=base_dir)
    ref = ArtifactRef(
        context_version=context_version,
        artifact_id=artifact_id,
        module="parse",
        run_id=run_id,
        artifact_type="IntentCompilationResult",
        revision="v1",
    )
    artifact_store.store(ref, result.model_dump(mode="json"))
    logger.info("[parse_aggregate] IntentCompilationResult stored: %s", ref)

    content = build_parse_review_package(
        result=result,
        specs=specs,
        gate_decision=gate_decision,
        artifact_ref=ref,
        run_id=run_id,
    )
    review_pkg = _content_to_review_package(content, ref, run_id)
    review_id = write_review_package(review_pkg, base_dir=base_dir)
    logger.info("[parse_aggregate] review package written: review_id=%s", review_id)

    return {
        "parse_result_ref": {
            "artifact_id": artifact_id,
            "module": "parse",
            "run_id": run_id,
            "artifact_type": "IntentCompilationResult",
            "revision": "v1",
            "context_version": context_version,
        },
        "parse_gate_decision": gate_decision.model_dump(mode="json"),
        "parse_review_id": review_id,
    }


__all__ = ["compile_program", "compile_program_async", "parse_aggregate"]
