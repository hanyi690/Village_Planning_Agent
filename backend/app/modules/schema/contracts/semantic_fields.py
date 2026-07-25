"""Semantic metadata — human-readable anchors for spatial entities.

Semantic metadata is NOT stored as RDF triples. It is persisted as a JSON
attachment alongside the KG, queried via joint query methods in queries.py.

Consumers:
  - PARSE Agent: populates these fields during structured output generation
  - LLM queries: semantic_store + RDF joint queries return enriched results
  - Visualization: uses natural_language_description as human-readable labels
  - Traceability: reasoning_trace + raw_text explain why decisions were made

Non-consumers:
  - EXECUTE MIP solver: only reads RDF structural data (land_use_code, area_ratio, etc.)
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class SemanticMetadata(BaseModel):
    """Human-readable semantic anchors — not stored as RDF triples.

    Natural language descriptions, spatial hints, reasoning traces, and original
    text that make the KG interpretable. Stored as JSON attachment alongside the
    RDF graph, joined at query time via queries.py.

    Fields are all optional with empty defaults for backward compatibility.
    """

    natural_language_description: str = Field(
        default="",
        description="Human-readable target description, e.g. '村北新增15%商业用地'",
    )
    spatial_hint: str = Field(
        default="",
        description="Original spatial reference, e.g. '村北', '靠近刘村'",
    )
    reasoning_trace: str = Field(
        default="",
        description="PARSE reasoning process that led to this target",
    )
    raw_text: str = Field(
        default="",
        description="User's original planning text fragment",
    )


__all__ = ["SemanticMetadata"]