"""Project grounding output into suitability without choosing a site."""

from __future__ import annotations

from typing import Any

from app.domain.suitability.model import SuitabilityCandidate, SuitabilitySurface


def build_suitability_surface(
    grounding_result: object,
    context: Any = None,
    *,
    policy: Any = None,
    catalog: Any = None,
    cache_dir: Any = None,
) -> SuitabilitySurface:
    """Expose candidate evidence and hard feasibility as a separate model."""

    if context is not None:
        return _build_evidence_suitability_surface(
            grounding_result,
            context,
            policy=policy,
            catalog=catalog,
            cache_dir=cache_dir,
        )

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


def _build_evidence_suitability_surface(
    grounding_result: object,
    context: Any,
    *,
    policy: Any,
    catalog: Any,
    cache_dir: Any,
) -> SuitabilitySurface:
    """Build parcel-granular terrain evidence before any allocation occurs."""
    from shapely.geometry import shape

    from app.domain.suitability.policy import load_suitability_policy
    from app.domain.suitability.spatial_factors import SpatialFactorIndex
    from app.domain.suitability.terrain_adapter import TerrainCandidateFeatureAdapter

    active_policy = policy or load_suitability_policy()
    adapter = TerrainCandidateFeatureAdapter.from_context(
        context,
        active_policy,
        catalog=catalog,
        cache_dir=cache_dir,
    )
    spatial_index = SpatialFactorIndex(context, active_policy)
    parcel_by_bsm = {
        str(getattr(parcel, "bsm", "") or ""): parcel
        for parcel in list(context.current_parcels() or [])
    }
    candidates: list[SuitabilityCandidate] = []
    diagnostics: dict[str, list[str]] = {}
    for source in tuple(getattr(grounding_result, "candidates", ()) or ()):
        target_id = str(
            getattr(source, "target_ref", None)
            or getattr(source, "project_ref", None)
            or ""
        )
        source_bsms = list(getattr(source, "source_parcels", None) or [])
        if not source_bsms:
            source_bsms = [""]
        for raw_bsm in source_bsms:
            bsm = str(raw_bsm or "")
            parcel = parcel_by_bsm.get(bsm)
            parcel_wkt = ""
            if parcel is not None and getattr(parcel, "geometry", None):
                try:
                    parcel_wkt = shape(parcel.geometry).wkt
                except Exception:
                    parcel_wkt = ""
            candidate_id = f"{str(getattr(source, 'site_id', '') or '')}:{bsm or 'unbound'}"
            typed_candidate = source.model_copy(
                update={
                    "site_id": candidate_id,
                    "source_parcels": [bsm] if bsm else [],
                    "available_geometry_wkt": parcel_wkt,
                }
            )
            feature = adapter.build_candidate(typed_candidate)
            spatial = spatial_index.evaluate(parcel) if parcel is not None else None
            reasons = list(feature.blocking_codes)
            if spatial is not None:
                reasons.extend(spatial.exclusion_codes)
            if reasons:
                diagnostics.setdefault(target_id or "__unbound__", []).extend(reasons)
            terrain_score = feature.terrain.score
            score_breakdown = (
                dict(spatial.score_breakdown) if spatial is not None else {}
            )
            if terrain_score is not None:
                score_breakdown["slope_hazard"] = float(terrain_score)
            composite_values = [
                score_breakdown[key]
                for key in (
                    "slope_hazard",
                    "road_access",
                    "service_coverage",
                    "hazard_safety",
                )
                if key in score_breakdown
            ]
            composite_score = (
                sum(composite_values) / len(composite_values)
                if composite_values
                else 0.0
            )
            candidates.append(
                SuitabilityCandidate(
                    candidate_id=candidate_id,
                    target_id=target_id,
                    source_parcels=[bsm] if bsm else [],
                    score=float(composite_score),
                    score_breakdown=score_breakdown,
                    hard_feasible=feature.hard_feasible and bool(
                        spatial is not None and spatial.hard_feasible
                    ),
                    exclusion_reasons=reasons,
                    evidence_refs=list(
                        dict.fromkeys(
                            list(feature.evidence_refs)
                            + (list(spatial.evidence_refs) if spatial is not None else [])
                        )
                    ),
                    available_geometry_wkt=parcel_wkt,
                    policy_ref=feature.policy_ref,
                    feature_ref=feature.feature_id,
                    availability_diagnostics=[
                        item.model_dump(mode="json") for item in feature.availability
                    ],
                )
            )
    for issue in tuple(getattr(grounding_result, "unresolved", ()) or ()):
        target_id = str(getattr(issue, "related_artifact_id", None) or "")
        if target_id:
            diagnostics.setdefault(target_id, []).append(
                str(getattr(issue, "code", "grounding_unresolved"))
            )
    return SuitabilitySurface(
        candidates=candidates,
        target_diagnostics={
            key: list(dict.fromkeys(values)) for key, values in diagnostics.items()
        },
        provenance={
            "policy_ref": active_policy.ref,
            "policy_digest": active_policy.digest,
            "evidence_availability": adapter.availability.model_dump(mode="json"),
        },
    )


__all__ = ["build_suitability_surface"]
