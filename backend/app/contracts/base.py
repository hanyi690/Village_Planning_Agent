"""Shared immutable base types for cross-boundary application contracts."""

from __future__ import annotations

from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, Field


JsonPrimitive: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonPrimitive | list[object] | dict[str, object]
JsonObject: TypeAlias = dict[str, object]


class StrictContractModel(BaseModel):
    """Serializable contract with strict typing and closed fields."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    schema_version: str = "1.0"
    digest: str = ""
    parent_digests: dict[str, str] = Field(default_factory=dict)
    provenance: JsonObject = Field(default_factory=dict)


__all__ = ["JsonObject", "JsonPrimitive", "JsonValue", "StrictContractModel"]
