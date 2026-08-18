"""Compile planning relations into auditable, non-LLM factors."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.contracts.planning.constraint_factor import (
    ConstraintFactor,
    RelationSatisfaction,
)
from app.contracts.planning.relation_parameters import RelationParameters


_RELATION_ALIASES = {
    "far": ("near", "far"),
    "contain": ("within_allowed_area", "contain"),
    "adjacent": ("co_locate", "adjacent"),
    "access_via": ("provide_access", "access_via"),
    "connect": ("connect_network", "connect"),
    "avoid": ("avoid_constraint", "avoid"),
}
_PARAMETER_REQUIRED = {
    "near",
    "far",
    "co_locate",
    "serve",
    "provide_access",
    "access_via",
    "connect_network",
    "connect",
    "precedes",
}


def compile_constraint_factors(intent_graph: Any) -> list[ConstraintFactor]:
    if intent_graph is None:
        return []
    relations = getattr(intent_graph, "relations", None)
    if relations is None and isinstance(intent_graph, dict):
        relations = intent_graph.get("relations", [])
    factors: list[ConstraintFactor] = []
    for relation in list(relations or []):
        if isinstance(relation, dict):
            value = relation
            get = value.get
        else:
            get = lambda key, default=None: getattr(relation, key, default)
        relation_id = str(get("relation_id", "") or "")
        raw_kind = str(get("relation_template", get("kind", "")) or "")
        kind, evaluator_key = _RELATION_ALIASES.get(raw_kind, (raw_kind, raw_kind))
        subject_ref = str(get("subject_ref", "") or "")
        object_ref = str(get("object_ref", "") or "")
        if not relation_id or not subject_ref or not kind:
            continue
        raw_parameters = get("parameters")
        factor_status = "pending" if evaluator_key == "precedes" else "unknown"
        if evaluator_key in _PARAMETER_REQUIRED and raw_parameters is None:
            factor_status = "deferred"
        try:
            factor = ConstraintFactor(
                factor_id=f"factor:{relation_id}",
                kind=kind,
                subject_ref=subject_ref,
                object_ref=object_ref,
                object_ref_kind=str(get("object_ref_kind", "target") or "target"),
                hard=str(get("criticality", "soft") or "soft") == "hard",
                evidence_refs=list(get("evidence_refs", []) or []),
                claim_refs=list(get("claim_refs", []) or []),
                status=factor_status,
                evaluator_key=evaluator_key,
                parameters=raw_parameters,
                subject_candidate_refs=list(get("subject_candidate_refs", []) or []),
                object_candidate_refs=list(get("object_candidate_refs", []) or []),
                geometry_scope=str(get("geometry_scope", "pair") or "pair"),
            )
        except ValidationError:
            continue
        factors.append(factor)
    return factors


def evaluate_relation_satisfaction(
    factors: list[ConstraintFactor], candidates: list[Any]
) -> list[RelationSatisfaction]:
    candidate_targets = {str(getattr(candidate, "target_ref", "") or "") for candidate in candidates}
    result: list[RelationSatisfaction] = []
    for factor in factors:
        status = factor.status
        detail = factor.detail
        if status == "unknown" and factor.kind != "precedes":
            if factor.object_ref and factor.object_ref not in candidate_targets:
                status = "deferred"
                detail = "object target has no grounded candidate yet"
            else:
                detail = "requires KG/topology or GIS evaluation; not inferred from name match"
        result.append(
            RelationSatisfaction(
                relation_id=factor.factor_id.removeprefix("factor:"),
                subject_ref=factor.subject_ref,
                object_ref=factor.object_ref,
                status=status,
                evidence_refs=list(factor.evidence_refs),
                factor_ids=[factor.factor_id],
                detail=detail,
                score=1.0 if status == "satisfied" else 0.0,
                criticality="hard" if factor.hard else "soft",
                evaluator_version="relation-evaluator-v1",
            )
        )
    return result


__all__ = ["compile_constraint_factors", "evaluate_relation_satisfaction"]
