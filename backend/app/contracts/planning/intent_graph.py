"""Typed planning intent graph contracts.

The intent graph preserves desired planning relations.  It is deliberately
separate from the execution DAG and from current-state KG facts.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.planning.relation_parameters import (
    RelationParameters,
    parameter_matches_template,
)

RelationTemplate = Literal[
    "within_allowed_area",
    "avoid_constraint",
    "near",
    "serve",
    "provide_access",
    "connect_network",
    "follow_alignment",
    "preserve_existing",
    "upgrade_existing",
    "part_of",
    "co_locate",
    "mutually_exclusive",
    "precedes",
    "contains",
    "located_in",
    "adjacent_to",
    "intersects",
    "overlaps",
]


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sorted_strings(values: list[str]) -> list[str]:
    return sorted({item for item in values if item})


def _node_payload(node: "PlanTargetNode") -> dict[str, object]:
    return node.model_dump(mode="json")


def _relation_payload(relation: "PlanRelationIntent") -> dict[str, object]:
    return {
        **relation.model_dump(mode="json"),
        "evidence_refs": relation.evidence_refs,
        "claim_refs": relation.claim_refs,
        "source_claim_refs": relation.source_claim_refs,
        "source_binding_refs": relation.source_binding_refs,
    }
TargetKind = Literal[
    "site_area", "zone", "facility", "road", "linear", "axis", "action"
]


class PlanTargetNode(BaseModel):
    target_id: str
    target_kind: TargetKind
    asset_kind: str = "none"
    operation: str = "new"
    name: str = ""
    existing_entity_ref: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    claim_refs: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    uncompiled_constraints: list[str] = Field(default_factory=list)
    # Explicit endpoint names from typed road/linear/axis parameters.  These
    # are semantic refs only; GROUND must bind them to GIS features.
    endpoint_refs: list[str] = Field(default_factory=list)
    # Typed locator/source refs carried forward for grounding work.  These are
    # hints or authoritative references, never resolved geometry identities.
    locator_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def canonicalize_collections(self) -> "PlanTargetNode":
        self.evidence_refs = _sorted_strings(self.evidence_refs)
        self.claim_refs = _sorted_strings(self.claim_refs)
        self.required_capabilities = _sorted_strings(self.required_capabilities)
        self.uncompiled_constraints = sorted(
            [item for item in self.uncompiled_constraints if item],
            key=lambda item: item,
        )
        self.endpoint_refs = _sorted_strings(self.endpoint_refs)
        self.locator_refs = _sorted_strings(self.locator_refs)
        return self


class PlanRelationIntent(BaseModel):
    schema_version: Literal["2.0"] = "2.0"
    relation_id: str
    relation_template: RelationTemplate
    subject_ref: str
    object_ref: str
    object_ref_kind: Literal["target", "entity", "place_hint", "constraint"] = "target"
    criticality: Literal["hard", "soft", "informational"] = "soft"
    evidence_refs: list[str] = Field(default_factory=list)
    claim_refs: list[str] = Field(default_factory=list)
    source: str = "planning_program"
    parameters: RelationParameters | None = None
    parameter_status: Literal["provided", "missing", "invalid", "not_required"] = "missing"
    source_claim_refs: list[str] = Field(default_factory=list)
    source_binding_refs: list[str] = Field(default_factory=list)
    geometry_scope: Literal["subject", "object", "pair", "network", "global"] = "pair"
    weight: float = Field(default=1.0, ge=0)

    @model_validator(mode="after")
    def validate_typed_parameters(self) -> "PlanRelationIntent":
        self.evidence_refs = _sorted_strings(self.evidence_refs)
        self.claim_refs = _sorted_strings(self.claim_refs)
        self.source_claim_refs = _sorted_strings(self.source_claim_refs)
        self.source_binding_refs = _sorted_strings(self.source_binding_refs)
        if self.parameters is None:
            if self.relation_template in {
                "contains",
                "located_in",
                "adjacent_to",
                "intersects",
                "overlaps",
            }:
                self.parameter_status = "not_required"
                return self
            if self.parameter_status == "provided":
                self.parameter_status = "missing"
            return self
        if not parameter_matches_template(self.relation_template, self.parameters):
            raise ValueError(
                f"parameters type {self.parameters.parameter_type!r} is invalid for "
                f"relation template {self.relation_template!r}"
            )
        self.parameter_status = "provided"
        return self


class PlanningIntentGraph(ContractMeta):
    schema_version: Literal["2.0"] = "2.0"
    nodes: list[PlanTargetNode] = Field(default_factory=list)
    relations: list[PlanRelationIntent] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    source_program_ref: str = ""
    solver_kind: Literal[
        "auto",
        "single_choice",
        "coverage",
        "parcel_assignment",
        "network_path",
        "topology_layout",
        "bounded_multiobjective",
    ] = "auto"
    solver_kind_reasons: list[str] = Field(default_factory=list)
    shared_resource_refs: list[str] = Field(default_factory=list)
    fingerprint: str = ""

    @model_validator(mode="after")
    def derive_fingerprint(self) -> "PlanningIntentGraph":
        self.nodes = sorted(self.nodes, key=lambda item: item.target_id)
        self.relations = sorted(self.relations, key=lambda item: item.relation_id)
        self.diagnostics = sorted([item for item in self.diagnostics if item], key=lambda item: item)
        self.solver_kind_reasons = _sorted_strings(self.solver_kind_reasons)
        self.shared_resource_refs = _sorted_strings(self.shared_resource_refs)
        if not self.fingerprint:
            payload = {
                "schema_version": self.schema_version,
                "nodes": [_node_payload(item) for item in self.nodes],
                "relations": [_relation_payload(item) for item in self.relations],
                "diagnostics": self.diagnostics,
                "source_program_ref": self.source_program_ref,
                "solver_kind": self.solver_kind,
                "solver_kind_reasons": self.solver_kind_reasons,
                "shared_resource_refs": self.shared_resource_refs,
            }
            raw = _canonical_json(payload).encode("utf-8")
            self.fingerprint = hashlib.sha256(raw).hexdigest()
        return self


__all__ = [
    "RelationTemplate", "TargetKind", "PlanTargetNode", "PlanRelationIntent",
    "PlanningIntentGraph",
]
