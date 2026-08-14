"""GROUND subgraph aggregate - deterministic orchestrator over SpatialResolver.

Consumes a list of ``SpatialReferenceSpec`` plus a ``PlanningContext`` and
produces a typed ``GroundingResult`` with ``CandidateSite[]`` candidates,
``StageIssue[]`` unresolved items and ``SpatialQueryEvidence[]`` rows.

Pure orchestration: candidate resolution is delegated to the (already-cleaned)
``SpatialResolver.resolve_spec``; no LLM is ever called. Given the same specs
and context the output is fully deterministic.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from shapely.geometry import shape
from shapely.ops import unary_union

from app.infrastructure.context.planning_context import PlanningContext
from app.contracts.artifacts.contract_meta import StageIssue
from app.contracts.spatial.grounding_contracts import (
    CandidateSite,
    CandidateUncertainty,
    GroundingResult,
    SpatialQueryEvidence,
)
from app.contracts.artifacts.provenance import Provenance
from app.contracts.spatial.spatial_reference_contracts import (
    ResolvedSpatialRef,
    SpatialReferenceSpec,
)
from app.spatial.grounding.resolver import SpatialResolver


def build_candidate_site(
    spec: SpatialReferenceSpec,
    resolved: ResolvedSpatialRef,
    index: int,
    context: Optional[PlanningContext] = None,
) -> CandidateSite:
    """Map one resolved spec to a ``CandidateSite``.

    Deterministic scheme: the site id combines the 1-based index with the
    first resolved BSM (when available) so repeated runs yield identical ids.
    """
    source_parcels = list(resolved.final_bsms)
    first_bsm = source_parcels[0] if source_parcels else ""
    site_id = f"site_{index + 1}_{first_bsm}" if first_bsm else f"site_{index + 1}"
    parcels_by_bsm = {}
    if context is not None:
        try:
            parcels = context.current_parcels()
            parcels_by_bsm = {
                str(getattr(parcel, "bsm", "") or (parcel.get("bsm", "") if isinstance(parcel, dict) else "")): parcel
                for parcel in parcels
            }
        except Exception:
            parcels_by_bsm = {}
    geometries = []
    area_ha = 0.0
    for bsm in source_parcels:
        parcel = parcels_by_bsm.get(str(bsm))
        if parcel is None:
            continue
        raw_geometry = parcel.get("geometry") if isinstance(parcel, dict) else getattr(parcel, "geometry", None)
        try:
            geometry = shape(raw_geometry) if isinstance(raw_geometry, dict) else None
            if geometry is not None and not geometry.is_empty and geometry.is_valid:
                geometries.append(geometry)
        except Exception:
            pass
        raw_area_sqm = parcel.get("area_sqm", 0) if isinstance(parcel, dict) else getattr(parcel, "area_sqm", 0)
        area_ha += float(raw_area_sqm or 0) / 10000.0
    geometry_wkt = resolved.reference_geometry_wkt or ""
    if not geometry_wkt and geometries:
        geometry_wkt = unary_union(geometries).wkt
    uncertainty = None
    uncertainty_reason = str(getattr(resolved, "uncertainty_reason", "") or "")
    uncertainty_radius = float(getattr(resolved, "uncertainty_radius_m", 0.0) or 0.0)
    if uncertainty_reason or uncertainty_radius > 0:
        uncertainty = CandidateUncertainty(
            radius_m=uncertainty_radius,
            reason_code=uncertainty_reason,
            source=str(resolved.provenance.get("path", "") or ""),
        )
    return CandidateSite(
        site_id=site_id,
        source_parcels=source_parcels,
        available_geometry_wkt=geometry_wkt,
        available_area_ha=area_ha,
        hard_constraint_result={"constraint_id": "ground_geometry", "passed": bool(geometry_wkt and area_ha > 0)},
        metrics={
            "confidence": resolved.confidence,
            "spec_type": spec.type,
            "uncertainty_reason": uncertainty_reason,
        },
        evidence_refs=list(source_parcels),
        target_ref=(getattr(spec, "target_id", None) or None),
        project_ref=(getattr(spec, "project_ref", None) or None),
        confidence=resolved.confidence,
        uncertainty=uncertainty,
    )


def ground_aggregate(
    specs: list[SpatialReferenceSpec],
    context: PlanningContext,
    mention_enhancements: Optional[Dict[str, List[str]]] = None,
) -> GroundingResult:
    """Resolve all specs through ``SpatialResolver`` into a ``GroundingResult``.

    Deterministic over its inputs: one resolver instance, ordered iteration.
    ``mention_enhancements`` (target_id -> [text mention, ...]) comes from the
    GROUND flash-LLM mention enhancer and is treated as input data, so given
    the same specs/context/enhancements the output is reproducible. Each spec
    contributes exactly one ``SpatialQueryEvidence`` row; specs with resolved
    bundle parcels contribute a ``CandidateSite``, the rest a ``StageIssue``.
    """
    run_id = (
        getattr(context, "run_id", None)
        or getattr(context, "session_id", None)
        or ""
    )
    resolver = SpatialResolver(context)

    candidates: List[CandidateSite] = []
    unresolved: List[StageIssue] = []
    spatial_query_evidence: List[SpatialQueryEvidence] = []

    for index, spec in enumerate(specs):
        # Design 06/12: TARGET_PROJECTION retains unresolved_reason as a
        # diagnostic, it must not skip resolution.  GROUND still attempts the
        # evidence index / gazetteer / directional fallbacks; specs that
        # cannot be bound stay unresolved and enter the HUMAN gate.
        resolved = resolver.resolve_spec(
            spec,
            mention_enhancements=mention_enhancements,
        )
        spec_type = getattr(spec, "type", "")
        spatial_query_evidence.append(
            SpatialQueryEvidence(
                query_type=f"resolve_spec:{spec_type}",
                query_params={
                    "type": spec_type,
                    "direction": getattr(spec, "direction", None),
                    "topo": getattr(spec, "topo", None),
                    "intervention_id": getattr(spec, "intervention_id", None),
                    "target_id": getattr(spec, "target_id", ""),
                    "spec_id": getattr(spec, "spec_id", ""),
                    "project_ref": getattr(spec, "project_ref", None),
                },
                result_count=len(resolved.final_bsms),
                result_refs=list(resolved.final_bsms),
                target_id=getattr(spec, "target_id", ""),
                spec_id=getattr(spec, "spec_id", ""),
            )
        )
        if resolved.final_bsms:
            candidate = build_candidate_site(spec, resolved, index, context)
            if candidate.available_area_ha > 0 and candidate.available_geometry_wkt:
                candidates.append(candidate)
            else:
                unresolved.append(
                    StageIssue(
                        stage="ground",
                        severity="warning",
                        code="resolved_geometry_invalid",
                        message="resolved BSMs have no valid positive-area geometry",
                        detail=f"target_id={getattr(spec, 'target_id', '')}; bsms={resolved.final_bsms}",
                        related_artifact_id=(getattr(spec, "target_id", "") or None),
                    )
                )
        else:
            unresolved.append(
                StageIssue(
                    stage="ground",
                    severity="warning",
                    code="spatial_reference_unresolved",
                    message=(
                        f"unresolved spec: no candidates resolved for "
                        f"type={spec_type}"
                    ),
                    detail=(
                        f"target_id={getattr(spec, 'target_id', '')}; "
                        f"spec_id={getattr(spec, 'spec_id', '')}; "
                        f"reason={getattr(spec, 'unresolved_reason', '') or 'no_candidates'}"
                    ),
                    related_artifact_id=(getattr(spec, "target_id", "") or None),
                )
            )

    provenance = Provenance(
        source="ground_aggregate",
        run_id=run_id,
        module="ground",
        trace=[f"specs:{len(specs)}"],
        natural_language_description=(
            "GROUND grounding result produced by ground_aggregate via SpatialResolver."
        ),
    )

    return GroundingResult(
        candidates=candidates,
        unresolved=unresolved,
        spatial_query_evidence=spatial_query_evidence,
        provenance=provenance,
    )


async def retrieve_evidence(
    context: Any,
    evidence_requests: Optional[List[str]] = None,
) -> List[SpatialQueryEvidence]:
    """Lightweight evidence re-check for GROUND EXPLORE retries.

    Gathers a small, serializable set of evidence rows describing what was
    re-checked against the current PlanningContext: bundle land-use layer
    counts, resolved parcel count, village anchors and gazetteer coverage.
    Never raises — any missing infrastructure simply yields fewer rows and a
    fully absent context returns ``[]``.
    """
    rows: List[SpatialQueryEvidence] = []
    try:
        if context is None:
            return rows

        workspace = getattr(context, "workspace", None)
        if workspace is not None:
            polygons = getattr(workspace, "polygons", None)
            if polygons is not None:
                rows.append(
                    SpatialQueryEvidence(
                        query_type="bundle:layer_counts",
                        query_params={"layers": sorted(str(k) for k in polygons.keys())},
                        result_count=len(polygons.keys()),
                        result_refs=[str(k) for k in polygons.keys()],
                    )
                )

        parcels = None
        if workspace is not None and hasattr(workspace, "current_parcels"):
            try:
                parcels = list(workspace.current_parcels())
            except Exception:
                parcels = None
        if parcels is None and hasattr(context, "current_parcels"):
            try:
                parcels = list(context.current_parcels())
            except Exception:
                parcels = None
        if parcels:
            rows.append(
                SpatialQueryEvidence(
                    query_type="bundle:parcel_count",
                    query_params={"count": len(parcels)},
                    result_count=len(parcels),
                    result_refs=[str(getattr(p, "bsm", "") or "") for p in parcels[:10]],
                )
            )

        anchors = getattr(context, "village_anchors", None) or []
        if anchors:
            rows.append(
                SpatialQueryEvidence(
                    query_type="context:village_anchors",
                    query_params={"count": len(anchors)},
                    result_count=len(anchors),
                    result_refs=[
                        str(a.get("name") or a.get("label") or "")
                        for a in anchors
                        if isinstance(a, dict)
                    ],
                )
            )

        gazetteer = getattr(context, "gazetteer", None)
        if gazetteer is not None:
            rows.append(
                SpatialQueryEvidence(
                    query_type="context:gazetteer",
                    query_params={"present": True},
                    result_count=1,
                    result_refs=["gazetteer"],
                )
            )

        if evidence_requests:
            rows.append(
                SpatialQueryEvidence(
                    query_type="retry:evidence_requests",
                    query_params={"requests": list(evidence_requests)},
                    result_count=len(evidence_requests),
                    result_refs=list(evidence_requests),
                )
            )
    except Exception:
        return []
    return rows


__all__ = ["ground_aggregate", "build_candidate_site", "retrieve_evidence"]
