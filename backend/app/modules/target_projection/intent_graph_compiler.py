"""Deterministic compilation of typed L3 programs into intent relations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from types import SimpleNamespace

from pydantic import TypeAdapter, ValidationError

from app.contracts.l3.l3_contracts import PlanningIntervention, PlanningProgram
from app.contracts.evidence.identity_contracts import EvidenceObservation, GroundedEntityBinding
from app.contracts.target_projection.intent_graph import PlanRelationIntent, PlanTargetNode, PlanningIntentGraph
from app.contracts.ground.relation_parameters import RelationParameters
from .relation_catalog import relation_spec
from .relation_validator import PlanningDiagnostic, validate_relation_intent
from app.core.common.solver_kind import infer_intent_solver_kind


_RELATION_PARAMETERS = TypeAdapter(RelationParameters)
_PARAMETER_TYPE_BY_TEMPLATE = {
    "within_allowed_area": "allowed_area",
    "avoid_constraint": "avoid_constraint",
    "near": "distance",
    "serve": "service",
    "provide_access": "access",
    "connect_network": "connect",
    "follow_alignment": "alignment",
    "preserve_existing": "existing_asset",
    "upgrade_existing": "existing_asset",
    "part_of": "part_of",
    "co_locate": "co_locate",
    "mutually_exclusive": "mutually_exclusive",
    "precedes": "precedes",
    "contains": "empty",
    "located_in": "empty",
    "adjacent_to": "empty",
    "intersects": "empty",
    "overlaps": "empty",
}


def _target_kind(intervention: PlanningIntervention) -> str:
    if intervention.category == "facility":
        return "facility"
    if intervention.category == "road":
        return "road" if intervention.asset_kind == "road" else "linear"
    if intervention.category == "axis":
        return "axis"
    if intervention.category == "zone":
        return "zone" if intervention.materialization_role == "land_use_assignment" else "site_area"
    if intervention.category in {"restoration", "protection", "site_area"}:
        return "site_area"
    return "action" if intervention.execution_mode == "non_spatial" else "site_area"


def _operation(intervention: PlanningIntervention) -> str:
    return {"widen": "upgrade", "harden": "upgrade"}.get(
        intervention.intervention_action, intervention.intervention_action
    )


def _capabilities(intervention: PlanningIntervention) -> list[str]:
    kind = _target_kind(intervention)
    if kind == "road":
        return ["road.construction"]
    if kind == "linear":
        return [f"linear.{intervention.asset_kind}"]
    if kind == "facility":
        return ["facility.placement"]
    if kind == "axis":
        return ["axis.construction"]
    if kind in {"site_area", "zone"}:
        return ["land.design"]
    return []


def _node(intervention: PlanningIntervention) -> PlanTargetNode:
    endpoint_parameters = (
        intervention.road_parameters
        or intervention.linear_parameters
        or intervention.axis_parameters
    )
    requirements = intervention.spatial_requirements
    locator_refs: list[str] = []
    if isinstance(requirements, dict):
        for key in (
            "location_hints",
            "affected_parcel_refs",
            "source_feature_refs",
            "source_fact_refs",
        ):
            values = requirements.get(key, [])
            if isinstance(values, str):
                values = [values]
            if isinstance(values, Sequence):
                locator_refs.extend(str(value) for value in values if str(value).strip())
    return PlanTargetNode(
        target_id=intervention.target_id or intervention.intervention_id,
        target_kind=_target_kind(intervention),
        asset_kind=intervention.asset_kind,
        operation=_operation(intervention),
        name=intervention.name,
        evidence_refs=list(dict.fromkeys([*intervention.evidence_refs, *intervention.claim_refs])),
        claim_refs=list(dict.fromkeys(intervention.claim_refs)),
        required_capabilities=_capabilities(intervention),
        uncompiled_constraints=list(intervention.constraints),
        endpoint_refs=list(getattr(endpoint_parameters, "connects", None) or []),
        locator_refs=locator_refs,
    )


def _shared_resource_refs(
    interventions: Sequence[PlanningIntervention],
) -> list[str]:
    refs: list[str] = []
    for intervention in interventions:
        requirements = intervention.spatial_requirements
        if not isinstance(requirements, Mapping):
            continue
        for key in (
            "shared_resource_refs",
            "parcel_membership_refs",
            "competing_parcel_refs",
        ):
            values = requirements.get(key, [])
            if isinstance(values, str):
                values = [values]
            if isinstance(values, Sequence):
                refs.extend(str(value) for value in values if str(value).strip())
    return list(dict.fromkeys(refs))


def _raw_parameter_payload(template: str, item: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = item.get("parameters")
    if raw is None:
        return None
    if hasattr(raw, "model_dump"):
        return raw.model_dump(mode="python")
    if not isinstance(raw, Mapping):
        return None
    payload = dict(raw)
    if not payload:
        # An explicitly empty parameter object is the provider's durable
        # representation of "this relation still needs GROUND inputs".  It
        # is missing, not a malformed typed value.
        return None
    payload.setdefault("parameter_type", _PARAMETER_TYPE_BY_TEMPLATE.get(template, ""))
    return payload


def _parse_parameters(
    template: str,
    item: Mapping[str, Any],
) -> tuple[RelationParameters | None, str, str | None]:
    spec = relation_spec(template)
    if spec is None:
        return None, "invalid", "unsupported_relation_template"
    payload = _raw_parameter_payload(template, item)
    if payload is None:
        if template in {"contains", "located_in", "adjacent_to", "intersects", "overlaps"}:
            return _RELATION_PARAMETERS.validate_python({"parameter_type": "empty"}), "not_required", None
        return None, "missing", None
    try:
        parameters = _RELATION_PARAMETERS.validate_python(payload)
    except (ValidationError, TypeError, ValueError):
        return None, "invalid", "relation_parameters_invalid"
    if parameters.parameter_type not in spec.parameter_types:
        return None, "invalid", "relation_parameter_type_mismatch"
    return parameters, "provided", None


def _provenance_refs(
    object_ref: str,
    item: Mapping[str, Any],
    observations: Sequence[EvidenceObservation],
    bindings: Sequence[GroundedEntityBinding],
) -> tuple[list[str], list[str], list[str]]:
    observation_refs = [
        str(value)
        for value in item.get("observation_refs", [])
        if str(value).strip()
    ]
    binding_refs = [
        str(value)
        for value in item.get("source_binding_refs", [])
        if str(value).strip()
    ]
    evidence_refs = [str(value) for value in item.get("evidence_refs", []) if str(value).strip()]
    for observation in observations:
        if object_ref and object_ref in {
            observation.observation_id,
            observation.mention,
            observation.normalized_name,
        }:
            observation_refs.append(observation.observation_id)
            evidence_refs.extend(observation.evidence_refs or observation.source_refs)
    for binding in bindings:
        if object_ref and object_ref in {
            binding.binding_id,
            binding.canonical_entity_ref,
            binding.mention_ref,
        }:
            binding_refs.append(binding.binding_id)
            evidence_refs.extend(binding.evidence_refs)
    return (
        list(dict.fromkeys(observation_refs)),
        list(dict.fromkeys(binding_refs)),
        list(dict.fromkeys(evidence_refs)),
    )


def _structured_relations(
    intervention: PlanningIntervention,
    valid_ids: set[str],
    diagnostics: list[PlanningDiagnostic],
    *,
    observations: Sequence[EvidenceObservation],
    bindings: Sequence[GroundedEntityBinding],
) -> list[PlanRelationIntent]:
    raw = (
        intervention.spatial_requirements.get("relations", [])
        if isinstance(intervention.spatial_requirements, dict)
        else []
    )
    if not isinstance(raw, list):
        diagnostics.append(PlanningDiagnostic(
            "relations_not_list", "relations must be a list", "error", intervention.target_id,
        ))
        return []
    result: list[PlanRelationIntent] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            diagnostics.append(PlanningDiagnostic(
                "relation_not_object", "relation declaration must be an object", "error",
                f"relation:{intervention.target_id}:{index}",
            ))
            continue
        template = str(item.get("relation_template") or item.get("template") or "").strip()
        relation_id = str(item.get("relation_id") or f"relation:{intervention.target_id}:{index}")
        spec = relation_spec(template)
        if spec is None:
            diagnostics.append(PlanningDiagnostic(
                "unsupported_relation_template", f"unsupported relation template {template!r}",
                "error", relation_id,
            ))
            continue
        subject = str(item.get("subject_ref") or intervention.target_id)
        object_ref = str(item.get("object_ref") or item.get("object_target_id") or "")
        object_kind = "target" if object_ref in valid_ids else str(
            item.get("object_ref_kind") or "entity"
        )
        if object_kind not in {"target", "entity", "place_hint", "constraint"}:
            diagnostics.append(PlanningDiagnostic(
                "relation_invalid_object_kind", f"invalid object ref kind {object_kind!r}",
                "error", relation_id,
            ))
            object_kind = "entity"
        parameters, parameter_status, parameter_error = _parse_parameters(template, item)
        criticality = str(item.get("criticality") or spec.default_criticality)
        if criticality not in {"hard", "soft", "informational"}:
            criticality = spec.default_criticality
        if parameter_error:
            diagnostics.append(PlanningDiagnostic(
                parameter_error,
                f"could not compile typed parameters for {template!r}; relation is deferred",
                "error" if criticality == "hard" else "warning", relation_id,
            ))
        if not object_ref:
            diagnostics.append(PlanningDiagnostic(
                "relation_missing_object", "relation has no object reference and is deferred",
                "error" if criticality == "hard" else "warning", relation_id,
            ))
        _, binding_refs, parameter_evidence = _provenance_refs(
            object_ref, item, observations, bindings,
        )
        relation = PlanRelationIntent(
            relation_id=relation_id,
            relation_template=template,
            subject_ref=subject,
            object_ref=object_ref,
            object_ref_kind=object_kind,
            criticality=criticality,
            evidence_refs=list(dict.fromkeys([
                *intervention.evidence_refs,
                *intervention.claim_refs,
                *parameter_evidence,
            ])),
            claim_refs=list(dict.fromkeys(intervention.claim_refs)),
            source=str(item.get("source") or "structured_spatial_requirements"),
            parameters=parameters,
            parameter_status=parameter_status,
            source_claim_refs=list(dict.fromkeys([
                *intervention.claim_refs,
                *[str(value) for value in item.get("source_claim_refs", []) if str(value).strip()],
            ])),
            source_binding_refs=binding_refs,
            geometry_scope=str(item.get("geometry_scope") or spec.geometry_scope),
            weight=float(item.get("weight") or 1.0),
        )
        result.append(relation)
    return result


def _typed_endpoint_relations(
    intervention: PlanningIntervention,
    *,
    valid_ids: set[str],
    existing_relations: Sequence[PlanRelationIntent],
) -> list[PlanRelationIntent]:
    """Preserve explicit road endpoint semantics as typed relation intents.

    ``connects`` names are not GIS identities.  The relation is therefore
    emitted with missing parameters and must be bound by GROUND against an
    authoritative network snapshot; it can never become a route by name
    matching alone.
    """

    if intervention.category != "road" or intervention.asset_kind != "road":
        return []
    parameters = intervention.road_parameters
    endpoint_refs = list(getattr(parameters, "connects", None) or [])
    if not endpoint_refs:
        return []
    existing = {
        (relation.subject_ref, relation.object_ref)
        for relation in existing_relations
        if relation.relation_template == "connect_network"
    }
    result: list[PlanRelationIntent] = []
    for index, endpoint_ref in enumerate(endpoint_refs):
        object_ref = str(endpoint_ref).strip()
        if not object_ref or (intervention.target_id, object_ref) in existing:
            continue
        result.append(
            PlanRelationIntent(
                relation_id=f"relation:{intervention.target_id}:connect:{index}",
                relation_template="connect_network",
                subject_ref=intervention.target_id,
                object_ref=object_ref,
                object_ref_kind="target" if object_ref in valid_ids else "place_hint",
                criticality="hard",
                evidence_refs=list(intervention.evidence_refs),
                claim_refs=list(intervention.claim_refs),
                source="typed_road_endpoint",
                parameter_status="missing",
                source_claim_refs=list(intervention.claim_refs),
                geometry_scope="network",
            )
        )
    return result


def compile_intent_graph_v2(
    program: PlanningProgram,
    *,
    observations: Sequence[EvidenceObservation] | None = None,
    bindings: Sequence[GroundedEntityBinding] | None = None,
) -> PlanningIntentGraph:
    """Compile a typed program into a parameterized graph without guessing."""

    observations = tuple(observations or ())
    bindings = tuple(bindings or ())
    nodes = [_node(item) for item in program.interventions]
    node_index = {node.target_id: node for node in nodes}
    valid_ids = set(node_index)
    diagnostics: list[PlanningDiagnostic] = []
    relations: list[PlanRelationIntent] = []
    for dependency in program.dependencies:
        relation_id = f"dependency:{dependency.from_intervention_id}:{dependency.to_intervention_id}"
        if dependency.from_intervention_id not in valid_ids or dependency.to_intervention_id not in valid_ids:
            diagnostics.append(PlanningDiagnostic(
                "dependency_unknown_target",
                f"dependency references unknown target {dependency.from_intervention_id!r} or {dependency.to_intervention_id!r}",
                "error", relation_id,
            ))
            continue
        relation = PlanRelationIntent(
            relation_id=relation_id,
            relation_template="precedes",
            subject_ref=dependency.from_intervention_id,
            object_ref=dependency.to_intervention_id,
            object_ref_kind="target",
            criticality="hard",
            source=dependency.dependency_type or "program_dependency",
            parameter_status="missing",
        )
        relations.append(relation)
        diagnostics.extend(validate_relation_intent(relation, node_index))
    for intervention in program.interventions:
        structured = _structured_relations(
            intervention, valid_ids, diagnostics,
            observations=observations, bindings=bindings,
        )
        relations.extend(structured)
        endpoint_relations = _typed_endpoint_relations(
            intervention,
            valid_ids=valid_ids,
            existing_relations=structured,
        )
        relations.extend(endpoint_relations)
        for relation in endpoint_relations:
            diagnostics.append(PlanningDiagnostic(
                "relation_parameters_pending_ground_binding",
                "typed road endpoint will be bound to the authoritative network snapshot in GROUND",
                "warning",
                relation.relation_id,
            ))
    for relation in relations:
        if relation.source == "typed_road_endpoint" and relation.parameters is None:
            continue
        diagnostics.extend(validate_relation_intent(relation, node_index))
    shared_resource_refs = _shared_resource_refs(program.interventions)
    solver_kind, solver_kind_reasons = infer_intent_solver_kind(
        SimpleNamespace(
            nodes=nodes,
            relations=relations,
            shared_resource_refs=shared_resource_refs,
        )
    )
    return PlanningIntentGraph(
        nodes=nodes,
        relations=relations,
        diagnostics=[str(item) for item in diagnostics],
        source_program_ref=str(program.artifact_id or ""),
        solver_kind=solver_kind,
        solver_kind_reasons=solver_kind_reasons,
        shared_resource_refs=shared_resource_refs,
    )


__all__ = ["compile_intent_graph_v2"]
