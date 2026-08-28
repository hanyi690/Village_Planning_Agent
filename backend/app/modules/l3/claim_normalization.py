"""Deterministic candidate space for the L3 claim compiler.

The LLM proposes meaning, but this module owns the identities it may select,
the relation choices available for a typed component, and the small semantic
decomposition needed when one planning package contains multiple physical
components.  It never creates geometry or turns a place hint into a target id.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Iterable

from app.contracts.l3.program import PlanningClaim
from app.modules.target_projection.relation_catalog import (
    RelationCandidate,
    relation_options,
    relation_spec,
)
from app.workflow.validation.l1_fact_catalog import (
    CANONICAL_L1_FACT_PREFIX,
    SPATIAL_L1_FACT_KINDS,
    is_canonical_l1_fact_id,
)


# Keep the compiler's public name while making the namespace and spatial-kind
# vocabulary come from the one shared L1 catalog.
SPATIAL_FACT_KINDS = SPATIAL_L1_FACT_KINDS


@dataclass(frozen=True)
class TypedRef:
    ref_id: str
    kind: str
    label: str = ""
    source: str = ""


@dataclass(frozen=True)
class TypedGroundingRequest:
    claim_id: str
    slot_path: str
    expected_kind: str
    query_text: str
    source_span: str = ""
    request_id: str = ""

    def __post_init__(self) -> None:
        payload = "|".join(
            (
                self.claim_id,
                self.slot_path,
                self.expected_kind,
                self.query_text,
                self.source_span,
            )
        ).encode("utf-8")
        if not self.request_id:
            object.__setattr__(
                self,
                "request_id",
                f"grounding:{hashlib.sha256(payload).hexdigest()[:24]}",
            )


def create_grounding_request(
    *,
    claim_id: str,
    slot_path: str,
    expected_kind: str,
    query_text: str,
    source_span: str = "",
) -> TypedGroundingRequest:
    """Create a stable typed request for an unresolved semantic slot."""

    return TypedGroundingRequest(
        claim_id=str(claim_id or "").strip(),
        slot_path=str(slot_path or "").strip(),
        expected_kind=str(expected_kind or "").strip(),
        query_text=str(query_text or "").strip(),
        source_span=str(source_span or "").strip(),
    )


@dataclass
class ClaimRegistry:
    """Current claim identities and their compiler-visible target kinds."""

    refs: dict[str, TypedRef]

    @classmethod
    def from_claims(cls, claims: list[PlanningClaim] | tuple[PlanningClaim, ...]) -> "ClaimRegistry":
        refs: dict[str, TypedRef] = {}
        for claim in claims:
            claim_id = str(claim.claim_id or "").strip()
            if not claim_id:
                continue
            refs[claim_id] = TypedRef(
                ref_id=claim_id,
                kind=claim_target_kind(claim),
                label=str(claim.statement or "").strip()[:120],
                source="claim_registry",
            )
        return cls(refs=refs)

    def options_for_kinds(self, kinds: frozenset[str]) -> list[TypedRef]:
        return sorted(
            (item for item in self.refs.values() if item.kind in kinds),
            key=lambda item: item.ref_id,
        )


def claim_target_kind(claim: Any) -> str:
    """Map a canonical claim to the same typed endpoint vocabulary as TARGET."""

    category = str(getattr(claim, "suggested_category", "") or "").strip()
    asset = str(getattr(claim, "asset_kind", "") or "").strip()
    if category == "facility":
        return "facility"
    if category == "road":
        return "road" if asset == "road" else "linear"
    if category == "axis":
        return "axis"
    if category == "zone":
        return (
            "zone"
            if getattr(getattr(claim, "polygon_parameters", None), "materialization_role", None)
            == "land_use_assignment"
            else "site_area"
        )
    if category in {"site_area", "restoration", "protection"}:
        return "site_area"
    return "action"


def compatible_objects(
    relation_template: str,
    registry: ClaimRegistry,
) -> list[TypedRef]:
    """Return existing registry identities accepted by a relation template."""

    spec = relation_spec(str(relation_template or "").strip())
    if spec is None:
        return []
    return registry.options_for_kinds(spec.object_kinds)


def source_fact_options(
    dimension_key: str,
    claim_semantics: str,
    facts: list[Any] | tuple[Any, ...],
    *,
    source_dimensions: Iterable[str] | None = None,
) -> list[TypedRef]:
    """Return exact source fact ids; never synthesize an identity."""

    dimension = str(dimension_key or "").strip()
    allowed_dimensions = {
        str(value).strip()
        for value in (source_dimensions or ())
        if str(value).strip()
    }
    if dimension:
        allowed_dimensions.update({dimension, "location", "spatial"})
    spatial = str(claim_semantics or "").strip().lower() in {
        "spatial",
        "spatial_intervention",
        "facility",
        "road",
        "linear",
        "axis",
        "zone",
        "site_area",
        "restoration",
        "protection",
    }
    result: list[TypedRef] = []
    for fact in facts:
        fact_id = str(getattr(fact, "fact_id", "") or "").strip()
        fact_dimension = str(getattr(fact, "dimension_key", "") or "").strip()
        fact_kind = str(getattr(fact, "fact_kind", "") or "").strip()
        if not is_canonical_l1_fact_id(fact_id):
            continue
        if allowed_dimensions and fact_dimension not in allowed_dimensions | {""}:
            continue
        if spatial and fact_kind not in SPATIAL_FACT_KINDS:
            continue
        result.append(
            TypedRef(
                ref_id=fact_id,
                kind="source_fact",
                label=str(getattr(fact, "statement", "") or "").strip()[:120],
                source=fact_kind,
            )
        )
    return sorted({item.ref_id: item for item in result}.values(), key=lambda item: item.ref_id)


@dataclass(frozen=True)
class ProjectIntentSkeleton:
    package_ref: str
    statement: str
    component_kinds: tuple[str, ...] = ()
    physical_kinds: tuple[str, ...] = ()
    semantic_relations: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectComponent:
    component_kind: str
    role: str


@dataclass(frozen=True)
class ProjectComponentPlan:
    package_ref: str
    components: tuple[ProjectComponent, ...]
    objective_relations: tuple[str, ...] = ()


def decompose_project_intent(skeleton: ProjectIntentSkeleton) -> ProjectComponentPlan:
    """Split mixed semantic packages without inventing physical works."""

    kinds = {str(item).strip() for item in skeleton.component_kinds if str(item).strip()}
    physical = {str(item).strip() for item in skeleton.physical_kinds if str(item).strip()}
    components: list[ProjectComponent] = []

    for kind in ("axis", "zone", "restoration_overlay", "protection_overlay", "site_area"):
        if kind in kinds:
            components.append(ProjectComponent(kind, "semantic_overlay" if kind in {
                "axis", "zone", "restoration_overlay", "protection_overlay"
            } else "site_component"))

    if "facility" in kinds or ("zone" in kinds and "serve" in skeleton.semantic_relations):
        components.append(ProjectComponent("facility", "physical_node"))
    if "road" in kinds or "linear" in kinds or physical.intersection({"road", "linear", "facility"}):
        physical_kind = "road" if "road" in physical or "road" in kinds else "linear"
        components.append(ProjectComponent(physical_kind, "physical_network"))
    if "land_use_assignment" in kinds:
        components.append(ProjectComponent("land_use_assignment", "land_use_assignment"))

    unique: dict[str, ProjectComponent] = {item.component_kind: item for item in components}
    return ProjectComponentPlan(
        package_ref=str(skeleton.package_ref or "").strip(),
        components=tuple(unique.values()),
        objective_relations=tuple(
            str(item).strip()
            for item in skeleton.semantic_relations
            if str(item).strip()
        ),
    )


__all__ = [
    "ClaimRegistry",
    "CANONICAL_L1_FACT_PREFIX",
    "ProjectComponent",
    "ProjectComponentPlan",
    "ProjectIntentSkeleton",
    "RelationCandidate",
    "SPATIAL_FACT_KINDS",
    "TypedGroundingRequest",
    "TypedRef",
    "claim_target_kind",
    "compatible_objects",
    "create_grounding_request",
    "decompose_project_intent",
    "relation_options",
    "source_fact_options",
]
