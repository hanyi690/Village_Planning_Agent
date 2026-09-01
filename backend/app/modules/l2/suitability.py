"""Project grounding output into suitability without choosing a site."""

from __future__ import annotations

from typing import Any, cast

from app.contracts.l2.planning_semantics import (
    RolePolicyDisposition,
    SuitabilityEvaluationResult,
    SuitabilityEvaluationTrace,
    SuitabilityFactorCode,
    SuitabilityFactorRecord,
    SuitabilityMaterializationRole,
)
from app.contracts.ground.grounding_contracts import CandidateSite
from app.modules.l2.suitability_model import SuitabilityCandidate, SuitabilitySurface
from app.modules.l2.suitability_spatial_factors import (
    MATERIALIZATION_ROLE_POLICY_UNAVAILABLE,
    MaterializationRolePolicy,
    SPATIAL_ROLE_POLICY_VERSION,
    normalize_materialization_role,
    normalize_suitability_factor_code,
    resolve_materialization_role_policy,
)


_CONTEXT_FREE_HARD_CONSTRAINT_EVALUATION_DEFERRED: SuitabilityFactorCode = (
    "HARD_CONSTRAINT_EVALUATION_DEFERRED"
)
_OVERLAY_ROLES = frozenset(
    {
        "functional_overlay",
        "protection_overlay",
        "restoration_overlay",
    }
)


def _geometry_kind_from_wkt(wkt_text: str) -> str:
    """Normalize a WKT geometry kind without imposing a source schema."""

    try:
        from shapely import wkt as shapely_wkt

        kind = str(shapely_wkt.loads(str(wkt_text or "")).geom_type).casefold()
    except Exception:
        return "unknown"
    if kind in {"point", "multipoint"}:
        return "point"
    if kind in {"linestring", "multilinestring"}:
        return "line"
    if kind in {"polygon", "multipolygon"}:
        return "polygon"
    return "unknown"


def _field_value(item: object, name: str, default: object = None) -> object:
    """Read a typed or mapping-backed value without imposing a model shape."""

    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _factor_record(
    factor_code: SuitabilityFactorCode,
    *,
    policy: RolePolicyDisposition,
    triggered: bool,
    hard_exclusion: bool,
    evidence_ref: str = "",
    detail: str = "",
) -> SuitabilityFactorRecord:
    return {
        "factor_code": factor_code,
        "policy": policy,
        "triggered": triggered,
        "hard_exclusion": hard_exclusion,
        "evidence_ref": evidence_ref,
        "detail": detail,
    }


def _role_policy_artifacts(
    materialization_role: object,
) -> tuple[
    SuitabilityMaterializationRole,
    MaterializationRolePolicy | None,
    list[SuitabilityFactorRecord],
    list[SuitabilityEvaluationTrace],
]:
    role_policy = resolve_materialization_role_policy(materialization_role)
    normalized_role = normalize_materialization_role(materialization_role)
    evaluation_trace: list[SuitabilityEvaluationTrace] = [
        {
            "step": "materialization_role_policy",
            "materialization_role": normalized_role,
            "policy_key": role_policy.policy_key if role_policy is not None else "",
            "policy": (
                dict(role_policy.factor_policies) if role_policy is not None else {}
            ),
            "result": "resolved" if role_policy is not None else "fail_closed",
        }
    ]
    hard_constraint_factors: list[SuitabilityFactorRecord] = []
    if role_policy is None:
        hard_constraint_factors.append(
            _factor_record(
                MATERIALIZATION_ROLE_POLICY_UNAVAILABLE,
                policy="site_hard_exclusion",
                triggered=True,
                hard_exclusion=True,
                detail="materialization_role is missing or unknown",
            )
        )
    return normalized_role, role_policy, hard_constraint_factors, evaluation_trace


