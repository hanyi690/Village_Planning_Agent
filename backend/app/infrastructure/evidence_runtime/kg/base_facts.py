"""BaseFacts semantic container; clearly not spatial truth.

No ``BaseFacts`` model exists in ``app/modules/kg/`` (only builder comments
reference the concept), so a minimal strict container is defined here. It is a
semantic index view, never geometry authority.
"""

from __future__ import annotations

from pydantic import Field

from app.contracts.base import JsonObject, StrictContractModel


class BaseFacts(StrictContractModel):
    """Semantic-index fact container; spatial facts live elsewhere."""

    facts: list[JsonObject] = Field(default_factory=list)
    provenance: JsonObject = Field(default_factory=dict)


__all__ = ["BaseFacts"]
