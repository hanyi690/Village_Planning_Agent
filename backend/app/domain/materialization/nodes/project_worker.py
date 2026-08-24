"""Project materializer: place each approved L3 project geometry."""

from __future__ import annotations

import math
from typing import Any, List

from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.nodes.worker_common import (
    _execution_intent_from_plan,
    _footprint_geometry,
    _plan_tasks,
    _task_value,
    _parcel_geometry,
    _resolve_parcel_by_bsm,
    _scenario_features_for_layer,
    _task_for_target,
    _attach_feature_lineage,
    _task_enabled,
    _task_execution_result,
)
from app.contracts.workflow.execution_plan_contracts import TypedActionResult, WorkerResult
from app.contracts.spatial.parcel_change_contracts import ParcelChange
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _metric_area_ha(geometry: Any, crs: str) -> float:
    """Measure a source-backed geometry in the same metric CRS as grounding.

    EXECUTE receives WKT in the bundle CRS.  Never use ``geometry.area``
    directly for geographic coordinates and never trust a catalog area field
    for a split/remainder; both can disagree with the approved candidate.
    """
    from app.spatial.model.crs_engine import get_metric_crs, project_geometry

    normalized = str(crs or "EPSG:4326").strip() or "EPSG:4326"
    try:
        from pyproj import CRS

        metric_crs = (
            get_metric_crs(float(geometry.representative_point().x))
            if CRS.from_user_input(normalized).is_geographic
            else normalized
        )
    except Exception:
        metric_crs = get_metric_crs(float(geometry.representative_point().x))
    projected = project_geometry(geometry, normalized, metric_crs)
    area = float(projected.area)
    if not math.isfinite(area):
        # Synthetic fixtures can sit outside the supported national CRS
        # zones (for example around longitude 0).  Keep the metric contract
        # without falling back to degree-square area.
        projected = project_geometry(geometry, normalized, "EPSG:3857")
        area = float(projected.area)
    return max(area / 10_000.0, 0.0) if math.isfinite(area) else 0.0


