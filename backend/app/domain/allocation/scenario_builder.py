"""Build immutable pre-execution scenarios from selected candidate geometry."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.contracts.planning.scenario import PlanningScenario, ScenarioFeature, ScenarioFinding
from app.contracts.spatial.candidate_geometry import CandidateGeometry


def _geometry_kind(candidate: CandidateGeometry) -> str:
    if candidate.kind in {"point", "line", "polygon", "multipatch"}:
        return candidate.kind
    upper = candidate.wkt.upper()
    if upper.startswith("POINT"):
        return "point"
    if upper.startswith(("LINESTRING", "MULTILINESTRING")):
        return "line"
    if upper.startswith(("POLYGON", "MULTIPOLYGON")):
        return "polygon"
    return "multipatch"


def build_scenario_features(
    selected_candidate_ids: Mapping[str, str],
    candidates: Mapping[str, CandidateGeometry],
    *,
    scenario_id: str,
    factors: Sequence[Any] = (),
    source_refs: Sequence[str] = (),
) -> list[ScenarioFeature]:
    relation_ids: dict[str, list[str]] = {}
    for factor in factors:
        relation_id = str(getattr(factor, "factor_id", "")).removeprefix("factor:")
        for ref in (getattr(factor, "subject_ref", ""), getattr(factor, "object_ref", "")):
            if ref:
                relation_ids.setdefault(ref, []).append(relation_id)
    result: list[ScenarioFeature] = []
    for target_id, candidate_id in sorted(selected_candidate_ids.items()):
        candidate = candidates.get(candidate_id)
        if candidate is None or not candidate.is_executable:
            continue
        feature_relation_ids = set(relation_ids.get(target_id, []))
        if not feature_relation_ids:
            feature_relation_ids.add(f"selection:{target_id}:{candidate_id}")
        refs = set(str(item) for item in source_refs if str(item))
        refs.update(str(item) for item in candidate.evidence_refs if str(item))
        refs.update(str(item) for item in candidate.source_bsms if str(item))
        if candidate.source_ref:
            refs.add(candidate.source_ref)
        if not refs:
            refs.add(f"candidate:{candidate_id}")
        feature = ScenarioFeature(
            feature_id=f"feature:{scenario_id}:{target_id}:{candidate_id}",
            scenario_id=scenario_id,
            target_id=target_id,
            candidate_id=candidate_id,
            geometry_kind=_geometry_kind(candidate),
            geometry_wkt=candidate.wkt,
            crs=candidate.crs,
            generation_operation="scenario_candidate_projection",
            source_refs=sorted(refs),
            relation_ids=sorted(feature_relation_ids),
        )
        result.append(feature)
    return result


def build_planning_scenario(
    *,
    scenario_id: str,
    problem: Any,
    selected_candidate_ids: Mapping[str, str],
    relation_satisfactions: Sequence[Any],
    features: Sequence[ScenarioFeature],
    metrics: Mapping[str, float] | None = None,
    findings: Sequence[ScenarioFinding] = (),
    status: str = "draft",
) -> PlanningScenario:
    return PlanningScenario(
        scenario_id=scenario_id,
        baseline_ref=str(getattr(problem, "baseline_ref", "") or ""),
        problem_fingerprint=str(getattr(problem, "fingerprint", "") or ""),
        selected_candidate_ids=dict(sorted(selected_candidate_ids.items())),
        feature_intents=sorted(features, key=lambda item: item.feature_id),
        relation_satisfactions=sorted(relation_satisfactions, key=lambda item: item.relation_id),
        metrics={str(key): float(value) for key, value in sorted((metrics or {}).items())},
        findings=list(findings),
        status=status,
    )


__all__ = ["build_planning_scenario", "build_scenario_features"]
