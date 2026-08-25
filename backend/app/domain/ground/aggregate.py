"""GROUND subgraph aggregate - deterministic orchestrator over SpatialResolver.

Consumes a list of ``SpatialReferenceSpec`` plus a ``PlanningContext`` and
produces a typed ``GroundingResult`` with ``CandidateSite[]`` candidates,
``StageIssue[]`` unresolved items and ``SpatialQueryEvidence[]`` rows.

Pure orchestration: candidate resolution is delegated to the (already-cleaned)
``SpatialResolver.resolve_spec``; no LLM is ever called. Given the same specs
and context the output is fully deterministic.
"""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
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
    GroundingFinding,
)
from app.domain.ground.constraint_factors import (
    attach_evidence_packet_relations,
    compile_constraint_factors,
    evaluate_relation_satisfaction,
)
from app.domain.ground.candidate_domain_builder import (
    build_candidate_domains,
    is_grounding_candidate,
)
from app.domain.common.solver_kind import collect_network_refs, infer_problem_solver_kind
from app.contracts.artifacts.provenance import Provenance
from app.contracts.spatial.spatial_reference_contracts import (
    GeometryRef,
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
    if not geometry_source_refs:
        for geometry_ref in list(getattr(resolved, "reference_geometries", None) or []):
            geometry_source_refs.extend(
                str(item)
                for item in [
                    getattr(geometry_ref, "source_ref", ""),
                    *(getattr(geometry_ref, "source_refs", None) or []),
                ]
                if str(item).strip()
            )
        geometry_source_refs = list(dict.fromkeys(geometry_source_refs))
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
        spatial_domain_kind=str(
            getattr(resolved, "spatial_domain_kind", "") or "unknown"
        ),
        source_parcel_count=len(source_parcels),
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
    resolved_provenance = getattr(resolved, "provenance", {}) or {}
    feature_bsms = list(
        dict.fromkeys(
            str(item)
            for item in (
                getattr(resolved, "feature_bsms", None)
                or resolved_provenance.get("feature_bsms", [])
            )
            if str(item).strip()
        )
    )
    source_feature_ids = list(
        dict.fromkeys(
            str(item)
            for item in (
                getattr(resolved, "source_feature_ids", None)
                or resolved_provenance.get("source_feature_ids", [])
            )
            if str(item).strip()
        )
    )
    entity_refs = list(
        dict.fromkeys(
            str(item)
            for item in (
                getattr(resolved, "entity_refs", None)
                or resolved_provenance.get("entity_refs", [])
            )
            if str(item).strip()
        )
    )
    relation_refs = list(
        dict.fromkeys(
            str(item)
            for item in (
                getattr(resolved, "relation_refs", None)
                or resolved_provenance.get("relation_refs", [])
            )
            if str(item).strip()
        )
    )
    l1_fact_refs = list(
        dict.fromkeys(
            str(item)
            for item in (
                getattr(resolved, "l1_fact_refs", None)
                or resolved_provenance.get("l1_fact_refs", [])
            )
            if str(item).strip()
        )
    )
    candidate_evidence_refs = list(
        dict.fromkeys(
            [
                *source_parcels,
                *geometry_source_refs,
                *feature_bsms,
                *source_feature_ids,
                *entity_refs,
                *relation_refs,
                *l1_fact_refs,
            ]
        )
    )
    geometry = CandidateGeometry(
        target_id=str(getattr(spec, "target_id", "") or ""),
        kind=geometry_kind,
        role=geometry_role,
        candidate_membership=(
            "required_member"
            if _spec_declares_required_source_collection(spec)
            else "alternative"
        ),
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
            else (
                str(getattr(resolved, "spatial_domain_kind", "") or "")
                if str(getattr(resolved, "spatial_domain_kind", "") or "")
                in {"parcel_extent", "bbox", "corridor", "village_scope"}
                else (
                    "parcel_extent"
                    if len(source_parcels) == 1
                    else ("parcel_set" if source_parcels else "none")
                )
            )
        ),
        spatial_domain_kind=str(
            getattr(resolved, "spatial_domain_kind", "") or "unknown"
        ),
        source_area_ha=area_ha or None,
        planning_area_ha=area_ha or None,
        coverage_ratio=1.0 if area_ha > 0 and source_parcels else None,
        candidate_bbox=(
            tuple(float(value) for value in resolved.bbox[:4])
            if getattr(resolved, "bbox", None)
            else (
                tuple(float(value) for value in shapely_wkt.loads(geometry_wkt).bounds)
                if geometry_wkt
                else None
            )
        ),
        source_ref=(
            geometry_source_refs[0]
            if geometry_source_refs
            else str(resolved.provenance.get("path", "") or "")
        ),
        source_refs=geometry_source_refs,
        evidence_refs=candidate_evidence_refs,
        confidence=float(resolved.confidence or 0.0),
        uncertainty_radius_m=uncertainty_radius,
        uncertainty_reason=uncertainty_reason,
        source_bsms=source_parcels,
        feature_bsms=feature_bsms,
        source_feature_ids=source_feature_ids,
        entity_refs=entity_refs,
        relation_refs=relation_refs,
        l1_fact_refs=l1_fact_refs,
        l1_snapshot_ref=str(
            getattr(resolved, "l1_snapshot_ref", "")
            or resolved_provenance.get("l1_snapshot_ref", "")
            or ""
        ),
        bundle_snapshot_digest=str(
            getattr(resolved, "bundle_snapshot_digest", "")
            or resolved_provenance.get("bundle_snapshot_digest", "")
            or ""
        ),
        source_binding_ref=str(
            getattr(resolved, "source_binding_ref", "")
            or resolved_provenance.get("source_binding_ref", "")
            or ""
        ),
        generation_operation=generation_operation,
        hard_constraint_status=hard_constraint_status,
    )
    return CandidateSite(
        site_id=site_id,
        source_parcels=source_parcels,
        available_geometry_wkt=geometry_wkt,
        available_area_ha=area_ha,
        source_area_ha=area_ha,
        coverage_ratio=1.0 if area_ha > 0 and source_parcels else None,
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
            "candidate_membership": (
                "required_member"
                if _spec_declares_required_source_collection(spec)
                else "alternative"
            ),
            "source_parcel_count": len(resolved.final_bsms),
            "spatial_domain_kind": str(
                getattr(resolved, "spatial_domain_kind", "") or "unknown"
            ),
            "candidate_bbox": (
                list(resolved.bbox[:4]) if getattr(resolved, "bbox", None) else None
            ),
        },
        evidence_refs=candidate_evidence_refs,
        target_ref=(getattr(spec, "target_id", None) or None),
        project_ref=(getattr(spec, "project_ref", None) or None),
        confidence=resolved.confidence,
        uncertainty=uncertainty,
        target_kind=target_kind,
        expected_output_kind=expected_output_kind,
        geometry=geometry,
        candidate_bbox=geometry.candidate_bbox,
    )