def _candidate_site_footprint_changes(
    project: Any,
    candidate: Any,
    parcel_by_bsm: dict[str, Any],
    brief: Any = None,
    *,
    include_remainder: bool = True,
) -> list[ParcelChange]:
    """Turn one approved site footprint into a source-backed parcel split.

    Overlay roles are deliberately excluded: they belong in the planned
    overlay layer and must not mutate current land-use classifications.  A
    footprint is materialized only when SELECT supplied a resolved
    classification, one source BSM, a positive audited area, and geometry
    contained by that source parcel.
    """
    if str(getattr(project, "materialization_role", "") or "") != "site_footprint":
        return []
    from shapely import wkt as shapely_wkt
    from shapely.geometry import shape

    from app.domain.materialization.classification_utils import _classification_from_decision
    from app.domain.materialization.land_design_worker import _parcel_classification

    classification = _classification_from_decision(
        getattr(project, "classification_decision", None)
    )
    source_bsms = list(dict.fromkeys(
        str(value)
        for value in (getattr(candidate, "source_bsms", None) or [])
        if str(value)
    ))
    if classification is None or len(source_bsms) != 1:
        return []
    # A fully prohibited source must never be revived by EXECUTE.  Partial
    # availability is valid: the approved candidate geometry is the clipped
    # footprint and the source parcel remainder is preserved separately.
    # An unknown source-backed parcel is equally non-executable: EXECUTE must
    # not turn an unresolved availability fact into an implicit whole-parcel
    # approval.  Exact non-parcel geometries may remain unknown, but this
    # worker only handles source-backed parcel footprints.
    availability_status = str(
        getattr(candidate, "availability_status", "unknown") or "unknown"
    )
    if availability_status in {"fully_unavailable", "unknown"}:
        return []
    # An adjacency requirement is a typed execution precondition.  The
    # presence of a nearby parcel alone never authorizes an implicit merge,
    # but an explicit requirement without adjacent evidence must fail closed.
    adjacency_required = bool(
        list(getattr(brief, "adjacency_requirements", None) or [])
    )
    if adjacency_required:
        # A nearby BSM is only context.  An execution that claims to
        # coordinate with it must carry both the adjacency evidence and a
        # typed relation ref frozen by SELECT/approval; otherwise the worker
        # would silently ignore the required neighboring operation.
        if (
            not list(getattr(candidate, "adjacent_parcel_bsms", None) or [])
            or not list(getattr(candidate, "adjacency_evidence_refs", None) or [])
            or not list(getattr(candidate, "relation_refs", None) or [])
        ):
            return []
    parcel = parcel_by_bsm.get(source_bsms[0])
    if parcel is None:
        return []
    try:
        source_geometry = shape(_parcel_geometry(parcel))
        footprint = shapely_wkt.loads(str(getattr(candidate, "wkt", "") or ""))
    except Exception:
        return []
    if (
        source_geometry.is_empty
        or footprint.is_empty
        or footprint.geom_type not in {"Polygon", "MultiPolygon"}
    ):
        return []
    # A partial-availability candidate is executable only inside the frozen
    # eligible parent extent.  Do not silently clip a forged/out-of-bounds
    # footprint back into that extent: the approved geometry identity would no
    # longer describe what EXECUTE materialized, so fail closed.
    eligible_geometry = None
    eligible_wkt = str(getattr(candidate, "eligible_geometry_wkt", "") or "")
    if availability_status == "partially_available" and eligible_wkt:
        try:
            eligible_geometry = shapely_wkt.loads(eligible_wkt).intersection(
                source_geometry
            )
        except Exception:
            return []
        if eligible_geometry.is_empty or not eligible_geometry.is_valid:
            return []
        excess = footprint.difference(eligible_geometry)
        if not excess.is_empty and float(excess.area) > max(
            float(footprint.area) * 1e-8,
            1e-12,
        ):
            return []
    footprint = footprint.intersection(source_geometry)
    if footprint.is_empty or footprint.area <= 0:
        return []
    geometry_crs = str(getattr(candidate, "crs", "EPSG:4326") or "EPSG:4326")
    # SELECT freezes the candidate's metric areas as part of the approved
    # geometry identity.  Use those values when present so the footprint and
    # remainder keep the exact approved area budget; derive them from WKT only
    # for older candidates that did not carry the metrics.
    source_area_ha = float(getattr(candidate, "source_area_ha", 0.0) or 0.0)
    planning_area_ha = float(getattr(candidate, "planning_area_ha", 0.0) or 0.0)
    if source_area_ha <= 0.0:
        source_area_ha = _metric_area_ha(source_geometry, geometry_crs)
    if planning_area_ha <= 0.0:
        planning_area_ha = _metric_area_ha(footprint, geometry_crs)
    if source_area_ha <= 0.0 or planning_area_ha <= 0.0:
        return []
    coverage_ratio = max(0.0, min(1.0, planning_area_ha / source_area_ha))
    source_wkt = source_geometry.wkt
    changes = [
        ParcelChange(
            bsm=f"{project.target_id}:footprint",
            action="create",
            derived_from_bsms=source_bsms,
            after_classification=classification,
            before_geometry_wkt=source_wkt,
            after_geometry_wkt=footprint.wkt,
            new_area_ha=planning_area_ha,
            source_area_ha=source_area_ha,
            coverage_ratio=coverage_ratio,
            availability_status=str(
                getattr(candidate, "availability_status", "unknown") or "unknown"
            ),
            eligible_area_ha=min(
                max(float(getattr(candidate, "eligible_area_ha", source_area_ha) or 0.0), 0.0),
                source_area_ha,
            )
            if getattr(candidate, "eligible_area_ha", None) is not None
            else None,
            excluded_area_ha=min(
                max(float(getattr(candidate, "excluded_area_ha", 0.0) or 0.0), 0.0),
                source_area_ha,
            )
            if getattr(candidate, "excluded_area_ha", None) is not None
            else None,
            adjacent_parcel_bsms=list(
                getattr(candidate, "adjacent_parcel_bsms", None) or []
            ),
            adjacency_evidence_refs=list(
                getattr(candidate, "adjacency_evidence_refs", None) or []
            ),
            project_ref=project.target_id,
            intervention_id=project.target_id,
            candidate_id=str(getattr(candidate, "candidate_id", "") or ""),
            feature_id=f"materialized:{project.target_id}:{getattr(candidate, 'candidate_id', '')}",
            target_id=project.target_id,
            scenario_id=str(getattr(candidate, "scenario_id", "") or ""),
            feature_bsms=list(getattr(candidate, "feature_bsms", None) or []),
            source_feature_ids=list(getattr(candidate, "source_feature_ids", None) or []),
            entity_refs=list(getattr(candidate, "entity_refs", None) or []),
            relation_refs=list(getattr(candidate, "relation_refs", None) or []),
            evidence_refs=list(getattr(candidate, "evidence_refs", None) or []),
            l1_snapshot_ref=str(getattr(candidate, "l1_snapshot_ref", "") or ""),
            bundle_snapshot_digest=str(getattr(candidate, "bundle_snapshot_digest", "") or ""),
        )
    ]
    remainder = source_geometry.difference(footprint)
    remainder_regions = [
        (
            "remainder",
            remainder,
            max(source_area_ha - planning_area_ha, 0.0),
        )
    ]
    # A partially available parcel has two distinct preserved regions: the
    # eligible-but-unallocated remainder and the excluded source geometry.
    # Keep them separate whenever SELECT froze the usable parent extent.
    eligible_wkt = str(getattr(candidate, "eligible_geometry_wkt", "") or "")
    if availability_status == "partially_available" and eligible_wkt:
        try:
            eligible_geometry = shapely_wkt.loads(eligible_wkt).intersection(source_geometry)
        except Exception:
            eligible_geometry = None
        if (
            eligible_geometry is not None
            and not eligible_geometry.is_empty
            and eligible_geometry.is_valid
        ):
            eligible_remainder = eligible_geometry.difference(footprint)
            excluded_geometry = source_geometry.difference(eligible_geometry)
            eligible_area = float(getattr(candidate, "eligible_area_ha", 0.0) or 0.0)
            excluded_area = float(getattr(candidate, "excluded_area_ha", 0.0) or 0.0)
            remainder_regions = [
                (
                    "remainder",
                    eligible_remainder,
                    max(eligible_area - planning_area_ha, 0.0),
                ),
                ("excluded", excluded_geometry, max(excluded_area, 0.0)),
            ]
    if include_remainder:
        preserved = _parcel_classification(parcel, source="preserve")
        for suffix, remainder, preserved_area_ha in remainder_regions:
            if remainder.is_empty or remainder.area <= 0:
                continue
            changes.append(
                ParcelChange(
                    bsm=f"{project.target_id}:{suffix}",
                    action="preserve",
                    derived_from_bsms=source_bsms,
                    before_classification=preserved,
                    after_classification=preserved,
                    before_geometry_wkt=source_wkt,
                    after_geometry_wkt=remainder.wkt,
                    new_area_ha=preserved_area_ha
                    or _metric_area_ha(remainder, geometry_crs),
                    source_area_ha=source_area_ha,
                    coverage_ratio=max(
                        0.0,
                        min(
                            1.0,
                            (preserved_area_ha or 0.0) / source_area_ha,
                        ),
                    ),
                    availability_status=availability_status,
                    eligible_area_ha=min(
                        max(
                            float(
                                getattr(
                                    candidate,
                                    "eligible_area_ha",
                                    source_area_ha,
                                )
                                or 0.0
                            ),
                            0.0,
                        ),
                        source_area_ha,
                    )
                    if getattr(candidate, "eligible_area_ha", None) is not None
                    else None,
                    excluded_area_ha=min(
                        max(
                            float(
                                getattr(candidate, "excluded_area_ha", 0.0)
                                or 0.0
                            ),
                            0.0,
                        ),
                        source_area_ha,
                    )
                    if getattr(candidate, "excluded_area_ha", None) is not None
                    else None,
                    adjacent_parcel_bsms=list(
                        getattr(candidate, "adjacent_parcel_bsms", None) or []
                    ),
                    adjacency_evidence_refs=list(
                        getattr(candidate, "adjacency_evidence_refs", None) or []
                    ),
                    project_ref=project.target_id,
                    intervention_id=project.target_id,
                    target_id=project.target_id,
                    scenario_id=str(
                        getattr(candidate, "scenario_id", "") or ""
                    ),
                    feature_bsms=list(
                        getattr(candidate, "feature_bsms", None) or []
                    ),
                    source_feature_ids=list(
                        getattr(candidate, "source_feature_ids", None) or []
                    ),
                    entity_refs=list(
                        getattr(candidate, "entity_refs", None) or []
                    ),
                    relation_refs=list(
                        getattr(candidate, "relation_refs", None) or []
                    ),
                    evidence_refs=list(
                        getattr(candidate, "evidence_refs", None) or []
                    ),
                    l1_snapshot_ref=str(
                        getattr(candidate, "l1_snapshot_ref", "") or ""
                    ),
                    bundle_snapshot_digest=str(
                        getattr(candidate, "bundle_snapshot_digest", "") or ""
                    ),
                )
            )
    return changes


