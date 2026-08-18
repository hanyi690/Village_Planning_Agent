"""Explicit migration from the legacy planning contracts to v2.

The migration intentionally does not infer relation thresholds.  A legacy
relation without typed parameters is preserved as a deferred relation and a
machine-readable finding is emitted for the caller to persist.
"""

from __future__ import annotations

from typing import Mapping

from pydantic import BaseModel, Field, ValidationError

from app.contracts.planning.intent_graph import (
    PlanRelationIntent,
    PlanTargetNode,
    PlanningIntentGraph,
    RelationTemplate,
)
from app.contracts.planning.relation_parameters import RelationParameters
from app.contracts.planning.scenario import ScenarioFeature


class MigrationFinding(BaseModel):
    code: str
    message: str
    relation_id: str = ""
    status: str = "deferred"


class PlanningMigrationResult(BaseModel):
    source_schema_version: str = "1.0"
    target_schema_version: str = "2.0"
    graph: PlanningIntentGraph
    findings: list[MigrationFinding] = Field(default_factory=list)


class ScenarioFeatureMigrationResult(BaseModel):
    feature: ScenarioFeature | None = None
    findings: list[MigrationFinding] = Field(default_factory=list)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({item for item in value if isinstance(item, str) and item})


def _float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _raw_relation_parameters(
    relation_template: str,
    value: object,
) -> object:
    raw_parameters = dict(value) if isinstance(value, Mapping) else value
    if isinstance(raw_parameters, dict) and "parameter_type" not in raw_parameters:
        inferred_types = {
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
        }
        inferred_type = inferred_types.get(relation_template)
        if inferred_type:
            raw_parameters["parameter_type"] = inferred_type
    return raw_parameters


def _typed_parameters(
    relation_id: str,
    relation_template: str,
    value: object,
    findings: list[MigrationFinding],
) -> RelationParameters | None:
    if value is None:
        findings.append(
            MigrationFinding(
                code="migration_missing_parameters",
                relation_id=relation_id,
                message=(
                    f"legacy relation {relation_id!r} ({relation_template}) has no "
                    "typed parameters; relation remains deferred"
                ),
            )
        )
        return None

    raw_parameters = _raw_relation_parameters(relation_template, value)
    try:
        relation = PlanRelationIntent(
            relation_id=relation_id,
            relation_template=relation_template,
            subject_ref="migration-subject",
            object_ref="migration-object",
            parameters=raw_parameters,
        )
        return relation.parameters
    except ValidationError as exc:
        findings.append(
            MigrationFinding(
                code="migration_invalid_parameters",
                relation_id=relation_id,
                message=str(exc),
            )
        )
        return None


def migrate_planning_v1_to_v2(payload: Mapping[str, object]) -> PlanningMigrationResult:
    """Migrate a v1 graph payload without guessing missing relation values."""

    raw_graph = _mapping(payload.get("intent_graph", payload))
    findings: list[MigrationFinding] = []
    nodes: list[PlanTargetNode] = []
    for raw_node in raw_graph.get("nodes", []):
        node = _mapping(raw_node)
        try:
            nodes.append(
                PlanTargetNode(
                    target_id=str(node.get("target_id", "")),
                    target_kind=node.get("target_kind", "action"),
                    asset_kind=str(node.get("asset_kind", "none")),
                    operation=str(node.get("operation", "new")),
                    name=str(node.get("name", "")),
                    existing_entity_ref=str(node.get("existing_entity_ref", "")),
                    evidence_refs=_strings(node.get("evidence_refs")),
                    claim_refs=_strings(node.get("claim_refs")),
                    required_capabilities=_strings(node.get("required_capabilities")),
                    uncompiled_constraints=_strings(node.get("uncompiled_constraints")),
                )
            )
        except ValidationError as exc:
            findings.append(MigrationFinding(code="migration_invalid_node", message=str(exc)))

    relations: list[PlanRelationIntent] = []
    for index, raw_relation in enumerate(raw_graph.get("relations", [])):
        relation = _mapping(raw_relation)
        relation_id = str(relation.get("relation_id", f"legacy-relation-{index}"))
        template = relation.get("relation_template", relation.get("kind", ""))
        if template not in RelationTemplate.__args__:
            findings.append(
                MigrationFinding(
                    code="migration_unsupported_relation_template",
                    relation_id=relation_id,
                    message=f"unsupported legacy relation template: {template!r}",
                )
            )
            continue
        parameters = _typed_parameters(
            relation_id,
            str(template),
            relation.get("parameters"),
            findings,
        )
        relations.append(
            PlanRelationIntent(
                relation_id=relation_id,
                relation_template=template,
                subject_ref=str(relation.get("subject_ref", "")),
                object_ref=str(relation.get("object_ref", "")),
                object_ref_kind=relation.get("object_ref_kind", "target"),
                criticality=relation.get("criticality", "soft"),
                evidence_refs=_strings(relation.get("evidence_refs")),
                claim_refs=_strings(relation.get("claim_refs")),
                source=str(relation.get("source", "planning_program")),
                parameters=parameters,
                parameter_status="provided" if parameters is not None else "missing",
                source_claim_refs=_strings(
                    relation.get("source_claim_refs", relation.get("claim_refs"))
                ),
                source_binding_refs=_strings(relation.get("source_binding_refs")),
                geometry_scope=str(relation.get("geometry_scope", "pair") or "pair"),
                weight=_float(relation.get("weight"), 1.0),
            )
        )

    graph = PlanningIntentGraph(
        schema_version="2.0",
        nodes=nodes,
        relations=relations,
        diagnostics=[
            *[item for item in raw_graph.get("diagnostics", []) if isinstance(item, str)],
            *[item.code for item in findings],
        ],
        source_program_ref=str(raw_graph.get("source_program_ref", "")),
    )
    return PlanningMigrationResult(graph=graph, findings=findings)


def migrate_planning_intent_graph_v1_to_v2(
    payload: Mapping[str, object],
) -> PlanningMigrationResult:
    return migrate_planning_v1_to_v2(payload)


def migrate_scenario_feature_v1_to_v2(
    payload: Mapping[str, object],
) -> ScenarioFeatureMigrationResult:
    """Read a legacy feature without weakening v2 write-time lineage rules.

    A legacy singular ``source_ref`` is explicitly promoted to ``source_refs``.
    If no source exists, the feature is not fabricated; callers receive a
    deferred finding and can preserve the raw artifact for audit.
    """

    raw = dict(payload)
    source_refs = _strings(raw.get("source_refs"))
    if not source_refs:
        source_ref = raw.get("source_ref")
        if isinstance(source_ref, str) and source_ref.strip():
            source_refs = [source_ref]
    if not source_refs:
        return ScenarioFeatureMigrationResult(
            findings=[
                MigrationFinding(
                    code="migration_missing_feature_source_refs",
                    message=(
                        "legacy scenario feature has no source_refs; feature remains "
                        "deferred and is not emitted as v2"
                    ),
                )
            ]
        )
    raw["source_refs"] = source_refs
    try:
        return ScenarioFeatureMigrationResult(
            feature=ScenarioFeature.model_validate(raw)
        )
    except ValidationError as exc:
        return ScenarioFeatureMigrationResult(
            findings=[
                MigrationFinding(
                    code="migration_invalid_scenario_feature",
                    message=str(exc),
                )
            ]
        )


__all__ = [
    "MigrationFinding",
    "PlanningMigrationResult",
    "ScenarioFeatureMigrationResult",
    "migrate_planning_v1_to_v2",
    "migrate_planning_intent_graph_v1_to_v2",
    "migrate_scenario_feature_v1_to_v2",
]
