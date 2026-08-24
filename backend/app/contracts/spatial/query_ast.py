"""Closed-set, snapshot-bound spatial query AST."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


EntityKind = Literal[
    "entity_type",
    "layer_group",
    "place_name",
    "feature_id",
    "bsm",
    "village",
]
FilterOperator = Literal["eq", "neq", "in", "contains", "gte", "lte", "gt", "lt"]
DistanceUnit = Literal["m", "km", "minutes"]
DistanceMetric = Literal["planar", "geodesic", "network"]
SortDirection = Literal["asc", "desc"]


class DatasetRef(BaseModel):
    """Authoritative dataset identity required by every executable query."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    snapshot_id: str
    layer_id: str

    @field_validator("dataset_id", "snapshot_id", "layer_id")
    @classmethod
    def _require_identity(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("dataset, snapshot, and layer identities are required")
        return normalized


class EntityRef(BaseModel):
    """Semantic entity reference; it deliberately has no coordinate field."""

    model_config = ConfigDict(extra="forbid")

    kind: EntityKind
    name: str = ""
    entity_id: str = ""
    aliases: tuple[str, ...] = Field(default_factory=tuple)
    scope: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _require_name_or_id(self) -> "EntityRef":
        self.aliases = tuple(dict.fromkeys(item.strip() for item in self.aliases if item.strip()))
        self.scope = tuple(dict.fromkeys(item.strip() for item in self.scope if item.strip()))
        if not self.name.strip() and not self.entity_id.strip():
            raise ValueError("entity reference requires a name or entity_id")
        return self


class AttributeFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    operator: FilterOperator
    value: Any

    @field_validator("field")
    @classmethod
    def _require_field(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("attribute filter field is required")
        return normalized


class RelationPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["within", "intersects", "contains", "touches", "nearest"]
    reference: EntityRef


class DistancePredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["distance_lte", "distance_gte"]
    reference: EntityRef
    threshold: float = Field(gt=0)
    unit: DistanceUnit
    metric: DistanceMetric

    @model_validator(mode="after")
    def _validate_metric(self) -> "DistancePredicate":
        if self.metric == "network" and self.unit != "minutes":
            raise ValueError("network distance must use minutes")
        if self.metric != "network" and self.unit == "minutes":
            raise ValueError("minutes distance must use network metric")
        return self


class TopologyPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["connected_to", "adjacent_to", "upstream_of", "downstream_of"]
    reference: EntityRef


SpatialPredicate = Annotated[
    Union[RelationPredicate, DistancePredicate, TopologyPredicate],
    Field(discriminator="kind"),
]


class AggregateSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["count", "area", "length", "min", "max", "sum"]
    field: str = ""


class SortSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    direction: SortDirection = "asc"

    @field_validator("field")
    @classmethod
    def _require_field(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("sort field is required")
        return normalized


class SpatialQuery(BaseModel):
    """Executable spatial query input with no free SQL or raw coordinates."""

    model_config = ConfigDict(extra="forbid")

    query_id: str
    query_version: str = "1.0"
    dataset: DatasetRef
    crs: str
    entity_refs: tuple[EntityRef, ...] = Field(default_factory=tuple)
    predicates: tuple[SpatialPredicate, ...] = Field(default_factory=tuple)
    filters: tuple[AttributeFilter, ...] = Field(default_factory=tuple)
    aggregate: AggregateSpec | None = None
    sort: tuple[SortSpec, ...] = Field(default_factory=tuple)
    limit: int = Field(default=100, ge=1, le=1000)
    fingerprint: str = ""

    @field_validator("query_id", "crs")
    @classmethod
    def _require_query_identity(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("query_id and CRS are required")
        return normalized

    @model_validator(mode="after")
    def _derive_fingerprint(self) -> "SpatialQuery":
        if not self.fingerprint:
            payload = self.model_dump(mode="json", exclude={"fingerprint"})
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            self.fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return self

    @property
    def execution_ready(self) -> bool:
        return bool(self.dataset.snapshot_id and self.dataset.layer_id and self.crs)


__all__ = [
    "AggregateSpec",
    "AttributeFilter",
    "DatasetRef",
    "DistancePredicate",
    "EntityRef",
    "RelationPredicate",
    "SortSpec",
    "SpatialPredicate",
    "SpatialQuery",
    "TopologyPredicate",
]
