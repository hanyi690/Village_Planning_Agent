"""Reference-only final product contract for the L1 boundary."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.artifacts.contract_meta import ContractMeta


L1ProductStatus = Literal["ready", "partial", "human_required", "blocked"]


class L1ProductManifest(ContractMeta):
    """Immutable references that make the post-GROUND L1 view reloadable.

    The manifest deliberately contains no fact rows or binding rows.  Those
    remain immutable child artifacts and are addressed through the references
    below.  ``status`` describes product usability and is not a workflow route.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    observation_product_ref: ArtifactRef
    l1_snapshot_ref: ArtifactRef
    binding_snapshot_ref: ArtifactRef
    world_projection_ref: ArtifactRef
    world_model_snapshot_ref: ArtifactRef
    world_model_snapshot_digest: str = Field(min_length=1)
    fact_row_digest: str = Field(min_length=1)
    binding_row_digest: str = Field(min_length=1)
    open_gap_refs: tuple[str, ...] = ()
    terminal_gap_refs: tuple[str, ...] = ()
    status: L1ProductStatus = "blocked"

    @field_validator("open_gap_refs", "terminal_gap_refs")
    @classmethod
    def normalize_gap_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted({str(value).strip() for value in values if str(value).strip()}))

    @model_validator(mode="after")
    def require_context_identity(self) -> "L1ProductManifest":
        if not self.context_version.strip() or not self.context_fingerprint.strip():
            raise ValueError("L1ProductManifest requires context identity")
        return self


__all__ = ["L1ProductManifest", "L1ProductStatus"]
