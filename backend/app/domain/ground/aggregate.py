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

from shapely import wkt as shapely_wkt
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from app.infrastructure.context.planning_context import PlanningContext
from app.contracts.artifacts.contract_meta import StageIssue
from app.contracts.spatial.grounding_contracts import (
    CandidateSite,
    CandidateUncertainty,
    GroundingResult,
    SpatialQueryEvidence,
)
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounded_problem import (
    GroundedPlanningProblem,
    GroundedTargetDomain,
)
from app.domain.ground.constraint_factors import (
    compile_constraint_factors,
    evaluate_relation_satisfaction,
)
from app.domain.ground.candidate_domain_builder import (
    build_candidate_domains,
    is_grounding_candidate,
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
    *,
    target_kind: str = "unknown",
    expected_output_kind: str = "unknown",
    source_parcels_override: Optional[List[str]] = None,
    geometry_wkt_override: Optional[str] = None,
    source_refs_override: Optional[List[str]] = None,
    authoritative_geometry: bool = False,
    generation_operation: str = "grounded_candidate",
    candidate_variant: str = "union",
) -> CandidateSite:
    """Map one resolved spec to a ``CandidateSite``.

    Deterministic scheme: the site id combines the 1-based index with the
    first resolved BSM (when available) so repeated runs yield identical ids.
    """
    source_parcels = list(
        resolved.final_bsms
        if source_parcels_override is None
        else source_parcels_override
    )
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
            geometry = shape(raw_geometry) if isinstance(raw_geometry, dict) else raw_geometry
            if geometry is not None and not geometry.is_empty and geometry.is_valid:
                geometries.append(geometry)
        except Exception:
            pass
        raw_area_sqm = parcel.get("area_sqm", 0) if isinstance(parcel, dict) else getattr(parcel, "area_sqm", 0)
        area_ha += float(raw_area_sqm or 0) / 10000.0
    geometry_wkt = (
        geometry_wkt_override
        if geometry_wkt_override is not None
        else resolved.reference_geometry_wkt or ""
    )
    geometry_source_refs = list(
        dict.fromkeys(str(item) for item in (source_refs_override or []) if str(item).strip())
    )
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
    geometry_kind = _geometry_kind(geometry_wkt)
    geometry_role = _geometry_role(
        geometry_kind,
        target_kind=target_kind,
        expected_output_kind=expected_output_kind,
        has_source_parcels=bool(source_parcels),
        uncertainty_reason=uncertainty_reason,
    )
    if candidate_variant == "parcel":
        geometry_role = (
            "corridor_candidate"
            if expected_output_kind == "line"
            else "parcel_candidate"
        )
    geometry_is_valid = geometry_kind != "unknown" and bool(geometry_wkt)
    hard_constraint_status, hard_constraint_detail = _candidate_constraint_status(
        geometry_wkt,
        context,
        geometry_is_valid=geometry_is_valid,
    )
    if (
        geometry_role == "execution_geometry"
        and hard_constraint_status in {"failed", "deferred", "unknown"}
    ):
        if geometry_kind == "point":
            geometry_role = "anchor_geometry"
        elif geometry_kind == "line" or expected_output_kind == "line":
            geometry_role = "corridor_candidate"
        else:
            geometry_role = (
                "parcel_candidate" if source_parcels else "scope_geometry"
            )
    geometry = CandidateGeometry(
        target_id=str(getattr(spec, "target_id", "") or ""),
        kind=geometry_kind,
        role=geometry_role,
        materialization_role=str(
            getattr(spec, "materialization_role", "")
            or ("site_footprint" if target_kind == "site_area" else "")
        ),
        wkt=geometry_wkt,
        granularity=(
            "exact_feature"
            if (
                (resolved.reference_geometry_wkt or authoritative_geometry)
                and geometry_kind in {"point", "line"}
            )
            else ("parcel_set" if source_parcels else "none")
        ),
        source_ref=(
            geometry_source_refs[0]
            if geometry_source_refs
            else str(resolved.provenance.get("path", "") or "")
        ),
        source_refs=geometry_source_refs,
        evidence_refs=list(dict.fromkeys([*source_parcels, *geometry_source_refs])),
        confidence=float(resolved.confidence or 0.0),
        uncertainty_radius_m=uncertainty_radius,
        uncertainty_reason=uncertainty_reason,
        source_bsms=source_parcels,
        generation_operation=generation_operation,
        hard_constraint_status=hard_constraint_status,
    )
    return CandidateSite(
        site_id=site_id,
        source_parcels=source_parcels,
        available_geometry_wkt=geometry_wkt,
        available_area_ha=area_ha,
        candidate_id=geometry.candidate_id,
        hard_constraint_result={
            "constraint_id": "ground_geometry",
            "passed": hard_constraint_status in {"pending", "passed"},
            "violation_detail": hard_constraint_detail,
        },
        metrics={
            "confidence": resolved.confidence,
            "spec_type": spec.type,
            "uncertainty_reason": uncertainty_reason,
            "candidate_variant": candidate_variant,
            "source_parcel_count": len(resolved.final_bsms),
        },
        evidence_refs=list(source_parcels),
        target_ref=(getattr(spec, "target_id", None) or None),
        project_ref=(getattr(spec, "project_ref", None) or None),
        confidence=resolved.confidence,
        uncertainty=uncertainty,
        target_kind=target_kind,
        expected_output_kind=expected_output_kind,
        geometry=geometry,
    )


