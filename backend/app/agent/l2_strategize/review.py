"""L2 review package builder - ReviewPackage content.

Roadmap Wave D review package content: 目标-问题-策略-证据矩阵、策略冲突.
Writes are delegated to services.review_package; this module constructs the
in-memory ReviewPackage.
"""
from __future__ import annotations

from typing import Any

from app.modules.ports.artifact_store import ArtifactRef
from app.modules.schema.contracts.l2_contracts import L2Strategy
from app.modules.schema.contracts.review_contracts import (
    ArtifactRefLite,
    ReviewPackage,
    ReviewStatus,
)
from app.modules.schema.contracts.workflow_contracts import GateDecision


def build_summary_md(strategy: L2Strategy, gate_decision: GateDecision) -> str:
    lines: list[str] = [f"# L2 STRATEGIZE 审查包 (artifact={strategy.artifact_id})", ""]
    lines.append(f"**Gate:** {'PASS' if gate_decision.passed else gate_decision.feedback_route or 'BLOCK'}")
    if gate_decision.evidence_requests:
        lines.append(f"**Evidence requests:** {', '.join(gate_decision.evidence_requests)}")
    lines.append("")

    lines.append("## 发展目标")
    for g in strategy.development_goals:
        lines.append(f"- {g}")
    if not strategy.development_goals:
        lines.append("- (无)")
    lines.append("")

    lines.append("## 空间结构")
    lines.append(f"- {strategy.spatial_structure}" if strategy.spatial_structure else "- (无)")
    lines.append("")

    lines.append("## 实施优先级")
    for p in strategy.implementation_priorities:
        lines.append(f"- {p}")
    if not strategy.implementation_priorities:
        lines.append("- (无)")
    lines.append("")

    lines.append("## 策略冲突")
    for c in strategy.strategy_conflicts:
        lines.append(f"- [{c.severity}] {c.description} (between: {', '.join(c.between) or '无'})")
    if not strategy.strategy_conflicts:
        lines.append("- (无)")
    lines.append("")

    lines.append("## 策略问题")
    for i in strategy.strategy_issues:
        lines.append(f"- [{i.severity}] {i.code}: {i.message}")
    if not strategy.strategy_issues:
        lines.append("- (无)")
    lines.append("")

    lines.append("## 证据缺口")
    for g in strategy.evidence_gaps:
        lines.append(f"- [{g.gap_id}] ({g.dimension}) {g.description}")
    if not strategy.evidence_gaps:
        lines.append("- (无)")
    lines.append("")

    lines.append("## 证据来源")
    for s in strategy.sources:
        lines.append(f"- {s.source_type}: {s.reference} (confidence={s.confidence})")
    if not strategy.sources:
        lines.append("- (无来源 - 需 EXPLORE 补齐)")
    lines.append("")

    return "\n".join(lines)


def build_trace_json(
    strategy: L2Strategy,
    dimension_reports_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "artifact_id": strategy.artifact_id,
        "context_version": strategy.context_version,
        "dimension_provenance": [
            {"source": p.source, "run_id": p.run_id, "module": p.module, "trace": p.trace}
            for p in strategy.dimension_provenance
        ],
        "dimension_reports": dimension_reports_meta or {},
        "extraction_steps": [
            "compile_l2_strategy (per dimension)",
            "merge_strategy_fragments",
            "evaluate_l2_gate",
        ],
    }


def build_preview_geojson(strategy: L2Strategy) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [],
        "properties": {
            "note": "L2 STRATEGIZE produces no spatial geometry; preview empty until GROUND/SELECT.",
            "artifact_id": strategy.artifact_id,
        },
    }


def build_l2_review_package(
    strategy: L2Strategy,
    artifact_ref: ArtifactRef,
    gate_decision: GateDecision,
    run_id: str,
) -> ReviewPackage:
    return ReviewPackage(
        run_id=run_id,
        module="l2_strategize",
        summary_md=build_summary_md(strategy, gate_decision),
        artifact_ref=ArtifactRefLite(
            artifact_id=artifact_ref.artifact_id,
            module=artifact_ref.module,
            run_id=artifact_ref.run_id,
            artifact_type=artifact_ref.artifact_type,
            revision=artifact_ref.revision,
        ),
        trace_json=build_trace_json(strategy),
        preview_geojson=build_preview_geojson(strategy),
        status=ReviewStatus.AWAITING_REVIEW,
    )


__all__ = [
    "build_l2_review_package",
    "build_summary_md",
    "build_trace_json",
    "build_preview_geojson",
]
