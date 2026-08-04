"""L1 review package builder - ReviewPackage content with 5 required sections.

Roadmap Wave B review package content: 事实、证据、约束、问题、证据缺口.
Writes are delegated to services.review_package; this module constructs the
in-memory ReviewPackage.
"""
from __future__ import annotations

from typing import Any

from app.modules.ports.artifact_store import ArtifactRef
from app.modules.schema.contracts.l1_contracts import L1Snapshot
from app.modules.schema.contracts.review_contracts import (
    ArtifactRefLite,
    ReviewPackage,
    ReviewStatus,
)
from app.modules.schema.contracts.workflow_contracts import GateDecision


def build_summary_md(snapshot: L1Snapshot, gate_decision: GateDecision) -> str:
    lines: list[str] = [f"# L1 OBSERVE 审查包 (artifact={snapshot.artifact_id})", ""]
    lines.append(f"**Gate:** {'PASS' if gate_decision.passed else gate_decision.feedback_route or 'BLOCK'}")
    if gate_decision.evidence_requests:
        lines.append(f"**Evidence requests:** {', '.join(gate_decision.evidence_requests)}")
    lines.append("")

    lines.append("## 事实")
    for f in snapshot.facts:
        lines.append(f"- {f}")
    if not snapshot.facts:
        lines.append("- (无)")
    lines.append("")

    lines.append("## 证据")
    for s in snapshot.sources:
        lines.append(f"- {s.source_type}: {s.reference} (confidence={s.confidence})")
    if not snapshot.sources:
        lines.append("- (无来源 - 需 EXPLORE 补齐)")
    lines.append("")

    lines.append("## 约束")
    for c in snapshot.constraints:
        lines.append(f"- {c}")
    if not snapshot.constraints:
        lines.append("- (无)")
    lines.append("")

    lines.append("## 问题")
    for i in snapshot.issues:
        lines.append(f"- [{i.severity}] {i.code}: {i.message}")
    if not snapshot.issues:
        lines.append("- (无)")
    lines.append("")

    lines.append("## 证据缺口")
    for g in snapshot.evidence_gaps:
        lines.append(f"- [{g.gap_id}] ({g.dimension}) {g.description}")
    if not snapshot.evidence_gaps:
        lines.append("- (无)")
    lines.append("")

    if snapshot.classification_refs:
        lines.append("## 现状分类（事实）")
        for r in snapshot.classification_refs:
            lines.append(f"- {r.system}/{r.code} {r.canonical_name} (source={r.source})")
        lines.append("")

    return "\n".join(lines)


def build_trace_json(
    snapshot: L1Snapshot,
    dimension_reports_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "artifact_id": snapshot.artifact_id,
        "context_version": snapshot.context_version,
        "dimension_provenance": [
            {"source": p.source, "run_id": p.run_id, "module": p.module, "trace": p.trace}
            for p in snapshot.dimension_provenance
        ],
        "dimension_reports": dimension_reports_meta or {},
        "extraction_steps": [
            "compile_l1_observation (per dimension)",
            "merge_fragments",
            "evaluate_l1_gate",
        ],
    }


def build_preview_geojson(snapshot: L1Snapshot) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [],
        "properties": {
            "note": "L1 OBSERVE produces no spatial geometry; preview empty until GROUND/SELECT.",
            "artifact_id": snapshot.artifact_id,
        },
    }


def build_l1_review_package(
    snapshot: L1Snapshot,
    artifact_ref: ArtifactRef,
    gate_decision: GateDecision,
    run_id: str,
) -> ReviewPackage:
    return ReviewPackage(
        run_id=run_id,
        module="l1_observe",
        summary_md=build_summary_md(snapshot, gate_decision),
        artifact_ref=ArtifactRefLite(
            artifact_id=artifact_ref.artifact_id,
            module=artifact_ref.module,
            run_id=artifact_ref.run_id,
            artifact_type=artifact_ref.artifact_type,
            revision=artifact_ref.revision,
        ),
        trace_json=build_trace_json(snapshot),
        preview_geojson=build_preview_geojson(snapshot),
        status=ReviewStatus.AWAITING_REVIEW,
    )


__all__ = [
    "build_l1_review_package",
    "build_summary_md",
    "build_trace_json",
    "build_preview_geojson",
]