def _spec_declares_required_source_collection(spec: Any) -> bool:
    """Return whether typed projection bound a complete source collection.

    A multi-feature Bundle result is normally a set of identity alternatives.
    Only an explicit collection binding with more than one exact source
    feature turns those records into jointly required members.  This keeps
    same-name facilities and hazard points out of ``all_members`` without
    relying on names, regexes, or geometry kinds.
    """

    collection_key = str(
        getattr(spec, "source_collection_key", "") or ""
    ).strip()
    reference = getattr(spec, "reference", None)
    filters = getattr(reference, "filter", None) or {}
    source_feature_ids = [
        str(value).strip()
        for value in (
            filters.get("source_feature_ids")
            or filters.get("exact_feature_ids")
            or []
        )
        if str(value).strip()
    ]
    if collection_key and len(set(source_feature_ids)) > 1:
        return True
    return any(
        _spec_declares_required_source_collection(child)
        for child in (getattr(spec, "children", None) or [])
    )


def _unique_evidence_geometry(context: Any, mention: str) -> Any:
    """Return one source-backed point geometry for an unbound facility mention."""
    graph = getattr(context, "evidence_graph", None)
    if graph is None or not mention or not hasattr(graph, "resolve_mention"):
        return None
    normalized_mention = str(mention).strip()
    facts = list(getattr(context, "location_facts", None) or [])
    role_markers = {"facility", "设施", "现状设施", "公共服务设施", "landmark"}
    has_facility_fact = any(
        normalized_mention
        in {
            str(getattr(fact, "mention", "") or "").strip(),
            str(getattr(fact, "normalized_name", "") or "").strip(),
        }
        and str(getattr(fact, "role", "") or "").strip() in role_markers
        for fact in facts
    )
    if facts and not has_facility_fact:
        return None
    cache = getattr(context, "_facility_geometry_cache", None)
    if cache is None:
        cache = {}
        setattr(context, "_facility_geometry_cache", cache)
    if normalized_mention in cache:
        return cache[normalized_mention]
    try:
        result = graph.resolve_mention(normalized_mention, role="facility")
    except Exception:
        return None
    workspace = getattr(context, "workspace", None)
    points = getattr(workspace, "points", None) if workspace is not None else None

    def _bundle_point_for_bsm(bsm: str) -> Any | None:
        if not bsm or points is None:
            return None
        for layer_name in ("facilities_current", "annotations_current"):
            try:
                layer = points.get(layer_name) if hasattr(points, "get") else None
                for feature in list(layer or []):
                    if str(getattr(feature, "bsm", "") or "").strip() != bsm:
                        continue
                    raw_geometry = getattr(feature, "geometry", None)
                    geometry = shape(raw_geometry) if isinstance(raw_geometry, dict) else raw_geometry
                    if geometry is not None and not geometry.is_empty and geometry.geom_type == "Point":
                        return geometry
            except Exception:
                continue
        return None

    spatial = []
    for candidate in list(getattr(result, "candidates", None) or []):
        feature_bsm = str(
            getattr(candidate, "feature_bsm", "")
            or getattr(candidate, "source_bsm", "")
            or ""
        ).strip()
        geometry = _bundle_point_for_bsm(feature_bsm)
        if geometry is None:
            continue
        spatial.append((candidate, geometry))
    if len(spatial) != 1:
        if len(cache) >= 64:
            cache.clear()
        cache[normalized_mention] = None
        return None
    candidate, point_geometry = spatial[0]
    feature_bsm = str(
        getattr(candidate, "feature_bsm", "")
        or getattr(candidate, "source_bsm", "")
        or ""
    ).strip()
    geometry_ref = point_geometry.wkt
    geometry = GeometryRef(
        wkt=geometry_ref,
        source_ref=str(getattr(candidate, "entity_ref", "") or feature_bsm),
        source_refs=list(
            dict.fromkeys(
                [
                    str(getattr(candidate, "entity_ref", "") or ""),
                    *list(getattr(candidate, "evidence_refs", None) or []),
                ]
            )
        ),
        source_bsms=list(
            dict.fromkeys(
                str(item)
                for item in (
                    getattr(candidate, "related_parcel_bsms", None)
                    or getattr(candidate, "source_bsms", None)
                    or []
                )
                if str(item).strip()
            )
        ),
        feature_bsms=[feature_bsm] if feature_bsm else [],
        feature_kind="facility_point",
    )
    if len(cache) >= 64:
        cache.clear()
    cache[normalized_mention] = geometry
    return geometry


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
    its source semantics. If parcel geometry is unavailable, one unresolved
    candidate is retained and remains fail-closed.
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

    if (
        resolved.reference_geometry_wkt
        or len(source_parcels) <= 1
        or str(getattr(resolved, "spatial_domain_kind", "") or "")
        in {"bbox", "corridor", "village_scope"}
    ):
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


