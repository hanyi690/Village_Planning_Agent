"""Project grounding output into suitability without choosing a site."""

from __future__ import annotations

from app.domain.suitability.model import SuitabilityCandidate, SuitabilitySurface


def build_suitability_surface(grounding_result: object) -> SuitabilitySurface:
    """Expose candidate evidence and hard feasibility as a separate model."""

    candidates: list[SuitabilityCandidate] = []
    diagnostics: dict[str, list[str]] = {}
    for candidate in tuple(getattr(grounding_result, "candidates", ()) or ()):
        target_id = str(getattr(candidate, "target_ref", None) or getattr(candidate, "project_ref", None) or "")
        hard = getattr(candidate, "hard_constraint_result", None)
        hard_feasible = bool(getattr(hard, "passed", False)) if hard is not None else False
        reasons: list[str] = []
        if not target_id:
            reasons.append("candidate_not_target_bound")
        if not hard_feasible:
            reasons.append("hard_constraints_not_proven")
        if not getattr(candidate, "source_parcels", None):
            reasons.append("no_source_parcel")
        if reasons:
            diagnostics.setdefault(target_id or "__unbound__", []).extend(reasons)
        candidates.append(
            SuitabilityCandidate(
                candidate_id=str(candidate.site_id),
                target_id=target_id,
                source_parcels=list(candidate.source_parcels),
                score=float((candidate.metrics or {}).get("confidence", 0.0)),
                hard_feasible=hard_feasible and not reasons,
                exclusion_reasons=reasons,
                evidence_refs=list(candidate.evidence_refs),
                available_geometry_wkt=str(getattr(candidate, "available_geometry_wkt", "") or ""),
            )
        )
    for issue in tuple(getattr(grounding_result, "unresolved", ()) or ()):
        target_id = str(getattr(issue, "related_artifact_id", None) or "")
        if target_id:
            diagnostics.setdefault(target_id, []).append(str(getattr(issue, "code", "grounding_unresolved")))
    return SuitabilitySurface(candidates=candidates, target_diagnostics=diagnostics)


__all__ = ["build_suitability_surface"]