def _parcel_geometry_records(
    context: Optional[PlanningContext],
    source_parcels: List[str],
) -> list[tuple[str, Any, Any]]:
    """Return valid bundle parcel geometries in source order.

    The resolver returns BSMs as evidence. This helper only reads geometry
    already present in the bundle; it never creates or enlarges a geometry.
    Invalid or missing parcel records are omitted so a parcel alternative
    cannot silently become an invented fallback polygon.
    """

    if context is None:
        return []
    try:
        parcels = context.current_parcels()
    except Exception:
        return []
    by_bsm = {
        str(
            getattr(parcel, "bsm", "")
            or (parcel.get("bsm", "") if isinstance(parcel, dict) else "")
        ): parcel
        for parcel in parcels
    }
    records: list[tuple[str, Any, Any]] = []
    for bsm in source_parcels:
        parcel = by_bsm.get(str(bsm))
        if parcel is None:
            continue
        raw_geometry = (
            parcel.get("geometry")
            if isinstance(parcel, dict)
            else getattr(parcel, "geometry", None)
        )
        try:
            geometry = shape(raw_geometry) if isinstance(raw_geometry, dict) else raw_geometry
            if geometry is None or geometry.is_empty or not geometry.is_valid:
                continue
        except Exception:
            continue
        raw_area_sqm = (
            parcel.get("area_sqm", 0)
            if isinstance(parcel, dict)
            else getattr(parcel, "area_sqm", 0)
        )
        area_ha = float(raw_area_sqm or 0) / 10000.0
        if area_ha <= 0:
            try:
                area_ha = float(geometry.area) / 10000.0
            except Exception:
                area_ha = 0.0
        records.append((str(bsm), geometry, area_ha))
    return records


