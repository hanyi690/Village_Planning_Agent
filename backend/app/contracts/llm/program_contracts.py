"""Provider-facing LLM contracts owned by the planning-program boundary."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


QuantityKind = Literal[
    "area",
    "length",
    "count",
    "capacity",
    "population",
    "ratio",
    "time",
]
ResolutionStatus = Literal["resolved", "abstain"]


class UnitResolution(BaseModel):
    """One field-scoped unit proposal returned by the typed provider call."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1, max_length=128)
    field_path: str = Field(min_length=1, max_length=256)
    raw_unit: str = Field(min_length=1, max_length=128)
    quantity_kind: QuantityKind
    normalized_unit: str = Field(max_length=128)
    status: ResolutionStatus


class UnitResolutionBatch(BaseModel):
    """Bounded batch envelope for unit repair proposals."""

    model_config = ConfigDict(extra="forbid")

    resolutions: list[UnitResolution] = Field(
        default_factory=list,
        max_length=64,
    )


__all__ = [
    "QuantityKind",
    "ResolutionStatus",
    "UnitResolution",
    "UnitResolutionBatch",
]
