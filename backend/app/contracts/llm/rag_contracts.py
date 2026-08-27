"""Small provider-facing contracts used by the RAG query planner."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


RagQuery = Annotated[str, Field(min_length=1, max_length=160)]


class RagQueryBatch(BaseModel):
    """Bounded query proposals; retrieval remains deterministic downstream."""

    model_config = ConfigDict(extra="forbid")

    queries: list[RagQuery] = Field(default_factory=list, max_length=8)


__all__ = ["RagQuery", "RagQueryBatch"]
