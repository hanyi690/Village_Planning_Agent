"""Typed recovery pointers for item-scoped workflow checkpoints."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RecoveryPointer(BaseModel):
    """Identify the exact item and source input that must be repaired."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: str = Field(min_length=1)
    item_kind: Literal["claim", "target", "relation", "artifact_input"]
    source_stage: str = Field(min_length=1)
    return_stage: str = Field(min_length=1)
    source_artifact_key: str = Field(min_length=1)
    source_artifact_ref: str = ""
    source_input_refs: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    expected_artifact_key: str = Field(min_length=1)
    reason_code: str = Field(min_length=1)
    fingerprint: str = ""

    @model_validator(mode="after")
    def canonicalize(self) -> "RecoveryPointer":
        for field_name in (
            "source_input_refs",
            "missing_requirements",
        ):
            values = getattr(self, field_name)
            normalized = sorted({str(value).strip() for value in values if str(value).strip()})
            object.__setattr__(self, field_name, normalized)
        payload = self.model_dump(mode="json", exclude={"fingerprint"})
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        derived = "sha256:" + hashlib.sha256(encoded).hexdigest()
        if self.fingerprint and self.fingerprint != derived:
            raise ValueError("recovery pointer fingerprint does not match content")
        object.__setattr__(self, "fingerprint", derived)
        return self


__all__ = ["RecoveryPointer"]