def _valid_anchor_geometry_wkt(value: Any) -> str | None:
    """Return canonical WKT only for valid non-empty anchor geometry."""
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        geometry = shapely_wkt.loads(raw)
    except Exception:
        return None
    if geometry.is_empty or not geometry.is_valid:
        return None
    if geometry.geom_type not in {
        "Point",
        "LineString",
        "MultiLineString",
        "Polygon",
        "MultiPolygon",
    }:
        return None
    return geometry.wkt


def _geometry_role(
    geometry_kind: str,
    *,
    target_kind: str,
    expected_output_kind: str,
    has_source_parcels: bool,
    uncertainty_reason: str = "",
    spatial_domain_kind: str = "unknown",
    source_parcel_count: int = 0,
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
        if (
            "coarse" in str(uncertainty_reason or "").lower()
            or spatial_domain_kind in {"bbox", "corridor", "village_scope"}
            or (spatial_domain_kind == "parcel_set" and source_parcel_count > 1)
        ):
            if expected_output_kind == "line":
                return "corridor_candidate"
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
    evidence_packets: Optional[Dict[str, Any]] = None,
    ground_llm_budget: Optional[Dict[str, Any]] = None,
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
    resolver = (
        SpatialResolver(context, ground_llm_budget=ground_llm_budget)
        if ground_llm_budget is not None
        else SpatialResolver(context)
    )

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
        # EvidenceGraph / gazetteer / directional fallbacks; specs that
        # cannot be bound stay unresolved and enter the HUMAN gate.
        resolve_kwargs = {"mention_enhancements": mention_enhancements}
        if evidence_packets is not None:
            resolve_kwargs["evidence_packet"] = (evidence_packets or {}).get(
                str(getattr(spec, "target_id", "") or "")
            )
        resolved = resolver.resolve_spec(spec, **resolve_kwargs)
        mention = resolver._spec_mention(spec) or ""
        evidence_geometry = _unique_evidence_geometry(context, mention)
        if evidence_geometry is not None and not resolved.reference_geometries:
            resolved = replace(
                resolved,
                final_bsms=list(resolved.final_bsms),
                reference_geometry_wkt=evidence_geometry.wkt,
                reference_geometries=[evidence_geometry],
                feature_bsms=list(
                    dict.fromkeys(
                        [
                            *list(getattr(resolved, "feature_bsms", None) or []),
                            *list(getattr(evidence_geometry, "feature_bsms", None) or []),
                        ]
                    )
                ),
                source_feature_ids=list(getattr(resolved, "source_feature_ids", None) or []),
                entity_refs=list(
                    dict.fromkeys(
                        [
                            *list(getattr(resolved, "entity_refs", None) or []),
                            *list(evidence_geometry.source_refs or []),
                        ]
                    )
                ),
                provenance={
                    **dict(resolved.provenance or {}),
                    "path": f"{str((resolved.provenance or {}).get('path', '') or 'resolve_spec')}+evidence_geometry",
                },
            )
        # 未解析且命中 L1 接地锚点 → 用锚点 BSM（实体级，同坐标=同实体），
        # 显式 provenance grounded_anchor。
        if not resolved.final_bsms:
            mention = resolver._spec_mention(spec) or ""
            anchor = anchors_by_name.get(mention) or anchors_by_name.get(mention.rstrip("村")) if mention else None
            if anchor is not None:
                anchor_bsms = list(getattr(anchor, "source_bsms", None) or [])
                anchor_geometry_wkt = _valid_anchor_geometry_wkt(
                    getattr(anchor, "geometry_ref", "")
                )
                if anchor_bsms or anchor_geometry_wkt:
                    resolved = replace(
                        resolved,
                        final_bsms=anchor_bsms,
                        bbox=None,
                        reference_geometry_wkt=anchor_geometry_wkt,
                        reference_geometries=[],
                        spatial_domain_kind=(
                            "exact_feature"
                            if anchor_geometry_wkt
                            else ("parcel_extent" if len(anchor_bsms) == 1 else "parcel_set")
                        ),
                        confidence=max(float(getattr(anchor, "confidence", 0.0) or 0.0), 0.35),
                        uncertainty_radius_m=250.0,
                        uncertainty_reason="grounded_anchor",
                        provenance={
                            "path": "grounded_anchor",
                            "mention": mention,
                            "entity_ref": str(getattr(anchor, "entity_ref", "") or ""),
                            "geometry_ref": anchor_geometry_wkt or "",
                        },
                    )
        mention = resolver._spec_mention(spec) or ""
        anchor = (
            anchors_by_name.get(mention)
            or anchors_by_name.get(mention.rstrip("村"))
            if mention
            else None
        )
        anchor_geometry_wkt = _valid_anchor_geometry_wkt(
            getattr(anchor, "geometry_ref", "") if anchor is not None else ""
        )
        anchor_bsms = list(getattr(anchor, "source_bsms", None) or []) if anchor is not None else []
        if (
            not resolved.reference_geometry_wkt
            and (anchor_geometry_wkt or anchor_bsms)
        ):
            resolved = replace(
                resolved,
                final_bsms=anchor_bsms or list(resolved.final_bsms),
                bbox=resolved.bbox,
                reference_geometry_wkt=anchor_geometry_wkt,
                reference_geometries=list(resolved.reference_geometries or []),
                spatial_domain_kind=(
                    "exact_feature"
                    if anchor_geometry_wkt
                    else ("parcel_extent" if len(anchor_bsms) == 1 else "parcel_set")
                ),
                confidence=max(
                    float(resolved.confidence or 0.0),
                    float(getattr(anchor, "confidence", 0.0) or 0.0),
                ),
                uncertainty_radius_m=float(
                    getattr(anchor, "uncertainty_radius_m", 0.0) or 0.0
                ),
                uncertainty_reason="grounded_anchor",
                provenance={
                    "path": "grounded_anchor",
                    "mention": mention,
                    "entity_ref": str(getattr(anchor, "entity_ref", "") or ""),
                    "geometry_ref": anchor_geometry_wkt,
                    "resolver_path": str(
                        (resolved.provenance or {}).get("path", "")
                    ),
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
            if (
                str(metadata.get("expected_output_kind", "")) == "line"
                and str(getattr(resolved, "spatial_domain_kind", "") or "unknown")
                != "exact_feature"
            ):
                resolved = replace(resolved, spatial_domain_kind="corridor")
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

    if evidence_packets:
        seen_packet_relation_ids: set[str] = set()
        for target_id, packet in dict(evidence_packets or {}).items():
            for relation in list(getattr(packet, "relation_evidence", None) or [])[:16]:
                relation_id = str(getattr(relation, "relation_id", "") or "").strip()
                if not relation_id or relation_id in seen_packet_relation_ids:
                    continue
                seen_packet_relation_ids.add(relation_id)
                subject = getattr(relation, "subject", None)
                object_ = getattr(relation, "object", None)
                subject_identity = getattr(subject, "identity", None)
                object_identity = getattr(object_, "identity", None)
                relation_refs = [
                    relation_id,
                    str(getattr(subject_identity, "bundle_feature_bsm", "") or ""),
                    str(getattr(object_identity, "bundle_feature_bsm", "") or ""),
                    str(getattr(subject, "geometry_ref", "") or ""),
                    str(getattr(object_, "geometry_ref", "") or ""),
                    *(getattr(relation, "provenance_refs", None) or []),
                ]
                spatial_query_evidence.append(
                    SpatialQueryEvidence(
                        query_type="evidence_packet_relation",
                        query_params={
                            "target_id": str(target_id),
                            "relation_id": relation_id,
                            "predicate": str(getattr(relation, "predicate", "") or ""),
                            "metric_value": getattr(relation, "metric_value", None),
                            "metric_unit": str(getattr(relation, "metric_unit", "") or ""),
                        },
                        result_count=1,
                        result_refs=list(dict.fromkeys(
                            str(value) for value in relation_refs if str(value).strip()
                        )),
                        target_id=str(target_id),
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

    network_snapshots = getattr(context, "networks", None) or {}
    current_network = network_snapshots.get("network:road:current")
    factors = compile_constraint_factors(
        intent_graph,
        default_network_ref=(
            "network:road:current" if current_network is not None else ""
        ),
        default_endpoint_tolerance_m=float(
            getattr(current_network, "snap_tolerance_m", 5.0) or 5.0
        ),
    )
    factors = attach_evidence_packet_relations(factors, evidence_packets)
    problem = _build_grounded_problem(
        candidates,
        unresolved,
        factors,
        evaluate_relation_satisfaction(factors, candidates),
        intent_graph,
    )
    from app.evidence.retrieval.requirements import requirements_from_ground

    problem.evidence_requirements = list(requirements_from_ground(problem))
    relation_satisfaction = problem.relation_satisfaction
    return GroundingResult(
        candidates=candidates,
        unresolved=unresolved,
        spatial_query_evidence=spatial_query_evidence,
        constraint_factors=factors,
        relation_satisfaction=relation_satisfaction,
        problem=problem,
        provenance=provenance,
        evidence_requirements=list(problem.evidence_requirements),
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
    grounding_findings = [
        GroundingFinding(
            code=str(issue.code or "grounding_unresolved"),
            severity=(
                "error"
                if str(issue.severity or "warning") == "error"
                else "warning"
            ),
            message=str(issue.message or issue.detail or issue.code or "grounding unresolved"),
            target_id=str(issue.related_artifact_id or ""),
        )
        for issue in unresolved
    ]
    candidate_domains = build_candidate_domains(candidates)
    candidate_geometries = [
        candidate.geometry
        for candidate in candidates
        if candidate.geometry is not None
    ]
    upstream_solver_kind = str(
        getattr(intent_graph, "solver_kind", "auto") or "auto"
    )
    shared_resource_refs = list(
        getattr(intent_graph, "shared_resource_refs", None) or []
    )
    inferred_kind, solver_kind_reasons = infer_problem_solver_kind(SimpleNamespace(
        solver_kind=upstream_solver_kind,
        solver_kind_reasons=list(
            getattr(intent_graph, "solver_kind_reasons", None) or []
        ),
        constraint_factors=factors,
        shared_resource_refs=shared_resource_refs,
        candidate_geometries=candidate_geometries,
        target_domains=list(domains.values()),
        candidate_domains=candidate_domains,
    ))
    solver_kind = (
        inferred_kind
        if inferred_kind in {
            "coverage",
            "parcel_assignment",
            "network_path",
            "topology_layout",
        }
        else "auto"
    )
    network_refs = collect_network_refs(SimpleNamespace(
        network_refs=[],
        constraint_factors=factors,
    ))
    diagnostics.extend(
        f"solver_kind:{solver_kind}:{reason}"
        for reason in solver_kind_reasons
    )
    return GroundedPlanningProblem(
        solver_kind=solver_kind,
        solver_kind_reasons=solver_kind_reasons,
        target_domains=list(domains.values()),
        constraint_factors=factors,
        relation_satisfaction=relation_satisfaction,
        diagnostics=diagnostics,
        intent_graph_fingerprint=fingerprint,
        candidate_domains=candidate_domains,
        candidate_geometries=candidate_geometries,
        network_refs=network_refs,
        shared_resource_refs=shared_resource_refs,
        unresolved=grounding_findings,
    )


def _ground_external_policy(enabled: bool) -> Any | None:
    if not enabled:
        return None
    from app.evidence.retrieval.external_search_policy import ExternalSearchPolicy

    return ExternalSearchPolicy(allowed_dimensions=["location"])


async def retrieve_evidence(
    context: Any,
    evidence_requests: Optional[List[str]] = None,
) -> List[SpatialQueryEvidence]:
    """Re-check GROUND gaps through the canonical EXPLORE evidence service.

    The stage contract still exposes ``SpatialQueryEvidence`` rows, so this
    adapter summarizes the bounded ``ExplorationResult`` without copying full
    reports or geometry.  Bundle layer counts remain useful diagnostics, but
    feature identities, L1 facts and KG topology now come from the same
    evidence path used by the public query and LLM tools.
    """
    rows: List[SpatialQueryEvidence] = []
    try:
        if context is None:
            return rows

        requests = [
            " ".join(str(item).split())
            for item in (evidence_requests or [])
            if " ".join(str(item).split())
        ]
        session_id = str(getattr(context, "session_id", "") or "").strip()
        if session_id and requests:
            from app.contracts.evidence.evidence_contracts import ExplorationRequest
            from app.evidence.retrieval.evidence_service import retrieve_evidence as retrieve

            query = "；".join(requests)[:1200]
            external_requested = any(
                token in query.casefold()
                for token in ("external", "外源", "网络", "web", "最新", "法规", "政策")
            )
            request = ExplorationRequest(
                run_id=session_id,
                request_type="evidence_gap",
                query=query,
                context_refs=["source:external"] if external_requested else [],
                stage="GROUND",
                dimension_key="location",
                query_purpose="gap_resolution",
                questions=requests[:8],
                required_facts=requests[:8],
                entity_scope=["facilities", "parcels", "roads", "waters"],
            )
            result = await retrieve(
                request,
                session_id,
                village_name=str(getattr(context, "village_name", "") or ""),
                external_port=getattr(context, "external_search_port", None),
                external_policy=getattr(context, "external_search_policy", None)
                or _ground_external_policy(external_requested),
            )
            packet = getattr(result, "evidence_packet", None)
            bundle = getattr(result, "evidence_bundle", None)
            packet_refs = []
            if packet is not None:
                for candidate in list(getattr(packet, "candidate_refs", None) or []):
                    identity = getattr(candidate, "identity", None)
                    for value in (
                        getattr(candidate, "geometry_ref", None),
                        getattr(identity, "bundle_feature_bsm", None),
                        *(getattr(candidate, "entity_refs", None) or []),
                    ):
                        if str(value or "").strip():
                            packet_refs.append(str(value))
                for relation in list(getattr(packet, "relation_evidence", None) or []):
                    if str(getattr(relation, "relation_id", "") or "").strip():
                        packet_refs.append(str(relation.relation_id))
            fact_refs = [
                str(value)
                for fact in list(getattr(bundle, "facts", None) or [])
                for value in [*(getattr(fact, "spatial_refs", None) or []), *(getattr(fact, "source_refs", None) or [])]
                if str(value or "").strip()
            ]
            refs = list(dict.fromkeys([*packet_refs, *fact_refs]))[:48]
            facts = list(getattr(bundle, "facts", None) or [])
            rows.append(
                SpatialQueryEvidence(
                    query_type="evidence:unified",
                    query_params={
                        "query": query,
                        "sufficiency": str(getattr(packet, "sufficiency", "") or ""),
                        "fact_count": len(facts),
                        "candidate_count": len(getattr(packet, "candidate_refs", None) or []) if packet is not None else 0,
                    },
                    result_count=len(refs),
                    result_refs=refs,
                )
            )

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

        if requests:
            rows.append(
                SpatialQueryEvidence(
                    query_type="retry:evidence_requests",
                    query_params={"requests": requests},
                    result_count=len(requests),
                    result_refs=requests,
                )
            )
    except Exception:
        return []
    return rows


__all__ = ["ground_aggregate", "build_candidate_site", "retrieve_evidence"]
