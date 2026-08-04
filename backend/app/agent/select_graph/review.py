"""SELECT review package builder - plain serializable dict.

Pure function: SiteSelectionDecision + briefs + GateDecision + GroundingResult
-> dict. No I/O. Mirrors the ground review convention (Chinese section headers,
pydantic models dumped to JSON-safe values).
"""
from __future__ import annotations

from typing import Any

from app.agent.select_graph.gate import select_gate_route
from app.modules.schema.contracts.grounding_contracts import GroundingResult
from app.modules.schema.contracts.selection_contracts import (
    LandDesignBrief,
    SiteSelectionDecision,
)
from app.modules.schema.contracts.workflow_contracts import GateDecision

_ROUTE_RATIONALE = {
    "PASS": "all targets placed with acceptable confidence",
    "RETRY_GROUND": "not all targets placed; re-run ground for more candidates",
    "HUMAN": "placed targets below confidence threshold; human review required",
}


def _build_input_candidate_summary(result: GroundingResult) -> dict[str, Any]:
    return {
        "candidate_site_count": len(result.candidates),
        "source_parcels_total": sum(len(c.source_parcels) for c in result.candidates),
        "sites": [
            {
                "site_id": c.site_id,
                "source_parcels_count": len(c.source_parcels),
            }
            for c in result.candidates
        ],
    }


def _build_full_ranking(decision: SiteSelectionDecision) -> list[dict[str, Any]]:
    return [r.model_dump() for r in decision.full_ranking]


def _build_eliminated(decision: SiteSelectionDecision) -> list[dict[str, Any]]:
    return [e.model_dump() for e in decision.eliminated]


def _build_final_combination(
    decision: SiteSelectionDecision, briefs: list[LandDesignBrief]
) -> dict[str, Any]:
    return {
        "selected_combination": decision.selected_combination,
        "briefs": [b.model_dump() for b in briefs],
    }


def _build_gate_decision(
    decision: SiteSelectionDecision, gate: GateDecision
) -> dict[str, Any]:
    target_count = decision.decision_factors.get("target_count")
    if gate.feedback_route:
        route = gate.feedback_route
    elif target_count is not None:
        route = select_gate_route(decision, target_count=target_count)
    else:
        route = "PASS"
    return {
        "route": route,
        "passed": gate.passed,
        "feedback_route": gate.feedback_route,
        "pending_requests": [pr.model_dump() for pr in gate.pending_requests],
        "rationale": _ROUTE_RATIONALE.get(route, "route undetermined"),
    }


def _build_provenance(decision: SiteSelectionDecision) -> dict[str, Any]:
    if decision.provenance is None:
        return {}
    return decision.provenance.model_dump(mode="json")


def build_preview_geojson(
    decision: SiteSelectionDecision, parcel_by_bsm: dict[str, dict] | None
) -> dict[str, Any]:
    """Build a GeoJSON FeatureCollection of the selected parcels for map preview."""
    properties = {
        "note": "SELECT map preview: selected parcels",
        "artifact_id": decision.artifact_id,
    }
    if not parcel_by_bsm:
        return {"type": "FeatureCollection", "features": [], "properties": properties}
    ranked_by_bsm = {r.candidate_id: r for r in decision.full_ranking}
    features = []
    for bsm in decision.selected_combination:
        parcel = parcel_by_bsm.get(bsm)
        if parcel is None:
            continue
        ranked = ranked_by_bsm.get(bsm)
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "source_bsm": bsm,
                    "rank": ranked.rank if ranked else None,
                    "score": ranked.score if ranked else 0.0,
                },
                "geometry": parcel.get("geometry"),
            }
        )
    return {"type": "FeatureCollection", "features": features, "properties": properties}


def build_select_review_package(
    decision: SiteSelectionDecision,
    briefs: list[LandDesignBrief],
    gate: GateDecision,
    result: GroundingResult,
    parcel_by_bsm: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """Construct the SELECT review package content dict (pure, no I/O)."""
    return {
        "输入候选摘要": _build_input_candidate_summary(result),
        "完整排名": _build_full_ranking(decision),
        "淘汰理由": _build_eliminated(decision),
        "最终组合": _build_final_combination(decision, briefs),
        "决策因子": decision.decision_factors,
        "Gate 决定": _build_gate_decision(decision, gate),
        "来源追溯": _build_provenance(decision),
        "地图预览": build_preview_geojson(decision, parcel_by_bsm),
    }


__all__ = ["build_select_review_package", "build_preview_geojson"]
