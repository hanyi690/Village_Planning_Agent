"""GROUND application boundary - bounded reasoning over SpatialResolver.

The application exposes two entry points: L1 semantic location resolution and
post-TARGET planning-target grounding.  The former produces reusable identity
bindings; the latter consumes typed ``SpatialReferenceSpec`` values and
produces a ``GroundingResult`` with ``CandidateSite[]`` candidates,
``StageIssue[]`` unresolved items and ``SpatialQueryEvidence[]`` rows.

Deterministic validation and geometry materialization remain here, while
``SpatialResolver.resolve_spec`` may invoke the bounded GROUND LLM to choose
among retrieval candidates. The model can only select an existing candidate;
it cannot create identity, membership, or geometry.
"""
from __future__ import annotations

from dataclasses import replace
from time import perf_counter
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from shapely import wkt as shapely_wkt
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from app.infrastructure.context_runtime.runtime import PlanningContext
from app.contracts.artifacts.contract_meta import StageIssue
from app.contracts.ground.grounding_contracts import (
    CandidateSite,
    CandidateUncertainty,
    GroundingResult,
    HardConstraintResult,
    SpatialQueryEvidence,
)
from app.contracts.ground.candidate_geometry import CandidateGeometry
from app.contracts.ground.grounded_problem import (
    GroundedPlanningProblem,
    GroundedTargetDomain,
    GroundingBinding,
    GroundingFinding,
)
from app.modules.ground.constraint_check import (
    attach_evidence_packet_relations,
    compile_constraint_factors,
    evaluate_relation_satisfaction,
)
from app.modules.ground.candidate_builder import (
    build_candidate_domains,
    is_grounding_candidate,
)
from app.core.common.solver_kind import collect_network_refs, infer_problem_solver_kind
from app.contracts.artifacts.provenance import Provenance
from app.contracts.ground.spatial_reference_contracts import (
    GeometryRef,
    ResolvedSpatialRef,
    SpatialReferenceSpec,
)
from app.spatial.grounding.resolver import SpatialResolver


def _run_async_from_sync(coro: Any) -> Any:
    """Run one async runtime operation from a sync GROUND entry point.

    L1 sidecar materialization is also exposed to synchronous recovery and
    command-line callers.  When a caller already owns an event loop, execute
    the short-lived orchestration in a worker thread instead of nesting
    ``asyncio.run``.  The operation itself still uses the current session
    context and never opens a historical-session channel.
    """

    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="ground-evidence") as executor:
        return executor.submit(asyncio.run, coro).result()


