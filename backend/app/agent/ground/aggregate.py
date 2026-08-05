"""GROUND subgraph aggregate - deterministic orchestrator over SpatialResolver.

Consumes a list of ``SpatialReferenceSpec`` plus a ``PlanningContext`` and
produces a typed ``GroundingResult`` with ``CandidateSite[]`` candidates,
``StageIssue[]`` unresolved items and ``SpatialQueryEvidence[]`` rows.

Pure orchestration: candidate resolution is delegated to the (already-cleaned)
``SpatialResolver.resolve_spec``; no LLM is ever called. Given the same specs
and context the output is fully deterministic.
"""
from __future__ import annotations

from typing import Any, List, Optional

from app.modules.context.planning_context import PlanningContext
from app.modules.schema.contracts.contract_meta import StageIssue
from app.modules.schema.contracts.grounding_contracts import (
    CandidateSite,
    GroundingResult,
    SpatialQueryEvidence,
)
from app.modules.schema.contracts.provenance import Provenance
from app.modules.schema.contracts.spatial_reference_contracts import (
    ResolvedSpatialRef,
    SpatialReferenceSpec,
)
from app.modules.spatial_ops.resolver import SpatialResolver


def build_candidate_site(
    spec: SpatialReferenceSpec,
    resolved: ResolvedSpatialRef,
    index: int,
) -> CandidateSite:
    """Map one resolved spec to a ``CandidateSite``.

    Deterministic scheme: the site id combines the 1-based index with the
    first resolved BSM (when available) so repeated runs yield identical ids.
    """
    source_parcels = list(resolved.final_bsms)
    first_bsm = source_parcels[0] if source_parcels else ""
    site_id = f"site_{index + 1}_{first_bsm}" if first_bsm else f"site_{index + 1}"
    return CandidateSite(
        site_id=site_id,
        source_parcels=source_parcels,
        available_geometry_wkt=resolved.reference_geometry_wkt or "",
        available_area_ha=0.0,
        hard_constraint_result=None,
        metrics={
            "confidence": resolved.confidence,
            "spec_type": spec.type,
        },
        evidence_refs=list(source_parcels),
        target_ref=(getattr(spec, "intervention_id", None) or None),
        project_ref=(getattr(spec, "project_ref", None) or None),
    )


def ground_aggregate(
    specs: list[SpatialReferenceSpec],
    context: PlanningContext,
) -> GroundingResult:
    """Resolve all specs through ``SpatialResolver`` into a ``GroundingResult``.

    Deterministic: one resolver instance, ordered iteration, no LLM. Each spec
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
        resolved = resolver.resolve_spec(spec)
        spec_type = getattr(spec, "type", "")
        spatial_query_evidence.append(
            SpatialQueryEvidence(
                query_type=f"resolve_spec:{spec_type}",
                query_params={
                    "type": spec_type,
                    "direction": getattr(spec, "direction", None),
                    "topo": getattr(spec, "topo", None),
                    "intervention_id": getattr(spec, "intervention_id", None),
                    "project_ref": getattr(spec, "project_ref", None),
                },
                result_count=len(resolved.final_bsms),
                result_refs=list(resolved.final_bsms),
            )
        )
        if resolved.final_bsms:
            candidates.append(build_candidate_site(spec, resolved, index))
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

        bundle = getattr(context, "bundle", None)
        if bundle is not None:
            polygons = getattr(bundle, "polygons", None)
            if isinstance(polygons, dict):
                rows.append(
                    SpatialQueryEvidence(
                        query_type="bundle:layer_counts",
                        query_params={"layers": sorted(str(k) for k in polygons.keys())},
                        result_count=len(polygons),
                        result_refs=[str(k) for k in polygons.keys()],
                    )
                )

        parcels = None
        if bundle is not None and hasattr(bundle, "bundle_parcels"):
            try:
                parcels = list(bundle.bundle_parcels())
            except Exception:
                parcels = None
        if parcels is None and hasattr(context, "bundle_parcels"):
            try:
                parcels = list(context.bundle_parcels())
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
