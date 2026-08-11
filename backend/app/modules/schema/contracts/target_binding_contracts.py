"""Compile-time target binding contracts.

A TargetBinding is the immutable compile-time link that ties a target_id to
its intervention_id and (when a spatial spec exists) its spec_id. It is the
authoritative join key used across PARSE -> GROUND -> SELECT -> EXECUTE so
downstream stages never need to fall back to positional pairing.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class TargetBinding(BaseModel):
    """Immutable compile-time binding: target_id <-> intervention_id <-> spec_id."""
    target_id: str
    intervention_id: str
    spec_id: str
    project_ref: str
    target_type: str = ""
    expected_output_kind: str = ""

    model_config = {"frozen": True}


class TargetBindingTable(BaseModel):
    """Collection of TargetBindings, persisted as an artifact."""
    bindings: tuple[TargetBinding, ...] = Field(default_factory=tuple)

    model_config = {"frozen": True}

    def binding_for_target(self, target_id: str) -> TargetBinding | None:
        for b in self.bindings:
            if b.target_id == target_id:
                return b
        return None

    def binding_for_spec(self, spec_id: str) -> TargetBinding | None:
        for b in self.bindings:
            if b.spec_id == spec_id:
                return b
        return None


__all__ = ["TargetBinding", "TargetBindingTable"]