def build_candidate_sites(
    spec: SpatialReferenceSpec,
    resolved: ResolvedSpatialRef,
    index: int,
    context: Optional[PlanningContext] = None,
    *,
    target_kind: str = "unknown",
    expected_output_kind: str = "unknown",
) -> list[CandidateSite]:
    """Build a deterministic candidate domain without collapsing parcels.

    A resolved spec may refer to several BSMs. A union is useful as recall
    evidence but is a poor SELECT input: one prohibited parcel can poison the
    entire candidate, and a large disconnected polygon cannot express parcel
    capacity or exclusivity. When no exact geometry was supplied, expose one
    candidate per valid source parcel instead. Each alternative is checked
    independently against hard constraints.

    Explicit geometry remains one candidate because splitting it would discard
    its source semantics. If parcel geometry is unavailable, the legacy
    single candidate is retained and remains fail-closed.
    """

    source_parcels = list(resolved.final_bsms)
    reference_geometries = list(getattr(resolved, "reference_geometries", None) or [])
    if reference_geometries:
        candidates: list[CandidateSite] = []
        for offset, reference in enumerate(reference_geometries):
            source_bsms = list(getattr(reference, "source_bsms", None) or [])
            if not source_bsms:
                source_bsms = list(source_parcels)
            source_refs = list(
                dict.fromkeys(
                    str(item)
                    for item in [
                        str(getattr(reference, "source_ref", "") or ""),
                        *(getattr(reference, "source_refs", None) or []),
                    ]
                    if str(item).strip()
                )
            )
            candidates.append(
                build_candidate_site(
                    spec,
                    resolved,
                    index + offset,
                    context,
                    target_kind=target_kind,
                    expected_output_kind=expected_output_kind,
                    source_parcels_override=source_bsms,
                    geometry_wkt_override=str(getattr(reference, "wkt", "") or ""),
                    source_refs_override=source_refs,
                    authoritative_geometry=True,
                    generation_operation="grounded_source_feature",
                    candidate_variant="exact_feature",
                )
            )
        return candidates

    if resolved.reference_geometry_wkt or len(source_parcels) <= 1:
        return [
            build_candidate_site(
                spec,
                resolved,
                index,
                context,
                target_kind=target_kind,
                expected_output_kind=expected_output_kind,
            )
        ]

    records = _parcel_geometry_records(context, source_parcels)
    if len(records) <= 1:
        return [
            build_candidate_site(
                spec,
                resolved,
                index,
                context,
                target_kind=target_kind,
                expected_output_kind=expected_output_kind,
            )
        ]

    alternatives: list[CandidateSite] = []
    for offset, (bsm, geometry, _area_ha) in enumerate(records):
        alternatives.append(
            build_candidate_site(
                spec,
                resolved,
                index + offset,
                context,
                target_kind=target_kind,
                expected_output_kind=expected_output_kind,
                source_parcels_override=[bsm],
                geometry_wkt_override=geometry.wkt,
                generation_operation="grounded_parcel_alternative",
                candidate_variant="parcel",
            )
        )
    return alternatives


def _candidate_constraint_status(
    geometry_wkt: str,
    context: Optional[PlanningContext],
    *,
    geometry_is_valid: bool,
) -> tuple[str, str]:
    """Evaluate a candidate against the available prohibited-constraint index.

    GROUND must not claim a hard constraint pass merely because WKT parses.
    When no index is available the status remains ``pending`` and SELECT can
    preserve the candidate for a later gate; when the index proves an overlap
    the candidate is explicitly failed and cannot be materialized.
    """

    if not geometry_is_valid:
        return "failed", "candidate geometry is empty or invalid"
    constraint_index = getattr(context, "constraint_index", None) if context is not None else None
    if constraint_index is None:
        return "pending", "constraint index unavailable"
    try:
        from app.spatial.allocation.selection import _PROHIBITED_CONSTRAINTS

        geometry = shapely_wkt.loads(geometry_wkt)
        overlaps = constraint_index.geometry_in_constraint(mapping(geometry)) or []
        prohibited = sorted({
            str(getattr(item, "constraint_type", "") or "")
            for item in overlaps
            if str(getattr(item, "constraint_type", "") or "") in _PROHIBITED_CONSTRAINTS
        })
    except Exception as exc:  # noqa: BLE001
        return "deferred", f"constraint query failed: {type(exc).__name__}"
    if prohibited:
        return "failed", "prohibited constraint overlap: " + ",".join(prohibited)
    return "passed", ""


