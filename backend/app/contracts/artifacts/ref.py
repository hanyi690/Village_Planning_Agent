"""Canonical immutable content-addressed artifact reference.

This is the single canonical artifact reference implementation for the
backend.  It is frozen and forbids extra fields so a reference can never be
mutated or widened into a filesystem locator.  Filesystem ``path`` and
``revision``/``latest`` locator fields are rejected by construction, and the
digest/schema/identity fields are required so partial fake refs fail closed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


_SHA256_PREFIX = "sha256:"


class ArtifactRef(BaseModel):
    """Portable, immutable reference to one committed artifact blob."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    digest: str
    descriptor_digest: str
    media_type: str = "application/json"
    size_bytes: int
    schema_id: str
    schema_version: str
    semantic_digest: str
    parent_digests: dict[str, str] = Field(default_factory=dict)
    producer_stage: str
    run_id: str
    branch_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    provenance: dict[str, Any] = Field(default_factory=dict)

    @field_validator("digest", "descriptor_digest", "semantic_digest")
    @classmethod
    def require_sha256_digest(cls, value: str) -> str:
        if not value.startswith(_SHA256_PREFIX) or len(value) != 71:
            raise ValueError("digest must be a sha256:<64 hex chars> value")
        int(value[len(_SHA256_PREFIX):], 16)
        return value

    @field_validator("size_bytes")
    @classmethod
    def require_non_negative_size(cls, value: int) -> int:
        if value < 0:
            raise ValueError("size_bytes must be non-negative")
        return value

    @field_validator("schema_id", "schema_version", "producer_stage", "run_id", "branch_id")
    @classmethod
    def require_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("schema and identity fields must be non-empty")
        return value


__all__ = ["ArtifactRef"]