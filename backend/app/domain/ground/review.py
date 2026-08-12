"""GROUND review package builder - plain serializable dict.

Pure function: GroundingResult + GateDecision + specs -> dict. No I/O.
Mirrors the parse review convention (module="ground"): returns a plain dict
with Chinese section headers, JSON-serializable (pydantic models dumped).
"""
from __future__ import annotations

from typing import Any

from app.contracts.spatial.grounding_contracts import GroundingResult
from app.contracts.spatial.spatial_reference_contracts import SpatialReferenceSpec
from app.contracts.workflow.workflow_contracts import GateDecision

_ROUTE_RATIONALE = {
    "EXPLORE": "unresolved specs remain or no candidates resolved; request exploration",
    "HUMAN": "ambiguous candidates require human review",
    "PASS": "all specs resolved, candidates non-empty, no ambiguity",
}


def _build_input_spec_summary(specs: list[SpatialReferenceSpec]) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    for spec in specs:
        by_type[spec.type] = by_type.get(spec.type, 0) + 1
    return {
        "total": len(specs),
        "by_type": by_type,
        "specs": [spec.model_dump() for spec in specs],
    }


def _build_resolved_candidates(result: GroundingResult) -> list[dict[str, Any]]:
    return [
        {
            "site_id": c.site_id,
            "source_parcels_count": len(c.source_parcels),
            "source_parcels": list(c.source_parcels),
        }
        for c in result.candidates
    ]


def _build_unresolved_reasons(result: GroundingResult) -> list[dict[str, Any]]:
    return [
        {
            "stage": issue.stage,
            "severity": issue.severity,
            "code": issue.code,
            "message": issue.message,
            "detail": issue.detail,
        }
        for issue in result.unresolved
    ]


def _build_query_evidence(result: GroundingResult) -> list[dict[str, Any]]:
    return [
        {
            "query_type": e.query_type,
            "result_count": e.result_count,
            "result_refs": list(e.result_refs),
        }
        for e in result.spatial_query_evidence
    ]


def _build_constraint_coverage(result: GroundingResult) -> dict[str, Any]:
    checked = [c for c in result.candidates if c.hard_constraint_result is not None]
    if not checked:
        return {
            "note": "no constraint check performed",
            "total_candidates": len(result.candidates),
        }
    return {
        "checked": len(checked),
        "passed": sum(1 for c in checked if c.hard_constraint_result.passed),
        "failed": sum(1 for c in checked if not c.hard_constraint_result.passed),
        "total_candidates": len(result.candidates),
    }


def _build_gate_decision(gate: GateDecision) -> dict[str, Any]:
    route = gate.feedback_route or "PASS"
    return {
        "route": route,
        "passed": gate.passed,
        "pending_requests": [r.model_dump() for r in gate.pending_requests],
        "rationale": _ROUTE_RATIONALE.get(route, "route undetermined"),
    }


def _build_provenance(result: GroundingResult) -> dict[str, Any]:
    prov = result.provenance
    if prov is None:
        return {"source": "", "run_id": ""}
    return prov.model_dump(mode="json")


def _build_spec_candidate_mapping(
    result: GroundingResult, specs: list[SpatialReferenceSpec]
) -> dict[str, Any]:
    """Correlate each input spec to the candidate that resolved it.

    ground_aggregate does not emit a per-spec candidate linkage, so this is a
    deterministic index-based heuristic: spec i is paired with candidates[i]
    for i < len(candidates) (candidates are produced in resolved-spec order),
    and any spec index beyond the candidate list is marked unresolved.
    """
    mapping: list[dict[str, Any]] = []
    for index, spec in enumerate(specs):
        if index < len(result.candidates):
            candidate = result.candidates[index]
            mapping.append(
                {
                    "spec_index": index,
                    "spec_type": spec.type,
                    "site_id": candidate.site_id,
                    "status": "resolved",
                }
            )
        else:
            mapping.append(
                {
                    "spec_index": index,
                    "spec_type": spec.type,
                    "site_id": None,
                    "status": "unresolved",
                }
            )
    return {"mapping": mapping}


def build_ground_review_package(
    result: GroundingResult,
    gate: GateDecision,
    specs: list[SpatialReferenceSpec],
) -> dict[str, Any]:
    """Construct the GROUND review package content dict (pure, no I/O)."""
    return {
        "输入规格摘要": _build_input_spec_summary(specs),
        "已解析候选": _build_resolved_candidates(result),
        "未解析原因": _build_unresolved_reasons(result),
        "空间查询证据": _build_query_evidence(result),
        "约束覆盖": _build_constraint_coverage(result),
        "Gate 决定": _build_gate_decision(gate),
        "来源追溯": _build_provenance(result),
        "规格-候选映射": _build_spec_candidate_mapping(result, specs),
    }


__all__ = ["build_ground_review_package"]
