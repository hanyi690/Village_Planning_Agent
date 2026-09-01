"""Stable, bounded World Model query contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from app.contracts.base import StrictContractModel


class EntityQuery(StrictContractModel):
    query_text: str = ""
    concept_refs: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    scope_ref: str = ""
    relation: str = ""
    limit: int = 50


class RepresentationRequirement(StrictContractModel):
    entity_ref: str
    purpose: str = ""
    geometry_kinds: tuple[str, ...] = ()
    crs: str = ""
    require_loadable: bool = True
    limit: int = 50


class IdentityBindingProjectionRequest(StrictContractModel):
    """Dependency-keyed request for one bounded identity cognition page."""

    consumer_stage: Literal["L2", "L3"]
    consumer_dimension_key: str
    dependency_dimension_keys: tuple[str, ...] = Field(
        default=(),
        max_length=16,
    )
    work_item_refs: tuple[str, ...] = Field(default=(), max_length=16)
    mention_refs: tuple[str, ...] = Field(default=(), max_length=16)
    source_mention_refs: tuple[str, ...] = Field(
        default=(),
        max_length=16,
    )
    entity_refs: tuple[str, ...] = Field(default=(), max_length=16)
    scope_refs: tuple[str, ...] = Field(default=(), max_length=16)
    identity_statuses: tuple[
        Literal["resolved", "ambiguous", "unresolved", "not_applicable"],
        ...,
    ] = ("resolved", "ambiguous", "unresolved", "not_applicable")
    world_model_snapshot_ref: str
    world_model_snapshot_digest: str
    cursor: str = ""
    requested_page_size: int = Field(default=24, ge=1, le=32)

    @model_validator(mode="after")
    def require_dependency_selector(self) -> "IdentityBindingProjectionRequest":
        if not self.consumer_dimension_key.strip():
            raise ValueError("consumer_dimension_key is required")
        if not any((
            self.dependency_dimension_keys,
            self.work_item_refs,
            self.mention_refs,
            self.source_mention_refs,
            self.entity_refs,
            self.scope_refs,
        )):
            raise ValueError(
                "identity projection requires an explicit dependency selector"
            )
        return self

    @property
    def query_digest(self) -> str:
        payload = self.model_dump(
            mode="json",
            exclude={"cursor"},
        )
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return "sha256:" + hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()


class IdentityBindingProjectionRow(StrictContractModel):
    row_ref: str
    binding_ref: str
    work_item_ref: str
    source_mention_refs: tuple[str, ...] = ()
    source_dimensions: tuple[str, ...] = ()
    scope_refs: tuple[str, ...] = ()
    canonical_entity_ref: str = ""
    canonical_label: str = ""
    entity_types: tuple[str, ...] = ()
    identity_status: Literal[
        "resolved", "ambiguous", "unresolved", "not_applicable"
    ]
    candidate_count: int = 0
    candidate_labels: tuple[str, ...] = ()
    candidate_labels_truncated: bool = False
    evidence_refs: tuple[str, ...] = ()
    relation_refs: tuple[str, ...] = ()
    spatial_hint: str = ""
    location_expression_ref: str = ""
    location_expression_status: Literal[
        "none", "bound", "ambiguous", "unresolved"
    ] = "none"
    spatial_relation: str = ""
    anchor_entity_refs: tuple[str, ...] = ()
    anchor_work_item_refs: tuple[str, ...] = ()
    anchor_labels: tuple[str, ...] = ()
    distance_hint: str = ""
    uncertainty: str = ""
    representation_count: int = 0
    available_geometry_kinds: tuple[str, ...] = ()
    resource_count: int = 0
    resource_availability: Literal[
        "available", "none", "not_selected"
    ] = "not_selected"
    gap_ref: str = ""


class IdentityBindingProjectionPage(StrictContractModel):
    world_model_snapshot_ref: str
    world_model_snapshot_digest: str
    query_digest: str
    consumer_stage: Literal["L2", "L3"]
    consumer_dimension_key: str
    rows: tuple[IdentityBindingProjectionRow, ...] = ()
    matched_total: int = 0
    emitted_count: int = 0
    truncated: bool = False
    next_cursor: str = ""
    omitted_refs: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()


class RenderedIdentityBindingProjection(StrictContractModel):
    """Central Context Runtime output; only ``table`` enters the LLM."""

    page: IdentityBindingProjectionPage
    columns: tuple[str, ...]
    table_rows: tuple[dict[str, str | int | bool], ...] = ()
    table: str
    rendered_count: int = 0
    render_truncated: bool = False
    continuation_cursor: str = ""


__all__ = [
    "EntityQuery",
    "RepresentationRequirement",
    "IdentityBindingProjectionRequest",
    "IdentityBindingProjectionRow",
    "IdentityBindingProjectionPage",
    "RenderedIdentityBindingProjection",
]
