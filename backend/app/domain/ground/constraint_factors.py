"""Compile planning relations into auditable, non-LLM factors."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.contracts.planning.constraint_factor import (
    ConstraintFactor,
    RelationSatisfaction,
)
from app.contracts.planning.relation_parameters import RelationParameters
from app.contracts.planning.relation_parameters import ConnectParameters


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


def compile_constraint_factors(
    intent_graph: Any,
    *,
    default_network_ref: str = "",
    default_endpoint_tolerance_m: float = 5.0,
) -> list[ConstraintFactor]:
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
        if (
            raw_parameters is None
            and evaluator_key in {"connect", "connect_network"}
            and str(get("source", "") or "") == "typed_road_endpoint"
            and default_network_ref
        ):
            raw_parameters = ConnectParameters(
                network_kind="road",
                endpoint_tolerance_m=default_endpoint_tolerance_m,
                network_ref=default_network_ref,
            )
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


def attach_evidence_packet_relations(
    factors: list[ConstraintFactor],
    evidence_packets: Any,
) -> list[ConstraintFactor]:
    """Attach verified packet relations to already-declared planning factors.

    A KG relation is current-state evidence, not an implicit planning order.
    Therefore this function never creates a factor and never changes its
    hard/soft/status fields.  It only adds the packet relation provenance when
    the packet belongs to the factor subject target and its object reference
    matches one side of the verified relation.
    """
    if not factors or not evidence_packets:
        return factors

    output: list[ConstraintFactor] = []
    for factor in factors:
        evidence_refs = list(factor.evidence_refs)
        relation_details: list[str] = []
        for target_id, packet in dict(evidence_packets or {}).items():
            if str(getattr(factor, "subject_ref", "") or "") != str(target_id):
                continue
            object_ref = str(getattr(factor, "object_ref", "") or "").strip()
            if not object_ref:
                continue
            for relation in list(getattr(packet, "relation_evidence", None) or []):
                subject = getattr(relation, "subject", None)
                object_ = getattr(relation, "object", None)
                subject_tokens = _packet_relation_tokens(subject)
                object_tokens = _packet_relation_tokens(object_)
                if object_ref not in subject_tokens and object_ref not in object_tokens:
                    continue
                relation_id = str(getattr(relation, "relation_id", "") or "").strip()
                if relation_id:
                    evidence_refs.append(f"kg:relation:{relation_id}")
                subject_l1_refs = list(
                    getattr(subject, "l1_fact_refs", None) or []
                ) if subject is not None else []
                object_l1_refs = list(
                    getattr(object_, "l1_fact_refs", None) or []
                ) if object_ is not None else []
                evidence_refs.extend(
                    str(value)
                    for value in [
                        *(getattr(relation, "provenance_refs", None) or []),
                        getattr(subject, "geometry_ref", "") if subject is not None else "",
                        getattr(object_, "geometry_ref", "") if object_ is not None else "",
                        *subject_l1_refs,
                        *object_l1_refs,
                    ]
                    if str(value).strip()
                )
                predicate = str(getattr(relation, "predicate", "") or "").strip()
                if relation_id and predicate:
                    relation_details.append(f"{relation_id}:{predicate}")
        if relation_details:
            detail = str(getattr(factor, "detail", "") or "").strip()
            packet_detail = "evidence_packet_relations=" + ",".join(
                sorted(set(relation_details))
            )
            output.append(
                factor.model_copy(update={
                    "evidence_refs": list(dict.fromkeys(evidence_refs)),
                    "detail": "; ".join(
                        item for item in (detail, packet_detail) if item
                    ),
                })
            )
        else:
            output.append(factor)
    return output


def _packet_relation_tokens(feature_ref: Any) -> set[str]:
    if feature_ref is None:
        return set()
    identity = getattr(feature_ref, "identity", None)
    return {
        str(value).strip()
        for value in [
            getattr(identity, "bundle_feature_bsm", "") if identity is not None else "",
            getattr(identity, "source_feature_id", "") if identity is not None else "",
            getattr(identity, "source_bsm", "") if identity is not None else "",
            *(getattr(feature_ref, "entity_refs", None) or []),
        ]
        if str(value).strip()
    }


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


__all__ = [
    "attach_evidence_packet_relations",
    "compile_constraint_factors",
    "evaluate_relation_satisfaction",
]
