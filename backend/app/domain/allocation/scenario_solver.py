"""Private search primitives shared by the authoritative ScenarioOptimizer.

Candidate domains are enumerated in stable order (with a bounded search
budget), while geometry/network measurements remain in their dedicated
evaluators.  This module has no public solver entry point; callers consume the
``ScenarioSet`` produced by :mod:`scenario_optimizer`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import combinations
from math import comb
from typing import Any

from app.contracts.planning.constraint_factor import ConstraintFactor, RelationSatisfaction
from app.contracts.planning.scenario import ScenarioFinding
from app.contracts.spatial.grounded_problem import GroundedPlanningProblem
from app.domain.relations.service import RelationEvaluationContext, evaluate_relations, index_relation_features

from .network_subproblem import evaluate_network_subproblem
from .scenario_builder import build_scenario_features


_NETWORK_KEYS = frozenset({
    "connect", "connect_network", "access_via", "provide_access", "serve", "service"
})
_SEARCH_LIMIT = 20_000
_EXCLUSIVE_MATERIALIZATION_ROLES = frozenset({
    "land_use_assignment",
    "site_footprint",
})


@dataclass(frozen=True)
class _ChoiceOptions:
    """A replayable lazy option domain with an exact combinatorial count."""

    candidate_ids: tuple[str, ...]
    min_selected: int
    max_selected: int

    @property
    def count(self) -> int:
        return sum(
            comb(len(self.candidate_ids), size)
            for size in range(self.min_selected, self.max_selected + 1)
        )

    def __iter__(self):
        for size in range(self.min_selected, self.max_selected + 1):
            yield from combinations(self.candidate_ids, size)


def _bounded_choice_product(
    option_domains: Sequence[_ChoiceOptions],
    limit: int,
):
    """Yield at most ``limit`` rows without materializing any option pool.

    ``itertools.product`` snapshots every input iterable before yielding.  A
    subset domain such as C(100, 50) therefore cannot be passed to it even if
    the global search budget is one.  This depth-first product replays each
    small/lazy domain and stops consumption as soon as the global budget is
    exhausted.
    """

    emitted = 0
    prefix: list[tuple[str, ...]] = []

    def visit(index: int):
        nonlocal emitted
        if emitted >= limit:
            return
        if index == len(option_domains):
            emitted += 1
            yield tuple(prefix)
            return
        iterator = iter(option_domains[index])
        while emitted < limit:
            try:
                option = next(iterator)
            except StopIteration:
                break
            prefix.append(option)
            yield from visit(index + 1)
            prefix.pop()

    yield from visit(0)


def _candidate_score(candidate: Any) -> float:
    components = getattr(candidate, "suitability_components", {}) or {}
    numeric = [
        float(value)
        for key, value in sorted(components.items())
        if key not in {"capacity_area_m2", "area_m2"}
        and isinstance(value, (int, float))
    ]
    if numeric:
        return sum(numeric) / len(numeric)
    return max(0.0, min(1.0, float(getattr(candidate, "confidence", 0.0) or 0.0)))


def _factor_key(factor: ConstraintFactor) -> str:
    return factor.evaluator_key or factor.kind


def _candidate_is_selectable(candidate: Any) -> bool:
    """Return whether a grounded geometry may enter scenario selection.

    ``pending`` means that GROUND did not have a constraint index. It is not a
    proof of feasibility. An explicit failed/deferred/unknown status must
    never be promoted into a final planning feature.
    """

    if not bool(getattr(candidate, "is_executable", False)):
        return False
    # Polygon materialization is role-sensitive. A zone without an explicit
    # role must remain deferred: treating it as land-use assignment would
    # silently turn an unresolved functional/protection overlay into an
    # authoritative parcel claim.
    if (
        str(getattr(candidate, "kind", "") or "") in {"polygon", "multipatch"}
        and not str(getattr(candidate, "materialization_role", "") or "").strip()
    ):
        return False
    uncertainty = str(getattr(candidate, "uncertainty_reason", "") or "").lower()
    if any(token in uncertainty for token in ("coarse", "bbox", "village_scope")):
        return False
    if str(getattr(candidate, "role", "") or "") == "scope_geometry":
        return False
    status = str(getattr(candidate, "hard_constraint_status", "pending") or "pending")
    # A typed candidate with an unresolved hard-constraint status is evidence
    # only; it cannot enter a planning scenario.
    if status == "pending" and str(getattr(candidate, "materialization_role", "") or ""):
        return False
    return status not in {
        "failed",
        "deferred",
        "unknown",
    }


def _evaluate_assignment(
    problem: GroundedPlanningProblem,
    selected: Mapping[str, Sequence[str]],
    *,
    scenario_id: str,
    evaluator_context: RelationEvaluationContext,
) -> tuple[list[Any], list[RelationSatisfaction]]:
    # Scenario identity is owned by this solve invocation.  Rebind the
    # evaluator context for replay safety when a caller reuses a baseline
    # context with a different scenario id.
    context_scenario_id = str(getattr(evaluator_context, "scenario_id", "") or "")
    try:
        evaluator_context = replace(evaluator_context, scenario_id=scenario_id)
    except TypeError:
        pass
    candidates = {item.candidate_id: item for item in problem.candidate_geometries}
    features = build_scenario_features(
        selected,
        candidates,
        scenario_id=scenario_id,
        factors=problem.constraint_factors,
        source_refs=problem.source_artifact_refs,
    )
    reference_features = list(
        (getattr(evaluator_context, "reference_features", {}) or {}).values()
    )
    for feature in reference_features:
        feature_scenario_id = str(getattr(feature, "scenario_id", "") or "")
        belongs_to_context = bool(
            context_scenario_id
            and (
                feature_scenario_id == context_scenario_id
                or feature_scenario_id.startswith(f"{context_scenario_id}:")
            )
            and scenario_id.startswith(f"{context_scenario_id}:scenario:")
        )
        if feature_scenario_id not in {"", scenario_id} and not belongs_to_context:
            continue
        if feature_scenario_id != scenario_id and hasattr(feature, "model_copy"):
            feature = feature.model_copy(update={"scenario_id": scenario_id})
        features.append(feature)
    feature_index = index_relation_features(features)

    generic_factors: list[ConstraintFactor] = []
    network_results: list[RelationSatisfaction] = []
    networks = getattr(evaluator_context, "networks", {}) or {}
    demands = getattr(evaluator_context, "demands", None) or getattr(evaluator_context, "demand_snapshots", None) or {}
    for factor in sorted(problem.constraint_factors, key=lambda item: item.factor_id):
        if _factor_key(factor) in _NETWORK_KEYS:
            network_results.append(evaluate_network_subproblem(
                factor,
                feature_index,
                networks=networks,
                demands=demands,
                scenario_id=scenario_id,
                evaluator_version=str(getattr(evaluator_context, "evaluator_version", "relation-evaluator-v1")),
            ))
        else:
            generic_factors.append(factor)
    generic_results = evaluate_relations(
        generic_factors,
        features,
        evaluator_context,
    )
    by_id = {item.relation_id: item for item in [*generic_results, *network_results]}
    results = [
        by_id.get(
            factor.factor_id.removeprefix("factor:"),
            RelationSatisfaction(
                relation_id=factor.factor_id.removeprefix("factor:"),
                scenario_id=scenario_id,
                subject_ref=factor.subject_ref,
                object_ref=factor.object_ref,
                status="not_evaluable",
                criticality="hard" if factor.hard else "soft",
                factor_ids=[factor.factor_id],
                detail="relation_evaluator_missing_result",
            ),
        )
        for factor in sorted(problem.constraint_factors, key=lambda item: item.factor_id)
    ]
    return features, results


def _choices(
    problem: GroundedPlanningProblem,
) -> tuple[list[str], list[_ChoiceOptions], list[str]]:
    """Build deterministic candidate options for the legacy 3-tuple callers.

    The optimizer uses :func:`_choices_with_diagnostics` so malformed subset
    domains cannot be silently interpreted as ``choose_one``.  Keeping this
    small wrapper avoids widening the private helper's historical call shape
    for diagnostics/tests while preserving the stricter implementation.
    """
    targets, options, unavailable, _errors = _choices_with_diagnostics(problem)
    return targets, options, unavailable


def _choices_with_diagnostics(
    problem: GroundedPlanningProblem,
) -> tuple[list[str], list[_ChoiceOptions], list[str], list[str]]:
    """Return closed, deterministic selection options and cardinality errors.

    ``choose_subset`` means an exact member-count range.  It is deliberately
    not allowed to fall back to singleton choices: an omitted bound or a
    bound outside the executable candidate set changes the planning meaning
    and therefore fails closed with an auditable diagnostic.
    """
    geometry = {item.candidate_id: item for item in problem.candidate_geometries}
    targets: list[str] = []
    options: list[_ChoiceOptions] = []
    unavailable: list[str] = []
    errors: list[str] = []
    for domain in sorted(problem.candidate_domains, key=lambda item: item.target_id):
        ids = sorted({item for item in domain.candidate_ids if item in geometry})
        # Candidate-only geometry is valid evidence for grounding but cannot
        # become an execution feature in a PlanningScenario.
        ids = [item for item in ids if _candidate_is_selectable(geometry[item])]
        if ids:
            targets.append(domain.target_id)
            if domain.selection_mode == "all_members":
                options.append(_ChoiceOptions(tuple(ids), len(ids), len(ids)))
            elif domain.selection_mode == "choose_one":
                options.append(_ChoiceOptions(tuple(ids), 1, 1))
            else:
                min_selected = domain.min_selected
                max_selected = domain.max_selected
                if min_selected < 1:
                    errors.append(
                        f"invalid cardinality for target {domain.target_id}: "
                        "choose_subset requires min_selected >= 1"
                    )
                    options.append(_ChoiceOptions((), 1, 0))
                    continue
                if max_selected is None:
                    errors.append(
                        f"unbounded choose_subset for target {domain.target_id}: "
                        "max_selected is required"
                    )
                    options.append(_ChoiceOptions((), 1, 0))
                    continue
                if max_selected < min_selected:
                    errors.append(
                        f"invalid cardinality for target {domain.target_id}: "
                        "max_selected must be >= min_selected"
                    )
                    options.append(_ChoiceOptions((), 1, 0))
                    continue
                if max_selected > len(ids) or min_selected > len(ids):
                    errors.append(
                        f"invalid cardinality for target {domain.target_id}: "
                        f"requested {min_selected}..{max_selected} members for "
                        f"{len(ids)} executable candidates"
                    )
                    options.append(_ChoiceOptions((), 1, 0))
                    continue
                options.append(
                    _ChoiceOptions(tuple(ids), min_selected, max_selected)
                )
        else:
            # Candidate-only/unresolved domains are valid grounding evidence,
            # but they must be deferred independently instead of poisoning an
            # otherwise executable partial scenario.
            unavailable.append(domain.target_id)
    return targets, options, unavailable, errors


def _prune_spatial_conflicts(
    selected: Mapping[str, Sequence[str]],
    candidates: Mapping[str, Any],
) -> tuple[dict[str, tuple[str, ...]], list[tuple[str, str, str]]]:
    """Keep a deterministic non-overlapping subset of exclusive footprints.

    Protection/restoration/functional overlays are intentionally non-exclusive
    and may overlap.  Land-use assignments and site/project footprints are
    authoritative ownership claims, so selecting two intersecting candidates
    would produce an internally contradictory planning layer.  When domains
    have no alternate candidate, defer the lower-ranked target rather than
    materializing overlapping geometry.
    """
    rows = []
    for target_id, candidate_ids in selected.items():
        for candidate_id in candidate_ids:
            candidate = candidates.get(candidate_id)
            if candidate is None:
                continue
            role = _candidate_materialization_role(candidate)
            rows.append((target_id, candidate_id, candidate, role))
    # Higher-confidence/suitability candidates win; target/candidate IDs break
    # ties and keep replay fingerprints stable.
    rows.sort(
        key=lambda row: (
            row[3] not in _EXCLUSIVE_MATERIALIZATION_ROLES,
            -_candidate_score(row[2]),
            row[0],
            row[1],
        )
    )
    kept: list[tuple[str, str, Any, str, Any]] = []
    dropped: list[tuple[str, str, str]] = []
    for target_id, candidate_id, candidate, role in rows:
        if role not in _EXCLUSIVE_MATERIALIZATION_ROLES:
            kept.append((target_id, candidate_id, candidate, role, None))
            continue
        try:
            from shapely import wkt

            geometry = wkt.loads(str(getattr(candidate, "wkt", "") or ""))
        except Exception:
            geometry = None
        conflict = None
        if geometry is not None and not geometry.is_empty:
            for other_target, _other_candidate, other, other_role, other_geometry in kept:
                if other_target == target_id:
                    continue
                if (
                    other_role not in _EXCLUSIVE_MATERIALIZATION_ROLES
                    or other_geometry is None
                ):
                    continue
                try:
                    if geometry.intersection(other_geometry).area > 1e-12:
                        conflict = other_target
                        break
                except Exception:
                    continue
        if conflict:
            dropped.append((target_id, candidate_id, conflict))
            continue
        kept.append((target_id, candidate_id, candidate, role, geometry))
    grouped: dict[str, list[str]] = {}
    for target_id, candidate_id, *_ in kept:
        grouped.setdefault(target_id, []).append(candidate_id)
    return {
        target_id: tuple(sorted(candidate_ids))
        for target_id, candidate_ids in grouped.items()
    }, dropped


def _candidate_materialization_role(candidate: Any) -> str:
    """Resolve the exclusive/non-exclusive role for old untyped candidates."""

    explicit = str(getattr(candidate, "materialization_role", "") or "")
    if explicit:
        return explicit
    legacy_role = str(getattr(candidate, "role", "") or "")
    if legacy_role == "functional_overlay":
        return "functional_overlay"
    if legacy_role == "protection_overlay":
        return "protection_overlay"
    if legacy_role == "restoration_overlay":
        return "restoration_overlay"
    if legacy_role in {"execution_geometry", "parcel_candidate"}:
        return "site_footprint"
    return ""


def _finding(code: str, message: str, *, severity: str = "error", relation_id: str = "", target_id: str = "") -> ScenarioFinding:
    return ScenarioFinding(
        code=code,
        severity=severity,
        message=message,
        relation_id=relation_id,
        target_id=target_id,
    )
