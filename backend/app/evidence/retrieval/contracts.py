"""Persisted contracts for the Explore -> Bundle Binder boundary."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


ExploreDomain = Literal["road", "facility", "landuse", "zone", "regulation", "axis", "project"]


class ExplorationInstruction(BaseModel):
    """An evidence-first, non-geometric spatial request.

    Coordinates are deliberately absent.  An Explore result may name BSMs or a
    candidate bbox, but geometry becomes usable only after deterministic bundle
    binding.
    """

    instruction_id: str
    source_chunk_id: str
    section_title: str = ""
    source_page: Optional[int] = None
    evidence_text: str
    domain: ExploreDomain
    action: str = ""
    entity_mentions: List[str] = Field(default_factory=list)
    entity_types: List[str] = Field(default_factory=list)
    spatial_relations: List[Dict[str, Any]] = Field(default_factory=list)
    requested_bundle_queries: List[str] = Field(default_factory=list)
    candidate_bsm_list: List[str] = Field(default_factory=list)
    candidate_bbox: Optional[List[float]] = None
    constraints: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: float = 0.0
    requires_human_confirmation: bool = True


class ExplorationInstructionCollection(BaseModel):
    schema_version: str = "exploration-instructions-v1"
    session_id: str
    village_name: str = ""
    instructions: List[ExplorationInstruction] = Field(default_factory=list)
    kg_session_ref: str = ""


__all__ = [
    "ExploreDomain",
    "ExplorationInstruction",
    "ExplorationInstructionCollection",
]