async def _retrieve_l1_evidence_packets(
    context: PlanningContext,
    mentions: list[Any],
    observations: list[Any],
    *,
    round_index: int = 0,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Retrieve current L1 location evidence through the unified facade."""

    from app.contracts.evidence.requirement_contracts import EvidenceRequirement
    from app.modules.evidence.application import EvidenceApplication, EvidenceContext
    from app.modules.ground.reference_resolution import _mention_spec

    session_id = str(getattr(context, "session_id", "") or "").strip()
    if not session_id:
        return {}, [{"status": "skipped", "reason": "missing_session_id"}]
    evidence = EvidenceApplication()
    packets: dict[str, Any] = {}
    diagnostics: list[dict[str, Any]] = []

    async def retrieve_one(mention: Any, observation: Any) -> None:
        observation_id = str(
            getattr(observation, "observation_id", "") or ""
        ).strip()
        name = str(
            getattr(mention, "normalized_name", "")
            or getattr(mention, "mention", "")
            or ""
        ).strip()
        if not observation_id or not name:
            return
        spec = _mention_spec(mention, observation_id, context)
        requirement = EvidenceRequirement(
            requirement_id=f"{session_id}:ground:l1:{observation_id}:r{round_index}",
            request_id=f"{session_id}:ground:l1-location:r{round_index}",
            producer_stage="GROUND",
            statement=(
                f"定位当前 L1 地点工作项：{name}"
                + (
                    f"；GROUND补充定位轮次={round_index}；重新检查当前源中的候选、"
                    "关系和空间引用，仅返回可验证来源证据，不生成新身份或几何"
                    if round_index > 0
                    else ""
                )
            ),
            kind="spatial",
            source_families=(
                "data",
                "gis",
                "kg",
                "artifact",
                "external_map_cache",
            ),
            scope=tuple(spec.all_retrieval_scopes()),
            spatial_granularity="feature",
            allowed_inference="exact",
            evidence_role="location_binding",
            success_condition="返回当前源中的候选、来源定位和可验证的空间引用",
            metadata={
                "observation_ref": observation_id,
                "mention": name,
                "role": str(getattr(mention, "role", "") or "unknown"),
                "entry_point": "l1_direct_grounding",
                "ground_round": round_index,
                "selection_cardinality": "one",
            },
        )
        try:
            from app.workflow.cognition_context import open_cognition_round

            cognition_round = open_cognition_round(
                context,
                (requirement,),
                workflow_run_id=f"{session_id}:ground:l1-location:r{round_index}",
                branch_id="main",
                round_number=round_index,
                max_rounds=16,
            )
            evidence_context = EvidenceContext.from_runtime_context(
                context,
                session_id=session_id,
                run_id=f"{session_id}:ground:l1-location:r{round_index}",
                stage="GROUND",
                dimension_key="location",
                purpose=f"l1_location_resolution:round:{round_index}",
                request_type="spatial_lookup",
                cognition_round=cognition_round,
                context_refs=tuple(
                    value
                    for value in (
                        str(getattr(context, "l1_snapshot_ref", "") or ""),
                    )
                    if value
                ),
            )
            result = await evidence.retrieve(
                requirement,
                evidence_context,
                spatial_spec=spec,
                candidate_offset=0,
                candidate_limit=16,
            )
            packet = getattr(result, "evidence_packet", None)
            if packet is not None:
                missing = list(
                    getattr(packet, "missing_evidence", None) or []
                )
                if (
                    getattr(packet, "candidates_truncated", False)
                    or getattr(packet, "next_candidate_offset", None) is not None
                ):
                    missing.append("l1_candidate_set_bounded_to_first_16")
                packet = packet.model_copy(update={
                    "candidate_refs": list(
                        getattr(packet, "candidate_refs", None) or []
                    )[:16],
                    "candidate_offset": 0,
                    "candidate_limit": 16,
                    "missing_evidence": list(dict.fromkeys(missing))[:12],
                })
            if packet is not None:
                packets[observation_id] = packet
            coverage = getattr(result, "coverage", None)
            diagnostics.append({
                "observation_ref": observation_id,
                "status": "packet" if packet is not None else "empty",
                "page_count": 1 if packet is not None else 0,
                "candidate_count": len(
                    getattr(packet, "candidate_refs", None) or []
                ) if packet is not None else 0,
                "candidate_total": int(
                    getattr(packet, "candidate_total", 0) or 0
                ) if packet is not None else 0,
                "coverage": str(
                    getattr(coverage, "stop_reason", "") or ""
                ),
                "unresolved_requirements": list(
                    getattr(coverage, "unresolved_requirements", None) or []
                )[:4] if coverage is not None else [],
            })
        except Exception as exc:  # noqa: BLE001 - keep one mention auditable
            diagnostics.append({
                "observation_ref": observation_id,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            })

    await __import__("asyncio").gather(
        *(retrieve_one(mention, observation)
          for mention, observation in zip(mentions, observations))
    )
    return packets, diagnostics


def _load_l1_evidence_packets(
    state: Mapping[str, Any],
    mentions: list[Any],
    observations: list[Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Reload the exact L1 Evidence receipts before scheduling more work."""

    from pathlib import Path

    from app.contracts.artifacts.ref import ArtifactRef
    from app.contracts.evidence.retrieval_artifact_contracts import (
        EvidenceRetrievalArtifact,
    )
    from app.infrastructure.artifacts import (
        ContentAddressedArtifactRepository,
    )
    from app.infrastructure.paths import run_tmp_root

    artifact_root = str(state.get("artifact_root") or "").strip()
    repository = ContentAddressedArtifactRepository(
        Path(artifact_root).resolve() if artifact_root else run_tmp_root()
    )
    run_id = str(state.get("run_id") or state.get("session_id") or "")
    branch_id = str(state.get("branch_id") or "main")
    context_fingerprint = str(state.get("context_fingerprint") or "")
    world_model_digest = str(
        state.get("world_model_snapshot_digest")
        or (state.get("context_ref") or {}).get(
            "world_model_snapshot_digest"
        )
        or ""
    )
    valid_work_items = {
        str(getattr(item, "observation_id", "") or "")
        for item in observations
    }
    selected: dict[str, tuple[tuple[int, str], Any]] = {}
    diagnostics: list[dict[str, Any]] = []
    seen_descriptors: set[str] = set()
    for mention in mentions:
        for raw_ref in list(
            getattr(mention, "evidence_artifact_refs", None) or []
        ):
            ref = ArtifactRef.model_validate(raw_ref)
            if ref.descriptor_digest in seen_descriptors:
                continue
            seen_descriptors.add(ref.descriptor_digest)
            if ref.run_id != run_id or ref.branch_id != branch_id:
                raise RuntimeError(
                    "L1 Evidence receipt belongs to another run or branch"
                )
            if ref.schema_id != "EvidenceRetrievalArtifact":
                raise RuntimeError(
                    "LocationMention carries a non-retrieval Evidence ref"
                )
            artifact = EvidenceRetrievalArtifact.model_validate(
                repository.get_json(ref)
            )
            if artifact.fingerprint != str(
                ref.provenance.get("fingerprint") or ""
            ):
                raise RuntimeError("L1 Evidence receipt fingerprint mismatch")
            authority = artifact.authority
            if (
                authority.workflow_run_id != run_id
                or authority.branch_id != branch_id
                or (
                    context_fingerprint
                    and authority.context_fingerprint != context_fingerprint
                )
                or (
                    world_model_digest
                    and authority.world_model_snapshot_digest
                    != world_model_digest
                )
            ):
                raise RuntimeError("L1 Evidence receipt authority mismatch")
            requirements = list(
                artifact.canonical_request.requirements or []
            )
            if len(requirements) != 1:
                raise RuntimeError(
                    "L1 location Evidence receipt must have one requirement"
                )
            requirement = requirements[0]
            metadata = dict(requirement.metadata or {})
            work_item_ref = str(
                metadata.get("location_work_item_key") or ""
            )
            if (
                requirement.evidence_role != "l1_location_identity"
                or work_item_ref not in valid_work_items
            ):
                raise RuntimeError(
                    "L1 Evidence receipt does not match this location work item"
                )
            generation = int(metadata.get("recovery_generation") or 0)
            rank = (generation, artifact.fingerprint)
            previous = selected.get(work_item_ref)
            if previous is None or rank > previous[0]:
                selected[work_item_ref] = (rank, artifact)

    packets: dict[str, Any] = {}
    for work_item_ref, (_rank, artifact) in sorted(selected.items()):
        packets[work_item_ref] = artifact.evidence_packet
        diagnostics.append({
            "observation_ref": work_item_ref,
            "status": "reused_l1_receipt",
            "fingerprint": artifact.fingerprint,
            "outcome": artifact.outcome.status,
            "candidate_total": artifact.evidence_packet.candidate_total,
            "candidate_identity_total": (
                artifact.evidence_packet.candidate_identity_total
            ),
            "cache_retrieval_avoided": True,
        })
    return packets, diagnostics


def _merge_l1_evidence_packet_maps(
    current: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """Merge current-source L1 evidence waves without losing candidate pages."""

    merged = dict(current or {})
    for observation_id, packet in dict(incoming or {}).items():
        if packet is None:
            continue
        previous = merged.get(observation_id)
        if previous is None:
            merged[observation_id] = packet
            continue
        refs: list[Any] = []
        seen_refs: set[str] = set()
        relations: list[Any] = []
        seen_relations: set[str] = set()
        source_spans: list[str] = []
        missing: list[str] = []
        traces: list[dict[str, Any]] = []
        for page in (previous, packet):
            for ref in list(getattr(page, "candidate_refs", None) or []):
                key = str(
                    getattr(ref, "candidate_id", "")
                    or getattr(getattr(ref, "identity", None), "source_feature_id", "")
                    or ref
                )
                if key and key not in seen_refs:
                    seen_refs.add(key)
                    refs.append(ref)
            for relation in list(getattr(page, "relation_evidence", None) or []):
                key = str(getattr(relation, "relation_id", "") or "")
                if key and key not in seen_relations:
                    seen_relations.add(key)
                    relations.append(relation)
            for value in (getattr(page, "source_spans", None) or []):
                text = str(value).strip()
                if text and text not in source_spans:
                    source_spans.append(text)
            missing.extend(
                str(value).strip()
                for value in (getattr(page, "missing_evidence", None) or [])
                if str(value).strip()
            )
            traces.extend(
                item
                for item in (getattr(page, "query_trace", None) or [])
                if isinstance(item, dict)
            )
        incomplete = bool(
            getattr(previous, "candidates_truncated", False)
            or getattr(previous, "next_candidate_offset", None) is not None
            or getattr(packet, "candidates_truncated", False)
            or getattr(packet, "next_candidate_offset", None) is not None
        )
        merged[observation_id] = previous.model_copy(update={
            "candidate_refs": refs,
            "candidate_total": max(
                len(refs),
                int(getattr(previous, "candidate_total", 0) or 0),
                int(getattr(packet, "candidate_total", 0) or 0),
            ),
            "candidate_offset": 0,
            "candidates_truncated": incomplete,
            "next_candidate_offset": (
                getattr(packet, "next_candidate_offset", None)
                if incomplete
                else None
            ),
            "ambiguity_status": (
                "multiple"
                if len(refs) > 1
                else "resolved"
                if len(refs) == 1 and not incomplete
                else str(getattr(packet, "ambiguity_status", "unresolved") or "unresolved")
            ),
            "relation_evidence": relations,
            "source_spans": source_spans[:24],
            "missing_evidence": list(dict.fromkeys(missing))[:16],
            "query_trace": traces[-64:],
        })
    return merged


def _attach_l1_binding_source_mentions(
    bindings: list[Any],
    observations: list[Any],
) -> list[Any]:
    """Retain every source row behind one deduplicated identity work item."""

    sources_by_work_item = {
        str(getattr(item, "observation_id", "") or ""): list(
            getattr(item, "source_mention_refs", None) or []
        )
        for item in observations
    }
    return [
        binding.model_copy(update={
            "observation_refs": list(dict.fromkeys([
                str(getattr(binding, "mention_ref", "") or ""),
                *sources_by_work_item.get(
                    str(getattr(binding, "mention_ref", "") or ""),
                    [],
                ),
            ])),
        })
        for binding in bindings
    ]


def _l1_retry_observations(bindings: list[Any]) -> set[str]:
    """Return only L1 observations still requiring semantic re-evaluation."""

    return {
        str(getattr(binding, "mention_ref", "") or "").strip()
        for binding in bindings
        if (
            str(
                getattr(binding, "identity_status", "unresolved")
                or "unresolved"
            ) in {"ambiguous", "unresolved"}
            or str(
                getattr(binding, "location_expression_status", "none")
                or "none"
            ) in {"ambiguous", "unresolved"}
        )
        and str(getattr(binding, "mention_ref", "") or "").strip()
    }


def build_candidate_site(
    spec: SpatialReferenceSpec,
    resolved: ResolvedSpatialRef,
    index: int,
    context: Optional[PlanningContext] = None,
    *,
    target_kind: str = "unknown",
    expected_output_kind: str = "unknown",
    materialization_role: str = "",
    source_parcels_override: Optional[List[str]] = None,
    geometry_wkt_override: Optional[str] = None,
    source_refs_override: Optional[List[str]] = None,
    reference_geometry_override: Any = None,
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
    # DATA features do not expose the historical ``area_sqm`` parcel field.
    # Derive an area only from their authoritative geometry when possible so
    # large unnamed polygons retain a usable planning extent.  The area
    # engine handles geographic and projected CRS without making the DATA
    # schema depend on a particular attribute name.
    if area_ha <= 0 and not source_parcels and geometry_wkt:
        try:
            from app.spatial.model.area_engine import calculate_area_ha

            derived_area_ha = float(calculate_area_ha(shapely_wkt.loads(geometry_wkt)))
            if derived_area_ha > 0:
                area_ha = derived_area_ha
        except Exception:
            area_ha = 0.0
    geometry_source_refs = list(
        dict.fromkeys(str(item) for item in (source_refs_override or []) if str(item).strip())
    )
    representation_refs: list[str] = []
    reference_geometries = (
        [reference_geometry_override]
        if reference_geometry_override is not None
        else list(getattr(resolved, "reference_geometries", None) or [])
    )
    for geometry_ref in reference_geometries:
        representation_ref = str(getattr(geometry_ref, "representation_ref", "") or "").strip()
        if representation_ref:
            representation_refs.append(representation_ref)
        if not geometry_source_refs:
            geometry_source_refs.extend(
                str(item)
                for item in [
                    getattr(geometry_ref, "source_ref", ""),
                    *(getattr(geometry_ref, "source_refs", None) or []),
                ]
                if str(item).strip()
            )
    geometry_source_refs = list(dict.fromkeys(geometry_source_refs))
    representation_refs = list(dict.fromkeys(representation_refs))
    first_reference = reference_geometries[0] if reference_geometries else None
    # ``source_snapshot_ref`` is an audit identifier, never a CRS fallback.
    # A missing representation CRS therefore resolves to the catalog's
    # canonical normalized CRS instead of emitting an invalid snapshot id as
    # a coordinate system.
    reference_crs = str(getattr(first_reference, "crs", "") or "EPSG:4326")
    reference_source_crs = str(getattr(first_reference, "source_crs", "") or "")
    source_snapshot_ref = str(
        getattr(first_reference, "source_snapshot_ref", "")
        or getattr(resolved, "source_snapshot_ref", "")
        or getattr(spec, "source_snapshot_ref", "")
        or ""
    )
    resource_digest = str(
        getattr(first_reference, "content_digest", "")
        or getattr(spec, "source_feature_digest", "")
        or ""
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
        spatial_domain_kind=str(
            getattr(resolved, "spatial_domain_kind", "") or "unknown"
        ),
        source_parcel_count=len(source_parcels),
    )
    if candidate_variant == "parcel":
        geometry_role = (
            "corridor_candidate"
            if expected_output_kind == "line"
            and str(getattr(resolved, "spatial_domain_kind", "") or "") == "corridor"
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
            geometry_role = (
                "corridor_candidate"
                if str(getattr(resolved, "spatial_domain_kind", "") or "") == "corridor"
                else "scope_geometry"
            )
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
    selected_source_feature_ref = str(
        getattr(first_reference, "source_feature_id", "") or ""
    ).strip()
    resolved_source_feature_ids = list(dict.fromkeys(
        str(item)
        for item in (
            getattr(resolved, "source_feature_ids", None)
            or resolved_provenance.get("source_feature_ids", [])
        )
        if str(item).strip()
    ))
    source_feature_ids = (
        [selected_source_feature_ref]
        if selected_source_feature_ref
        else resolved_source_feature_ids
    )
    reference_entity_refs = list(dict.fromkeys(
        str(item)
        for item in [
            *(getattr(first_reference, "entity_refs", None) or []),
            getattr(first_reference, "entity_ref", ""),
        ]
        if str(item).strip()
    ))
    resolved_entity_refs = list(dict.fromkeys(
        str(item)
        for item in (
            getattr(resolved, "entity_refs", None)
            or resolved_provenance.get("entity_refs", [])
        )
        if str(item).strip()
    ))
    entity_refs = (
        reference_entity_refs
        if reference_entity_refs
        else resolved_entity_refs
    )
    reference_part_refs = list(dict.fromkeys(
        str(item)
        for item in [
            *(getattr(first_reference, "part_refs", None) or []),
            getattr(first_reference, "part_ref", ""),
        ]
        if str(item).strip()
    ))
    resolved_part_refs = list(dict.fromkeys(
        str(item)
        for item in (
            getattr(resolved, "part_refs", None)
            or resolved_provenance.get("part_refs", [])
        )
        if str(item).strip()
    ))
    part_refs = (
        reference_part_refs
        if reference_part_refs
        else (resolved_part_refs if len(resolved_part_refs) == 1 else [])
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
    grounding_confidence = max(0.0, min(1.0, float(resolved.confidence or 0.0)))
    resolved_materialization_role = str(
        materialization_role
        or getattr(spec, "materialization_role", "")
        or (
            "site_footprint"
            if target_kind == "site_area"
            else ("land_use_assignment" if target_kind == "zone" else "")
        )
    ).strip()
    geometry = CandidateGeometry(
        target_id=str(getattr(spec, "target_id", "") or ""),
        physical_project_ref=str(getattr(spec, "physical_project_ref", "") or ""),
        component_claim_refs=list(getattr(spec, "component_claim_refs", None) or []),
        component_fact_refs=list(getattr(spec, "component_fact_refs", None) or []),
        kind=geometry_kind,
        role=geometry_role,
        candidate_membership=(
            "required_member"
            if _spec_declares_required_source_collection(spec)
            else "alternative"
        ),
        materialization_role=resolved_materialization_role,
        wkt=geometry_wkt,
        crs=reference_crs,
        source_crs=reference_source_crs,
        source_snapshot_ref=source_snapshot_ref,
        resource_digest=resource_digest,
        operation="read",
        granularity=(
            "exact_feature"
            if (
                (resolved.reference_geometry_wkt or authoritative_geometry)
                and geometry_kind != "unknown"
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
        part_ref=(
            part_refs[0]
            if len(part_refs) == 1 and len(entity_refs) == 1
            else ""
        ),
        resource_refs=[
            ref for ref in geometry_source_refs
            if str(ref).startswith("resource:")
        ],
        representation_refs=representation_refs,
        evidence_refs=candidate_evidence_refs,
        identity_confidence=grounding_confidence,
        geometry_confidence=grounding_confidence,
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
        availability_status=(
            "fully_available"
            if hard_constraint_status == "passed"
            and str(getattr(resolved, "spatial_domain_kind", "") or "") == "exact_feature"
            else "fully_unavailable"
            if hard_constraint_status == "failed"
            else "unknown"
        ),
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
            "identity_confidence": grounding_confidence,
            "geometry_confidence": grounding_confidence,
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
            "candidate_materialization_allowed": not _search_scope_blocks_materialization(
                resolved
            ),
            "candidate_bbox": (
                list(resolved.bbox[:4]) if getattr(resolved, "bbox", None) else None
            ),
        },
        evidence_refs=candidate_evidence_refs,
        target_ref=(getattr(spec, "target_id", None) or None),
        project_ref=(getattr(spec, "project_ref", None) or None),
        physical_project_ref=str(getattr(spec, "physical_project_ref", "") or ""),
        component_claim_refs=list(getattr(spec, "component_claim_refs", None) or []),
        component_fact_refs=list(getattr(spec, "component_fact_refs", None) or []),
        identity_confidence=grounding_confidence,
        geometry_confidence=grounding_confidence,
        uncertainty=uncertainty,
        target_kind=target_kind,
        expected_output_kind=expected_output_kind,
        geometry=geometry,
        candidate_bbox=geometry.candidate_bbox,
        candidate_materialization_allowed=not _search_scope_blocks_materialization(
            resolved
        ),
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
    materialization_role: str = "",
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

    if _search_scope_blocks_materialization(resolved):
        return []

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
                    materialization_role=materialization_role,
                    source_parcels_override=source_bsms,
                    geometry_wkt_override=str(getattr(reference, "wkt", "") or ""),
                    source_refs_override=source_refs,
                    reference_geometry_override=reference,
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
                materialization_role=materialization_role,
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
                materialization_role=materialization_role,
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
                materialization_role=materialization_role,
                source_parcels_override=[bsm],
                geometry_wkt_override=geometry.wkt,
                generation_operation="grounded_parcel_alternative",
                candidate_variant="parcel",
            )
        )
    return alternatives


def _search_scope_payload(search_scope: Any) -> dict[str, Any] | None:
    if search_scope is None:
        return None
    if hasattr(search_scope, "model_dump"):
        return search_scope.model_dump(mode="python")
    if isinstance(search_scope, dict):
        return dict(search_scope)
    return None


def _search_scope_result_refs(search_scope: Any) -> list[str]:
    payload = _search_scope_payload(search_scope) or {}
    result_refs = list(dict.fromkeys(
        str(value).strip()
        for value in payload.get("scope_bsms", [])
        if str(value).strip()
    ))
    bbox = payload.get("bbox")
    if bbox:
        try:
            result_refs.append(
                "bbox:" + ",".join(f"{float(value):.6f}" for value in bbox[:4])
            )
        except (TypeError, ValueError, IndexError):
            pass
    return result_refs


def _search_scope_issue(spec: SpatialReferenceSpec, resolved: ResolvedSpatialRef) -> StageIssue:
    payload = _search_scope_payload(getattr(resolved, "search_scope", None)) or {}
    missing = ",".join(payload.get("missing_requirements", []) or []) or "authoritative_geometry"
    scope_type = str(payload.get("scope_type", "") or getattr(resolved, "spatial_domain_kind", "") or "unknown")
    source = str(payload.get("source", "") or str((resolved.provenance or {}).get("path", "") or "search_scope"))
    reason = str(payload.get("reason", "") or getattr(resolved, "uncertainty_reason", "") or "coarse_reference")
    scope_bsms = list(dict.fromkeys(
        str(value).strip()
        for value in payload.get("scope_bsms", [])
        if str(value).strip()
    ))
    bbox = payload.get("bbox")
    bbox_text = ""
    if bbox:
        try:
            bbox_text = ",".join(f"{float(value):.6f}" for value in bbox[:4])
        except (TypeError, ValueError, IndexError):
            bbox_text = ""
    return StageIssue(
        stage="ground",
        severity="warning",
        code="search_scope_not_materialized",
        message=(
            "coarse search scope retained for retrieval only; "
            "candidate materialization remains disabled"
        ),
        detail=(
            f"target_id={getattr(spec, 'target_id', '')}; "
            f"scope_type={scope_type}; "
            f"source={source}; "
            f"reason={reason}; "
            f"scope_bsms={scope_bsms}; "
            f"bbox={bbox_text or 'none'}; "
            f"missing_requirements={missing}"
        ),
        related_artifact_id=(getattr(spec, "target_id", "") or None),
    )


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
        from app.core.common.constraint_codes import PROHIBITED_LAND_CONSTRAINTS

        geometry = shapely_wkt.loads(geometry_wkt)
        overlaps = constraint_index.geometry_in_constraint(mapping(geometry)) or []
        prohibited = sorted({
            str(getattr(item, "constraint_type", "") or "")
            for item in overlaps
            if str(getattr(item, "constraint_type", "") or "") in PROHIBITED_LAND_CONSTRAINTS
        })
    except Exception as exc:  # noqa: BLE001
        return "deferred", f"constraint query failed: {type(exc).__name__}"
    if prohibited:
        return "failed", "prohibited constraint overlap: " + ",".join(prohibited)
    return "passed", ""


def _close_undeclared_geometry_constraints(
    candidates: list[CandidateSite],
    factors: list[Any],
    intent_graph: Any,
    context: Optional[PlanningContext],
) -> None:
    """Close a pending static-constraint check only on an accepted closed set.

    DATA-only sessions legitimately have no legacy ``ConstraintIndex``.  A
    missing index is not itself proof that a target is feasible, so candidate
    construction initially records ``pending``.  Once TARGET_PROJECTION has
    supplied its complete intent graph, however, a target with no uncompiled
    constraints and no declared hard geometry factor has an explicitly empty
    static-constraint set.  That set is vacuously satisfied; hard relational
    factors (near/access/connect/etc.) remain independently evaluated by the
    relation solver and are never closed here.

    This is deliberately narrower than a fallback: it only upgrades exact,
    local DATA bindings with entity/part/representation/resource/snapshot
    lineage.  A bbox, village scope, legacy BSM extent, unresolved target, or
    target carrying any uncompiled/static hard constraint remains pending.
    """

    if getattr(context, "constraint_index", None) is not None:
        return
    nodes = {
        str(getattr(node, "target_id", "") or ""): node
        for node in list(getattr(intent_graph, "nodes", None) or [])
        if str(getattr(node, "target_id", "") or "").strip()
    }
    static_kinds = {"within_allowed_area", "avoid_constraint"}
    blocked_targets = {
        str(getattr(factor, "subject_ref", "") or "")
        for factor in factors
        if bool(getattr(factor, "hard", False))
        and str(getattr(factor, "kind", "") or "") in static_kinds
    }
    has_global_static_constraint = any(
        bool(getattr(factor, "hard", False))
        and str(getattr(factor, "kind", "") or "") in static_kinds
        and str(getattr(factor, "geometry_scope", "") or "") == "global"
        for factor in factors
    )
    intent_fingerprint = str(getattr(intent_graph, "fingerprint", "") or "")
    for candidate in candidates:
        geometry = candidate.geometry
        target_id = str(candidate.target_ref or getattr(geometry, "target_id", "") or "")
        node = nodes.get(target_id)
        if geometry is None or geometry.hard_constraint_status != "pending":
            continue
        if has_global_static_constraint or target_id in blocked_targets:
            continue
        if node is None or list(getattr(node, "uncompiled_constraints", None) or []):
            continue
        if (
            geometry.spatial_domain_kind != "exact_feature"
            or not geometry.entity_refs
            or not geometry.part_ref
            or not geometry.resource_refs
            or not geometry.representation_refs
            or not geometry.source_snapshot_ref
            or not geometry.resource_digest
        ):
            continue
        geometry.hard_constraint_status = "passed"
        geometry.availability_status = "fully_available"
        candidate.hard_constraint_result = HardConstraintResult(
            constraint_id="declared_geometry_constraint_set",
            passed=True,
            violation_detail="",
        )
        candidate.metrics = {
            **dict(candidate.metrics or {}),
            "hard_constraint_basis": "no_declared_geometry_constraints",
            "intent_graph_fingerprint": intent_fingerprint,
        }


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


def _search_scope_blocks_materialization(resolved: Any) -> bool:
    search_scope = getattr(resolved, "search_scope", None)
    if search_scope is None:
        return False
    if isinstance(search_scope, dict):
        return search_scope.get("candidate_materialization_allowed") is not True
    return not bool(getattr(search_scope, "candidate_materialization_allowed", False))


def _enforce_search_scope_invariant(resolved: ResolvedSpatialRef) -> ResolvedSpatialRef:
    """Keep a blocked retrieval scope from being rematerialized by fallbacks."""
    if not _search_scope_blocks_materialization(resolved):
        return resolved
    provenance = dict(getattr(resolved, "provenance", None) or {})
    provenance["search_scope_materialization_guard"] = "blocked"
    return replace(
        resolved,
        final_bsms=[],
        bbox=None,
        reference_geometry_wkt=None,
        reference_geometries=[],
        feature_bsms=[],
        provenance=provenance,
    )


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
            if spatial_domain_kind == "corridor":
                return "corridor_candidate"
            return "parcel_candidate" if has_source_parcels else "scope_geometry"
        if (
            expected_output_kind in {"polygon", "parcel"}
            and target_kind in {"site_area", "zone", "restoration", "protection"}
        ):
            return "execution_geometry"
        if expected_output_kind == "line" and spatial_domain_kind == "corridor":
            return "corridor_candidate"
        return "parcel_candidate" if has_source_parcels else "scope_geometry"
    return "unknown"


def ground_aggregate(
    specs: list[SpatialReferenceSpec],
    context: PlanningContext,
    intent_graph: Any = None,
    target_metadata: Optional[Dict[str, Dict[str, str]]] = None,
    evidence_packets: Optional[Dict[str, Any]] = None,
    ground_llm_budget: Optional[Dict[str, Any]] = None,
) -> GroundingResult:
    """Resolve all specs through ``SpatialResolver`` into a ``GroundingResult``.

    Deterministic over its inputs: one resolver instance, ordered iteration.
    Each spec contributes exactly one ``SpatialQueryEvidence`` row; specs with
    resolved bundle parcels contribute a ``CandidateSite``, the rest a
    ``StageIssue``.
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

    candidates: List[CandidateSite] = []
    unresolved: List[StageIssue] = []
    spatial_query_evidence: List[SpatialQueryEvidence] = []
    search_scope_trace: list[str] = []
    search_scope_bindings: list[GroundingBinding] = []

    for index, spec in enumerate(specs):
        # TARGET_PROJECTION retains unresolved_reason as a diagnostic; GROUND
        # resolves only through the typed DATA/WM candidate boundary.
        resolve_kwargs: Dict[str, Any] = {}
        if evidence_packets is not None:
            resolve_kwargs["evidence_packet"] = (evidence_packets or {}).get(
                str(getattr(spec, "target_id", "") or "")
            )
        resolved = _enforce_search_scope_invariant(
            resolver.resolve_spec(spec, **resolve_kwargs)
        )
        resolved = _enforce_search_scope_invariant(resolved)
        spec_type = getattr(spec, "type", "")
        search_scope_payload = _search_scope_payload(getattr(resolved, "search_scope", None))
        resolution_provenance = dict(getattr(resolved, "provenance", None) or {})
        selection_trace = [
            {
                key: value
                for key, value in {
                    "mention": item.get("mention", ""),
                    "packet_selection_status": item.get("packet_selection_status", ""),
                    "selection_contract_status": item.get("selection_contract_status", ""),
                    "packet_selection_reason": item.get("packet_selection_reason", ""),
                    "selected_candidate_ids": list(
                        item.get("selected_candidate_ids", []) or []
                    ),
                    "candidate_set_digest": item.get("candidate_set_digest", ""),
                    "input_digest": item.get("input_digest", ""),
                }.items()
                if value not in ("", [], None)
            }
            for item in list(
                resolution_provenance.get("ground_candidate_selection", []) or []
            )[:16]
            if isinstance(item, dict)
        ]
        result_refs = list(resolved.final_bsms)
        if not result_refs and search_scope_payload is not None:
            result_refs = _search_scope_result_refs(getattr(resolved, "search_scope", None))
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
                    **(
                        {"search_scope": search_scope_payload}
                        if search_scope_payload is not None
                        else {}
                    ),
                    "resolution_path": str(
                        resolution_provenance.get("path", "") or ""
                    ),
                    "packet_selection_status": str(
                        resolution_provenance.get("packet_selection_status", "")
                        or ""
                    ),
                    "candidate_selection": selection_trace,
                },
                result_count=len(result_refs),
                result_refs=result_refs,
                target_id=getattr(spec, "target_id", ""),
                spec_id=getattr(spec, "spec_id", ""),
            )
        )
        if search_scope_payload is not None:
            search_scope_trace.append(
                "search_scope:"
                f"{getattr(spec, 'target_id', '') or getattr(spec, 'spec_id', '') or spec_type}:"
                f"{search_scope_payload.get('scope_type', 'unknown')}:"
                f"{search_scope_payload.get('source', '')}:"
                f"{search_scope_payload.get('reason', '')}"
            )
        if _search_scope_blocks_materialization(resolved):
            unresolved.append(_search_scope_issue(spec, resolved))
            scope = getattr(resolved, "search_scope", None)
            target_id = str(getattr(spec, "target_id", "") or "")
            spec_id = str(getattr(spec, "spec_id", "") or index)
            scope_type = str(getattr(scope, "scope_type", "unknown") or "unknown")
            scope_reason = str(
                getattr(scope, "reason", "")
                or getattr(resolved, "uncertainty_reason", "")
                or "coarse_search_scope"
            )
            missing_requirements = list(
                getattr(scope, "missing_requirements", None) or []
            )
            scope_diagnostics = [
                "search_scope_not_materialized",
                f"scope_type:{scope_type}",
                *(
                    f"missing_requirement:{value}"
                    for value in missing_requirements
                    if str(value).strip()
                ),
            ]
            if getattr(scope, "bbox", None):
                scope_diagnostics.append("bbox_available_for_retrieval_only")
            search_scope_bindings.append(GroundingBinding(
                binding_id=f"ground:{target_id}:scope:{spec_id}",
                target_id=target_id,
                geometry_kind="unknown",
                materialization_role=str(
                    getattr(spec, "materialization_role", "") or ""
                ),
                source_snapshot_ref=str(
                    getattr(scope, "source_snapshot_ref", "")
                    or getattr(spec, "source_snapshot_ref", "")
                    or ""
                ),
                ambiguity=scope_reason,
                diagnostics=scope_diagnostics,
                status="candidate_only",
                confidence=(
                    float(resolved.confidence)
                    if getattr(resolved, "confidence", None) is not None
                    else None
                ),
                evidence_refs=list(dict.fromkeys(
                    str(value)
                    for value in [
                        *(getattr(scope, "provenance_refs", None) or []),
                        getattr(spec, "source_binding_ref", ""),
                        *(getattr(spec, "l1_fact_refs", None) or []),
                    ]
                    if str(value).strip()
                )),
            ))
        elif (
            resolved.final_bsms
            or resolved.reference_geometry_wkt
            or getattr(resolved, "reference_geometries", None)
        ):
            metadata = (target_metadata or {}).get(str(getattr(spec, "target_id", "")), {})
            target_materialization_role = str(
                metadata.get("materialization_role", "")
                or metadata.get("representation_purpose", "")
                or ""
            ).strip()
            if (
                str(metadata.get("representation_purpose", "")) == "corridor"
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
                materialization_role=target_materialization_role,
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
            if search_scope_payload is not None:
                unresolved.append(_search_scope_issue(spec, resolved))
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
                    str(getattr(subject_identity, "source_feature_id", "") or ""),
                    str(getattr(object_identity, "source_feature_id", "") or ""),
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
        trace=[f"specs:{len(specs)}", *search_scope_trace],
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
    _close_undeclared_geometry_constraints(
        candidates,
        factors,
        intent_graph,
        context,
    )
    problem = _build_grounded_problem(
        candidates,
        unresolved,
        factors,
        evaluate_relation_satisfaction(factors, candidates),
        intent_graph,
        context=context,
        search_scope_bindings=search_scope_bindings,
        target_metadata=target_metadata,
    )
    from app.modules.evidence.requirements import requirements_from_ground

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


def _data_binding_diagnostics(
    geometry: CandidateGeometry,
    catalog: Any,
) -> list[str]:
    """Validate one exact GROUND tuple against the frozen DATA catalog.

    Candidate fields are claims until the selected representation/resource
    can be reopened and its normalized geometry matches the candidate WKT.
    Keeping this check at the GROUND boundary prevents a syntactically valid
    but foreign WKT/ref tuple from being marked resolved.
    """

    diagnostics: list[str] = []
    scalar_requirements = {
        "target_ref": bool(str(geometry.target_id or "").strip()),
        "entity_ref": len(geometry.entity_refs) == 1,
        "part_ref": bool(str(geometry.part_ref or "").strip()),
        "representation_ref": len(geometry.representation_refs) == 1,
        "resource_ref": len(geometry.resource_refs) == 1,
        "source_feature_ref": len(geometry.source_feature_ids) == 1,
        "source_snapshot_ref": bool(str(geometry.source_snapshot_ref or "").strip()),
        "resource_digest": bool(str(geometry.resource_digest or "").strip()),
        "crs": bool(str(geometry.crs or "").strip()),
        "materialization_role": bool(str(geometry.materialization_role or "").strip()),
        "evidence_refs": bool(geometry.evidence_refs),
    }
    diagnostics.extend(
        f"{field}_missing_or_ambiguous"
        for field, ready in scalar_requirements.items()
        if not ready
    )
    if geometry.role != "execution_geometry":
        diagnostics.append(f"geometry_role_not_executable:{geometry.role}")
    if geometry.spatial_domain_kind != "exact_feature":
        diagnostics.append(
            f"geometry_domain_not_exact:{geometry.spatial_domain_kind}"
        )
    if geometry.hard_constraint_status != "passed":
        diagnostics.append(
            f"hard_constraint_not_passed:{geometry.hard_constraint_status}"
        )
    if geometry.availability_status not in {
        "fully_available",
        "partially_available",
    }:
        diagnostics.append(
            f"availability_not_resolved:{geometry.availability_status}"
        )
    authority_refs = [
        *geometry.resource_refs,
        *geometry.representation_refs,
        *geometry.source_feature_ids,
    ]
    if any(
        value.startswith("external-observation:")
        or ":external-observation:" in value
        for value in authority_refs
    ):
        diagnostics.append("external_observation_geometry_forbidden")
    if not geometry.grounding_ready:
        diagnostics.append("grounding_confidence_not_trusted")
    if catalog is None:
        diagnostics.append("data_catalog_unavailable")
        return list(dict.fromkeys(diagnostics))
    catalog_snapshot = getattr(catalog, "snapshot", None)
    admission_index = None
    admission_error = False
    if catalog_snapshot is None:
        diagnostics.append("data_catalog_snapshot_unavailable")
    else:
        from app.data.admission import (
            assert_current_world_catalog,
            build_admission_index,
        )

        # Keep both checks at the GROUND boundary.  The index lets us explain
        # which binding is not admitted; the assertion also fails closed when
        # the frozen catalog contains any unclassified/planned current-world
        # rows or dangling representations/capabilities.
        try:
            admission_index = build_admission_index(catalog_snapshot)
        except (TypeError, ValueError):
            admission_error = True
            diagnostics.append("data_admission_index_unavailable")
        try:
            assert_current_world_catalog(catalog_snapshot)
        except (TypeError, ValueError):
            admission_error = True
            diagnostics.append("data_catalog_current_world_admission_failed")
    representation_ref = (
        geometry.representation_refs[0]
        if len(geometry.representation_refs) == 1
        else ""
    )
    representation = (
        catalog.get_representation(representation_ref)
        if representation_ref
        else None
    )
    if representation is None:
        diagnostics.append("data_representation_not_found")
        return list(dict.fromkeys(diagnostics))
    if catalog_snapshot is not None and admission_index is not None:
        from app.data.admission import (
            feature_admission_verdict,
            is_admitted_representation,
        )

        if not is_admitted_representation(
            catalog_snapshot,
            representation,
            index=admission_index,
        ):
            diagnostics.append("data_representation_not_admitted_current_evidence")
        representation_dataset_ref = str(
            getattr(representation, "dataset_ref", "") or ""
        )
        representation_feature_ref = str(
            getattr(representation, "source_feature_ref", "") or ""
        )
        source_feature = next(
            (
                item
                for item in catalog_snapshot.features
                if str(getattr(item, "dataset_ref", "") or "")
                == representation_dataset_ref
                and str(getattr(item, "source_feature_ref", "") or "")
                == representation_feature_ref
            ),
            None,
        )
        if source_feature is None:
            diagnostics.append("data_feature_not_found_for_representation")
        elif not feature_admission_verdict(
            catalog_snapshot,
            source_feature,
        ).admitted:
            diagnostics.append("data_feature_not_admitted_current_evidence")
        allowed_resource_refs = (
            admission_index.resource_refs
            | admission_index.representation_resource_refs
        )
        if str(getattr(representation, "resource_ref", "") or "") not in allowed_resource_refs:
            diagnostics.append("data_resource_not_admitted_current_evidence")
        if admission_error:
            # A catalog-level admission failure is itself a hard boundary
            # failure, even when this particular representation is in the
            # admitted subset.  Keep the detailed predicate diagnostics above
            # for the audit ledger.
            diagnostics.append("data_binding_admission_not_verified")
    if not str(getattr(representation, "geometry_ref", "") or "").strip():
        diagnostics.append("data_geometry_ref_missing")
    expected_resource_ref = str(getattr(representation, "resource_ref", "") or "")
    if geometry.resource_refs != [expected_resource_ref]:
        diagnostics.append("resource_ref_representation_mismatch")
    expected_snapshot_ref = str(
        getattr(representation, "source_snapshot_ref", "") or ""
    )
    catalog_snapshot_ref = str(
        getattr(getattr(catalog, "snapshot", None), "snapshot_id", "") or ""
    )
    if (
        geometry.source_snapshot_ref != expected_snapshot_ref
        or expected_snapshot_ref != catalog_snapshot_ref
    ):
        diagnostics.append("source_snapshot_representation_mismatch")
    expected_digest = str(getattr(representation, "content_digest", "") or "")
    if geometry.resource_digest != expected_digest:
        diagnostics.append("resource_digest_representation_mismatch")
    expected_crs = str(
        getattr(representation, "normalized_crs", "")
        or getattr(representation, "crs", "")
        or ""
    )
    if geometry.crs != expected_crs:
        diagnostics.append("crs_representation_mismatch")
    if str(getattr(representation, "status", "") or "") != "available":
        diagnostics.append("data_representation_unavailable")
    source_feature_ref = str(
        getattr(representation, "source_feature_ref", "") or ""
    )
    if geometry.source_feature_ids != [source_feature_ref]:
        diagnostics.append("source_feature_representation_mismatch")
    try:
        source_geometry = catalog.resolve_geometry(
            representation_ref=representation_ref,
            normalized=True,
        )
        candidate_geometry = shapely_wkt.loads(str(geometry.wkt or ""))
        if (
            not isinstance(source_geometry, dict)
            or candidate_geometry.is_empty
            or not candidate_geometry.is_valid
            or not shape(source_geometry).equals(candidate_geometry)
        ):
            diagnostics.append("candidate_geometry_resource_mismatch")
    except Exception:
        diagnostics.append("candidate_geometry_resource_unreadable")
    return list(dict.fromkeys(diagnostics))


def _data_binding_status(
    geometry: CandidateGeometry,
    catalog: Any,
) -> str:
    diagnostics = _data_binding_diagnostics(geometry, catalog)
    if not diagnostics:
        return "resolved"
    if any(
        len(values) > 1
        for values in (
            geometry.entity_refs,
            geometry.representation_refs,
            geometry.resource_refs,
            geometry.source_feature_ids,
        )
    ):
        return "ambiguous"
    missing_local_geometry = any(
        item in diagnostics
        for item in {
            "data_catalog_unavailable",
            "data_representation_not_found",
            "data_representation_unavailable",
            "candidate_geometry_resource_mismatch",
            "candidate_geometry_resource_unreadable",
        }
    )
    if missing_local_geometry and not geometry.source_bsms:
        return "unresolved"
    return "candidate_only"


def _build_grounded_problem(
    candidates: list[CandidateSite],
    unresolved: list[StageIssue],
    factors: list[Any],
    relation_satisfaction: list[Any],
    intent_graph: Any,
    *,
    context: Optional[PlanningContext] = None,
    search_scope_bindings: Optional[list[GroundingBinding]] = None,
    target_metadata: Optional[Dict[str, Dict[str, str]]] = None,
) -> GroundedPlanningProblem:
    catalog = (
        getattr(context, "data_resource_catalog", None)
        if context is not None
        else None
    )
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
        binding_status = (
            _data_binding_status(candidate.geometry, catalog)
            if candidate.geometry is not None
            else "unresolved"
        )
        if binding_status == "resolved":
            domain.status = "resolved"
        elif binding_status == "ambiguous" and domain.status != "resolved":
            domain.status = "ambiguous"
        elif (
            binding_status == "candidate_only"
            and domain.status not in {"resolved", "ambiguous"}
        ):
            domain.status = "candidate_only"

    for binding in list(search_scope_bindings or []):
        target_id = str(binding.target_id or "")
        if not target_id:
            continue
        metadata = (target_metadata or {}).get(target_id, {})
        domain = domains.setdefault(
            target_id,
            GroundedTargetDomain(
                target_id=target_id,
                target_kind=str(metadata.get("target_kind", "unknown") or "unknown"),
                expected_output_kind=str(
                    metadata.get("expected_output_kind", "unknown") or "unknown"
                ),
                status="candidate_only",
            ),
        )
        if domain.status != "resolved":
            domain.status = "candidate_only"
        domain.evidence_refs.extend(binding.evidence_refs)
        domain.unresolved_reason = binding.ambiguity or "coarse_search_scope"

    for issue in unresolved:
        target_id = str(issue.related_artifact_id or "")
        if not target_id:
            continue
        domain = domains.setdefault(target_id, GroundedTargetDomain(target_id=target_id))
        domain.unresolved_reason = str(issue.code or issue.message or "unresolved")
        if (
            not domain.candidate_site_refs
            and domain.status != "candidate_only"
        ):
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
    diagnostics.extend(
        f"search_scope:{str(issue.related_artifact_id or '')}:{str(issue.detail or '')}"
        for issue in unresolved
        if str(issue.code or "") == "search_scope_not_materialized"
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
    ambiguous_identity_target_ids: set[str] = set()
    for target_id in {
        str(item.target_id or "") for item in candidate_geometries if item.target_id
    }:
        target_candidates = [
            item for item in candidate_geometries
            if str(item.target_id or "") == target_id
        ]
        entity_refs = {
            str(entity_ref)
            for item in target_candidates
            for entity_ref in item.entity_refs
            if str(entity_ref).strip()
        }
        explicit_collection = bool(target_candidates) and all(
            item.candidate_membership == "required_member"
            for item in target_candidates
        )
        if len(entity_refs) > 1 and not explicit_collection:
            ambiguous_identity_target_ids.add(target_id)
    for domain in candidate_domains:
        if domain.target_id in ambiguous_identity_target_ids:
            domain.status = "ambiguous"
    for target_id in ambiguous_identity_target_ids:
        if target_id in domains:
            domains[target_id].status = "ambiguous"
            domains[target_id].unresolved_reason = "multiple_world_entities"
        diagnostics.append(f"ambiguous_world_entities:{target_id}")
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
    # Promote the GROUND result to an explicit identity→representation
    # binding ledger. KG identity, DATA resource and executable geometry are
    # separate fields; a missing or mismatched field preserves recall but
    # blocks resolved/executable status.
    grounding_bindings: list[GroundingBinding] = list(search_scope_bindings or [])
    for candidate in candidates:
        geometry = candidate.geometry
        if geometry is None:
            continue
        target_id = str(candidate.target_ref or candidate.project_ref or geometry.target_id or "")
        if not target_id:
            continue
        resource_refs = list(getattr(geometry, "resource_refs", ()) or ())
        representation_refs = list(
            getattr(geometry, "representation_refs", ()) or ()
        )
        resource_ref = resource_refs[0] if len(resource_refs) == 1 else ""
        representation_ref = (
            representation_refs[0] if len(representation_refs) == 1 else ""
        )
        representation = (
            catalog.get_representation(representation_ref)
            if catalog is not None and representation_ref
            else None
        )
        source_feature_ref = str(
            getattr(representation, "source_feature_ref", "")
            or next(iter(getattr(geometry, "source_feature_ids", ()) or ()), "")
            or ""
        )
        if representation is not None:
            resource_ref = str(getattr(representation, "resource_ref", "") or resource_ref)
        source_snapshot_ref = str(
            getattr(representation, "source_snapshot_ref", "")
            or getattr(geometry, "source_snapshot_ref", "")
            or (getattr(getattr(catalog, "snapshot", None), "snapshot_id", "") if catalog is not None else "")
            or ""
        )
        resource_digest = str(
            getattr(representation, "content_digest", "")
            or getattr(geometry, "resource_digest", "")
            or ""
        )
        binding_crs = str(
            getattr(representation, "normalized_crs", "")
            or getattr(representation, "crs", "")
            or getattr(geometry, "crs", "")
            or ""
        )
        source_crs = str(
            getattr(representation, "source_crs", "")
            or getattr(geometry, "source_crs", "")
            or ""
        )
        binding_diagnostics = list(getattr(geometry, "schema_diagnostics", None) or [])
        diagnostic_text = [
            str(getattr(item, "code", "") or item)
            for item in binding_diagnostics
            if str(getattr(item, "code", "") or item).strip()
        ]
        data_binding_diagnostics = _data_binding_diagnostics(geometry, catalog)
        diagnostic_text.extend(data_binding_diagnostics)
        binding_status = _data_binding_status(geometry, catalog)
        if target_id in ambiguous_identity_target_ids:
            binding_status = "ambiguous"
            diagnostic_text.append("multiple_world_entities")
        constraint_basis = str(
            (candidate.metrics or {}).get("hard_constraint_basis", "") or ""
        ).strip()
        if constraint_basis:
            diagnostic_text.append(f"hard_constraint_basis:{constraint_basis}")
        binding_id = f"ground:{target_id}:{geometry.candidate_id}"
        grounding_bindings.append(
            GroundingBinding(
                binding_id=binding_id,
                target_id=target_id,
                candidate_ref=str(getattr(geometry, "candidate_id", "") or ""),
                entity_ref=(
                    geometry.entity_refs[0]
                    if len(getattr(geometry, "entity_refs", ()) or ()) == 1
                    else ""
                ),
                part_ref=str(getattr(geometry, "part_ref", "") or ""),
                representation_ref=representation_ref,
                resource_ref=resource_ref,
                geometry_ref=str(
                    getattr(representation, "geometry_ref", "")
                    or ""
                ),
                geometry_kind=str(getattr(geometry, "kind", "unknown") or "unknown"),
                materialization_role=str(getattr(geometry, "materialization_role", "") or ""),
                source_snapshot_ref=source_snapshot_ref,
                source_feature_refs=([source_feature_ref] if source_feature_ref else []),
                crs=binding_crs,
                resource_digest=resource_digest,
                ambiguity=(
                    ""
                    if binding_status == "resolved"
                    else (
                        str(getattr(geometry, "uncertainty_reason", "") or "")
                        or "binding_tuple_ambiguous"
                        if binding_status == "ambiguous"
                        else "unresolved_geometry"
                        if binding_status == "unresolved"
                        else "candidate_only"
                    )
                ),
                diagnostics=diagnostic_text,
                hard_constraint_status=str(
                    getattr(geometry, "hard_constraint_status", "unknown") or "unknown"
                ),
                availability_status=str(
                    getattr(geometry, "availability_status", "unknown") or "unknown"
                ),
                # A valid WKT is not enough to enter SELECT.  The candidate
                # must pass CandidateGeometry's DATA-backed executability
                # contract and the hard-constraint gate.  Legacy bundle/BSM
                # rows therefore remain auditable candidate-only bindings
                # until a local representation/resource is available.
                status=binding_status,
                confidence=(
                    float(geometry.geometry_confidence)
                    if geometry.geometry_confidence is not None
                    else None
                ),
                evidence_refs=list(geometry.evidence_refs),
            )
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
        bindings=sorted(
            {item.binding_id: item for item in grounding_bindings}.values(),
            key=lambda item: item.binding_id,
        ),
        unresolved=grounding_findings,
    )


from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.artifacts.ref import ArtifactRef


class GroundRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    context_version: str = Field(min_length=1)
    target_projection_ref: ArtifactRef

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> "GroundRunRequest":
        ref = (state.get("artifact_refs") or {}).get("target_projection")
        if not ref:
            raise RuntimeError("GROUND requires the canonical target_projection artifact ref")
        return cls(
            run_id=str(state.get("run_id") or state.get("session_id") or ""),
            session_id=str(state.get("session_id") or ""),
            context_version=str(state.get("context_version") or ""),
            target_projection_ref=ArtifactRef.model_validate(ref),
        )


class GroundRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    request: GroundRunRequest
    grounding: GroundingResult
    artifact_ref: ArtifactRef
    gate_ref: ArtifactRef
    state_patch: Dict[str, Any] = Field(default_factory=dict)

    def to_state_patch(self) -> dict[str, Any]:
        return dict(self.state_patch)


class GroundApplication:
    """Run the workflow GROUND boundary and reload its typed result."""

    @staticmethod
    async def materialize_l1_locations(state: Mapping[str, Any]) -> dict[str, Any]:
        """Run GROUND's pre-planning L1 location-resolution entry point.

        This is intentionally not a TARGET_PROJECTION call.  L1 location
        mentions are useful spatial work items before any planning intent
        exists, so GROUND resolves them directly from the current context and
        persists replay sidecars and commits the decisions into the session
        World Model.  Runtime/lineage failures block; semantic ambiguity is a
        typed gap and may never be converted into a fallback location.
        """

        from app.contracts.l1.l1_contracts import L1ObservationSnapshot
        from app.core.settings import COGNITION_WORLD_MODEL_MODE
        from app.infrastructure.artifacts.runtime import load_artifact
        from app.infrastructure.context_runtime.manager import (
            build_planning_context,
            context_has_cognition_ports,
            get_cached_context,
        )
        from app.modules.ground.reference_resolution import resolve_l1_location_mentions
        from app.modules.ground.reasoning import reason_l1_location_candidates
        from app.spatial.grounding.call_budget import get_ground_llm_budget

        materialization_started = perf_counter()
        session_id = str(state.get("session_id") or "").strip()
        if not session_id:
            raise RuntimeError(
                "L1_LOCATION_GROUNDING_INPUT_MISSING: session_id is required"
            )
        from app.workflow.stages.support import require_upstream_gates

        require_upstream_gates(dict(state), ("data", "kg", "evidence"))
        from app.workflow.state import load_root_gate

        provisional_l1_gate = load_root_gate(dict(state), "l1")
        context = get_cached_context(session_id)
        snapshot = load_artifact(dict(state), "l1_snapshot", L1ObservationSnapshot)
        if snapshot is None:
            raise RuntimeError(
                "L1_LOCATION_GROUNDING_INPUT_MISSING: l1_snapshot is required"
            )
        from app.infrastructure.artifacts.runtime import validate_artifact_context

        l1_ref = (state.get("artifact_refs") or {}).get("l1_snapshot")
        validate_artifact_context(dict(state), "l1_snapshot", l1_ref)
        context_ref = dict(state.get("context_ref") or {})
        expected_mode = str(
            COGNITION_WORLD_MODEL_MODE or "off"
        ).strip().lower()
        expected_snapshot_digest = str(
            context_ref.get("snapshot_digest")
            or context_ref.get("data_snapshot_digest")
            or ""
        ).strip()
        expected_world_model_digest = str(
            state.get("world_model_snapshot_digest")
            or context_ref.get("world_model_snapshot_digest")
            or ""
        ).strip()
        live_world_model_digest = str(
            getattr(getattr(context, "world_model", None), "snapshot_digest", "")
            or ""
        )
        context_requires_reload = bool(
            context is None
            or not context_has_cognition_ports(
                context,
                world_model_mode=expected_mode,
            )
            or (
                expected_world_model_digest
                and live_world_model_digest != expected_world_model_digest
            )
        )
        if context_requires_reload:
            data_catalog = state.get("data_catalog") or getattr(
                context,
                "data_resource_catalog",
                None,
            )
            if data_catalog is None:
                from app.data.catalog.session_resource_catalog import (
                    load_session_data_catalog,
                )

                data_catalog = await load_session_data_catalog(
                    session_id,
                    village_name=str(
                        (state.get("config") or {}).get("village_name") or ""
                    ),
                )
            if data_catalog is None:
                raise RuntimeError(
                    "L1_LOCATION_GROUNDING_CONTEXT_MISSING: DATA catalog cannot be restored"
                )

            schema_mapping_snapshot = getattr(
                context,
                "schema_mapping_snapshot",
                None,
            )
            schema_mapping_ref_value = (state.get("artifact_refs") or {}).get(
                "schema_mapping_snapshot"
            )
            if isinstance(schema_mapping_ref_value, Mapping):
                schema_mapping_artifact_ref = str(
                    schema_mapping_ref_value.get("descriptor_digest")
                    or schema_mapping_ref_value.get("digest")
                    or ""
                )
            else:
                schema_mapping_artifact_ref = str(
                    getattr(schema_mapping_ref_value, "descriptor_digest", "")
                    or getattr(schema_mapping_ref_value, "digest", "")
                    or ""
                )
            if schema_mapping_ref_value is not None:
                from app.contracts.cognition.decision import (
                    SourceSemanticMappingSnapshot,
                )

                schema_mapping_snapshot = load_artifact(
                    dict(state),
                    "schema_mapping_snapshot",
                    SourceSemanticMappingSnapshot,
                )
            if expected_mode in {"shadow", "prefer_v2", "v2_only"} and (
                schema_mapping_snapshot is None
                or not schema_mapping_artifact_ref
            ):
                raise RuntimeError(
                    "L1_LOCATION_GROUNDING_CONTEXT_MISSING: exact schema mapping artifact is required"
                )
            context_version_text = str(
                context_ref.get("version")
                or state.get("context_version")
                or getattr(context, "version", "")
                or ""
            )
            context = await build_planning_context(
                session_id,
                village_name=str(
                    (state.get("config") or {}).get("village_name") or ""
                ),
                refresh=True,
                include_reports=False,
                version=(
                    int(context_version_text)
                    if context_version_text.isdigit()
                    else None
                ),
                expected_snapshot_digest=expected_snapshot_digest or None,
                expected_world_model_digest=expected_world_model_digest or None,
                data_catalog=data_catalog,
                schema_mapping_snapshot=schema_mapping_snapshot,
                schema_mapping_artifact_ref=schema_mapping_artifact_ref,
                artifact_root=str(state.get("artifact_root") or ""),
                defer_cognition_bootstrap=False,
            )
        if expected_mode in {"shadow", "prefer_v2", "v2_only"} and not (
            context_has_cognition_ports(
                context,
                world_model_mode=expected_mode,
            )
        ):
            raise RuntimeError(
                "L1_LOCATION_GROUNDING_CONTEXT_MISSING: WorldModel ports are unavailable"
            )
        mentions = list(getattr(snapshot, "location_mentions", None) or [])
        context.l1_fact_records = list(getattr(snapshot, "fact_records", None) or [])
        context.l1_snapshot_ref = str(
            ((state.get("artifact_refs") or {}).get("l1_snapshot") or {}).get("digest")
            if isinstance((state.get("artifact_refs") or {}).get("l1_snapshot"), dict)
            else getattr((state.get("artifact_refs") or {}).get("l1_snapshot"), "digest", "")
        )
        mode = str(getattr(context, "world_model_mode", "") or "").strip().lower()
        if mode not in {"shadow", "prefer_v2", "v2_only"}:
            raise RuntimeError(
                "L1_LOCATION_GROUNDING_CONTEXT_MISSING: v2 World Model mode is required"
            )
        is_v2 = mode in {"shadow", "prefer_v2", "v2_only"}
        from app.modules.ground.projections import build_l1_identity_work_items

        mentions, observations = build_l1_identity_work_items(mentions)
        context.location_mentions = mentions
        context.evidence_observations = observations
        evidence_packets, evidence_diagnostics = _load_l1_evidence_packets(
            state,
            mentions,
            observations,
        )
        l1_iterations: list[dict[str, Any]] = []
        previous_signature: tuple[Any, ...] | None = None
        previous_binding_statuses: dict[str, str] = {}
        bindings: list[Any] = []
        deterministic_started = perf_counter()
        bindings = resolve_l1_location_mentions(context, max_rounds=1)
        bindings = _attach_l1_binding_source_mentions(bindings, observations)
        context.grounded_bindings = bindings
        retry_observation_ids = _l1_retry_observations(bindings)
        previous_binding_statuses = {
            str(getattr(binding, "mention_ref", "") or "").strip(): str(
                getattr(binding, "status", "unresolved") or "unresolved"
            )
            for binding in bindings
            if str(getattr(binding, "mention_ref", "") or "").strip()
        }
        l1_iterations.append({
            "phase": "indexed_data_kg_resolution",
            "active_observation_ids": sorted(previous_binding_statuses),
            "binding_statuses": dict(sorted(previous_binding_statuses.items())),
            "retry_observation_ids": sorted(retry_observation_ids),
            "elapsed_ms": round((perf_counter() - deterministic_started) * 1000, 1),
        })
        max_rounds = 1
        for round_index in range(max_rounds):
            active_pairs = [
                (mention, observation)
                for mention, observation in zip(mentions, observations)
                if str(
                    getattr(observation, "observation_id", "") or ""
                ).strip() in retry_observation_ids
            ]
            if not active_pairs:
                break
            evidence_wave_started = perf_counter()
            retrieval_pairs = [
                item
                for item in active_pairs
                if str(
                    getattr(item[1], "observation_id", "") or ""
                ) not in evidence_packets
            ]
            if retrieval_pairs:
                round_packets, round_diagnostics = (
                    await _retrieve_l1_evidence_packets(
                        context,
                        [item[0] for item in retrieval_pairs],
                        [item[1] for item in retrieval_pairs],
                        round_index=round_index,
                    )
                )
            else:
                round_packets, round_diagnostics = {}, []
            evidence_packets = _merge_l1_evidence_packet_maps(
                evidence_packets,
                round_packets,
            )
            evidence_diagnostics.extend(round_diagnostics)
            ground_llm_budget = get_ground_llm_budget(
                context,
                scope_key=f"l1-location:{context.l1_snapshot_ref}",
            )
            batch_decisions = await reason_l1_location_candidates(
                context,
                [item[0] for item in active_pairs],
                [item[1] for item in active_pairs],
                {
                    str(getattr(observation, "observation_id", "") or ""): evidence_packets.get(
                        str(getattr(observation, "observation_id", "") or "")
                    )
                    for _mention, observation in active_pairs
                    if str(getattr(observation, "observation_id", "") or "")
                    in evidence_packets
                },
                budget=ground_llm_budget,
                round_index=round_index,
            )
            bindings = resolve_l1_location_mentions(
                context,
                ground_llm_budget=ground_llm_budget,
                evidence_packets=evidence_packets,
                candidate_selection_decisions=batch_decisions,
                max_rounds=1,
            )
            bindings = _attach_l1_binding_source_mentions(
                bindings,
                observations,
            )
            context.grounded_bindings = bindings
            retry_observation_ids = _l1_retry_observations(bindings)
            binding_statuses = {
                str(getattr(binding, "mention_ref", "") or "").strip(): str(
                    getattr(binding, "status", "unresolved") or "unresolved"
                )
                for binding in bindings
                if str(getattr(binding, "mention_ref", "") or "").strip()
            }
            signature = tuple(
                (
                    observation_id,
                    tuple(
                        str(
                            getattr(ref, "candidate_id", "")
                            or getattr(getattr(ref, "identity", None), "source_feature_id", "")
                            or ref
                        )
                        for ref in list(
                            getattr(packet, "candidate_refs", None) or []
                        )
                    ),
                    tuple(getattr(packet, "source_spans", None) or []),
                    tuple(getattr(packet, "missing_evidence", None) or []),
                )
                for observation_id, packet in sorted(evidence_packets.items())
            )
            l1_iterations.append({
                "phase": "immediate_evidence_resolution",
                "round": round_index + 1,
                "active_observation_ids": sorted(
                    str(getattr(observation, "observation_id", "") or "").strip()
                    for _mention, observation in active_pairs
                ),
                "packet_count": len(round_packets),
                "candidate_count": sum(
                    len(getattr(packet, "candidate_refs", None) or [])
                    for packet in round_packets.values()
                ),
                "binding_statuses": dict(sorted(binding_statuses.items())),
                "became_resolvable_observation_ids": sorted(
                    observation_id
                    for observation_id, status in binding_statuses.items()
                    if status in {"exact_feature", "feature_set", "inferred_scope"}
                    and previous_binding_statuses.get(observation_id)
                    not in {"exact_feature", "feature_set", "inferred_scope"}
                ),
                "retry_observation_ids": sorted(retry_observation_ids),
                "new_packet_content": signature != previous_signature,
                "elapsed_ms": round(
                    (perf_counter() - evidence_wave_started) * 1000,
                    1,
                ),
            })
            if not retry_observation_ids:
                break
            if round_index > 0 and signature == previous_signature:
                l1_iterations[-1]["stop_reason"] = "evidence_wave_unchanged"
                break
            if retry_observation_ids:
                l1_iterations[-1]["stop_reason"] = (
                    "immediate_evidence_exhausted_typed_gap_required"
                )
            previous_signature = signature
            previous_binding_statuses = binding_statuses
        if is_v2:
            from app.contracts.evidence.identity_contracts import (
                EvidenceObservationSnapshot,
                GroundedEntityBindingSnapshot,
            )
            from app.infrastructure.artifacts.runtime import store_artifact

            observation_snapshot = EvidenceObservationSnapshot(
                observations=observations,
                provenance_refs=[str(getattr(context, "l1_snapshot_ref", "") or "")],
                parent_digest=str(getattr(context, "l1_snapshot_ref", "") or ""),
            )
            observation_ref_data = store_artifact(
                dict(state), "l1_observations", "ground", "EvidenceObservationSnapshot", observation_snapshot
            )
            binding_state = {
                **dict(state),
                "artifact_refs": {
                    **dict(state.get("artifact_refs") or {}),
                    "l1_observations": observation_ref_data,
                },
            }
            binding_snapshot = GroundedEntityBindingSnapshot(
                bindings=bindings,
                observation_snapshot_ref=str(observation_ref_data.get("digest") or ""),
                parent_digest=str(observation_ref_data.get("digest") or ""),
                source_world_model_snapshot_ref=str(
                    getattr(
                        getattr(context, "world_model", None)
                        or getattr(context, "world_model_shadow", None),
                        "snapshot_ref",
                        "",
                    )
                    or ""
                ),
                source_world_model_snapshot_digest=str(
                    getattr(
                        getattr(context, "world_model", None)
                        or getattr(context, "world_model_shadow", None),
                        "snapshot_digest",
                        "",
                    )
                    or ""
                ),
                status_counts={
                    status: sum(
                        1
                        for item in bindings
                        if item.identity_status == status
                    )
                    for status in sorted({
                        item.identity_status for item in bindings
                    })
                },
                relative_location_status_counts={
                    status: sum(
                        1
                        for item in bindings
                        if item.location_expression_status == status
                    )
                    for status in sorted({
                        item.location_expression_status
                        for item in bindings
                    })
                },
            )
            binding_ref_data = store_artifact(
                binding_state, "l1_bindings", "ground", "GroundedEntityBindingSnapshot", binding_snapshot
            )
            from app.contracts.cognition.identity_projection import (
                IdentityBindingCommitEnvelope,
                IdentityBindingCommitResult,
            )
            from app.contracts.cognition.snapshot import (
                SessionWorldModelSnapshot,
            )

            base_world_snapshot = load_artifact(
                dict(state),
                "world_model_snapshot",
                SessionWorldModelSnapshot,
            )
            base_world_ref_data = dict(
                (state.get("artifact_refs") or {}).get(
                    "world_model_snapshot"
                )
                or {}
            )
            if base_world_snapshot is None or not base_world_ref_data:
                raise RuntimeError(
                    "L1_IDENTITY_COMMIT_INPUT_MISSING: base World Model artifact is required"
                )
            l1_ref_data = dict(
                (state.get("artifact_refs") or {}).get("l1_snapshot")
                or {}
            )
            commit_port = getattr(
                getattr(context, "ports", None),
                "world_model_commit",
                None,
            )
            commit_identity = getattr(
                commit_port,
                "commit_identity_bindings",
                None,
            )
            if not callable(commit_identity):
                raise RuntimeError(
                    "L1_IDENTITY_COMMIT_PORT_MISSING: World Model identity commit is unavailable"
                )
            envelope = IdentityBindingCommitEnvelope(
                run_id=str(
                    state.get("run_id") or state.get("session_id") or ""
                ),
                branch_id=str(state.get("branch_id") or "main"),
                l1_snapshot_artifact_ref=ArtifactRef.model_validate(
                    l1_ref_data
                ),
                source_world_model_artifact_ref=(
                    ArtifactRef.model_validate(base_world_ref_data)
                ),
                source_world_model_snapshot=base_world_snapshot,
                observation_artifact_ref=ArtifactRef.model_validate(
                    observation_ref_data
                ),
                observation_snapshot=observation_snapshot,
                binding_artifact_ref=ArtifactRef.model_validate(
                    binding_ref_data
                ),
                binding_snapshot=binding_snapshot,
            )
            commit_result = IdentityBindingCommitResult.model_validate(
                commit_identity(envelope)
            )
            if (
                not commit_result.committed
                or commit_result.status not in {"committed", "noop"}
                or commit_result.world_model_snapshot is None
            ):
                raise RuntimeError(
                    "L1_IDENTITY_COMMIT_FAILED: "
                    + str(
                        commit_result.error_type
                        or commit_result.status
                    )
                )

            source_context_ref = dict(state.get("context_ref") or {})
            source_context_fingerprint = str(
                state.get("context_fingerprint") or ""
            )
            schema_mapping_ref_value = (
                state.get("artifact_refs") or {}
            ).get("schema_mapping_snapshot")
            schema_mapping_artifact_ref = str(
                (
                    schema_mapping_ref_value.get("descriptor_digest")
                    if isinstance(schema_mapping_ref_value, Mapping)
                    else getattr(
                        schema_mapping_ref_value,
                        "descriptor_digest",
                        "",
                    )
                )
                or ""
            )
            context_version_text = str(
                source_context_ref.get("version")
                or state.get("context_version")
                or getattr(context, "version", "")
                or ""
            )
            refreshed_context = await build_planning_context(
                session_id,
                village_name=str(
                    (state.get("config") or {}).get("village_name")
                    or getattr(context, "village_name", "")
                    or ""
                ),
                refresh=True,
                include_reports=False,
                version=(
                    int(context_version_text)
                    if context_version_text.isdigit()
                    else None
                ),
                expected_snapshot_digest=expected_snapshot_digest or None,
                expected_world_model_digest=(
                    commit_result.world_model_snapshot_digest
                ),
                data_catalog=getattr(
                    context,
                    "data_resource_catalog",
                    None,
                ),
                schema_mapping_snapshot=getattr(
                    context,
                    "schema_mapping_snapshot",
                    None,
                ),
                schema_mapping_artifact_ref=schema_mapping_artifact_ref,
                artifact_root=str(state.get("artifact_root") or ""),
                defer_cognition_bootstrap=False,
            )
            from app.workflow.layers.context_bootstrap import (
                _context_authority,
            )

            (
                resulting_context_version,
                resulting_context_fingerprint,
                resulting_context_ref,
            ) = _context_authority(
                refreshed_context,
                session_id=session_id,
            )
            if (
                resulting_context_ref.get(
                    "world_model_snapshot_digest"
                )
                != commit_result.world_model_snapshot_digest
            ):
                raise RuntimeError(
                    "L1_IDENTITY_CONTEXT_PUBLICATION_FAILED: child World Model digest mismatch"
                )
            current_state = {
                **dict(state),
                "context_version": resulting_context_version,
                "context_fingerprint": resulting_context_fingerprint,
                "context_ref": resulting_context_ref,
                "world_model_snapshot_ref": (
                    commit_result.world_model_snapshot_ref
                ),
                "world_model_snapshot_digest": (
                    commit_result.world_model_snapshot_digest
                ),
                "artifact_refs": {
                    **dict(state.get("artifact_refs") or {}),
                    "l1_observations": observation_ref_data,
                    "l1_bindings": binding_ref_data,
                },
            }
            current_world_ref_data = store_artifact(
                current_state,
                "world_model_current_snapshot",
                "ground",
                "SessionWorldModelSnapshot",
                commit_result.world_model_snapshot,
                parent_keys=(
                    "world_model_snapshot",
                    "l1_snapshot",
                    "l1_observations",
                    "l1_bindings",
                ),
            )
            observation_ref_payload = observation_ref_data
            binding_ref_payload = binding_ref_data
        context.grounded_bindings = bindings
        from app.contracts.evidence.stage_contracts import (
            EvidenceGapScheduleRecord,
        )

        gap_rows: list[dict[str, Any]] = []
        for binding in bindings:
            if binding.identity_status in {"ambiguous", "unresolved"}:
                gap_rows.append(EvidenceGapScheduleRecord(
                    gap_ref=f"ground-gap:{binding.mention_ref}",
                    producer_stage="GROUND",
                    subject_refs=tuple(
                        value
                        for value in (
                            binding.mention_ref,
                            binding.canonical_entity_ref,
                        )
                        if value
                    ),
                    missing_fields=("canonical_entity_ref",),
                    source_digest=str(
                        getattr(context, "l1_snapshot_ref", "") or ""
                    ),
                    earliest_resolution_stage="evidence",
                    deferred_until="",
                    allowed_sources=(
                        "data",
                        "gis",
                        "kg",
                        "artifact",
                        "external_map_cache",
                    ),
                    retrieval_capability="spatial_lookup",
                    status=(
                        "requires_human_confirmation"
                        if binding.identity_status == "ambiguous"
                        else "not_available"
                    ),
                    evidence_refs=tuple(binding.evidence_refs),
                    failure_reason=binding.uncertainty_reason,
                    recovery_pointer=(
                        f"{session_id}:ground:l1:{binding.mention_ref}"
                    ),
                ).model_dump(mode="json"))
            if binding.location_expression_status in {
                "ambiguous", "unresolved",
            }:
                gap_rows.append(EvidenceGapScheduleRecord(
                    gap_ref=(
                        f"ground-relation-gap:{binding.mention_ref}"
                    ),
                    producer_stage="GROUND",
                    subject_refs=tuple(dict.fromkeys([
                        binding.mention_ref,
                        *binding.anchor_entity_refs,
                        *binding.anchor_work_item_refs,
                    ])),
                    missing_fields=(
                        "spatial_relation",
                        "anchor_entity_refs",
                    ),
                    source_digest=str(
                        getattr(context, "l1_snapshot_ref", "") or ""
                    ),
                    earliest_resolution_stage="evidence",
                    deferred_until="",
                    allowed_sources=(
                        "data",
                        "gis",
                        "kg",
                        "artifact",
                        "external_map_cache",
                    ),
                    retrieval_capability=(
                        "relative_location_anchor_lookup"
                    ),
                    status=(
                        "requires_human_confirmation"
                        if binding.location_expression_status == "ambiguous"
                        else "not_available"
                    ),
                    evidence_refs=tuple(dict.fromkeys([
                        *binding.evidence_refs,
                        *binding.relation_evidence_refs,
                    ])),
                    failure_reason=binding.uncertainty_reason,
                    recovery_pointer=(
                        f"{session_id}:ground:l1-relation:"
                        f"{binding.mention_ref}"
                    ),
                ).model_dump(mode="json"))
        identity_transition_refs: dict[str, Any] = {}
        identity_transition_patch: dict[str, Any] = {}
        if is_v2:
            from app.contracts.cognition.stage_contracts import (
                L1WorldProjectionSnapshot,
            )
            from app.contracts.workflow.workflow_contracts import (
                GateDecision,
                PendingRequest,
            )
            from app.workflow.stage_adapter import persist_gate_decision

            current_world_ref = ArtifactRef.model_validate(
                current_world_ref_data
            )
            projection = L1WorldProjectionSnapshot(
                context_version=str(resulting_context_version),
                context_fingerprint=resulting_context_fingerprint,
                artifact_id=(
                    "l1-world-projection:"
                    + commit_result.projection_fingerprint.removeprefix(
                        "sha256:"
                    )[:24]
                ),
                status=(
                    "ready"
                    if provisional_l1_gate.passed and not gap_rows
                    else "partial"
                ),
                l1_snapshot_artifact_ref=envelope.l1_snapshot_artifact_ref,
                observation_artifact_ref=envelope.observation_artifact_ref,
                binding_artifact_ref=envelope.binding_artifact_ref,
                source_world_model_artifact_ref=(
                    envelope.source_world_model_artifact_ref
                ),
                resulting_world_model_artifact_ref=current_world_ref,
                source_world_model_snapshot_ref=(
                    commit_result.parent_world_model_snapshot_ref
                ),
                source_world_model_snapshot_digest=(
                    commit_result.parent_world_model_snapshot_digest
                ),
                resulting_world_model_snapshot_ref=(
                    commit_result.world_model_snapshot_ref
                ),
                resulting_world_model_snapshot_digest=(
                    commit_result.world_model_snapshot_digest
                ),
                resulting_world_model_version=(
                    commit_result.world_model_version
                ),
                identity_projection_fingerprint=(
                    commit_result.projection_fingerprint
                ),
                source_context_ref=source_context_ref,
                resulting_context_ref=resulting_context_ref,
                source_context_fingerprint=source_context_fingerprint,
                resulting_context_fingerprint=(
                    resulting_context_fingerprint
                ),
                work_item_count=len(mentions),
                source_mention_count=sum(
                    len(getattr(item, "source_mention_refs", None) or [])
                    for item in observations
                ),
                status_counts={
                    status: sum(
                        1
                        for item in bindings
                        if item.identity_status == status
                    )
                    for status in sorted({
                        item.identity_status for item in bindings
                    })
                },
                relative_location_status_counts={
                    status: sum(
                        1
                        for item in bindings
                        if item.location_expression_status == status
                    )
                    for status in sorted({
                        item.location_expression_status
                        for item in bindings
                    })
                },
                gap_refs=tuple(
                    str(item.get("gap_ref") or "")
                    for item in gap_rows
                    if str(item.get("gap_ref") or "")
                ),
            )
            projection_state = {
                **current_state,
                "artifact_refs": {
                    **dict(current_state.get("artifact_refs") or {}),
                    "world_model_current_snapshot": current_world_ref_data,
                },
            }
            projection_ref_data = store_artifact(
                projection_state,
                "l1_world_projection",
                "ground",
                "L1WorldProjectionSnapshot",
                projection,
                parent_keys=(
                    "world_model_snapshot",
                    "world_model_current_snapshot",
                    "l1_snapshot",
                    "l1_observations",
                    "l1_bindings",
                ),
            )
            identity_pending = [
                PendingRequest(
                    request_id=f"l1-identity:{binding.mention_ref}",
                    stage="l1",
                    request_type=(
                        "identity_human_confirmation"
                        if binding.identity_status == "ambiguous"
                        else "identity_evidence_recovery"
                    ),
                    context={
                        "work_item_ref": binding.mention_ref,
                        "identity_status": binding.identity_status,
                        "candidate_entity_refs": list(
                            binding.candidate_entity_refs
                        )[:16],
                        "uncertainty_reason": (
                            binding.uncertainty_reason
                        ),
                        "recovery_pointer": (
                            f"{session_id}:ground:l1:{binding.mention_ref}"
                        ),
                    },
                )
                for binding in bindings
                if binding.identity_status in {"ambiguous", "unresolved"}
            ]
            relative_pending = [
                PendingRequest(
                    request_id=f"l1-relative-location:{binding.mention_ref}",
                    stage="l1",
                    request_type=(
                        "relative_location_human_confirmation"
                        if binding.location_expression_status == "ambiguous"
                        else "relative_location_evidence_recovery"
                    ),
                    context={
                        "work_item_ref": binding.mention_ref,
                        "location_expression_ref": (
                            binding.location_expression_ref
                        ),
                        "location_expression_status": (
                            binding.location_expression_status
                        ),
                        "spatial_relation": binding.spatial_relation,
                        "anchor_entity_refs": list(
                            binding.anchor_entity_refs
                        )[:16],
                        "anchor_work_item_refs": list(
                            binding.anchor_work_item_refs
                        )[:16],
                        "uncertainty_reason": (
                            binding.uncertainty_reason
                        ),
                        "recovery_pointer": (
                            f"{session_id}:ground:l1-relation:"
                            f"{binding.mention_ref}"
                        ),
                    },
                )
                for binding in bindings
                if binding.location_expression_status in {
                    "ambiguous", "unresolved",
                }
            ]
            ground_pending = [*identity_pending, *relative_pending]
            provisional_pending = list(
                provisional_l1_gate.pending_requests or []
            )
            final_passed = bool(
                provisional_l1_gate.passed
                and not provisional_pending
                and not provisional_l1_gate.evidence_requests
                and not ground_pending
            )
            identity_route = (
                "HUMAN"
                if any(
                    binding.identity_status == "ambiguous"
                    or binding.location_expression_status == "ambiguous"
                    for binding in bindings
                )
                else "EXPLORE"
                if ground_pending
                else None
            )
            final_route = (
                None
                if final_passed
                else provisional_l1_gate.feedback_route
                or identity_route
                or "EXPLORE"
            )
            final_gate = GateDecision(
                stage="l1",
                passed=final_passed,
                feedback_route=final_route,
                pending_requests=[
                    *provisional_pending,
                    *ground_pending,
                ],
                evidence_requests=list(
                    provisional_l1_gate.evidence_requests or []
                ),
                context_version=str(resulting_context_version),
                artifact_id=(
                    "gate-l1-world:"
                    + commit_result.projection_fingerprint.removeprefix(
                        "sha256:"
                    )[:24]
                ),
                route_reason=(
                    "l1_world_projection_ready"
                    if final_passed
                    else "l1_world_projection_has_explicit_gaps"
                ),
            )
            gate_state = {
                **projection_state,
                "artifact_refs": {
                    **dict(projection_state.get("artifact_refs") or {}),
                    "l1_world_projection": projection_ref_data,
                },
            }
            final_gate_ref = persist_gate_decision(
                gate_state,
                "l1",
                final_gate,
                output_refs={
                    "l1_snapshot": l1_ref_data,
                    "l1_world_projection": projection_ref_data,
                    "world_model_current_snapshot": (
                        current_world_ref_data
                    ),
                },
            )
            identity_transition_refs = {
                "world_model_current_snapshot": current_world_ref_data,
                "l1_world_projection": projection_ref_data,
                "l1_gate": final_gate_ref.model_dump(mode="json"),
            }
            identity_transition_patch = {
                "context_version": resulting_context_version,
                "context_fingerprint": resulting_context_fingerprint,
                "context_ref": resulting_context_ref,
                "world_model_snapshot_ref": (
                    commit_result.world_model_snapshot_ref
                ),
                "world_model_snapshot_digest": (
                    commit_result.world_model_snapshot_digest
                ),
                "l1_identity_projection_status": projection.status,
                "l1_identity_projection_fingerprint": (
                    projection.identity_projection_fingerprint
                ),
            }
        return {
            **identity_transition_patch,
            "artifact_refs": {
                "l1_observations": observation_ref_payload,
                "l1_bindings": binding_ref_payload,
                **identity_transition_refs,
            },
            "l1_spatial_resolution": {
                "status_counts": {
                    status: sum(
                        1
                        for item in bindings
                        if item.identity_status == status
                    )
                    for status in sorted({
                        item.identity_status for item in bindings
                    })
                },
                "relative_location_status_counts": {
                    status: sum(
                        1
                        for item in bindings
                        if item.location_expression_status == status
                    )
                    for status in sorted({
                        item.location_expression_status
                        for item in bindings
                    })
                },
                "geometry_inventory_status_counts": {
                    status: sum(1 for item in bindings if item.status == status)
                    for status in sorted({item.status for item in bindings})
                },
                "work_item_count": len(mentions),
                "source_mention_count": sum(
                    len(getattr(item, "source_mention_refs", None) or [])
                    for item in observations
                ),
                "elapsed_ms": round(
                    (perf_counter() - materialization_started) * 1000,
                    1,
                ),
                "resolved_by": "ground.current_context",
                "unresolved_gap_count": len(gap_rows),
                "gap_rows": gap_rows[:64],
                "evidence_facade": {
                    "packet_count": len(evidence_packets),
                    "diagnostics": evidence_diagnostics[:64],
                },
                "iterations": l1_iterations,
            },
        }

    @staticmethod
    def load(state: Mapping[str, Any]) -> GroundingResult:
        from app.infrastructure.artifacts.runtime import load_artifact

        result = load_artifact(dict(state), "grounding_result", GroundingResult)
        if result is None:
            raise RuntimeError("GROUND did not commit GroundingResult")
        return result

    async def run(self, state: Mapping[str, Any]) -> GroundRunResult:
        request = GroundRunRequest.from_state(state)
        from app.workflow.stages.support import require_upstream_gates

        require_upstream_gates(
            dict(state),
            (
                "data", "kg", "evidence", "l1", "l2", "l3",
                "target_projection",
            ),
        )
        from app.infrastructure.artifacts.runtime import validate_artifact_context

        validate_artifact_context(dict(state), "target_projection", request.target_projection_ref)
        from .stage import ground_node

        patch = dict(await ground_node(dict(state)))
        refs = {**dict(state.get("artifact_refs") or {}), **dict(patch.get("artifact_refs") or {})}
        result = self.load({**dict(state), **patch, "artifact_refs": refs})
        return GroundRunResult(
            request=request,
            grounding=result,
            artifact_ref=ArtifactRef.model_validate(refs["grounding_result"]),
            gate_ref=ArtifactRef.model_validate(refs["ground_gate"]),
            state_patch=patch,
        )


async def run_ground(state: Mapping[str, Any]) -> GroundRunResult:
    """Run GROUND through the canonical business-module facade."""

    return await GroundApplication().run(state)


async def run_ground_stage(state: Mapping[str, Any]) -> dict[str, Any]:
    """Workflow adapter that keeps GROUND orchestration behind its facade."""

    return (await run_ground(state)).to_state_patch()


def run_l1_location_grounding(state: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve L1 location mentions without requiring TARGET_PROJECTION."""

    return _run_async_from_sync(GroundApplication.materialize_l1_locations(state))


__all__ = [
    "GroundApplication",
    "GroundRunRequest",
    "GroundRunResult",
    "run_ground",
    "run_ground_stage",
    "run_l1_location_grounding",
    "ground_aggregate",
    "build_candidate_site",
]
