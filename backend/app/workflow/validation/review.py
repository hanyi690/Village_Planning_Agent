"""RECONCILE review package builder - plain serializable dict.

Pure function: FinalManifest + GateDecision -> dict. No I/O.
Mirrors the validate/ground/select/execute review convention (Chinese
section headers, pydantic models dumped to JSON-safe values).
Deterministic only.
"""
from __future__ import annotations

from typing import Any

from app.contracts.delivery.reconciliation_contracts import (
    CoverageMatrixRow,
    FinalManifest,
)
from app.contracts.workflow.workflow_contracts import GateDecision

_LINK_FIELDS = (
    ("intervention_to_spec", "spec_index"),
    ("spec_to_candidate", "candidate_site_id"),
    ("candidate_to_selection", "selected_bsm"),
    ("selection_to_change", "change_bsm"),
    ("change_to_planned", "planned_parcel_bsm"),
)

_ROUTE_RATIONALE = {
    "PASS": "chain coverage complete; no blocking inconsistencies",
    "RETRY_L3": "dominant inconsistencies attributed to L3",
    "RETRY_EXECUTE": "dominant inconsistencies attributed to EXECUTE",
    "HUMAN": "ambiguous attribution; human review required",
}


def _link_present(row: CoverageMatrixRow, field: str) -> bool:
    if field == "spec_index":
        return row.spec_index is not None
    return bool(getattr(row, field))


def _build_coverage_summary(report: FinalManifest) -> dict[str, Any]:
    rows = report.coverage_matrix.rows
    by_status = {"covered": 0, "partial": 0, "missing": 0}
    for row in rows:
        by_status[row.status] += 1
    return {
        "row_count": len(rows),
        "by_status": by_status,
        "rows": [row.model_dump() for row in rows],
    }


def _build_chain_coverage(report: FinalManifest) -> dict[str, Any]:
    rows = report.coverage_matrix.rows
    links = {}
    for name, field in _LINK_FIELDS:
        covered = sum(1 for row in rows if _link_present(row, field))
        links[name] = {"covered": covered, "missing": len(rows) - covered}
    return links


def _build_inconsistency_list(report: FinalManifest) -> list[dict[str, Any]]:
    return [inc.model_dump() for inc in report.inconsistencies]


def _build_area_drift(report: FinalManifest) -> list[dict[str, Any]]:
    return [
        {
            "intervention_id": inc.intervention_id,
            "expected": inc.expected,
            "actual": inc.actual,
            "severity": inc.severity,
        }
        for inc in report.inconsistencies
        if inc.field == "area"
    ]


def _build_stage_attribution(report: FinalManifest) -> dict[str, int]:
    counts: dict[str, int] = {}
    for inc in report.inconsistencies:
        counts[inc.responsible_stage] = counts.get(inc.responsible_stage, 0) + 1
    return counts


def _build_backward_lineage(report: FinalManifest) -> list[dict[str, Any]]:
    traces = []
    for row in report.coverage_matrix.rows:
        if row.status == "missing":
            traces.append({"intervention_id": row.intervention_id, "trace": ["missing"]})
            continue
        traces.append(
            {
                "intervention_id": row.intervention_id,
                "trace": [
                    f"spec:{row.spec_index}",
                    f"candidate:{row.candidate_site_id}",
                    f"selection:{row.selected_bsm}",
                    f"change:{row.change_bsm}",
                    f"planned:{row.planned_parcel_bsm}",
                ],
            }
        )
    return traces


def _build_gate_decision(gate: GateDecision) -> dict[str, Any]:
    route = gate.feedback_route or "PASS"
    return {
        "route": route,
        "passed": gate.passed,
        "pending_requests": [pr.model_dump() for pr in gate.pending_requests],
        "rationale": _ROUTE_RATIONALE.get(route, "route undetermined"),
    }


def _build_provenance(report: FinalManifest) -> dict[str, Any]:
    if report.provenance is None:
        return {}
    return report.provenance.model_dump(mode="json")


def build_reconcile_review_package(
    report: FinalManifest, gate: GateDecision
) -> dict[str, Any]:
    """Construct the RECONCILE review package content dict (pure, no I/O)."""
    return {
        "覆盖矩阵摘要": _build_coverage_summary(report),
        "链覆盖详情": _build_chain_coverage(report),
        "不一致清单": _build_inconsistency_list(report),
        "面积偏差详情": _build_area_drift(report),
        "按阶段归因": _build_stage_attribution(report),
        "向后谱系": _build_backward_lineage(report),
        "Gate 决定": _build_gate_decision(gate),
        "来源追溯": _build_provenance(report),
    }


__all__ = ["build_reconcile_review_package"]