def _shared_parcel_remainder_changes(
    source_bsm: str,
    parcel: Any,
    candidates: list[Any],
    footprint_changes: list[ParcelChange],
) -> list[ParcelChange]:
    """Preserve eligible and excluded remainders after shared BSM use."""
    from shapely import wkt as shapely_wkt
    from shapely.geometry import shape
    from shapely.ops import unary_union

    try:
        source_geometry = shape(_parcel_geometry(parcel))
        footprints = [
            shapely_wkt.loads(str(change.after_geometry_wkt or ""))
            for change in footprint_changes
            if str(change.after_geometry_wkt or "")
        ]
    except Exception:
        return []
    if source_geometry.is_empty or not footprints:
        return []
    union = unary_union(footprints).intersection(source_geometry)
    remainder = source_geometry.difference(union)
    if remainder.is_empty or remainder.area <= 0:
        return []
    source_area_ha = max(
        float(getattr(candidate, "source_area_ha", 0.0) or 0.0)
        for candidate in candidates
    )
    planning_area_ha = sum(
        float(getattr(candidate, "planning_area_ha", 0.0) or 0.0)
        for candidate in candidates
    )
    if source_area_ha <= 0 or planning_area_ha <= 0 or planning_area_ha > source_area_ha + 1e-9:
        return []
    from app.domain.materialization.land_design_worker import _parcel_classification

    preserved = _parcel_classification(parcel, source="preserve")
    availability = {
        str(getattr(candidate, "availability_status", "unknown") or "unknown")
        for candidate in candidates
    }
    availability_status = availability.pop() if len(availability) == 1 else "unknown"
    eligible_values = [
        float(getattr(candidate, "eligible_area_ha", 0.0) or 0.0)
        for candidate in candidates
        if getattr(candidate, "eligible_area_ha", None) is not None
    ]
    excluded_values = [
        float(getattr(candidate, "excluded_area_ha", 0.0) or 0.0)
        for candidate in candidates
        if getattr(candidate, "excluded_area_ha", None) is not None
    ]
    eligible_area = min(
        max(max(eligible_values or [source_area_ha]), 0.0),
        source_area_ha,
    )
    excluded_area = (
        min(max(max(excluded_values), 0.0), source_area_ha)
        if excluded_values and availability_status != "fully_available"
        else None
    )
    adjacent_bsms = sorted(
        {
            str(value)
            for candidate in candidates
            for value in (getattr(candidate, "adjacent_parcel_bsms", None) or [])
            if str(value)
        }
    )
    adjacency_refs = sorted(
        {
            str(value)
            for candidate in candidates
            for value in (getattr(candidate, "adjacency_evidence_refs", None) or [])
            if str(value)
        }
    )
    feature_bsms = sorted(
        {
            str(value)
            for candidate in candidates
            for value in (getattr(candidate, "feature_bsms", None) or [])
            if str(value)
        }
    )
    source_feature_ids = sorted(
        {
            str(value)
            for candidate in candidates
            for value in (getattr(candidate, "source_feature_ids", None) or [])
            if str(value)
        }
    )
    entity_refs = sorted(
        {
            str(value)
            for candidate in candidates
            for value in (getattr(candidate, "entity_refs", None) or [])
            if str(value)
        }
    )
    relation_refs = sorted(
        {
            str(value)
            for candidate in candidates
            for value in (getattr(candidate, "relation_refs", None) or [])
            if str(value)
        }
    )
    evidence_refs = sorted(
        {
            str(value)
            for candidate in candidates
            for value in (getattr(candidate, "evidence_refs", None) or [])
            if str(value)
        }
    )
    common = {
        "action": "preserve",
        "derived_from_bsms": [source_bsm],
        "before_classification": preserved,
        "after_classification": preserved,
        "before_geometry_wkt": source_geometry.wkt,
        "source_area_ha": source_area_ha,
        "availability_status": availability_status,
        "eligible_area_ha": eligible_area,
        "excluded_area_ha": excluded_area,
        "adjacent_parcel_bsms": adjacent_bsms,
        "adjacency_evidence_refs": adjacency_refs,
        "project_ref": f"parcel-resource:{source_bsm}",
        "intervention_id": f"parcel-resource:{source_bsm}",
        "target_id": f"shared:{source_bsm}",
        "scenario_id": str(getattr(candidates[0], "scenario_id", "") or ""),
        "feature_bsms": feature_bsms,
        "source_feature_ids": source_feature_ids,
        "entity_refs": entity_refs,
        "relation_refs": relation_refs,
        "evidence_refs": evidence_refs,
        "l1_snapshot_ref": str(getattr(candidates[0], "l1_snapshot_ref", "") or ""),
        "bundle_snapshot_digest": str(
            getattr(candidates[0], "bundle_snapshot_digest", "") or ""
        ),
    }
    regions = [("remainder", remainder, max(source_area_ha - planning_area_ha, 0.0))]
    eligible_wkts = {
        str(getattr(candidate, "eligible_geometry_wkt", "") or "")
        for candidate in candidates
    }
    if availability_status == "partially_available" and len(eligible_wkts) == 1:
        eligible_wkt = next(iter(eligible_wkts))
        if eligible_wkt:
            try:
                eligible_geometry = shapely_wkt.loads(eligible_wkt).intersection(
                    source_geometry
                )
            except Exception:
                eligible_geometry = None
            if (
                eligible_geometry is not None
                and not eligible_geometry.is_empty
                and eligible_geometry.is_valid
            ):
                regions = [
                    (
                        "remainder",
                        eligible_geometry.difference(union),
                        max(eligible_area - planning_area_ha, 0.0),
                    ),
                    (
                        "excluded",
                        source_geometry.difference(eligible_geometry),
                        max(excluded_area or 0.0, 0.0),
                    ),
                ]
    changes: list[ParcelChange] = []
    for suffix, region, area_ha in regions:
        if region.is_empty or region.area <= 0:
            continue
        changes.append(
            ParcelChange(
                bsm=f"shared:{source_bsm}:{suffix}",
                after_geometry_wkt=region.wkt,
                new_area_ha=area_ha or _metric_area_ha(region, "EPSG:4326"),
                coverage_ratio=max(
                    0.0,
                    min(1.0, (area_ha or 0.0) / source_area_ha),
                ),
                feature_id=f"materialized:shared:{source_bsm}:{suffix}",
                **common,
            )
        )
    return changes


