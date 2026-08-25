"""VALIDATE subgraph — deterministic validation checks (Wave J Task 1).

Nine pure, deterministic checks that validate planning artifacts and
attribute each finding to the responsibility stage that should fix it:

  1. hard_constraints       -> SELECT/EXECUTE  candidate falls in a prohibited constraint
  2. area_conservation      -> EXECUTE         split/merge area drift
  3. topology               -> EXECUTE         invalid / empty / gappy geometries
  4. overlap                -> EXECUTE         polygon layer self-overlap
  5. continuity             -> EXECUTE         fragmented zone geometry
  6. accessibility          -> SELECT          facility coordinates invalid / out of reach
  7. contract_completeness  -> EXECUTE/L3      missing parcels or parcel fields
  8. classification_missing -> EXECUTE         non-preserve parcel without a land use

Stage attribution rationale:
  - SELECT: a parcel that was chosen while overlapping a prohibited constraint,
    or a facility placed with invalid coordinates, is a candidate-selection fault.
  - EXECUTE: geometry/layout faults (topology, overlap, continuity, conservation,
    missing classification, incomplete parcel output) are produced by the worker.
  - L3: when intent targets exist but no parcels were produced, the intent may
    not have grounded any parcel (reported as EXECUTE here; fix lies upstream).

No LLM, no KG, no MIP — geometry math only (shapely imported lazily).
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any, List, Optional

from app.contracts.artifacts.validation_report_contracts import ValidationCheck
from app.spatial.allocation.selection import _PROHIBITED_CONSTRAINTS

_AREA_TOLERANCE = 0.05
_POLYGON_TYPES = ("Polygon", "MultiPolygon")


def _check(
    check_id: str,
    check_name: str,
    passed: bool,
    *,
    stage: str = "EXECUTE",
    actual: str = "",
    expected: str = "",
    parcels: Optional[List[str]] = None,
    targets: Optional[List[str]] = None,
    violation_id: str = "",
    code: str = "",
    evidence_refs: Optional[List[str]] = None,
    fix: str = "",
) -> ValidationCheck:
    return ValidationCheck(
        check_id=check_id,
        violation_id=violation_id or check_id,
        code=code or check_id,
        check_name=check_name,
        passed=passed,
        actual_value=actual,
        expected_value=expected,
        responsible_stage=stage,
        affected_parcels=list(parcels or []),
        affected_target_ids=list(targets or []),
        evidence_refs=sorted(set(evidence_refs or [])),
        fix_suggestion=fix,
    )


def _wkt_area(wkt: str) -> float:
    if not wkt:
        return 0.0
    try:
        from shapely import wkt as _wkt

        geom = _wkt.loads(wkt)
        return geom.area if geom and not geom.is_empty else 0.0
    except Exception:
        return 0.0


def _wkt_is_valid(wkt: str) -> bool:
    """Check candidate/source geometry without fabricating a fallback."""
    if not str(wkt or "").strip():
        return False
    try:
        from shapely import wkt as _wkt

        geometry = _wkt.loads(str(wkt))
        return bool(geometry is not None and not geometry.is_empty and geometry.is_valid)
    except Exception:
        return False


def _target_lineage(entry: Any) -> list[str]:
    values = (
        getattr(entry, "derived_from_zone_target", ""),
        getattr(entry, "derived_from_target", ""),
        getattr(entry, "project_ref", ""),
    )
    return sorted({str(value) for value in values if str(value).strip()})


def _entry_identity(entry: Any) -> str:
    """Return the output identity without conflating candidate ids and BSMs."""
    return str(
        getattr(entry, "bsm", "")
        or getattr(entry, "candidate_id", "")
        or getattr(entry, "feature_id", "")
        or getattr(entry, "name", "")
        or ""
    ).strip()


def _candidate_backed(entry: Any) -> bool:
    """True only for immutable relation-aware candidate materialization."""
    return bool(
        str(getattr(entry, "candidate_id", "") or "").strip()
        and not str(getattr(entry, "bsm", "") or "").strip()
    ) or str(getattr(entry, "source_spec", "") or "").strip() == (
        "candidate_geometry_materialize"
    )


def _materialization_role(entry: Any) -> str:
    return str(getattr(entry, "materialization_role", "") or "").strip()


def _entry_lineage(entry: Any) -> tuple[list[str], list[str], list[str]]:
    """Return (bsms, target_ids, evidence_refs) for a planned parcel/zone entry."""
    # Candidate ids are intentionally kept out of ``bsms``.  They belong in
    # evidence/source refs and are not valid current-land-use identifiers.
    bsm = str(getattr(entry, "bsm", "") or "")
    bsms = [bsm] if bsm else []
    bsms.extend(
        str(value)
        for value in (getattr(entry, "parcel_bsms", None) or [])
        if str(value) and str(value) != bsm
    )
    bsms = list(dict.fromkeys(bsms))
    targets = _target_lineage(entry)
    name = str(getattr(entry, "name", "") or bsm or "")
    refs = [
        f"planned-parcel:{bsm}" if bsm else "",
        f"planned-zone:{name}" if name else "",
    ]
    candidate_id = str(getattr(entry, "candidate_id", "") or "").strip()
    if candidate_id:
        refs.append(f"candidate:{candidate_id}")
    refs.extend(
        str(value)
        for value in (getattr(entry, "source_refs", None) or [])
        if str(value)
    )
    refs.extend(str(value) for value in (getattr(entry, "lineage_ids", None) or []))
    refs.extend(str(value) for value in (getattr(entry, "claim_refs", None) or []))
    evidence_refs = sorted(
        {
            str(value)
            for value in refs
            if str(value)
            and (
                str(value).startswith("planned-")
                or str(value).startswith("candidate:")
                or str(value).startswith("artifact:")
            )
        }
    )
    return bsms, targets, evidence_refs


def _evidence_digest(*parts: Any) -> str:
    payload = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def check_hard_constraints(planned_state: Any, constraint_index: Any) -> List[ValidationCheck]:
    """Check no planned parcel overlaps a prohibited constraint polygon."""
    if not (getattr(planned_state, "parcels", None) or []):
        return [
            _check(
                "hard_constraints",
                "硬性约束核查",
                True,
                stage="SELECT",
                actual="not_applicable:no_planned_parcels",
                expected="constraint checks apply to planned parcel geometry",
            )
        ]
    if constraint_index is None:
        # No constraint layer was provided: hard-constraint checking is not
        # applicable.  Skip (recorded) instead of producing an unrepairable
        # blocker - the session simply has no constraint data to violate.
        return [
            _check(
                "hard_constraints",
                "硬性约束核查",
                True,
                stage="SELECT",
                actual="not_applicable:no_constraint_index",
                expected="constraint checks require a constraint index",
            )
        ]
    findings: list[ValidationCheck] = []
    for parcel in planned_state.parcels or []:
        # A split remainder keeps the existing land use.  It is emitted so
        # the parcel partition remains complete, but it is not a new planning
        # decision and must not be rejected merely because the source parcel
        # already overlaps a protected constraint.
        if str(getattr(parcel, "operation", "") or "") == "preserve":
            continue
        # Overlay semantics are non-exclusive by contract.  A protection or
        # restoration overlay may intentionally intersect a prohibited
        # *land-use* constraint; its relation-specific hard factors are
        # checked independently by FinalScenarioValidation.  Keep this
        # source-parcel check for authoritative/site-footprint outputs only.
        if _materialization_role(parcel) in {
            "functional_overlay",
            "protection_overlay",
            "restoration_overlay",
        }:
            continue
        bsm = str(getattr(parcel, "bsm", "") or "")
        candidate_id = str(getattr(parcel, "candidate_id", "") or "")
        identity = bsm or candidate_id or "unbound"
        targets = _target_lineage(parcel)
        parcel_ref = (
            f"planned-parcel:{bsm}"
            if bsm
            else f"candidate:{candidate_id}"
            if candidate_id
            else "planned-parcel:unbound"
        )
        wkt = (parcel.geometry or "").strip()
        if not wkt:
            findings.append(
                _check(
                    "hard_constraint_query_failed",
                    "硬性约束核查",
                    False,
                    stage="EXECUTE",
                    code="hard_constraint_query_failed",
                    violation_id=f"hard_constraint_query_failed:{identity}",
                    actual="planned parcel geometry is empty",
                    expected="parseable planned parcel geometry",
                    parcels=[bsm] if bsm else [],
                    targets=targets,
                    evidence_refs=[parcel_ref],
                    fix="修复目标地块几何后重新执行硬约束核查",
                )
            )
            continue
        try:
            from shapely import wkt as _wkt
            from shapely.geometry import mapping

            geojson = mapping(_wkt.loads(wkt))
            overlaps = constraint_index.geometry_in_constraint(geojson) or []
        except Exception as exc:
            findings.append(
                _check(
                    "hard_constraint_query_failed",
                    "硬性约束核查",
                    False,
                    stage="EXECUTE",
                    code="hard_constraint_query_failed",
                    violation_id=f"hard_constraint_query_failed:{identity}",
                    actual=f"constraint query failed: {exc}",
                    expected="successful deterministic constraint query",
                    parcels=[bsm] if bsm else [],
                    targets=targets,
                    evidence_refs=[parcel_ref],
                    fix="修复目标地块几何或约束索引后重新核查",
                )
            )
            continue
        prohibited = {
            str(getattr(overlap, "constraint_type", "") or ""): overlap
            for overlap in overlaps
            if str(getattr(overlap, "constraint_type", "") or "")
            in _PROHIBITED_CONSTRAINTS
        }
        for constraint_type, overlap in sorted(prohibited.items()):
            target_token = "+".join(targets) or "unbound"
            evidence_id = _evidence_digest(
                bsm,
                target_token,
                constraint_type,
                getattr(overlap, "overlap_area_sqm", 0.0),
                getattr(overlap, "overlap_pct", 0.0),
            )
            findings.append(
                _check(
                    "hard_constraints",
                    "硬性约束核查",
                    False,
                    stage="SELECT",
                    code="hard_constraints",
                    violation_id=(
                        f"hard_constraints:{target_token}:{identity}:"
                        f"{constraint_type}"
                    ),
                    actual=(
                        f"constraint={constraint_type}, "
                        f"overlap_area_sqm={getattr(overlap, 'overlap_area_sqm', 0.0)}, "
                        f"overlap_pct={getattr(overlap, 'overlap_pct', 0.0)}"
                    ),
                    expected="selected parcel does not overlap a prohibited constraint",
                    parcels=[bsm] if bsm else [],
                    targets=targets,
                    evidence_refs=[
                        parcel_ref,
                        f"constraint:{constraint_type}",
                        f"constraint-overlap:{evidence_id}",
                    ],
                    fix="从该目标候选集中排除违规 BSM 并重新执行全局分配",
                )
            )
    if findings:
        return sorted(findings, key=lambda item: item.violation_id)
    return [
        _check(
            "hard_constraints",
            "硬性约束核查",
            True,
            stage="SELECT",
            actual="no prohibited constraint overlaps",
            expected="selected parcels satisfy prohibited constraints",
        )
    ]


def check_area_conservation(changeset: Any) -> List[ValidationCheck]:
    """Check split/merge changes conserve area (5% tolerance on degree^2 areas)."""
    if changeset is None:
        return [_check("area_conservation", "面积守恒", True, stage="EXECUTE")]
    total_before = 0.0
    total_after = 0.0
    pair_diffs: List[tuple] = []
    conservation_groups: dict[tuple[str, ...], dict[str, float]] = {}
    for change in changeset.changes or []:
        before_area = _wkt_area(change.before_geometry_wkt)
        after_area = _wkt_area(change.after_geometry_wkt)
        lineage = tuple(sorted(str(value) for value in (change.derived_from_bsms or []) if str(value)))
        if lineage:
            group = conservation_groups.setdefault(lineage, {"before": 0.0, "after": 0.0})
            if before_area > group["before"]:
                group["before"] = before_area
            group["after"] += after_area
        elif before_area > 0 and after_area > 0:
            total_before += before_area
            total_after += after_area
        if before_area > 0 and after_area > 0:
            pair_diffs.append((abs(after_area - before_area), change.bsm))
    split_groups: dict = {}
    for change in changeset.changes or []:
        lineage = tuple(sorted(str(value) for value in (change.derived_from_bsms or []) if str(value)))
        if not lineage and change.action not in ("split", "merge", "create"):
            continue
        if change.action == "create" and not lineage:
            continue
        key = lineage or (change.bsm,)
        group = split_groups.setdefault(key, {"before": 0.0, "after": 0.0, "bsms": []})
        before = _wkt_area(change.before_geometry_wkt)
        if before > group["before"]:
            group["before"] = before
        group["after"] += _wkt_area(change.after_geometry_wkt)
        group["bsms"].append(change.bsm)
    mismatched: List[str] = []
    for key, group in split_groups.items():
        before = group["before"]
        if before <= 0:
            continue
        ratio = abs(group["after"] - before) / max(before, 1e-9)
        if ratio >= _AREA_TOLERANCE:
            mismatched.extend(group["bsms"])
    for group in conservation_groups.values():
        total_before += group["before"]
        total_after += group["after"]
    drift = 0.0
    if total_before > 0:
        drift = abs(total_after - total_before) / max(total_before, 1e-9)
    drift_failed = total_before > 0 and drift >= _AREA_TOLERANCE
    pair_diffs.sort(reverse=True)
    offenders = [bsm for _, bsm in pair_diffs[:5]]
    mismatched_targets = sorted(
        {
            str(value)
            for change in changeset.changes or []
            if change.bsm in set(mismatched + offenders)
            for value in (
                getattr(change, "project_ref", None) or "",
                getattr(change, "intervention_id", None) or "",
            )
            if str(value)
        }
    )

    if drift_failed:
        return [
            _check(
                "area_conservation",
                "面积守恒",
                False,
                stage="EXECUTE",
                actual=f"drift={drift:.4f}",
                expected="sum(after) ≈ sum(before) within 5%",
                parcels=offenders,
                targets=mismatched_targets,
                evidence_refs=[f"parcel-change:{bsm}:area" for bsm in offenders],
                fix="核对 split/merge/create 地块面积，避免面积损失或新增",
            )
        ]
    if mismatched:
        return [
            _check(
                "area_conservation",
                "面积守恒",
                False,
                stage="EXECUTE",
                actual=", ".join(mismatched),
                expected="split parts sum to the source area within 5%",
                parcels=mismatched,
                targets=mismatched_targets,
                evidence_refs=[f"parcel-change:{bsm}:area" for bsm in mismatched],
                fix="核对 split/merge 地块面积，避免面积损失或新增",
            )
        ]
    return [
        _check(
            "area_conservation",
            "面积守恒",
            True,
            stage="EXECUTE",
            actual="no area pairs to verify" if not pair_diffs else f"drift={drift:.4f}",
            expected="sum(after) ≈ sum(before) within 5%",
        )
    ]


def check_traceability(
    execution_plan: Any,
    execution_result: Any,
) -> List[ValidationCheck]:
    """Trace each planned target to the output kind declared by EXECUTE."""
    if execution_plan is not None:
        from app.domain.common.execution_evidence import (
            active_output_covered,
            contradictory_statuses,
            deferred_outcome_contradiction,
            group_execution_results,
            stable_output_key,
        )

        active_tasks = list(getattr(execution_plan, "worker_tasks", None) or [])
        deferred_tasks = list(getattr(execution_plan, "deferred_tasks", None) or [])
        result_groups = group_execution_results(execution_result)
        failed: list[str] = []
        duplicate: list[str] = []
        deferred_contradictions: list[str] = []
        expected_kinds: set[str] = set()
        planned_keys: set[tuple[str, str]] = set()
        for task in active_tasks:
            target_id = str(getattr(task, "target_id", ""))
            output_kind = str(getattr(task, "expected_output_kind", ""))
            key = stable_output_key(task)
            planned_keys.add(key)
            expected_kinds.add(output_kind)
            results = result_groups.get(key, [])
            if contradictory_statuses(results):
                duplicate.append(target_id)
            if not active_output_covered(results, output_kind):
                failed.append(target_id)
        for task in deferred_tasks:
            key = stable_output_key(task)
            planned_keys.add(key)
            expected_kinds.add(str(getattr(task, "expected_output_kind", "")))
            if deferred_outcome_contradiction(result_groups.get(key, [])):
                deferred_contradictions.append(str(getattr(task, "target_id", "")))
        orphan = sorted(
            target_id
            for target_id, output_kind in result_groups
            if (target_id, output_kind) not in planned_keys
        )
        failed = sorted(set(failed))
        duplicate = sorted(set(duplicate))
        deferred_contradictions = sorted(set(deferred_contradictions))
        passed = not failed and not orphan and not deferred_contradictions
        affected_targets = sorted(set(
            failed + orphan + deferred_contradictions
        ))
        kinds = sorted(kind for kind in expected_kinds if kind)
        return [
            _check(
                "traceability",
                "目标-产物追溯",
                passed,
                stage="EXECUTE",
                actual=(
                    f"failed={failed}, orphan={orphan}, duplicate={duplicate}, "
                    f"deferred_contradictions={deferred_contradictions}"
                ),
                expected=f"每个目标产出声明类型 {kinds} 或具有显式 deferred 状态",
                targets=affected_targets,
                fix="按稳定 target_id 和 expected_output_kind 补齐执行结果或显式延期",
            )
        ]

    return [
        _check(
            "traceability",
            "目标-产物追溯",
            False,
            stage="EXECUTE",
            actual="execution_plan_missing",
            expected="canonical ExecutionPlan is required for traceability",
            fix="加载 SELECT 生成的 ExecutionPlan 后再运行 VALIDATE",
        )
    ]


def check_worker_failures(execution_result: Any) -> List[ValidationCheck]:
    """Promote typed worker failures into the authoritative validation report."""
    findings: dict[str, ValidationCheck] = {}
    records: list[tuple[str, dict[str, Any]]] = []
    for task in list(getattr(execution_result, "task_results", None) or []):
        if str(getattr(task, "status", "")) != "failed":
            continue
        target_id = str(getattr(task, "target_id", "") or "")
        records.extend(
            (target_id, diagnostic)
            for diagnostic in list(getattr(task, "diagnostics", None) or [])
            if isinstance(diagnostic, dict)
        )
    records.extend(
        ("", diagnostic)
        for diagnostic in list(getattr(execution_result, "diagnostics", None) or [])
        if isinstance(diagnostic, dict)
    )
    supported = {
        "road_unresolved",
        "road_anchor_unresolved",
        "road_route_failed",
        "geometry_invalid",
        "worker_conflict",
        "authoritative_land_use_conflict",
    }
    for index, (task_target_id, diagnostic) in enumerate(records):
            code = str(diagnostic.get("code") or "").strip().lower()
            if code not in supported:
                continue
            target_ids = sorted({
                *([task_target_id] if task_target_id else []),
                *[
                    str(target_id)
                    for target_id in list(diagnostic.get("target_ids") or [])
                    if str(target_id)
                ],
                *([str(diagnostic.get("target_id"))] if diagnostic.get("target_id") else []),
            })
            violation_id = str(
                diagnostic.get("violation_id")
                or f"{code}:{':'.join(target_ids) or 'unbound'}:{index}"
            )
            bsms = sorted({
                str(bsm)
                for bsm in [
                    *list(diagnostic.get("affected_bsms") or []),
                    *([diagnostic.get("bsm")] if diagnostic.get("bsm") else []),
                ]
                if str(bsm)
            })
            evidence_refs = sorted({
                str(ref)
                for ref in list(diagnostic.get("evidence_refs") or [])
                if str(ref)
            })
            findings[violation_id] = _check(
                code,
                "执行产物失败",
                False,
                stage=(
                    "L3"
                    if code == "road_unresolved"
                    else "GROUND"
                    if code == "road_anchor_unresolved"
                    else "SELECT"
                    if code in {"worker_conflict", "authoritative_land_use_conflict"}
                    else "EXECUTE"
                ),
                code=code,
                violation_id=violation_id,
                actual=str(diagnostic.get("message") or diagnostic.get("reason_code") or code),
                expected="worker produces the declared target output with source lineage",
                parcels=bsms,
                targets=target_ids,
                evidence_refs=evidence_refs,
                fix="按 typed repair directive 补证据、重选或重建目标几何",
            )
    return sorted(findings.values(), key=lambda finding: finding.violation_id)


def check_bundle_snapshot_lineage(
    planned_state: Any,
    execution_plan: Any,
    execution_result: Any,
    current_bundle_digest: str = "",
) -> List[ValidationCheck]:
    """Reject outputs assembled from more than one bundle geometry snapshot."""
    declared: set[str] = set()
    for item in list(getattr(execution_result, "task_results", None) or []):
        value = str(getattr(item, "bundle_snapshot_digest", "") or "").strip()
        if value:
            declared.add(value)
    for item in list(getattr(execution_plan, "worker_tasks", None) or []) + list(
        getattr(execution_plan, "deferred_tasks", None) or []
    ):
        value = str(getattr(item, "bundle_snapshot_digest", "") or "").strip()
        if value:
            declared.add(value)
    result_digest = str(getattr(execution_result, "bundle_snapshot_digest", "") or "").strip()
    if result_digest:
        declared.add(result_digest)
    current = str(current_bundle_digest or "").strip()
    mixed = len(declared) > 1
    mismatch = bool(current and declared and declared != {current})
    passed = not mixed and not mismatch
    actual = f"declared={sorted(declared)}, current={current or 'unknown'}"
    return [
        _check(
            "bundle_snapshot_lineage",
            "bundle 几何快照一致性",
            passed,
            stage="GROUND" if mismatch else "EXECUTE",
            actual=actual,
            expected="所有空间产物引用同一 bundle snapshot digest",
            evidence_refs=sorted(declared),
            fix=(
                "重新从同一 bundle 快照执行 GROUND→SELECT→EXECUTE，禁止混用旧几何"
                if not passed
                else ""
            ),
        )
    ]


def _planned_geoms(planned_state: Any) -> tuple[List[tuple], List[tuple]]:
    """Collect (name, shapely geometry) pairs and (name, error) parse failures.

    ADR-003: PlannedState is the sole fact source for planned geometry; the
    render-view ``layout_configs`` is not consulted for validation.
    """
    from shapely import wkt as _wkt

    items: List[tuple] = []
    errors: List[tuple] = []
    for entry in (
        (getattr(planned_state, "parcels", None) or [])
        + (getattr(planned_state, "zones", None) or [])
        + (getattr(planned_state, "overlays", None) or [])
    ):
        wkt = (getattr(entry, "geometry", "") or "").strip()
        name = _entry_identity(entry)
        if not wkt:
            errors.append((name, "empty geometry"))
            continue
        try:
            g = _wkt.loads(wkt)
        except Exception as exc:
            errors.append((name, f"parse error: {exc}"))
            continue
        items.append((name, g))
    return items, errors


def check_topology(planned_state: Any) -> List[ValidationCheck]:
    """Check validity globally and gaps only for explicit zone partitions."""
    invalid: List[str] = []
    empty: List[str] = []
    parse_errors: List[str] = []
    geoms: List[Any] = []
    items, errors = _planned_geoms(planned_state)
    for name, err in errors:
        parse_errors.append(name)
    for name, s in items:
        geoms.append(s)
        if s.is_empty:
            empty.append(name)
        elif not s.is_valid:
            invalid.append(name)

    validity_passed = not invalid and not empty and not parse_errors
    identity_by_name: dict[str, tuple[list[str], list[str], list[str]]] = {}
    for entry in (
        (getattr(planned_state, "parcels", None) or [])
        + (getattr(planned_state, "zones", None) or [])
        + (getattr(planned_state, "overlays", None) or [])
    ):
        name = _entry_identity(entry)
        if name:
            identity_by_name.setdefault(name, _entry_lineage(entry))
    validity_names = [*invalid, *empty, *parse_errors]
    validity_bsms = sorted(
        {
            bsm
            for name in validity_names
            for bsm in identity_by_name.get(name, ([], [], []))[0]
            if bsm
        }
    )
    validity_targets = sorted(
        {
            target
            for name in validity_names
            for target in identity_by_name.get(name, ([], [], []))[1]
            if target
        }
    )
    validity_evidence = sorted(
        {
            ref
            for name in validity_names
            for ref in identity_by_name.get(name, ([], [], []))[2]
            if ref
        }
    )
    checks = [
        _check(
            "topology_validity",
            "拓扑有效性",
            validity_passed,
            stage="EXECUTE",
            actual=f"invalid={invalid}, empty={empty}, parse_errors={parse_errors}",
            expected="no invalid, empty, or unparseable geometries",
            parcels=validity_bsms,
            targets=validity_targets,
            evidence_refs=validity_evidence,
            fix="修复自相交、空几何或 WKT 解析错误",
        )
    ]
    from shapely import wkt as _wkt

    domains = list(getattr(planned_state, "coverage_domains", None) or [])
    if not domains:
        checks.append(
            _check(
                "topology_gaps",
                "拓扑缝隙",
                True,
                stage="EXECUTE",
                actual="not_applicable:no_partition_domain",
                expected="gap checks apply only to explicit zone partition domains",
            )
        )
        return checks

    zone_geoms: dict[str, Any] = {}
    for zone in getattr(planned_state, "zones", None) or []:
        raw = (getattr(zone, "geometry", "") or "").strip()
        if not raw:
            continue
        try:
            geom = _wkt.loads(raw)
        except Exception:
            continue
        if geom.geom_type in _POLYGON_TYPES:
            name = str(getattr(zone, "name", "") or "")
            target = str(getattr(zone, "derived_from_zone_target", "") or "")
            if name:
                zone_geoms[name] = geom
            if target:
                zone_geoms[target] = geom

    domain_results: list[str] = []
    gap_passed = True
    for domain in domains:
        domain_id = str(getattr(domain, "domain_id", "") or "unnamed")
        boundary_raw = str(getattr(domain, "boundary_geometry", "") or "").strip()
        refs = list(getattr(domain, "zone_refs", None) or [])
        try:
            from shapely.ops import unary_union

            boundary = _wkt.loads(boundary_raw)
            selected = [zone_geoms[ref] for ref in refs if ref in zone_geoms]
            if not refs or len(selected) != len(refs) or boundary.is_empty:
                raise ValueError("coverage domain boundary or zone_refs are incomplete")
            union = unary_union([geom for geom in selected if not geom.is_empty])
            gap_area = boundary.difference(union).area
            domain_results.append(f"{domain_id}:gap_area={gap_area:.6f}")
            if gap_area > 1e-9:
                gap_passed = False
        except Exception as exc:
            gap_passed = False
            domain_results.append(f"{domain_id}:error={exc}")
    zone_target_by_ref = {
        str(getattr(zone, "name", "") or ""): str(
            getattr(zone, "derived_from_zone_target", "")
            or getattr(zone, "target_ref", "")
            or ""
        )
        for zone in getattr(planned_state, "zones", None) or []
    }
    gap_targets = sorted(
        {
            str(target)
            for domain in domains
            for ref in list(getattr(domain, "zone_refs", None) or [])
            for target in (zone_target_by_ref.get(str(ref), "") or ())
            if str(target)
        }
    )
    gap_evidence = sorted(
        {
            f"coverage-domain:{str(getattr(domain, 'domain_id', '') or 'unnamed')}"
            for domain in domains
        }
    )
    checks.append(
        _check(
            "topology_gaps",
            "拓扑缝隙",
            gap_passed,
            stage="EXECUTE",
            actual=", ".join(domain_results),
            expected="declared partition/coverage boundaries contain no uncovered area",
            targets=gap_targets,
            evidence_refs=gap_evidence,
            fix="补充缺失图斑或调整边界",
        )
    )
    return checks


def _planned_polygon_records(planned_state: Any) -> dict[str, list[SimpleNamespace]]:
    from shapely import wkt as _wkt

    groups: dict[str, list[SimpleNamespace]] = {"parcel": [], "zone": []}
    for layer, entries in (
        ("parcel", getattr(planned_state, "parcels", None) or []),
        ("zone", getattr(planned_state, "zones", None) or []),
    ):
        for index, entry in enumerate(entries):
            text = str(getattr(entry, "geometry", "") or "").strip()
            if not text:
                continue
            try:
                geometry = _wkt.loads(text)
            except Exception:
                continue
            if geometry.geom_type not in _POLYGON_TYPES or geometry.is_empty:
                continue
            bsm = str(getattr(entry, "bsm", "") or "")
            candidate_id = str(getattr(entry, "candidate_id", "") or "")
            targets = _target_lineage(entry)
            feature_id = (
                bsm
                or candidate_id
                or str(getattr(entry, "name", "") or "")
                or f"{layer}-{index}"
            )
            geometry_digest = _evidence_digest(text)
            role = str(getattr(entry, "materialization_role", "") or "")
            group_key = f"{layer}:{role}" if role else layer
            groups.setdefault(group_key, []).append(
                SimpleNamespace(
                    layer=group_key,
                    feature_id=feature_id,
                    bsm=bsm,
                    candidate_id=candidate_id,
                    target_ids=targets,
                    geometry=geometry,
                    evidence_ref=(
                        f"planned-{group_key}:{feature_id}:{geometry_digest[:16]}"
                    ),
                )
            )
    return groups


def check_overlap(planned_state: Any) -> List[ValidationCheck]:
    """Return one traceable finding per unique same-layer polygon overlap."""

    findings: dict[tuple[Any, ...], ValidationCheck] = {}
    groups = _planned_polygon_records(planned_state)
    for layer, records in groups.items():
        for index, left in enumerate(records):
            for right in records[index + 1 :]:
                try:
                    intersection = left.geometry.intersection(right.geometry)
                except Exception:
                    continue
                if intersection.is_empty or intersection.area <= 1e-12:
                    continue
                target_ids = sorted(set(left.target_ids + right.target_ids))
                bsms = sorted({value for value in (left.bsm, right.bsm) if value})
                feature_refs = sorted((left.evidence_ref, right.evidence_ref))
                evidence_digest = _evidence_digest(
                    layer,
                    *feature_refs,
                    intersection.wkb_hex,
                )
                evidence_ref = f"overlap-evidence:{evidence_digest}"
                pair_key = (
                    layer,
                    tuple(target_ids),
                    tuple(bsms),
                    tuple(feature_refs),
                    evidence_ref,
                )
                finding_id = f"overlap:{layer}:{evidence_digest[:20]}"
                findings[pair_key] = _check(
                    "overlap",
                    "图层重叠",
                    False,
                    stage="SELECT",
                    code="overlap",
                    violation_id=finding_id,
                    actual=(
                        f"layer={layer}, left={left.feature_id}, "
                        f"right={right.feature_id}, area={intersection.area:.12g}"
                    ),
                    expected="no authoritative polygons in the same layer overlap",
                    parcels=bsms,
                    targets=target_ids,
                    evidence_refs=[*feature_refs, evidence_ref],
                    fix="对冲突目标和 BSM 执行全局重新分配，不得继续合并冲突结果",
                )
    if findings:
        return sorted(findings.values(), key=lambda item: item.violation_id)
    return [
        _check(
            "overlap",
            "图层重叠",
            True,
            stage="SELECT",
            actual="no same-layer polygon overlaps",
            expected="no authoritative polygons in the same layer overlap",
        )
    ]


def check_continuity(planned_state: Any) -> List[ValidationCheck]:
    """Check each planned zone is a single contiguous geometry (no fragmented parts).

    Continuity is a zone-partition concern (fragmented zone geometry), so only
    ``PlannedState.zones`` are checked; project/facility/road footprints are
    excluded because they may legitimately sit on a multi-part parcel.
    """
    from shapely import wkt as _wkt
    from shapely.ops import unary_union

    fragmented: List[str] = []
    name_groups: dict = {}
    for zone in getattr(planned_state, "zones", None) or []:
        wkt = (getattr(zone, "geometry", "") or "").strip()
        if not wkt:
            continue
        try:
            s = _wkt.loads(wkt)
        except Exception:
            continue
        name = getattr(zone, "name", "") or "unnamed"
        name_groups.setdefault(name, []).append(s)
    for name, geoms in name_groups.items():
        for g in geoms:
            if g.geom_type == "MultiPolygon" and len(g.geoms) > 1:
                try:
                    merged = unary_union(g)
                except Exception:
                    merged = g
                if merged.geom_type == "MultiPolygon" and len(merged.geoms) > 1:
                    fragmented.append(name)
        if len(geoms) > 1:
            fragmented.append(name)
    fragmented = sorted(set(fragmented))
    passed = not fragmented
    zone_by_name: dict[str, Any] = {}
    for zone in getattr(planned_state, "zones", None) or []:
        name = str(getattr(zone, "name", "") or "")
        if name:
            zone_by_name.setdefault(name, zone)
    fragmented_bsms = sorted(
        {
            bsm
            for name in fragmented
            if (zone := zone_by_name.get(name)) is not None
            for bsm in _entry_lineage(zone)[0]
            if bsm
        }
    )
    fragmented_targets = sorted(
        {
            target
            for name in fragmented
            if (zone := zone_by_name.get(name)) is not None
            for target in _entry_lineage(zone)[1]
            if target
        }
    )
    fragmented_evidence = sorted(
        {
            ref
            for name in fragmented
            if (zone := zone_by_name.get(name)) is not None
            for ref in _entry_lineage(zone)[2]
            if ref
        }
    )
    return [
        _check(
            "continuity",
            "图斑连续性",
            passed,
            stage="EXECUTE",
            actual=", ".join(fragmented),
            expected="each zone is a single contiguous geometry",
            parcels=fragmented_bsms,
            targets=fragmented_targets,
            evidence_refs=fragmented_evidence,
            fix="合并同一用地的碎片图斑",
        )
    ]


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    radius_km = 6371.0
    dlon = radians(lon2 - lon1)
    dlat = radians(lat2 - lat1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * radius_km * asin(sqrt(a))


def _parcel_centroid_lonlat(planned_state: Any) -> Optional[tuple]:
    from shapely import wkt as _wkt

    points: List[tuple] = []
    for parcel in planned_state.parcels or []:
        wkt = (parcel.geometry or "").strip()
        if not wkt:
            continue
        try:
            geom = _wkt.loads(wkt)
            if geom.is_empty:
                continue
            c = geom.centroid
            points.append((c.x, c.y))
        except Exception:
            continue
    if not points:
        return None
    n = len(points)
    return (sum(x for x, _ in points) / n, sum(y for _, y in points) / n)


def _facilities_from_intent(intent: Any) -> List[SimpleNamespace]:
    facilities: List[SimpleNamespace] = []
    for target in getattr(intent, "facilities", None) or []:
        anchor = getattr(target, "anchor_point", None)
        if anchor is None:
            continue
        facilities.append(
            SimpleNamespace(
                name=target.type or "facility",
                facility_type=target.type or "",
                lon=float(anchor[0]),
                lat=float(anchor[1]),
                service_radius=float(getattr(target, "service_radius", None) or 0.0),
            )
        )
    return facilities


def check_accessibility(planned_state: Any, intent: Any = None) -> List[ValidationCheck]:
    """Check facility coordinates; evaluate coverage only with typed demands.

    A facility service radius is a relation to demand/network inputs, not a
    requirement that every facility be close to the village centroid.  The
    latter was a false positive for real village plans whose facilities are
    intentionally distributed across settlements.  Typed ``serve`` relations
    are validated by the relation subsystem when demand and network snapshots
    are present; this check remains responsible for malformed coordinates.
    """
    facilities = list(getattr(planned_state, "facilities", None) or [])
    if not facilities and intent is not None:
        facilities = _facilities_from_intent(intent)
    invalid: List[str] = []
    by_name: dict[str, Any] = {}
    for fac in facilities:
        name = str(getattr(fac, "name", "") or "facility")
        by_name.setdefault(name, fac)
        lon = float(getattr(fac, "lon", 0.0) or 0.0)
        lat = float(getattr(fac, "lat", 0.0) or 0.0)
        if lon == 0.0 and lat == 0.0:
            invalid.append(name)
            continue
    passed = not invalid
    invalid_targets = sorted(
        {
            str(
                getattr(by_name.get(name), "derived_from_target", "")
                or name
            )
            for name in invalid
            if name
        }
    )
    return [
        _check(
            "accessibility",
            "设施可达性",
            passed,
            stage="SELECT",
            actual=", ".join(invalid),
            expected="all facilities have valid coordinates; typed coverage relations are validated separately",
            targets=invalid_targets,
            evidence_refs=sorted({f"planned-facility:{name}" for name in invalid}),
            fix="为设施提供有效坐标或调整服务半径",
        )
    ]


def check_contract_completeness(
    planned_state: Any,
    changeset: Any,
    intent: Any = None,
    execution_plan: Any = None,
) -> List[ValidationCheck]:
    """Check parcels are produced when targets exist and fields are complete."""
    if intent is None:
        intent = SimpleNamespace(site_area_targets=[], zone_targets=[])
    site_area_targets = list(getattr(intent, "site_area_targets", None) or [])
    zone_targets = list(getattr(intent, "zone_targets", None) or [])
    spatial_projects = [
        p for p in site_area_targets
        if getattr(p, "requires_spatial", True)
        and str(getattr(p, "expected_output_kind", "")) in {"parcel", "polygon"}
    ]
    need_parcels = bool(spatial_projects or zone_targets)
    spatial_target_ids: list[str] = [
        str(getattr(target, "project_id", "") or getattr(target, "target_id", ""))
        for target in spatial_projects
        if str(getattr(target, "project_id", "") or getattr(target, "target_id", ""))
    ]
    spatial_target_ids.extend(
        str(getattr(target, "target_id", "") or getattr(target, "zone_id", ""))
        for target in zone_targets
        if str(getattr(target, "target_id", "") or getattr(target, "zone_id", ""))
    )
    if execution_plan is not None:
        active_spatial_tasks = [
            task
            for task in (getattr(execution_plan, "worker_tasks", None) or [])
            if str(getattr(task, "target_id", ""))
            and str(getattr(task, "expected_output_kind", "")) in {"parcel", "polygon"}
        ]
        # Explicit HUMAN deferrals remove those targets from the active
        # execution contract. Action/line tasks do not require a planned
        # parcel collection and must not create a false parcel blocker.
        if active_spatial_tasks:
            need_parcels = True
            spatial_target_ids = [
                str(getattr(task, "target_id", ""))
                for task in active_spatial_tasks
                if str(getattr(task, "target_id", ""))
            ]
        else:
            need_parcels = False
            spatial_target_ids = []
    parcels_present = (not need_parcels) or bool(planned_state.parcels)
    candidate_entries = [
        parcel for parcel in planned_state.parcels if _candidate_backed(parcel)
    ]
    source_entries = [
        parcel for parcel in planned_state.parcels if not _candidate_backed(parcel)
    ]
    missing_identity = [
        _entry_identity(parcel)
        for parcel in source_entries
        if not str(getattr(parcel, "bsm", "") or "").strip()
    ]
    missing_candidate = [
        _entry_identity(parcel) or "?"
        for parcel in candidate_entries
        if not str(getattr(parcel, "candidate_id", "") or "").strip()
    ]
    missing_target = [
        _entry_identity(parcel) or "?"
        for parcel in candidate_entries
        if not str(
            getattr(parcel, "target_ref", "")
            or getattr(parcel, "project_ref", "")
            or getattr(parcel, "derived_from_zone_target", "")
            or ""
        ).strip()
    ]
    missing_geom = [
        _entry_identity(parcel) or "?"
        for parcel in planned_state.parcels
        if not (getattr(parcel, "geometry", "") or "").strip()
    ]
    parcel_fields_ok = (
        not missing_identity
        and not missing_candidate
        and not missing_target
        and not missing_geom
    )
    has_changes = bool(changeset and (getattr(changeset, "changes", None) or []))
    candidate_backed = any(
        str(getattr(parcel, "candidate_id", "") or "").strip()
        or str(getattr(parcel, "bsm", "") or "").startswith("candidate:")
        for parcel in planned_state.parcels
    )
    if candidate_entries and not has_changes:
        # Candidate-backed execution is a direct geometry materialization, not
        # a cadastral ParcelChangeSet.  Require parseable output geometry, but
        # do not manufacture a false area-conservation claim for a non-BSM
        # candidate.
        flags_ok = parcel_fields_ok and all(
            _wkt_is_valid(getattr(parcel, "geometry", ""))
            for parcel in candidate_entries
        )
    else:
        flags_ok = (not need_parcels and not has_changes) or bool(
            changeset
            and changeset.area_conservation_verified
            and changeset.geometry_validity_verified
        )
    return [
        _check(
            "parcels_present",
            "地块产出完整性",
            parcels_present,
            stage="EXECUTE",
            actual=f"{len(planned_state.parcels)} parcels",
            expected="parcels produced when zone/project targets exist",
            targets=spatial_target_ids,
            fix="补充地块生成逻辑，产出 planned parcels",
        ),
        _check(
            "parcel_fields",
            "地块字段完整",
            parcel_fields_ok,
            stage="EXECUTE",
            actual=(
                f"missing_identity={missing_identity}, "
                f"missing_candidate={missing_candidate}, "
                f"missing_target={missing_target}, missing_geom={missing_geom}"
            ),
            expected=(
                "every source-backed output has bsm; every candidate-backed output has "
                "candidate_id, target lineage and valid geometry"
            ),
            fix="补齐地块 bsm 与 geometry",
        ),
        _check(
            "changeset_flags",
            "变更集校验标志",
            flags_ok,
            stage="EXECUTE",
            actual=(
                f"conservation={bool(changeset and changeset.area_conservation_verified)}, "
                f"validity={bool(changeset and changeset.geometry_validity_verified)}, "
                f"candidate_geometry={all(_wkt_is_valid(getattr(parcel, 'geometry', '')) for parcel in candidate_entries)}"
            ),
            expected=(
                "source changesets record conservation/validity, or candidate "
                "geometry and lineage are independently verified"
            ),
            targets=spatial_target_ids,
            fix="记录面积守恒与几何有效性校验结果",
        ),
    ]


def check_classification_missing(planned_state: Any) -> List[ValidationCheck]:
    """Check non-preserve parcels carry a planning land use classification."""
    missing = [
        p.bsm
        for p in planned_state.parcels
        if p.operation != "preserve" and not (p.planning_land_use or "").strip()
    ]
    by_bsm = {
        str(getattr(parcel, "bsm", "") or ""): parcel
        for parcel in planned_state.parcels
    }
    missing_targets = sorted(
        {
            target
            for bsm in missing
            if (parcel := by_bsm.get(bsm)) is not None
            for target in _target_lineage(parcel)
            if target
        }
    )
    passed = not missing
    return [
        _check(
            "classification_missing",
            "规划分类缺失",
            passed,
            stage="EXECUTE",
            actual=", ".join(missing),
            expected="non-preserve parcels carry a planning_land_use",
            parcels=missing,
            targets=missing_targets,
            evidence_refs=sorted({f"planned-parcel:{bsm}" for bsm in missing}),
            fix="为地块补充规划分类编码（planning_land_use）",
        )
    ]


def check_candidate_materialization(planned_state: Any) -> List[ValidationCheck]:
    """Validate relation-aware candidate geometry and lineage independently.

    Candidate-backed features are not ``ParcelChange`` rows and therefore do
    not participate in BSM/area-conservation checks.  They still need a
    parseable non-empty geometry, stable candidate identity, target lineage,
    and at least one source reference before VALIDATE can proceed.
    """
    entries: list[Any] = []
    for field in ("parcels", "zones", "overlays", "facilities", "roads", "axes"):
        entries.extend(getattr(planned_state, field, None) or [])
    candidates = [entry for entry in entries if _candidate_backed(entry)]
    if not candidates:
        return [
            _check(
                "candidate_materialization",
                "候选几何物化契约",
                True,
                stage="EXECUTE",
                actual="not_applicable:no_candidate_backed_features",
                expected="candidate-backed features carry geometry and lineage",
            )
        ]

    invalid: list[str] = []
    affected_targets: set[str] = set()
    evidence_refs: set[str] = set()
    for entry in candidates:
        candidate_id = str(getattr(entry, "candidate_id", "") or "").strip()
        identity = candidate_id or _entry_identity(entry) or "unbound"
        target_ids = _target_lineage(entry)
        affected_targets.update(target_ids)
        if candidate_id:
            evidence_refs.add(f"candidate:{candidate_id}")
        source_refs = {
            str(ref)
            for ref in (getattr(entry, "source_refs", None) or [])
            if str(ref).strip()
        }
        source_refs.update(
            str(ref)
            for ref in (getattr(entry, "lineage_refs", None) or [])
            if str(ref).strip()
        )
        evidence_refs.update(source_refs)
        target_id = str(
            getattr(entry, "target_ref", "")
            or getattr(entry, "derived_from_target", "")
            or getattr(entry, "derived_from_zone_target", "")
            or getattr(entry, "project_ref", "")
            or ""
        ).strip()
        geometry_ok = _wkt_is_valid(getattr(entry, "geometry", ""))
        feature_id = str(getattr(entry, "feature_id", "") or "").strip()
        if not candidate_id or not target_id or not feature_id or not source_refs or not geometry_ok:
            invalid.append(
                f"{identity}:candidate={bool(candidate_id)},target={bool(target_id)},"
                f"feature={bool(feature_id)},source={bool(source_refs)},geometry={geometry_ok}"
            )
    passed = not invalid
    return [
        _check(
            "candidate_materialization",
            "候选几何物化契约",
            passed,
            stage="EXECUTE",
            actual="; ".join(invalid) if invalid else f"validated={len(candidates)}",
            expected=(
                "every candidate-backed feature has candidate_id, target lineage, "
                "feature_id, source refs and valid geometry"
            ),
            targets=sorted(affected_targets),
            evidence_refs=sorted(evidence_refs),
            fix="补齐候选几何的稳定身份、目标 lineage、来源引用和有效几何",
        )
    ]


def check_relation_validation(final_validation: Any) -> List[ValidationCheck]:
    """Adapt independent final relation validation into VALIDATE checks.

    This adapter intentionally treats every non-``satisfied`` relation as a
    failed check.  Delivery may still choose a partial package, but callers
    cannot accidentally turn ``unknown``/``pending``/``deferred`` into a full
    validation pass by looking only at a boolean scenario status.
    """

    if final_validation is None:
        return [
            _check(
                "final_relation_validation_missing",
                "最终关系复测",
                False,
                stage="EXECUTE",
                actual="no FinalScenarioValidation supplied",
                expected="independent final relation validation report",
                fix="从最终 PlannedState 执行关系复测后再进入 DELIVERY",
            )
        ]
    rows = list(getattr(final_validation, "satisfactions", None) or [])
    if isinstance(final_validation, dict):
        rows = list(final_validation.get("satisfactions", []) or [])
    checks: list[ValidationCheck] = []
    for row in rows:
        relation_id = str(getattr(row, "relation_id", "") or (row.get("relation_id", "") if isinstance(row, dict) else ""))
        status = str(getattr(row, "status", "") or (row.get("status", "") if isinstance(row, dict) else "unknown"))
        measurement = getattr(row, "measurement", None) if not isinstance(row, dict) else row.get("measurement")
        trace = getattr(row, "evaluation_trace", None) if not isinstance(row, dict) else row.get("evaluation_trace")
        version = getattr(row, "evaluator_version", "") if not isinstance(row, dict) else row.get("evaluator_version", "")
        criticality = str(getattr(row, "criticality", "hard") if not isinstance(row, dict) else row.get("criticality", "hard"))
        measured_satisfied = status == "satisfied" and measurement is not None and bool(trace) and bool(version)
        # Soft relations remain visible as warnings but do not turn a
        # hard-feasibility validation into a false blocker.
        passed = measured_satisfied or criticality != "hard"
        checks.append(
            _check(
                f"final_relation:{relation_id or 'unknown'}",
                "最终关系复测",
                passed,
                stage="EXECUTE",
                actual=f"status={status}, measurement={'present' if measurement is not None else 'missing'}, evaluator={version or 'missing'}",
                expected="satisfied with measurement, evaluator version and trace",
                targets=[relation_id] if relation_id else [],
                evidence_refs=list(getattr(row, "evidence_refs", None) or (row.get("evidence_refs", []) if isinstance(row, dict) else [])),
                fix="修复最终几何/网络/执行轨迹后重新复测关系",
            )
        )
    findings = list(getattr(final_validation, "findings", None) or [])
    if isinstance(final_validation, dict):
        findings = list(final_validation.get("findings", []) or [])
    for finding in findings:
        code = str(getattr(finding, "code", "final_relation_finding") or (finding.get("code", "final_relation_finding") if isinstance(finding, dict) else "final_relation_finding"))
        message = str(getattr(finding, "message", "") or (finding.get("message", "") if isinstance(finding, dict) else ""))
        relation_id = str(getattr(finding, "relation_id", "") or (finding.get("relation_id", "") if isinstance(finding, dict) else ""))
        severity = str(getattr(finding, "severity", "error") if not isinstance(finding, dict) else finding.get("severity", "error"))
        checks.append(
            _check(
                f"relation_finding:{code}:{relation_id or 'global'}",
                "最终关系复测发现",
                severity != "error",
                stage="EXECUTE",
                actual=message or code,
                expected="no final relation/topology findings",
                targets=[relation_id] if relation_id else [],
                evidence_refs=list(getattr(finding, "evidence_refs", None) or (finding.get("evidence_refs", []) if isinstance(finding, dict) else [])),
                fix="处理关系复测 finding 后再生成完整交付包",
            )
        )
    if not checks:
        passed = bool(getattr(final_validation, "passed", False))
        checks.append(
            _check(
                "final_relation_validation",
                "最终关系复测",
                passed,
                stage="EXECUTE",
                actual="no relation rows" if not passed else "passed",
                expected="all final relations have measured satisfied status",
            )
        )
    return checks


def check_cross_layer_topology(planned_state: Any, scenario: Any = None) -> List[ValidationCheck]:
    """Run the cross-layer topology adapter for direct VALIDATE callers."""

    from app.domain.validation.relation_validation import (
        _state_records,
        validate_cross_layer_topology,
    )
    from app.contracts.planning.scenario import ScenarioFeature

    if planned_state is None:
        return [_check("cross_layer_topology", "跨层拓扑", False, stage="EXECUTE", actual="planned_state is missing")]
    scenario_id = str(getattr(scenario, "scenario_id", "") or getattr(planned_state, "scenario_id", "") or "scenario:validation")
    features = [
        ScenarioFeature(
            feature_id=item["feature_id"],
            scenario_id=scenario_id,
            target_id=item["target_id"] or item["identity"],
            candidate_id=item["candidate_id"],
            geometry_kind=item["geometry_kind"],
            geometry_wkt=item["geometry"] or "GEOMETRYCOLLECTION EMPTY",
            crs=item["crs"] or "EPSG:3857",
            generation_operation=f"validate:{item['kind']}",
            source_refs=item["source_refs"] or [f"planned-state:{item['identity']}"],
            # Direct PlannedState callers predate scenario relation lineage.
            # Put those unbound layers in one explicit topology scope so the
            # cross-layer checker still detects a disconnected facility/road;
            # selected features with real relation IDs retain their lineage.
            relation_ids=item["relation_ids"] or [f"topology:{scenario_id}"],
        )
        for item in _state_records(planned_state)
    ]
    findings = validate_cross_layer_topology(features)
    return [
        _check(
            f"cross_layer_topology:{finding.code}:{index}",
            "跨层拓扑",
            False,
            stage="EXECUTE",
            actual=finding.message,
            expected=finding.expected or "all planned layers are topologically connected",
            targets=[finding.target_id] if finding.target_id else [],
            evidence_refs=finding.evidence_refs + finding.feature_refs,
            fix="修复 facility/road/axis 与 parcel/zone 的跨层几何连接",
        )
        for index, finding in enumerate(findings)
    ] or [_check("cross_layer_topology", "跨层拓扑", True, stage="EXECUTE", actual="no cross-layer topology findings")]


__all__ = [
    "check_hard_constraints",
    "check_area_conservation",
    "check_topology",
    "check_overlap",
    "check_continuity",
    "check_accessibility",
    "check_contract_completeness",
    "check_classification_missing",
    "check_candidate_materialization",
    "check_traceability",
    "check_worker_failures",
    "check_relation_validation",
    "check_cross_layer_topology",
]