def _geometry_kind(geometry_wkt: str) -> str:
    if not geometry_wkt:
        return "unknown"
    try:
        geom_type = str(shapely_wkt.loads(geometry_wkt).geom_type).lower()
    except Exception:
        return "unknown"
    if geom_type in {"point", "multipoint"}:
        return "point"
    if geom_type in {"linestring", "multilinestring"}:
        return "line"
    if geom_type in {"polygon", "multipolygon"}:
        return "polygon"
    return "unknown"


def _geometry_role(
    geometry_kind: str,
    *,
    target_kind: str,
    expected_output_kind: str,
    has_source_parcels: bool,
    uncertainty_reason: str = "",
) -> str:
    if (
        geometry_kind == "point"
        and expected_output_kind == "point"
        and target_kind == "facility"
    ):
        return "execution_geometry"
    if geometry_kind == "point" and expected_output_kind == "point":
        return "anchor_geometry"
    if geometry_kind == "line" and expected_output_kind == "line":
        return "execution_geometry"
    if geometry_kind == "polygon":
        # A village/bbox/coarse composite is a recall domain, not a final
        # execution footprint.  The resolver deliberately returns these
        # geometries so SELECT can retain an auditable candidate-only target,
        # but materialising the whole coarse parcel pool would create broad
        # overlaps and falsely pass it as a plan layer.
        if "coarse" in str(uncertainty_reason or "").lower():
            return "parcel_candidate" if has_source_parcels else "scope_geometry"
        if (
            expected_output_kind in {"polygon", "parcel"}
            and target_kind in {"site_area", "zone", "restoration", "protection"}
        ):
            return "execution_geometry"
        if expected_output_kind == "line":
            return "corridor_candidate"
        return "parcel_candidate" if has_source_parcels else "scope_geometry"
    return "unknown"