def _project_worker(state: ExecuteAgentState) -> WorkerResult:
    """Project worker: place each L3 project on the SSD-selected parcel.

    Joins selected parcels and design briefs by stable target ID. Non-spatial
    action targets produce typed action results and never parcel changes.
    """
    from app.domain.materialization.land_design_worker import design_project_footprint

    if not _task_enabled(state, "site_area"):
        return WorkerResult(worker_type="site_area")

    projects = list(getattr(_execution_intent_from_plan(state), "site_area_targets", None) or [])
    parcel_by_bsm = _resolve_parcel_by_bsm(state)
    selected_by_target = {
        str(_task_value(task, "target_id", "")): str(_task_value(_task_value(task, "assignment"), "selected_bsm", ""))
        for task in _plan_tasks(state, {"site_area_footprint"})
        if _task_value(_task_value(task, "assignment"), "selected_bsm", "")
    }
    projects_by_target = {
        str(getattr(project, "target_id", "")): project for project in projects
        if getattr(project, "target_id", "")
    }
    briefs = list(state.land_design_briefs or [])
    briefs_by_target = {
        str(brief.project_ref): brief
        for brief in briefs
        if getattr(brief, "project_ref", "")
    }
    candidate_geometry_by_id = getattr(state, "candidate_geometry_by_id", {}) or {}
    candidate_tasks_by_target: dict[str, list[tuple[str, Any]]] = {}
    for task in _plan_tasks(state, {"site_area_footprint"}):
        candidate_id = str(_task_value(task, "candidate_id", "") or "")
        target_id = str(_task_value(task, "target_id", "") or "")
        if candidate_id and target_id:
            candidate_tasks_by_target.setdefault(target_id, []).append((candidate_id, task))
    # Several approved site-footprint tasks may consume different members of
    # one source BSM.  Prepare them as one resource transaction: each member
    # gets its own footprint, while the source remainder is preserved once
    # after the union.  If the group is not provably safe, every member is
    # failed closed rather than emitting duplicate remainders.
    shared_group_by_candidate: dict[str, str] = {}
    shared_group_diagnostics: dict[str, str] = {}
    shared_footprint_changes_by_candidate: dict[str, list[ParcelChange]] = {}
    shared_remainder_by_bsm: dict[str, list[ParcelChange]] = {}
    candidate_groups: dict[str, list[tuple[str, Any, Any]]] = {}
    for target_id, entries in candidate_tasks_by_target.items():
        project = projects_by_target.get(target_id)
        if project is None or str(getattr(project, "materialization_role", "") or "") != "site_footprint":
            continue
        for candidate_id, task in entries:
            candidate = candidate_geometry_by_id.get(candidate_id)
            source_bsms = list(getattr(candidate, "source_bsms", None) or []) if candidate is not None else []
            if candidate is None or len(source_bsms) != 1:
                continue
            candidate_groups.setdefault(str(source_bsms[0]), []).append((target_id, candidate_id, task))
    for source_bsm, entries in candidate_groups.items():
        target_ids = {item[0] for item in entries}
        if len(entries) < 2 or len(target_ids) != len(entries):
            continue
        for target_id, candidate_id, _task in entries:
            shared_group_by_candidate[candidate_id] = source_bsm
        candidates = [candidate_geometry_by_id[item[1]] for item in entries]
        try:
            from shapely import wkt as shapely_wkt

            geometries = [shapely_wkt.loads(str(getattr(item, "wkt", "") or "")) for item in candidates]
            overlap = any(
                geometries[left].intersection(geometries[right]).area > 1e-12
                for left in range(len(geometries))
                for right in range(left + 1, len(geometries))
            )
        except Exception:
            overlap = True
        if overlap:
            shared_group_diagnostics[source_bsm] = "shared_parcel_subgeometry_overlap_at_execute"
            continue
        footprint_changes: list[ParcelChange] = []
        safe = True
        for target_id, candidate_id, _task in entries:
            project = projects_by_target.get(target_id)
            parcel = parcel_by_bsm.get(source_bsm)
            if project is None or parcel is None:
                safe = False
                break
            member_changes = _candidate_site_footprint_changes(
                project,
                candidate_geometry_by_id[candidate_id],
                parcel_by_bsm,
                briefs_by_target.get(target_id),
                include_remainder=False,
            )
            if len(member_changes) != 1:
                safe = False
                break
            footprint_changes.extend(member_changes)
        source_area_ha = max(
            float(getattr(candidate, "source_area_ha", 0.0) or 0.0)
            for candidate in candidates
        )
        planning_area_ha = sum(
            float(getattr(candidate, "planning_area_ha", 0.0) or 0.0)
            for candidate in candidates
        )
        eligible_area_ha = min(
            [
                float(getattr(candidate, "eligible_area_ha", 0.0) or 0.0)
                for candidate in candidates
                if getattr(candidate, "eligible_area_ha", None) is not None
            ]
            or [source_area_ha]
        )
        if (
            not safe
            or source_area_ha <= 0
            or planning_area_ha <= 0
            or planning_area_ha > min(source_area_ha, eligible_area_ha) + 1e-9
        ):
            shared_group_diagnostics[source_bsm] = "shared_parcel_capacity_or_materialization_invalid"
            continue
        remainders = _shared_parcel_remainder_changes(
            source_bsm,
            parcel_by_bsm[source_bsm],
            candidates,
            footprint_changes,
        )
        if not remainders:
            shared_group_diagnostics[source_bsm] = "shared_parcel_remainder_invalid"
            continue
        for (_target_id, candidate_id, _task), change in zip(entries, footprint_changes):
            shared_footprint_changes_by_candidate[candidate_id] = [change]
        shared_remainder_by_bsm[source_bsm] = remainders
    candidate_by_target = {
        target_id: entries[0][0]
        for target_id, entries in candidate_tasks_by_target.items()
    }
    def _is_executable_candidate(candidate: Any) -> bool:
        if candidate is None:
            return False
        declared = getattr(candidate, "is_executable", None)
        if declared is not None:
            return bool(declared)
        role = str(getattr(candidate, "role", "") or "")
        wkt = str(getattr(candidate, "wkt", "") or "").strip()
        availability = str(
            getattr(candidate, "availability_status", "unknown") or "unknown"
        )
        source_bsms = list(getattr(candidate, "source_bsms", None) or [])
        return bool(
            role == "execution_geometry"
            and wkt
            and availability != "fully_unavailable"
            and not (availability == "unknown" and source_bsms)
        )

    direct_candidate_targets = {
        target_id
        for target_id, candidate_id in candidate_by_target.items()
        if _is_executable_candidate(candidate_geometry_by_id.get(candidate_id))
    }
    non_executable_candidate_targets = {
        target_id
        for target_id, candidate_id in candidate_by_target.items()
        if candidate_geometry_by_id.get(candidate_id) is not None
        and target_id not in direct_candidate_targets
    }
    features = []
    changes: List[ParcelChange] = []
    completed_target_ids = set()
    completed_candidate_keys: set[tuple[str, str]] = set()
    direct_materialization_diagnostics: dict[str, str] = {}
    shared_remainders_used: set[str] = set()
    action_results = [
        TypedActionResult(
            target_id=project.target_id,
            action=project.action,
            details={"name": project.name},
        )
        for project in projects
        if not getattr(project, "requires_spatial", True)
        or getattr(project, "expected_output_kind", "") == "action"
    ]
    for target_id, bsm in selected_by_target.items():
        # An executable SELECT geometry is already the planning subgeometry.
        # Do not expand it back to the full source BSM through land design.
        if target_id in direct_candidate_targets or target_id in non_executable_candidate_targets:
            continue
        project = projects_by_target.get(target_id)
        if project is None or not getattr(project, "requires_spatial", True):
            continue
        parcel = parcel_by_bsm.get(str(bsm))
        if parcel is None or not _parcel_geometry(parcel):
            continue
        if getattr(project, "expected_output_kind", "") == "action":
            continue
        brief = briefs_by_target.get(target_id)
        if brief is None:
            continue
        change_list = design_project_footprint(project, brief, str(bsm), parcel_by_bsm)
        if not change_list:
            continue
        changes.extend(change_list)
        completed_target_ids.add(target_id)
        primary = change_list[0]
        props = {
            "project_id": project.target_id,
            "project_name": getattr(project, "name", ""),
            "project_category": getattr(project, "category", "other"),
            "action": getattr(project, "action", "new"),
            "scale_text": getattr(project, "scale_text", ""),
            "source_bsm": str(bsm),
            "source_instruction_id": getattr(project, "source_instruction_id", ""),
            "source_report_key": getattr(project, "source_report_key", ""),
            "candidate_bsms": list(getattr(project, "candidate_bsms", None) or []),
            "constraint_check": "passed",
            "geometry_source": "land_design_worker",
            "change_action": primary.action,
        }
        props["project_ref"] = target_id
        features.append({
            "type": "Feature",
            "properties": props,
            "geometry": _footprint_geometry(primary, _parcel_geometry(parcel)),
        })

    # Relation-aware candidates are not necessarily cadastral parcels.  A
    # typed execution geometry is authoritative and is materialized directly;
    # the parcel design branch above is used only when SELECT did not produce
    # an executable candidate for that task.
    from shapely import wkt as shapely_wkt
    from shapely.geometry import mapping as shapely_mapping
    for target_id, candidate_id, candidate_task in [
        (target_id, candidate_id, task)
        for target_id, entries in candidate_tasks_by_target.items()
        for candidate_id, task in entries
    ]:
        candidate_key = (target_id, candidate_id)
        if candidate_key in completed_candidate_keys:
            continue
        candidate = candidate_geometry_by_id.get(candidate_id)
        geometry_wkt = str(getattr(candidate, "wkt", "") or "")
        if candidate is None or str(getattr(candidate, "role", "") or "") != "execution_geometry":
            continue
        if not geometry_wkt:
            continue
        try:
            geometry = shapely_mapping(shapely_wkt.loads(geometry_wkt))
        except Exception:
            continue
        if not geometry or not geometry.get("type"):
            continue
        project = projects_by_target.get(target_id)
        if project is None:
            continue
        semantic_role = str(getattr(project, "materialization_role", "") or "")
        if semantic_role == "site_footprint":
            shared_source_bsm = shared_group_by_candidate.get(candidate_id)
            if shared_source_bsm and candidate_id not in shared_footprint_changes_by_candidate:
                direct_materialization_diagnostics[target_id] = shared_group_diagnostics.get(
                    shared_source_bsm,
                    "shared_parcel_group_not_materializable",
                )
                continue
            footprint_changes = (
                list(shared_footprint_changes_by_candidate.get(candidate_id, []))
                if shared_source_bsm
                else _candidate_site_footprint_changes(
                    project,
                    candidate,
                    parcel_by_bsm,
                    briefs_by_target.get(target_id),
                )
            )
            if shared_source_bsm and shared_source_bsm not in shared_remainder_by_bsm:
                direct_materialization_diagnostics[target_id] = shared_group_diagnostics.get(
                    shared_source_bsm,
                    "shared_parcel_remainder_missing",
                )
                continue
            source_bsms = [
                str(value)
                for value in (getattr(candidate, "source_bsms", None) or [])
                if str(value)
            ]
            has_source_geometry = bool(
                len(source_bsms) == 1
                and parcel_by_bsm.get(source_bsms[0]) is not None
                and _parcel_geometry(parcel_by_bsm[source_bsms[0]])
            )
            if not footprint_changes and has_source_geometry:
                adjacency_required = bool(
                    list(
                        getattr(briefs_by_target.get(target_id), "adjacency_requirements", None)
                        or []
                    )
                )
                if adjacency_required and not list(
                    getattr(candidate, "adjacent_parcel_bsms", None) or []
                ):
                    diagnostic = "approved_site_footprint_adjacency_evidence_missing"
                elif adjacency_required and not list(
                    getattr(candidate, "adjacency_evidence_refs", None) or []
                ):
                    diagnostic = "approved_site_footprint_adjacency_evidence_missing"
                elif adjacency_required and not list(
                    getattr(candidate, "relation_refs", None) or []
                ):
                    diagnostic = "approved_site_footprint_adjacency_relation_missing"
                else:
                    diagnostic = "approved_site_footprint_cannot_be_materialized_as_source_backed_change"
                direct_materialization_diagnostics[target_id] = diagnostic
                continue
            changes.extend(footprint_changes)
            if shared_source_bsm:
                shared_remainders_used.add(shared_source_bsm)
        features.append({
            "type": "Feature",
            "properties": {
                "target_id": target_id,
                "project_id": target_id,
                "project_name": getattr(project, "name", ""),
                "project_category": getattr(project, "category", "other"),
                "candidate_id": candidate_id,
                "source_bsms": list(getattr(candidate, "source_bsms", None) or []),
                "feature_bsms": list(getattr(candidate, "feature_bsms", None) or []),
                "crs": str(getattr(candidate, "crs", "") or "EPSG:4326"),
                "source_feature_ids": list(
                    getattr(candidate, "source_feature_ids", None) or []
                ),
                "entity_refs": list(getattr(candidate, "entity_refs", None) or []),
                "relation_refs": list(getattr(candidate, "relation_refs", None) or []),
                "evidence_refs": list(getattr(candidate, "evidence_refs", None) or []),
                "l1_snapshot_ref": str(
                    getattr(candidate, "l1_snapshot_ref", "") or ""
                ),
                "bundle_snapshot_digest": str(
                    getattr(candidate, "bundle_snapshot_digest", "") or ""
                ),
                "subgeometry_operation": str(
                    getattr(candidate, "subgeometry_operation", "") or ""
                ),
                "subgeometry_diagnostics": list(
                    getattr(candidate, "subgeometry_diagnostics", None) or []
                ),
                "spatial_domain_kind": str(
                    getattr(candidate, "spatial_domain_kind", "") or ""
                ),
                "source_area_ha": getattr(candidate, "source_area_ha", None),
                "planning_area_ha": getattr(candidate, "planning_area_ha", None),
                "coverage_ratio": getattr(candidate, "coverage_ratio", None),
                "availability_status": str(
                    getattr(candidate, "availability_status", "unknown") or "unknown"
                ),
                "eligible_area_ha": getattr(candidate, "eligible_area_ha", None),
                "excluded_area_ha": getattr(candidate, "excluded_area_ha", None),
                "adjacent_parcel_bsms": list(
                    getattr(candidate, "adjacent_parcel_bsms", None) or []
                ),
                "adjacency_evidence_refs": list(
                    getattr(candidate, "adjacency_evidence_refs", None) or []
                ),
                "scenario_id": str(_task_value(_task_for_target(state, target_id, candidate_id=candidate_id), "scenario_id", "") or ""),
                "source_refs": list(dict.fromkeys([
                    *list(getattr(candidate, "source_refs", None) or []),
                    *list(getattr(candidate, "evidence_refs", None) or []),
                    str(getattr(candidate, "source_ref", "") or ""),
                ])) or ["candidate_geometry"],
                "generation_operation": "candidate_geometry_materialize",
                "materialization_role": str(
                    getattr(project, "materialization_role", "")
                    or "site_footprint"
                ),
                "hard_constraint_status": str(
                    getattr(candidate, "hard_constraint_status", "") or ""
                ),
                "parcel_change_materialized": bool(
                    semantic_role == "site_footprint"
                    and any(change.project_ref == target_id for change in changes)
                ),
            },
            "geometry": geometry,
        })
        completed_target_ids.add(target_id)
        completed_candidate_keys.add(candidate_key)

    for source_bsm in sorted(shared_remainders_used):
        changes.extend(shared_remainder_by_bsm.get(source_bsm, []))

    layers = []
    if features:
        layers.append({
            "layerType": "planned_project",
            "layerName": "规划项目",
            "data": {"type": "FeatureCollection", "features": features},
        })
    unresolved = []
    if projects_by_target and not features and not action_results:
        unresolved.append({
            "code": "project_output_empty",
            "message": "Project targets exist but none could be placed on a constraint-safe candidate parcel.",
        })
    task_results = []
    occurrence_by_target: dict[str, int] = {}
    for project in projects:
        target_occurrence = occurrence_by_target.get(str(project.target_id), 0)
        occurrence_by_target[str(project.target_id)] = target_occurrence + 1
        candidate_entries = candidate_tasks_by_target.get(str(project.target_id), [])
        selected_task = (
            candidate_entries[min(target_occurrence, len(candidate_entries) - 1)][1]
            if candidate_entries else None
        )
        selected_candidate_id = (
            str(_task_value(selected_task, "candidate_id", "") or "")
            if selected_task else ""
        )
        selected_candidate_key = (str(project.target_id), selected_candidate_id)
        selected_succeeded = (
            selected_candidate_key in completed_candidate_keys
            if selected_candidate_id
            else project.target_id in completed_target_ids
        )
        if project.target_id in direct_materialization_diagnostics:
            selected_succeeded = False
        deferred_candidate = (
            project.target_id in non_executable_candidate_targets
            and not selected_succeeded
        )
        candidate = candidate_geometry_by_id.get(
            candidate_by_target.get(project.target_id, "")
        )
        task_result = _task_execution_result(
            state,
            "site_area_footprint",
            project.target_id,
            task_id=str(_task_value(selected_task, "task_id", "") or "") if selected_task else "",
            candidate_id=selected_candidate_id,
            status=(
                "succeeded"
                if selected_succeeded
                else "deferred"
                if deferred_candidate
                else "failed"
            ),
            diagnostics=(
                []
                if selected_succeeded
                else [{
                    "code": (
                        "candidate_geometry_not_executable"
                        if deferred_candidate
                        else direct_materialization_diagnostics.get(
                            project.target_id,
                            "project_output_missing",
                        )
                    ),
                    "target_id": project.target_id,
                    "candidate_id": str(getattr(candidate, "candidate_id", "") or ""),
                    "geometry_role": str(getattr(candidate, "role", "") or ""),
                    "subgeometry_operation": str(
                        getattr(candidate, "subgeometry_operation", "") or ""
                    ),
                    "subgeometry_diagnostics": list(
                        getattr(candidate, "subgeometry_diagnostics", None) or []
                    ),
                }]
            ),
        )
        if task_result is not None:
            task_results.append(task_result)
    scenario_features = [
        item
        for layer in layers
        for item in _scenario_features_for_layer(
            state, layer, generation_operation="project_worker"
        )
    ]
    _attach_feature_lineage(task_results, scenario_features)
    return WorkerResult(
        worker_type="site_area",
        task_results=task_results,
        layers=layers,
        parcel_changes=changes,
        action_results=action_results,
        unresolved_items=unresolved,
        diagnostics=[{
            "code": "project_ok",
            "projects_placed": len(features),
            "changes": len(changes),
            "actions": len(action_results),
        }],
        scenario_features=scenario_features,
        task_id=(
            str(getattr(state.execution_plan.worker_tasks[0], "task_id", ""))
            if state.execution_plan and len(state.execution_plan.worker_tasks) == 1
            else ""
        ),
    )