def _structured_role_factor_records(
    candidate: CandidateSite,
    role_policy: MaterializationRolePolicy | None,
) -> list[SuitabilityFactorRecord]:
    """Normalize explicit grounding factor evidence into a closed record."""

    raw_factors = list(candidate.hard_constraint_factors)
    if candidate.hard_constraint_result is not None:
        raw_factors.extend(candidate.hard_constraint_result.hard_constraint_factors)

    records: list[SuitabilityFactorRecord] = []
    for raw_factor in raw_factors:
        raw_code = raw_factor.factor_code.strip()
        factor_code = normalize_suitability_factor_code(raw_code)
        disposition = (
            role_policy.classify(factor_code) if role_policy is not None else None
        )
        if disposition is None:
            disposition = "site_hard_exclusion"
        detail = raw_factor.detail
        if factor_code == "UNKNOWN_HARD_CONSTRAINT_FACTOR":
            detail = "; ".join(
                item
                for item in (
                    f"unrecognized_factor_code:{raw_code}" if raw_code else "missing_factor_code",
                    raw_factor.detail,
                )
                if item
            )
        records.append(
            _factor_record(
                factor_code,
                policy=disposition,
                triggered=raw_factor.triggered,
                hard_exclusion=(
                    raw_factor.triggered and disposition == "site_hard_exclusion"
                ),
                evidence_ref=raw_factor.evidence_ref,
                detail=detail,
            )
        )
    return records


