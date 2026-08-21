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
    plan_intent: Any = None,
) -> SuitabilitySurface:
    """Expose candidate evidence and hard feasibility as a separate model."""

    if context is not None:
        return _build_evidence_suitability_surface(
            grounding_result,
            context,
            policy=policy,
            catalog=catalog,
            cache_dir=cache_dir,
            plan_intent=plan_intent,
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
    plan_intent: Any,
) -> SuitabilitySurface:
    """Build parcel-granular terrain evidence before any allocation occurs."""
    from shapely.geometry import shape

    from app.domain.suitability.policy import load_suitability_policy
    from app.domain.suitability.spatial_factors import SpatialFactorIndex
    from app.domain.suitability.terrain_adapter import TerrainCandidateFeatureAdapter
    from app.domain.suitability.subgeometry import derive_planning_subgeometry

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
    target_by_id = _target_by_id(plan_intent)
    workspace = getattr(context, "workspace", None)
    metadata = getattr(workspace, "metadata", None)
    geometry_crs = str(
        getattr(metadata, "crs", "")
        or getattr(context, "geometry_crs", "")
        or "EPSG:4326"
    )
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
            parcel_area_ha = 0.0
            if parcel is not None and getattr(parcel, "geometry", None):
                try:
                    parcel_wkt = shape(parcel.geometry).wkt
                except Exception:
                    parcel_wkt = ""
            if parcel is not None:
                parcel_area_ha = float(
                    getattr(parcel, "area_sqm", 0.0) or 0.0
                ) / 10000.0
            target_area_ha = _target_area_ha(target_by_id.get(target_id))
            clip_result = None
            if parcel_wkt and _can_clip_target(target_by_id.get(target_id)):
                clip_result = derive_planning_subgeometry(
                    parcel_wkt,
                    source_crs=geometry_crs,
                    target_area_ha=target_area_ha,
                    tolerance_pct=5.0,
                )
            candidate_wkt = (
                clip_result.geometry_wkt
                if clip_result is not None and clip_result.geometry_wkt
                else parcel_wkt
            )
            available_area_ha = (
                float(clip_result.planning_area_ha)
                if clip_result is not None and clip_result.geometry_wkt
                else parcel_area_ha
            )
            source_area_ha = (
                parcel_area_ha
                if parcel_area_ha > 0
                else float(clip_result.source_area_ha) if clip_result is not None else 0.0
            )
            raw_coverage_ratio = (
                available_area_ha / source_area_ha
                if source_area_ha > 0 and available_area_ha >= 0
                else None
            )
            geometry_operation = (
                clip_result.operation if clip_result is not None else "bundle_extent"
            )
            geometry_diagnostics = list(clip_result.diagnostics) if clip_result is not None else []
            coverage_ratio = raw_coverage_ratio
            if raw_coverage_ratio is not None and raw_coverage_ratio > 1.0:
                coverage_ratio = 1.0
                geometry_diagnostics.append("coverage_ratio_clamped_to_source_extent")
            candidate_id = f"{str(getattr(source, 'site_id', '') or '')}:{bsm or 'unbound'}"
            typed_candidate = source.model_copy(
                update={
                    "site_id": candidate_id,
                    "source_parcels": [bsm] if bsm else [],
                    "available_geometry_wkt": candidate_wkt,
                }
            )
            feature = adapter.build_candidate(typed_candidate)
            spatial = (
                spatial_index.evaluate(parcel, geometry=candidate_wkt)
                if parcel is not None
                else None
            )
            reasons = list(feature.blocking_codes)
            if spatial is not None:
                reasons.extend(spatial.exclusion_codes)
            if "planning_area_insufficient" in geometry_diagnostics:
                reasons.append("planning_area_insufficient")
            if "subdivision_failed" in geometry_diagnostics:
                reasons.append("planning_subdivision_failed")
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
                    ) and not any(
                        item in {"planning_area_insufficient", "planning_subdivision_failed"}
                        for item in reasons
                    ),
                    exclusion_reasons=reasons,
                    evidence_refs=list(
                        dict.fromkeys(
                            list(feature.evidence_refs)
                            + (list(spatial.evidence_refs) if spatial is not None else [])
                        )
                    ),
                    available_geometry_wkt=candidate_wkt,
                    available_area_ha=available_area_ha,
                    source_area_ha=source_area_ha,
                    coverage_ratio=coverage_ratio,
                    geometry_operation=geometry_operation,
                    geometry_crs=geometry_crs,
                    geometry_diagnostics=geometry_diagnostics,
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


def _target_by_id(plan_intent: Any) -> dict[str, Any]:
    if plan_intent is None:
        return {}
    result: dict[str, Any] = {}
    for field_name in ("site_area_targets", "zone_targets"):
        for target in list(getattr(plan_intent, field_name, None) or []):
            target_id = str(getattr(target, "target_id", "") or "")
            if target_id:
                result[target_id] = target
    return result


def _target_area_ha(target: Any) -> float | None:
    if target is None:
        return None
    footprint = getattr(target, "footprint_area_m2", None)
    if footprint is not None and float(footprint) > 0:
        return float(footprint) / 10000.0
    area = getattr(target, "area_ha", None)
    if area is not None and float(area) > 0:
        return float(area)
    return None


def _can_clip_target(target: Any) -> bool:
    if target is None or _target_area_ha(target) is None:
        return False
    output_kind = str(getattr(target, "expected_output_kind", "") or "")
    role = str(getattr(target, "materialization_role", "") or "")
    return output_kind in {"parcel", "polygon"} and role not in {
        "functional_overlay",
        "protection_overlay",
        "restoration_overlay",
    }


__all__ = ["build_suitability_surface"]
