"""World entity and part identity contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.contracts.base import StrictContractModel


class WorldEntity(StrictContractModel):
    entity_ref: str
    concept_refs: tuple[str, ...] = ()
    canonical_name: str = ""
    canonical_label: str = ""
    aliases: tuple[str, ...] = ()
    valid_time: str = ""
    identity_status: Literal[
        "provisional",
        "resolved",
        "ambiguous",
        "superseded",
    ] = "provisional"
    semantic_status: Literal[
        "unresolved",
        "accepted",
        "ambiguous",
        "superseded",
    ] = "unresolved"
    capabilities: tuple[str, ...] = ()
    accepted_assertion_refs: tuple[str, ...] = ()
    supporting_source_refs: tuple[str, ...] = ()
    lifecycle_state: Literal["observed", "planned", "superseded"] = "observed"


class EntityPart(StrictContractModel):
    part_ref: str
    entity_ref: str
    source_record_refs: tuple[str, ...] = ()
    valid_time: str = ""
    geometry_kind: str = "unknown"
    lifecycle_state: Literal["observed", "planned", "superseded"] = "observed"


class LogicalPartProposal(StrictContractModel):
    """A semantic proposal for the scope of one ``EntityPart``.

    This is deliberately not a geometry contract.  A large source polygon can
    remain one logical part until a target's constraints and operation scope
    establish that it must be split.  The proposal therefore carries only
    KG/DATA references; any eventual geometry is resolved from the referenced
    DATA representations by GROUND/SELECT.
    """

    proposal_ref: str
    entity_ref: str
    part_ref: str
    source_record_refs: tuple[str, ...] = ()
    source_feature_refs: tuple[str, ...] = ()
    representation_refs: tuple[str, ...] = ()
    constraint_refs: tuple[str, ...] = ()
    operation_refs: tuple[str, ...] = ()
    large_entity_hint: bool = False
    status: Literal["candidate", "accepted", "ambiguous", "rejected"] = "candidate"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


__all__ = ["EntityPart", "LogicalPartProposal", "WorldEntity"]
