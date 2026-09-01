"""Typed, replayable products emitted by one L1/L2/L3 dimension worker.

The report database remains useful for human-facing prose and audit history,
but it is not a semantic dependency store.  A dimension worker commits this
small envelope to CAS and the layer aggregate consumes the exact descriptor
carried by the workflow checkpoint.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field, model_validator

from app.contracts.artifacts.contract_meta import ContractMeta


DimensionStage = Literal["l1", "l2", "l3"]
DimensionProductStatus = Literal["completed", "pending", "human_required"]


class DimensionProductArtifact(ContractMeta):
    """One immutable dimension result and its dependency closure.

    ``product`` is validated again against ``product_schema_id`` by the owning
    aggregate.  Keeping the status in the same typed envelope lets a failed or
    quarantined dimension remain explicit instead of disappearing from a
    partial aggregate.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    stage: DimensionStage
    layer: Literal[1, 2, 3]
    dimension_key: str = Field(min_length=1)
    status: DimensionProductStatus
    product_schema_id: Literal[
        "L1DimensionOutput",
        "L2DecisionSet",
        "PlanningClaimSet",
    ]
    product: dict[str, Any] = Field(default_factory=dict)
    input_artifact_digests: dict[str, str] = Field(default_factory=dict)
    dependency_product_refs: tuple[str, ...] = ()
    dependency_product_digests: dict[str, str] = Field(default_factory=dict)
    evidence_gap_refs: tuple[str, ...] = ()
    input_digest: str = ""
    diagnostics: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_dimension_product(self) -> "DimensionProductArtifact":
        expected_layer = {"l1": 1, "l2": 2, "l3": 3}[self.stage]
        if self.layer != expected_layer:
            raise ValueError("dimension product stage/layer mismatch")
        expected_schema = {
            "l1": "L1DimensionOutput",
            "l2": "L2DecisionSet",
            "l3": "PlanningClaimSet",
        }[self.stage]
        if self.product_schema_id != expected_schema:
            raise ValueError("dimension product schema does not match its stage")
        if self.status == "completed" and not self.product:
            raise ValueError("completed dimension product requires a typed payload")
        if self.status != "completed" and not self.diagnostics:
            raise ValueError("incomplete dimension product requires diagnostics")
        dependency_keys = set(self.dependency_product_refs)
        if set(self.dependency_product_digests) != dependency_keys:
            raise ValueError("dimension dependency refs/digests do not have exact closure")
        if any(
            not value.startswith("sha256:") or len(value) != 71
            for value in self.dependency_product_digests.values()
        ):
            raise ValueError("dimension dependency digest must be sha256")
        if not dependency_keys.issubset(self.input_artifact_digests):
            raise ValueError("dimension dependencies must be declared as artifact inputs")
        return self


def dimension_product_key(layer: int, dimension_key: str) -> str:
    """Return the stable checkpoint key for one dimension product."""

    normalized = str(dimension_key or "").strip()
    if layer not in {1, 2, 3} or not normalized:
        raise ValueError("dimension product key requires layer 1..3 and a dimension")
    if any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for character in normalized):
        raise ValueError("dimension product key contains unsupported characters")
    return f"l{layer}_dimension__{normalized}"


__all__ = [
    "DimensionProductArtifact",
    "DimensionProductStatus",
    "DimensionStage",
    "dimension_product_key",
]