def _context_free_hard_feasibility(
    normalized_role: SuitabilityMaterializationRole,
    role_policy: MaterializationRolePolicy | None,
    hard_constraint_passed: bool,
    structured_factors: list[SuitabilityFactorRecord],
) -> tuple[
    bool,
    SuitabilityEvaluationResult,
    list[str],
    list[SuitabilityFactorRecord],
]:
    if role_policy is None:
        return False, "fail_closed", [MATERIALIZATION_ROLE_POLICY_UNAVAILABLE], []

    triggered_factors = [factor for factor in structured_factors if factor["triggered"]]
    hard_exclusions = [
        factor["factor_code"]
        for factor in triggered_factors
        if factor["hard_exclusion"]
    ]
    if hard_exclusions:
        return False, "failed", list(hard_exclusions), []
    if hard_constraint_passed:
        return True, "passed", [], []
    triggered_hard_policies = [
        factor for factor in triggered_factors if factor["policy"] != "advisory"
    ]
    if triggered_hard_policies and all(
        factor["policy"] == "overlay_constraint"
        for factor in triggered_hard_policies
    ):
        return True, "passed_by_role_policy", [], []
    if normalized_role in _OVERLAY_ROLES:
        return (
            False,
            "deferred",
            [_CONTEXT_FREE_HARD_CONSTRAINT_EVALUATION_DEFERRED],
            [
                _factor_record(
                    _CONTEXT_FREE_HARD_CONSTRAINT_EVALUATION_DEFERRED,
                    policy="overlay_constraint",
                    triggered=True,
                    hard_exclusion=False,
                    detail=(
                        "aggregate hard result failed without structured "
                        "site-hard exclusion evidence"
                    ),
                )
            ],
        )
    return False, "failed", ["hard_constraints_not_proven"], []


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
    target_by_id = _target_by_id(plan_intent)
    for raw_candidate in tuple(getattr(grounding_result, "candidates", ()) or ()):
        candidate = cast(CandidateSite, raw_candidate)
        target_id = str(candidate.target_ref or candidate.project_ref or "")
        target = target_by_id.get(target_id)
        materialization_role = _candidate_materialization_role(candidate, target)
        (
            normalized_role,
            role_policy,
            hard_constraint_factors,
            evaluation_trace,
        ) = _role_policy_artifacts(materialization_role)
        hard = candidate.hard_constraint_result
        hard_constraint_passed = (
            bool(hard.passed) if hard is not None else False
        )
        explicit_suitability = candidate.suitability_score
        evaluation_trace.append(
            {
                "step": "context_free_grounding_result",
                "hard_constraint_passed": hard_constraint_passed,
            }
        )
        structured_factors = _structured_role_factor_records(candidate, role_policy)
        hard_constraint_factors.extend(structured_factors)
        for factor in structured_factors:
            evaluation_trace.append(
                {
                    "step": "context_free_spatial_factor",
                    "materialization_role": normalized_role,
                    "policy_key": role_policy.policy_key if role_policy else "",
                    **factor,
                }
            )
        reasons: list[str] = []
        if not target_id:
            reasons.append("candidate_not_target_bound")
        (
            hard_feasible,
            hard_result,
            hard_reasons,
            deferred_factors,
        ) = _context_free_hard_feasibility(
            normalized_role,
            role_policy,
            hard_constraint_passed,
            structured_factors,
        )
        reasons.extend(hard_reasons)
        hard_constraint_factors.extend(deferred_factors)
        # A context-free caller may still provide an exact DATA geometry.
        # BSM is a legacy cadastral identity, not a prerequisite for a
        # candidate.  Only reject candidates when neither parcel identity nor
        # an executable geometry/source reference is present.
        if not candidate.source_parcels and not (
            str(candidate.available_geometry_wkt or "").strip()
            or str(getattr(candidate.geometry, "wkt", "") or "").strip()
            or list(getattr(candidate.geometry, "resource_refs", None) or [])
            or list(getattr(candidate.geometry, "source_refs", None) or [])
        ):
            reasons.append("candidate_spatial_resource_missing")
        candidate_geometry = getattr(candidate, "geometry", None)
        candidate_wkt = str(
            candidate.available_geometry_wkt
            or getattr(candidate_geometry, "wkt", "")
            or ""
        )
        candidate_kind = _geometry_kind_from_wkt(candidate_wkt)
        expected_kind = str(
            _field_value(target, "expected_output_kind", "")
            or _field_value(target, "output_kind", "")
            or ""
        ).casefold()
        if expected_kind == "parcel":
            expected_kind = "polygon"
        if expected_kind and candidate_kind != "unknown" and candidate_kind != expected_kind:
            reasons.append(
                f"candidate_geometry_kind_mismatch:{candidate_kind}!={expected_kind}"
            )
        geometry_area_ha = float(
            getattr(candidate_geometry, "planning_area_ha", None)
            or getattr(candidate_geometry, "source_area_ha", None)
            or getattr(candidate, "available_area_ha", None)
            or 0.0
        )
        source_area_ha = float(
            getattr(candidate, "source_area_ha", None)
            or getattr(candidate_geometry, "source_area_ha", None)
            or geometry_area_ha
            or 0.0
        )
        coverage_ratio = (
            max(0.0, min(1.0, geometry_area_ha / source_area_ha))
            if source_area_ha > 0
            else None
        )
        availability_status = str(
            getattr(candidate_geometry, "availability_status", "")
            or "fully_available"
        )
        if availability_status not in {
            "fully_available",
            "partially_available",
            "fully_unavailable",
            "unknown",
        }:
            availability_status = "unknown"
        if explicit_suitability is None:
            diagnostics.setdefault(target_id or "__unbound__", []).append("no_suitability_evaluator")
        evaluation_trace.append(
            {
                "step": "context_free_role_policy_result",
                "materialization_role": normalized_role,
                "policy_key": role_policy.policy_key if role_policy is not None else "",
                "result": hard_result,
                "hard_feasible_before_candidate_requirements": hard_feasible,
            }
        )
        reasons = list(dict.fromkeys(reasons))
        if reasons:
            diagnostics.setdefault(target_id or "__unbound__", []).extend(reasons)
        candidates.append(
            SuitabilityCandidate(
                candidate_id=candidate.site_id,
                target_id=target_id,
                source_parcels=list(candidate.source_parcels),
                materialization_role=normalized_role,
                role_policy_key=role_policy.policy_key if role_policy is not None else "",
                materialization_role_policy=(
                    dict(role_policy.factor_policies) if role_policy is not None else {}
                ),
                score=float(explicit_suitability or 0.0),
                hard_feasible=hard_feasible and not reasons,
                exclusion_reasons=reasons,
                evidence_refs=list(candidate.evidence_refs),
                hard_constraint_factors=hard_constraint_factors,
                evaluation_trace=evaluation_trace,
                available_geometry_wkt=candidate_wkt,
                eligible_geometry_wkt=candidate_wkt if hard_feasible and not reasons else "",
                available_area_ha=geometry_area_ha,
                source_area_ha=source_area_ha,
                coverage_ratio=coverage_ratio,
                geometry_operation="data_resource_extent" if not candidate.source_parcels else "bundle_extent",
                geometry_crs=str(getattr(candidate_geometry, "crs", "") or "EPSG:4326"),
                availability_status=availability_status,
                eligible_area_ha=geometry_area_ha if hard_feasible and not reasons else 0.0,
                excluded_area_ha=(
                    max(source_area_ha - geometry_area_ha, 0.0)
                    if source_area_ha > 0
                    else None
                ),
                feature_ref=str(getattr(candidate_geometry, "source_ref", "") or ""),
            )
        )
    for issue in tuple(getattr(grounding_result, "unresolved", ()) or ()):
        target_id = str(getattr(issue, "related_artifact_id", None) or "")
        if target_id:
            diagnostics.setdefault(target_id, []).append(str(getattr(issue, "code", "grounding_unresolved")))
    return SuitabilitySurface(
        candidates=candidates,
        target_diagnostics=diagnostics,
        provenance={
            "materialization_role_policy_version": SPATIAL_ROLE_POLICY_VERSION,
            "evaluated_materialization_roles": sorted(
                {candidate.materialization_role for candidate in candidates}
            ),
        },
    )


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
    from shapely.geometry.base import BaseGeometry

    from app.modules.l2.suitability_policy import load_suitability_policy
    from app.modules.l2.suitability_spatial_factors import SpatialFactorIndex
    from app.modules.l2.suitability_terrain_adapter import TerrainCandidateFeatureAdapter
    from app.modules.l2.suitability_subgeometry import derive_planning_subgeometry

    active_policy = policy or load_suitability_policy()
    adapter = TerrainCandidateFeatureAdapter.from_context(
        context,
        active_policy,
        catalog=catalog,
        cache_dir=cache_dir,
    )
    spatial_index = SpatialFactorIndex(context, active_policy)
    # Do not touch the legacy current-parcels accessor for a catalog-only
    # request.  It is needed only when at least one candidate explicitly
    # carries a source BSM and adjacency must be evaluated.
    has_parcel_candidates = any(
        bool(getattr(candidate, "source_parcels", None) or [])
        for candidate in tuple(getattr(grounding_result, "candidates", ()) or ())
    )
    parcel_by_bsm = (
        {
            str(getattr(parcel, "bsm", "") or ""): parcel
            for parcel in list(context.current_parcels() or [])
        }
        if has_parcel_candidates
        else {}
    )
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

    def adjacent_parcels(
        candidate_wkt: str,
        source_bsm: str,
        source_wkt: str = "",
    ) -> tuple[list[str], list[str]]:
        if not candidate_wkt and not source_wkt:
            return [], []
        try:
            from shapely import wkt as shapely_wkt

            candidate_geometry = (
                shapely_wkt.loads(candidate_wkt) if candidate_wkt else None
            )
            source_geometry = (
                shapely_wkt.loads(source_wkt) if source_wkt else None
            )
        except Exception:
            return [], []
        adjacent: list[str] = []
        refs: list[str] = []
        for other_bsm, other in parcel_by_bsm.items():
            if not other_bsm or other_bsm == source_bsm:
                continue
            try:
                raw_geometry = getattr(other, "geometry", None)
                if isinstance(raw_geometry, BaseGeometry):
                    other_geometry = raw_geometry
                else:
                    other_geometry = shape(raw_geometry)
                if other_geometry.is_empty:
                    continue
                # Touching parcels are the primary relation; a tiny tolerance
                # covers floating-point seams introduced by clipping.
                # A clipped footprint can sit wholly inside its source BSM,
                # so adjacency must be evaluated against both the selected
                # footprint and the full source extent.  This records a
                # possible execution dependency without merging the parcels.
                candidate_adjacent = bool(
                    candidate_geometry is not None
                    and (
                        candidate_geometry.touches(other_geometry)
                        or candidate_geometry.buffer(1e-9).intersects(other_geometry)
                    )
                )
                source_adjacent = bool(
                    source_geometry is not None
                    and (
                        source_geometry.touches(other_geometry)
                        or source_geometry.buffer(1e-9).intersects(other_geometry)
                    )
                )
                if candidate_adjacent or source_adjacent:
                    adjacent.append(other_bsm)
                    refs.append(f"bundle:landuse_current:{source_bsm}:adjacent:{other_bsm}")
            except Exception:
                continue
        return sorted(set(adjacent)), sorted(set(refs))
    for source in tuple(getattr(grounding_result, "candidates", ()) or ()):
        target_id = str(
            getattr(source, "target_ref", None)
            or getattr(source, "project_ref", None)
            or ""
        )
        target = target_by_id.get(target_id)
        materialization_role = _candidate_materialization_role(source, target)
        (
            normalized_role,
            role_policy,
            fallback_role_factors,
            fallback_role_trace,
        ) = _role_policy_artifacts(materialization_role)
        source_bsms = list(getattr(source, "source_parcels", None) or [])
        # Generic DATA features (roads, facilities, water, uploaded polygons)
        # are valid SELECT inputs even when no parcel BSM exists.  They must
        # not be routed through the parcel terrain adapter, which would turn
        # an otherwise executable source geometry into a synthetic
        # ``parcel-not-found`` failure.
        if not source_bsms:
            source_geometry = getattr(source, "geometry", None)
            generic_wkt = str(
                getattr(source, "available_geometry_wkt", "")
                or getattr(source_geometry, "wkt", "")
                or ""
            ).strip()
            generic_kind = str(getattr(source_geometry, "kind", "") or "").casefold()
            if generic_kind not in {"point", "line", "polygon", "multipatch"}:
                try:
                    from shapely import wkt as shapely_wkt

                    parsed_kind = str(shapely_wkt.loads(generic_wkt).geom_type).casefold()
                    generic_kind = (
                        "point" if parsed_kind in {"point", "multipoint"}
                        else "line" if parsed_kind in {"linestring", "multilinestring"}
                        else "polygon" if parsed_kind in {"polygon", "multipolygon"}
                        else "unknown"
                    )
                except Exception:
                    generic_kind = "unknown"
            hard = getattr(source, "hard_constraint_result", None)
            hard_passed = bool(getattr(hard, "passed", False)) if hard is not None else False
            generic_reasons: list[str] = []
            if not target_id:
                generic_reasons.append("candidate_not_target_bound")
            if generic_kind == "unknown" or not generic_wkt:
                generic_reasons.append("generic_source_geometry_missing_or_invalid")
            if hard is None:
                generic_reasons.append("hard_constraints_pending")
            elif not hard_passed:
                generic_reasons.append(
                    str(getattr(hard, "violation_detail", "hard_constraints_not_passed") or "hard_constraints_not_passed")
                )
            expected_kind = str(
                _field_value(target, "expected_output_kind", "")
                or _field_value(target, "output_kind", "")
                or ""
            ).casefold()
            if expected_kind == "parcel":
                expected_kind = "polygon"
            if expected_kind and generic_kind != "unknown" and generic_kind != expected_kind:
                generic_reasons.append(
                    f"candidate_geometry_kind_mismatch:{generic_kind}!={expected_kind}"
                )
            generic_reasons = list(dict.fromkeys(generic_reasons))
            generic_score = getattr(source_geometry, "suitability_score", None)
            if generic_score is None:
                generic_score = getattr(source, "suitability_score", None)
            generic_score = max(0.0, min(1.0, float(generic_score or 0.0)))
            generic_refs = list(dict.fromkeys([
                *(getattr(source, "evidence_refs", None) or []),
                *(getattr(source_geometry, "source_refs", None) or []),
                str(getattr(source_geometry, "source_ref", "") or ""),
            ]))
            generic_refs = [str(item) for item in generic_refs if str(item).strip()]
            if not generic_refs:
                generic_refs = [f"candidate:{getattr(source, 'site_id', '') or target_id}"]
            geometry_area_ha = float(
                getattr(source_geometry, "planning_area_ha", None)
                or getattr(source_geometry, "source_area_ha", None)
                or getattr(source, "available_area_ha", None)
                or 0.0
            )
            source_area_ha = float(
                getattr(source, "source_area_ha", None)
                or getattr(source_geometry, "source_area_ha", None)
                or geometry_area_ha
                or 0.0
            )
            coverage_ratio = (
                max(0.0, min(1.0, geometry_area_ha / source_area_ha))
                if source_area_ha > 0
                else None
            )
            availability_status = str(
                getattr(source_geometry, "availability_status", "")
                or "fully_available"
            )
            if availability_status not in {
                "fully_available",
                "partially_available",
                "fully_unavailable",
                "unknown",
            }:
                availability_status = "unknown"
            generic_score_breakdown = {
                "source_geometry": generic_score,
            }
            candidates.append(
                SuitabilityCandidate(
                    candidate_id=str(getattr(source, "site_id", "") or target_id),
                    target_id=target_id,
                    source_parcels=[],
                    materialization_role=normalized_role,
                    role_policy_key=(str(role_policy.policy_key) if role_policy is not None else ""),
                    materialization_role_policy=(
                        dict(role_policy.factor_policies) if role_policy is not None else {}
                    ),
                    score=generic_score,
                    score_breakdown=generic_score_breakdown,
                    hard_feasible=hard_passed and not generic_reasons,
                    exclusion_reasons=generic_reasons,
                    evidence_refs=generic_refs,
                    hard_constraint_factors=[],
                    evaluation_trace=[
                        {
                            "step": "geometry_prepared",
                            "materialization_role": normalized_role,
                            "geometry_source": "candidate_geometry",
                            "result": "ok" if generic_kind != "unknown" else "invalid",
                        }
                    ],
                    available_geometry_wkt=generic_wkt,
                    eligible_geometry_wkt=generic_wkt if hard_passed and not generic_reasons else "",
                    available_area_ha=geometry_area_ha,
                    source_area_ha=source_area_ha,
                    coverage_ratio=coverage_ratio,
                    geometry_operation="data_resource_extent",
                    geometry_crs=str(getattr(source_geometry, "crs", "") or "EPSG:4326"),
                    geometry_diagnostics=[],
                    availability_status=availability_status,
                    eligible_area_ha=geometry_area_ha if hard_passed and not generic_reasons else 0.0,
                    excluded_area_ha=(
                        max(source_area_ha - geometry_area_ha, 0.0)
                        if source_area_ha > 0
                        else None
                    ),
                    policy_ref="",
                    feature_ref=str(getattr(source_geometry, "source_ref", "") or ""),
                )
            )
            continue
        for raw_bsm in source_bsms:
            bsm = str(raw_bsm or "")
            parcel = parcel_by_bsm.get(bsm)
            parcel_lookup_diagnostic = (
                f"CANDIDATE_SOURCE_PARCEL_NOT_FOUND:{bsm}"
                if bsm
                else "CANDIDATE_SOURCE_PARCEL_LOOKUP_UNAVAILABLE"
            )
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
                prohibited_wkts = _constraint_avoid_wkts(context, parcel_wkt)
                clip_result = derive_planning_subgeometry(
                    parcel_wkt,
                    source_crs=geometry_crs,
                    target_area_ha=target_area_ha,
                    avoid_geometry_wkts=(prohibited_wkts if _can_clip_target(target_by_id.get(target_id)) else ()),
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
            # The source polygon is the geometric authority for availability
            # and area ratios.  Catalog area attributes are retained for
            # recall/provenance but can be stale or calculated in another CRS;
            # using them here can turn a partially excluded parcel into a
            # falsely fully-available one (or make eligible area exceed source
            # area).  The clip result is measured in its metric CRS.
            source_area_ha = (
                float(clip_result.source_area_ha)
                if clip_result is not None and float(clip_result.source_area_ha) > 0
                else parcel_area_ha
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
            availability_status = (
                str(clip_result.availability_status)
                if clip_result is not None
                else "unknown"
            )
            eligible_area_ha = (
                min(
                    max(float(clip_result.eligible_area_ha), 0.0),
                    source_area_ha,
                )
                if clip_result is not None
                else None
            )
            # Keep availability a partition of the source extent.  A stale
            # catalog area or a CRS conversion rounding difference must never
            # produce ``eligible > source`` or an unrelated excluded area.
            excluded_area_ha = (
                max(source_area_ha - eligible_area_ha, 0.0)
                if clip_result is not None and eligible_area_ha is not None
                else None
            )
            adjacent_bsms, adjacency_refs = adjacent_parcels(
                candidate_wkt, bsm, parcel_wkt
            )
            coverage_ratio = raw_coverage_ratio
            if raw_coverage_ratio is not None and raw_coverage_ratio > 1.0:
                coverage_ratio = 1.0
                geometry_diagnostics.append("coverage_ratio_clamped_to_source_extent")
            candidate_id = f"{str(getattr(source, 'site_id', '') or '')}:{bsm or 'unbound'}"
            spatial = (
                spatial_index.evaluate(
                    parcel,
                    geometry=candidate_wkt,
                    materialization_role=materialization_role,
                )
                if parcel is not None
                else None
            )
            # GROUND evaluates the recall candidate as a union of all source
            # parcels.  A prohibited overlap in that coarse union must not
            # poison every parcel-level SELECT alternative: rebase the hard
            # result on the exact refined geometry before terrain evaluation.
            hard_result = getattr(source, "hard_constraint_result", None)
            if (
                bsm
                and spatial is not None
                and hard_result is not None
                and not bool(getattr(hard_result, "passed", False))
            ):
                from app.contracts.ground.grounding_contracts import HardConstraintResult

                hard_result = HardConstraintResult(
                    constraint_id="select_parcel_geometry",
                    passed=bool(spatial.hard_feasible),
                    violation_detail="|".join(spatial.exclusion_codes),
                )
            typed_candidate = source.model_copy(
                update={
                    "site_id": candidate_id,
                    "source_parcels": [bsm] if bsm else [],
                    "available_geometry_wkt": candidate_wkt,
                    "hard_constraint_result": hard_result,
                }
            )
            feature = adapter.build_candidate(typed_candidate)
            reasons = list(feature.blocking_codes)
            if spatial is not None:
                reasons.extend(spatial.exclusion_codes)
            elif role_policy is None:
                reasons.extend(
                    str(factor["factor_code"]) for factor in fallback_role_factors
                )
            if parcel is None:
                reasons.append(parcel_lookup_diagnostic)
            if "planning_area_insufficient" in geometry_diagnostics:
                reasons.append("planning_area_insufficient")
            if "subdivision_failed" in geometry_diagnostics:
                reasons.append("planning_subdivision_failed")
            reasons = list(dict.fromkeys(reasons))
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
                    materialization_role=(
                        str(spatial.materialization_role)
                        if spatial is not None
                        else normalized_role
                    ),
                    role_policy_key=(
                        str(spatial.policy_key)
                        if spatial is not None
                        else role_policy.policy_key if role_policy is not None else ""
                    ),
                    materialization_role_policy=(
                        dict(spatial.materialization_role_policy)
                        if spatial is not None
                        else (
                            dict(role_policy.factor_policies)
                            if role_policy is not None
                            else {}
                        )
                    ),
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
                    hard_constraint_factors=(
                        list(spatial.hard_constraint_factors)
                        if spatial is not None
                        else list(fallback_role_factors)
                    ),
                    evaluation_trace=(
                        list(spatial.evaluation_trace)
                        if spatial is not None
                        else [
                            *fallback_role_trace,
                            {
                                "step": "parcel_lookup",
                                "materialization_role": normalized_role,
                                "policy_key": (
                                    role_policy.policy_key
                                    if role_policy is not None
                                    else ""
                                ),
                                "bsm": bsm,
                                "result": "missing",
                                "diagnostic": parcel_lookup_diagnostic,
                            },
                        ]
                    ),
                    available_geometry_wkt=candidate_wkt,
                    eligible_geometry_wkt=(
                        str(getattr(clip_result, "eligible_geometry_wkt", "") or "")
                        if clip_result is not None
                        else ""
                    ),
                    available_area_ha=available_area_ha,
                    source_area_ha=source_area_ha,
                    coverage_ratio=coverage_ratio,
                    geometry_operation=geometry_operation,
                    geometry_crs=geometry_crs,
                    geometry_diagnostics=geometry_diagnostics,
                    availability_status=availability_status,
                    eligible_area_ha=eligible_area_ha,
                    excluded_area_ha=excluded_area_ha,
                    adjacent_parcel_bsms=adjacent_bsms,
                    adjacency_evidence_refs=adjacency_refs,
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
            "materialization_role_policy_version": SPATIAL_ROLE_POLICY_VERSION,
            "evaluated_materialization_roles": sorted(
                {
                    str(candidate.materialization_role)
                    for candidate in candidates
                    if str(candidate.materialization_role)
                }
            ),
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


def _candidate_materialization_role(source: Any, target: Any = None) -> str:
    geometry = getattr(source, "geometry", None)
    for value in (
        getattr(target, "materialization_role", None),
        getattr(geometry, "materialization_role", None),
        getattr(source, "materialization_role", None),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


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


def _constraint_avoid_wkts(context: Any, source_wkt: str = "") -> list[str]:
    """Return prohibited source polygons for parcel-level clipping.

    The constraint index already owns authoritative source geometry.  Reading
    its rows here keeps clipping in the same CRS and avoids the old
    all-or-nothing parcel rejection.  If the index is unavailable, the list
    stays empty and the candidate remains explicitly deferred by suitability.
    """

    index = getattr(context, "constraint_index", None)
    frame = getattr(index, "_gdf", None) if index is not None else None
    if frame is None:
        return []
    try:
        source_geometry = None
        if source_wkt:
            from shapely import wkt as shapely_wkt

            source_geometry = shapely_wkt.loads(source_wkt)
        from app.core.common.constraint_codes import PROHIBITED_LAND_CONSTRAINTS

        values = []
        for _, row in frame.iterrows():
            if str(row.get("constraint_type", "") or "") not in PROHIBITED_LAND_CONSTRAINTS:
                continue
            geometry = row.get("geometry")
            if geometry is not None and not geometry.is_empty:
                if source_geometry is not None and not (
                    geometry.intersects(source_geometry)
                    or geometry.touches(source_geometry)
                ):
                    continue
                values.append(geometry.wkt)
        return list(dict.fromkeys(values))
    except Exception:
        return []


__all__ = ["build_suitability_surface"]