def ground_aggregate(
    specs: list[SpatialReferenceSpec],
    context: PlanningContext,
    mention_enhancements: Optional[Dict[str, List[str]]] = None,
    intent_graph: Any = None,
    target_metadata: Optional[Dict[str, Dict[str, str]]] = None,
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

    # L1 接地锚点消费（设计 §5.1）：mention→锚点映射，未解析 spec 优先落锚点 BSM
    anchors_by_name: Dict[str, Any] = {}
    for anchor in getattr(context, "grounded_anchors", None) or []:
        name = str(getattr(anchor, "normalized_name", "") or getattr(anchor, "mention", "") or "").strip()
        if not name:
            continue
        anchors_by_name.setdefault(name, anchor)
        if name.endswith("村"):
            anchors_by_name.setdefault(name[:-1], anchor)

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
        # 未解析且命中 L1 接地锚点 → 用锚点 BSM（实体级，同坐标=同实体），
        # 显式 provenance grounded_anchor。
        if not resolved.final_bsms:
            mention = resolver._spec_mention(spec) or ""
            anchor = anchors_by_name.get(mention) or anchors_by_name.get(mention.rstrip("村")) if mention else None
            if anchor is not None:
                anchor_bsms = list(getattr(anchor, "source_bsms", None) or [])
                if anchor_bsms:
                    from app.contracts.spatial.spatial_reference_contracts import ResolvedSpatialRef

                    resolved = ResolvedSpatialRef(
                        final_bsms=anchor_bsms,
                        bbox=None,
                        confidence=max(float(getattr(anchor, "confidence", 0.0) or 0.0), 0.35),
                        uncertainty_radius_m=250.0,
                        uncertainty_reason="grounded_anchor",
                        provenance={
                            "path": "grounded_anchor",
                            "mention": mention,
                            "entity_ref": str(getattr(anchor, "entity_ref", "") or ""),
                        },
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
        if (
            resolved.final_bsms
            or resolved.reference_geometry_wkt
            or getattr(resolved, "reference_geometries", None)
        ):
            metadata = (target_metadata or {}).get(str(getattr(spec, "target_id", "")), {})
            candidate_sites = build_candidate_sites(
                spec,
                resolved,
                index,
                context,
                target_kind=str(metadata.get("target_kind", "unknown")),
                expected_output_kind=str(metadata.get("expected_output_kind", "unknown")),
            )
            valid_candidates = [
                candidate
                for candidate in candidate_sites
                if is_grounding_candidate(candidate)
            ]
            if valid_candidates:
                candidates.extend(valid_candidates)
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

    factors = compile_constraint_factors(intent_graph)
    problem = _build_grounded_problem(
        candidates,
        unresolved,
        factors,
        evaluate_relation_satisfaction(factors, candidates),
        intent_graph,
    )
    relation_satisfaction = problem.relation_satisfaction
    return GroundingResult(
        candidates=candidates,
        unresolved=unresolved,
        spatial_query_evidence=spatial_query_evidence,
        constraint_factors=factors,
        relation_satisfaction=relation_satisfaction,
        problem=problem,
        provenance=provenance,
    )


def _build_grounded_problem(
    candidates: list[CandidateSite],
    unresolved: list[StageIssue],
    factors: list[Any],
    relation_satisfaction: list[Any],
    intent_graph: Any,
) -> GroundedPlanningProblem:
    domains: dict[str, GroundedTargetDomain] = {}
    for candidate in candidates:
        target_id = str(candidate.target_ref or "")
        if not target_id:
            continue
        domain = domains.setdefault(
            target_id,
            GroundedTargetDomain(
                target_id=target_id,
                target_kind=candidate.target_kind,
                expected_output_kind=candidate.expected_output_kind,
                status="unresolved",
            ),
        )
        domain.candidate_site_refs.append(candidate.site_id)
        if candidate.geometry is not None:
            domain.geometry_roles.append(candidate.geometry.role)
        domain.evidence_refs.extend(candidate.evidence_refs)
        pending_constraint_check = (
            candidate.geometry is not None
            and candidate.geometry.hard_constraint_status == "pending"
        )
        if (
            candidate.geometry is not None
            and candidate.geometry.is_executable
            and (
                candidate.geometry.hard_constraint_status == "passed"
                or pending_constraint_check
            )
        ):
            domain.status = "resolved"
        elif candidate.geometry is not None and domain.status != "resolved":
            domain.status = "candidate_only"
        else:
            domain.status = "ambiguous"

    for issue in unresolved:
        target_id = str(issue.related_artifact_id or "")
        if not target_id:
            continue
        domain = domains.setdefault(target_id, GroundedTargetDomain(target_id=target_id))
        domain.unresolved_reason = str(issue.code or issue.message or "unresolved")
        if not domain.candidate_site_refs:
            domain.status = "unresolved"

    for domain in domains.values():
        domain.candidate_site_refs = list(dict.fromkeys(domain.candidate_site_refs))
        domain.geometry_roles = list(dict.fromkeys(domain.geometry_roles))
        domain.evidence_refs = list(dict.fromkeys(domain.evidence_refs))

    fingerprint = str(getattr(intent_graph, "fingerprint", "") or "")
    diagnostics = [
        f"unresolved_target:{domain.target_id}"
        for domain in domains.values()
        if domain.status == "unresolved"
    ]
    diagnostics.extend(
        f"relation_{item.status}:{item.relation_id}"
        for item in relation_satisfaction
        if item.status in {"deferred", "violated", "unknown"}
    )
    return GroundedPlanningProblem(
        target_domains=list(domains.values()),
        constraint_factors=factors,
        relation_satisfaction=relation_satisfaction,
        diagnostics=diagnostics,
        intent_graph_fingerprint=fingerprint,
        candidate_domains=build_candidate_domains(candidates),
        candidate_geometries=[
            candidate.geometry
            for candidate in candidates
            if candidate.geometry is not None
        ],
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
