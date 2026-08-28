"""Build the SELECT solver readiness report without invoking a solver."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.contracts.select.solver_readiness import (
    BackendReadiness,
    CandidateReadiness,
    DemandReadiness,
    NetworkReadiness,
    ReadinessReason,
    RelationReadiness,
    SnapshotReadiness,
    SolverReadiness,
    TargetReadiness,
    TaskGraphReadiness,
)
from app.contracts.ground.grounded_problem import GroundedPlanningProblem
from app.modules.select.solver_portfolio import (
    SolverBackendRegistry,
    build_solver_problem_view,
    default_solver_registry,
)
from app.spatial.relations.registry import (
    RelationEvaluatorRegistry,
    build_default_relation_registry,
)
from app.contracts.target_projection.p1_closure import build_relation_readiness


def _clean(value: object) -> str:
    return str(value or "").strip()


def _values(value: object, name: str) -> dict[str, object]:
    raw = value.get(name) if isinstance(value, dict) else getattr(value, name, None)
    return dict(raw or {}) if isinstance(raw, dict) else {}


def _refs(value: object, name: str) -> set[str]:
    raw = value.get(name) if isinstance(value, dict) else getattr(value, name, None)
    return {_clean(item) for item in (raw or ()) if _clean(item)}


def _default_relation_registry() -> RelationEvaluatorRegistry:
    return build_default_relation_registry()


def _reason(
    code: str,
    message: str,
    *,
    severity: str,
    ref: str = "",
    source_refs: set[str] | list[str] | tuple[str, ...] = (),
) -> ReadinessReason:
    return ReadinessReason(
        code=code,
        message=message,
        severity=severity,  # type: ignore[arg-type]
        ref=ref,
        source_refs=sorted({str(item) for item in source_refs if str(item).strip()}),
    )


def _source_refs(problem: GroundedPlanningProblem | None) -> set[str]:
    if problem is None:
        return set()
    refs = set(_clean(item) for item in problem.source_artifact_refs if _clean(item))
    refs.update(_clean(item) for item in problem.scope_source_refs if _clean(item))
    refs.update(
        _clean(item)
        for target in problem.target_domains
        for item in target.evidence_refs
        if _clean(item)
    )
    refs.update(
        _clean(item)
        for candidate in problem.candidate_geometries
        for item in [
            *candidate.source_refs,
            *candidate.evidence_refs,
            *candidate.source_feature_ids,
            candidate.l1_snapshot_ref,
            candidate.bundle_snapshot_digest,
        ]
        if _clean(item)
    )
    return refs


def _dimension(
    dimension_type: type,
    *,
    status: str,
    reasons: list[ReadinessReason],
    refs: set[str],
    **kwargs: Any,
) -> Any:
    blockers = {
        reason.ref
        for reason in reasons
        if reason.severity == "hard" and reason.ref
    }
    blockers.update(
        reason.code
        for reason in reasons
        if reason.severity == "hard" and not reason.ref
    )
    return dimension_type(
        status=status,
        blocker_refs=sorted(blockers),
        source_refs=sorted(refs),
        reasons=reasons,
        **kwargs,
    )


def build_solver_readiness(
    problem: GroundedPlanningProblem | None,
    *,
    demand_portfolio: Any = None,
    context: Any = None,
    task_graph: Any = None,
    relation_registry: RelationEvaluatorRegistry | None = None,
    solver_registry: SolverBackendRegistry | None = None,
    evaluator_context: Any = None,
) -> SolverReadiness:
    """Construct readiness from typed inputs and registry support only.

    This function performs no suitability evaluation, refinement, compilation,
    or optimization.  Hard missing inputs become blockers; absent optional
    provenance is retained as an advisory so it cannot be mistaken for proof.
    """

    source_refs = _source_refs(problem)
    target_reasons: list[ReadinessReason] = []
    relation_reasons: list[ReadinessReason] = []
    demand_reasons: list[ReadinessReason] = []
    network_reasons: list[ReadinessReason] = []
    candidate_reasons: list[ReadinessReason] = []
    backend_reasons: list[ReadinessReason] = []
    snapshot_reasons: list[ReadinessReason] = []
    task_reasons: list[ReadinessReason] = []

    if problem is None:
        target_reasons.append(_reason(
            "missing:grounded_problem",
            "SELECT has no GroundedPlanningProblem to preflight",
            severity="hard",
            ref="problem:grounded",
        ))
        target = _dimension(TargetReadiness, status="not_groundable", reasons=target_reasons, refs=set(), target_ids=())
        empty = {
            key: _dimension(cls, status="pending", reasons=[], refs=set(), **kwargs)
            for key, cls, kwargs in (
                ("relation", RelationReadiness, {"relation_refs": ()}),
                ("demand", DemandReadiness, {"demand_refs": ()}),
                ("network", NetworkReadiness, {"network_refs": ()}),
                ("candidate", CandidateReadiness, {"candidate_refs": ()}),
                ("backend", BackendReadiness, {}),
                ("snapshot", SnapshotReadiness, {"snapshot_refs": ()}),
                ("task_graph", TaskGraphReadiness, {"task_refs": ()}),
            )
        }
        return SolverReadiness(
            problem_fingerprint="",
            status="not_groundable",
            target=target,
            relation=empty["relation"],
            demand=empty["demand"],
            network=empty["network"],
            candidate=empty["candidate"],
            backend=empty["backend"],
            snapshot=empty["snapshot"],
            task_graph=empty["task_graph"],
            blocker_refs=target.blocker_refs,
            source_refs=[],
            advisories=[],
        )

    target_ids = {
        _clean(item.target_id)
        for item in [*problem.target_domains, *problem.candidate_domains]
        if _clean(item.target_id)
    }
    target_reasons.extend(
        _reason(
            f"target:{item.target_id}:{item.status}",
            f"target {item.target_id} is {item.status}",
            severity="hard",
            ref=f"target:{item.target_id}",
            source_refs=set(item.evidence_refs),
        )
        for item in problem.target_domains
        if item.status != "resolved"
    )
    if not target_ids:
        target_reasons.append(_reason(
            "missing:target",
            "no grounded target is available for SELECT",
            severity="hard",
            ref="target:missing",
        ))
    target_status = "not_groundable" if any(item.severity == "hard" for item in target_reasons) else "ready"
    target = _dimension(TargetReadiness, status=target_status, reasons=target_reasons, refs=source_refs, target_ids=tuple(sorted(target_ids)))

    candidate_refs = {
        _clean(item.candidate_id)
        for item in problem.candidate_geometries
        if _clean(item.candidate_id)
    }
    if problem.candidate_completeness.status != "candidate_complete":
        status = (
            "human_required"
            if problem.candidate_completeness.status == "human_required"
            else "not_groundable"
            if problem.candidate_completeness.status == "not_groundable"
            else "blocked"
        )
        candidate_reasons.append(_reason(
            f"candidate_completeness:{problem.candidate_completeness.status}",
            "; ".join(problem.candidate_completeness.reasons) or "candidate completeness is not ready",
            severity="hard",
            ref=f"candidate_completeness:{problem.candidate_completeness.status}",
            source_refs=source_refs,
        ))
    else:
        status = "ready"
    for domain in problem.candidate_domains:
        if domain.status == "candidate_only":
            candidate_reasons.append(_reason(
                "candidate_only",
                f"target {domain.target_id} has search candidates but no executable candidate domain",
                severity="hard",
                ref=f"target:{domain.target_id}",
            ))
    for candidate in problem.candidate_geometries:
        if candidate.schema_status != "valid":
            candidate_reasons.append(_reason(
                f"candidate_schema:{candidate.schema_status}",
                f"candidate {candidate.candidate_id} has pending or invalid candidate schema",
                severity="hard",
                ref=f"candidate:{candidate.candidate_id}",
                source_refs=set(candidate.source_refs) | set(candidate.evidence_refs),
            ))
        if candidate.spatial_domain_kind in {"bbox", "village_scope"} or candidate.role == "scope_geometry":
            candidate_reasons.append(_reason(
                "search_scope_not_executable",
                f"candidate {candidate.candidate_id} is search scope, not executable geometry",
                severity="hard",
                ref=f"candidate:{candidate.candidate_id}",
            ))
    if candidate_reasons and status == "ready":
        status = "human_required" if any("candidate_only" in item.code for item in candidate_reasons) else "blocked"
    candidate = _dimension(CandidateReadiness, status=status, reasons=candidate_reasons, refs=source_refs, candidate_refs=tuple(sorted(candidate_refs)))

    factors = list(problem.constraint_factors)
    relation_ids = {_clean(item.factor_id) for item in factors if _clean(item.factor_id)}
    relation_registry = relation_registry or _default_relation_registry()
    satisfaction_by_factor = {
        _clean(ref): item
        for item in problem.relation_satisfaction
        for ref in [*_refs(item, "factor_ids"), _clean(item.relation_id)]
        if _clean(ref)
    }
    for factor in factors:
        key = _clean(factor.evaluator_key or factor.kind)
        evaluator_available = key == "precedes" or relation_registry.get(key) is not None
        if key != "precedes" and not evaluator_available:
            relation_reasons.append(_reason(
                "missing:relation_evaluator",
                f"no relation evaluator is registered for {key}",
                severity="hard" if factor.hard else "advisory",
                ref=f"relation-evaluator:{key}",
                source_refs=set(factor.evidence_refs),
            ))
        readiness = build_relation_readiness(
            factor,
            satisfaction_by_factor.get(_clean(factor.factor_id)),
            evaluator_available=evaluator_available,
        )
        for reason in readiness.reasons:
            relation_reasons.append(_reason(
                f"relation_readiness:{reason}",
                f"relation {factor.factor_id} readiness is {reason}",
                severity=(
                    "hard"
                    if factor.hard
                    and readiness.evaluation_readiness != "pending_selection"
                    else "advisory"
                ),
                ref=f"relation:{factor.factor_id}",
                source_refs=set(readiness.evidence_refs) | set(readiness.source_snapshot_refs),
            ))
        if readiness.evaluation_readiness == "pending_selection":
            relation_reasons.append(_reason(
                "relation_pending_selection",
                f"relation {factor.factor_id} awaits scenario candidate selection",
                severity="advisory",
                ref=f"relation:{factor.factor_id}",
                source_refs=set(readiness.evidence_refs) | set(readiness.source_snapshot_refs),
            ))
        satisfaction = satisfaction_by_factor.get(_clean(factor.factor_id))
        if (
            factor.hard
            and satisfaction is not None
            and satisfaction.status in {"not_evaluable", "deferred"}
            and readiness.evaluation_readiness != "pending_selection"
        ):
            relation_reasons.append(_reason(
                f"relation_satisfaction:{satisfaction.status}",
                f"hard relation {factor.factor_id} is {satisfaction.status}",
                severity="hard",
                ref=f"relation:{factor.factor_id}",
                source_refs=set(satisfaction.evidence_refs),
            ))
        if (
            factor.hard
            and factor.status in {"deferred", "not_evaluable"}
            and satisfaction is None
            and readiness.evaluation_readiness != "pending_selection"
        ):
            relation_reasons.append(_reason(
                f"relation_factor:{factor.status}",
                f"hard relation factor {factor.factor_id} is {factor.status}",
                severity="hard",
                ref=f"relation:{factor.factor_id}",
                source_refs=set(factor.evidence_refs),
            ))
    if any(item.severity == "hard" for item in relation_reasons):
        relation_status = "blocked"
    elif relation_reasons:
        relation_status = "pending"
    else:
        relation_status = "ready"
    relation = _dimension(RelationReadiness, status=relation_status, reasons=relation_reasons, refs=source_refs, relation_refs=tuple(sorted(relation_ids)))

    demand_refs = {
        _clean(getattr(factor.parameters, "demand_ref", ""))
        for factor in factors
        if _clean(getattr(factor.parameters, "demand_ref", ""))
    }
    demands = {
        _clean(item.demand_id): item
        for item in list(getattr(demand_portfolio, "demands", None) or [])
        if _clean(getattr(item, "demand_id", ""))
    }
    demand_criticality = {
        _clean(getattr(factor.parameters, "demand_ref", "")): "hard" if factor.hard else "soft"
        for factor in factors
        if _clean(getattr(factor.parameters, "demand_ref", ""))
    }
    for factor in factors:
        ref = _clean(getattr(factor.parameters, "demand_ref", ""))
        if ref and factor.hard:
            demand_criticality[ref] = "hard"
    for ref in sorted(demand_refs):
        if ref not in demands:
            demand_reasons.append(_reason(
                "missing:demand",
                f"demand artifact is missing {ref}",
                severity="hard" if demand_criticality.get(ref) == "hard" else "advisory",
                ref=f"demand:{ref}",
            ))
    if not demand_refs and not demands:
        demand_reasons.append(_reason(
            "demand_not_declared",
            "no explicit demand snapshot is required by the current parcel-only route",
            severity="advisory",
        ))
    demand = _dimension(DemandReadiness, status="blocked" if any(item.severity == "hard" for item in demand_reasons) else "pending" if demand_reasons else "ready", reasons=demand_reasons, refs=source_refs, demand_refs=tuple(sorted(demand_refs)))

    network_refs = set(problem.network_refs)
    network_refs.update(
        _clean(ref)
        for factor in factors
        for ref in [*factor.network_refs, getattr(factor.parameters, "network_ref", "")]
        if _clean(ref)
    )
    networks = _values(context, "networks") or _values(context, "network_snapshots")
    network_criticality: dict[str, str] = {}
    for factor in factors:
        factor_refs = {
            _clean(ref)
            for ref in [*factor.network_refs, getattr(factor.parameters, "network_ref", "")]
            if _clean(ref)
        }
        for ref in factor_refs:
            if factor.hard or network_criticality.get(ref) != "hard":
                network_criticality[ref] = "hard" if factor.hard else "soft"
    for ref in sorted(network_refs):
        if ref not in networks:
            network_reasons.append(_reason(
                "missing:network",
                f"network snapshot is missing {ref}",
                severity="hard" if network_criticality.get(ref) == "hard" else "advisory",
                ref=f"network:{ref}",
            ))
    network = _dimension(
        NetworkReadiness,
        status=(
            "blocked"
            if any(item.severity == "hard" for item in network_reasons)
            else "pending"
            if network_reasons
            else "ready"
        ),
        reasons=network_reasons,
        refs=source_refs,
        network_refs=tuple(sorted(network_refs)),
    )

    effective_evaluator_context = evaluator_context or SimpleNamespace(
        networks=networks,
        demands=demands,
    )
    solver_registry = solver_registry or default_solver_registry()
    view = build_solver_problem_view(problem, evaluator_context=effective_evaluator_context)
    resolution = solver_registry.resolve(problem, view)
    if resolution.backend is None:
        backend_reasons.append(_reason(
            "missing:solver_backend",
            "no registered solver backend can support the grounded problem",
            severity="hard",
            ref=f"solver-kind:{view.problem_kind}",
            source_refs=set(view.required_input_refs),
        ))
        backend_reasons.extend(
            _reason(
                "backend_support",
                code,
                severity="advisory",
                ref=f"solver-kind:{view.problem_kind}",
            )
            for code in resolution.support.reason_codes
        )
        backend_status = "blocked"
        backend_id = ""
        backend_version = ""
    else:
        backend_status = "ready"
        backend_id = _clean(resolution.backend.backend_id)
        backend_version = _clean(resolution.backend.backend_version)
    backend = _dimension(
        BackendReadiness,
        status=backend_status,
        reasons=backend_reasons,
        refs=set(view.required_input_refs),
        backend_id=backend_id,
        backend_version=backend_version,
        problem_kind=view.problem_kind,
    )

    snapshot_refs = source_refs | {problem.baseline_ref} - {""}
    if not problem.baseline_ref:
        snapshot_reasons.append(_reason(
            "baseline_snapshot_missing",
            "problem has no explicit baseline snapshot reference",
            severity="advisory",
            ref="snapshot:baseline",
        ))
    snapshot = _dimension(SnapshotReadiness, status="pending" if snapshot_reasons else "ready", reasons=snapshot_reasons, refs=snapshot_refs, snapshot_refs=tuple(sorted(snapshot_refs)))

    task_refs = {
        _clean(task.task_id)
        for task in list(getattr(task_graph, "tasks", None) or [])
        if _clean(getattr(task, "task_id", ""))
    }
    if task_graph is None:
        task_reasons.append(_reason(
            "task_graph_missing",
            "planning task graph was not supplied to SELECT preflight",
            severity="advisory",
            ref="task-graph:missing",
        ))
    else:
        for task in list(getattr(task_graph, "tasks", None) or []):
            if str(getattr(task, "status", "")) in {"blocked", "failed"}:
                task_reasons.append(_reason(
                    f"task:{task.status}",
                    f"planning task {task.task_id} is {task.status}",
                    severity="hard",
                    ref=f"task:{task.task_id}",
                ))
    task_status = "blocked" if any(item.severity == "hard" for item in task_reasons) else "pending" if task_reasons else "ready"
    task_graph_readiness = _dimension(TaskGraphReadiness, status=task_status, reasons=task_reasons, refs=source_refs, task_refs=tuple(sorted(task_refs)))

    dimensions = [target, relation, demand, network, candidate, backend, snapshot, task_graph_readiness]
    hard_statuses = {item.status for item in dimensions if item.blocker_refs}
    if "not_groundable" in hard_statuses:
        status = "not_groundable"
    elif "human_required" in hard_statuses:
        status = "human_required"
    elif hard_statuses:
        status = "blocked"
    else:
        status = "ready"
    blocker_refs = sorted({ref for item in dimensions for ref in item.blocker_refs})
    advisories = [
        reason
        for item in dimensions
        for reason in item.reasons
        if reason.severity == "advisory"
    ]
    return SolverReadiness(
        problem_fingerprint=problem.fingerprint,
        status=status,
        target=target,
        relation=relation,
        demand=demand,
        network=network,
        candidate=candidate,
        backend=backend,
        snapshot=snapshot,
        task_graph=task_graph_readiness,
        blocker_refs=blocker_refs,
        source_refs=sorted(source_refs),
        advisories=advisories,
    )


__all__ = ["build_solver_readiness"]
