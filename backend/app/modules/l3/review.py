"""L3 review package builder - ReviewPackage content.

Wave E roadmap review package content: 项目表、土地需求表、项目依赖图、遗漏项.
Writes are delegated to services.review_package; this module constructs the
in-memory ReviewPackage.
"""
from __future__ import annotations

from typing import Any

from app.contracts.artifacts.ref import ArtifactRef as ArtifactDescriptor
from app.contracts.l3.l3_contracts import PlanningProgram
from app.contracts.workflow.review_contracts import (
    ArtifactDescriptorProjection,
    ReviewPackage,
    ReviewStatus,
)
from app.contracts.workflow.workflow_contracts import GateDecision


def build_summary_md(program: PlanningProgram, gate_decision: GateDecision) -> str:
    lines: list[str] = [f"# L3 PLAN 审查包 (artifact={program.artifact_id})", ""]
    lines.append(f"**Gate:** {'PASS' if gate_decision.passed else gate_decision.feedback_route or 'BLOCK'}")
    if gate_decision.evidence_requests:
        lines.append(f"**Evidence requests:** {', '.join(gate_decision.evidence_requests)}")
    lines.append("")

    lines.append("## 干预项目")
    for i in program.interventions:
        lines.append(f"- {i.intervention_id}: {i.name} ({i.category}, {i.scale})")
    if not program.interventions:
        lines.append("- (无)")
    lines.append("")

    lines.append("## 项目依赖")
    for d in program.dependencies:
        lines.append(f"- {d.from_intervention_id} -> {d.to_intervention_id}")
    if not program.dependencies:
        lines.append("- (无)")
    lines.append("")

    lines.append("## 遗漏项")
    for o in program.omissions:
        lines.append(f"- {o}")
    if not program.omissions:
        lines.append("- (无)")
    lines.append("")

    lines.append("## 程序问题")
    for i in program.program_issues:
        lines.append(f"- [{i.severity}] {i.code}: {i.message}")
    if not program.program_issues:
        lines.append("- (无)")
    lines.append("")

    lines.append("## 证据缺口")
    for g in program.evidence_gaps:
        lines.append(f"- [{g.gap_id}] ({g.dimension}) {g.description}")
    if not program.evidence_gaps:
        lines.append("- (无)")
    lines.append("")

    lines.append("## 证据来源")
    for s in program.sources:
        lines.append(f"- {s.source_type}: {s.reference} (confidence={s.confidence})")
    if not program.sources:
        lines.append("- (无来源 - 需 EXPLORE 补齐)")
    lines.append("")

    return "\n".join(lines)


def build_trace_json(
    program: PlanningProgram,
    dimension_reports_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "artifact_id": program.artifact_id,
        "context_version": program.context_version,
        "dimension_provenance": [
            {"source": p.source, "run_id": p.run_id, "module": p.module, "trace": p.trace}
            for p in program.dimension_provenance
        ],
        "dimension_reports": dimension_reports_meta or {},
        "extraction_steps": [
            "PlanningClaimSet (per dimension)",
            "merge_l3_fragments",
            "evaluate_l3_gate",
        ],
    }


def build_preview_geojson(program: PlanningProgram) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [],
        "properties": {
            "note": "L3 PLAN produces no spatial geometry; preview empty until GROUND/SELECT.",
            "artifact_id": program.artifact_id,
        },
    }


def build_l3_review_package(
    program: PlanningProgram,
    artifact_ref: ArtifactDescriptor,
    gate_decision: GateDecision,
    run_id: str,
) -> ReviewPackage:
    return ReviewPackage(
        run_id=run_id,
        module="l3_plan",
        summary_md=build_summary_md(program, gate_decision),
        artifact_ref=ArtifactDescriptorProjection.model_validate(artifact_ref.model_dump()),
        trace_json=build_trace_json(program),
        preview_geojson=build_preview_geojson(program),
        status=ReviewStatus.AWAITING_REVIEW,
    )


__all__ = [
    "build_l3_review_package",
    "build_summary_md",
]
