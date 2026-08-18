"""Spatial reference contracts - closed-set spatial query DSL for PARSE.

Defines the typed contract between PARSE (NL -> spec) and KG/spatial_ops
(spec -> candidate BSM -> precise BSM). LLM produces a SpatialReferenceSpec
via instructor; KG consumes it via resolve_candidates; spatial_ops consumes
the CandidateSet for geometric refinement.

See docs/gis/integration/PARSE_SPATIAL_GROUNDING_DESIGN.md §2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field, field_validator


_VALID_TOPO = ("sfTouches", "sfWithin", "sfIntersects", "sfContains", "nearby", "connected_via_road")
_VALID_TYPES = ("directional", "distance", "topological", "attributive", "composed")
_VALID_KINDS = ("entity_type", "layer_group", "place_name", "bsm", "village")
_VALID_DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
_VALID_OPS = ("and", "or", "not")


class RefObject(BaseModel):
    """Reference object: resolves to a KG entity or layer group."""
    kind: str = Field(..., description="Closed set: " + ", ".join(_VALID_KINDS))
    filter: Optional[Dict[str, Any]] = Field(None, description="Attribute filter, e.g. {label_contains:'学校'}")

    model_config = {"extra": "forbid"}

    @field_validator("kind")
    @classmethod
    def kind_must_be_valid(cls, v: str) -> str:
        if v not in _VALID_KINDS:
            raise ValueError(f"kind must be one of {_VALID_KINDS}, got '{v}'")
        return v


class SpatialReferenceSpec(BaseModel):
    """PARSE-produced spatial reference specification. Closed-set, LLM-filled."""
    type: str = Field(..., description="Closed set: " + ", ".join(_VALID_TYPES))
    reference: Optional[RefObject] = None
    direction: Optional[str] = Field(None, description="8-wind: " + ", ".join(_VALID_DIRECTIONS))
    relation: Optional[str] = Field(None, description="within | beyond (for distance type)")
    distance_m: Optional[float] = None
    topo: Optional[str] = Field(None, description="GeoSPARQL/pln relation: " + ", ".join(_VALID_TOPO))
    attr_filter: Optional[Dict[str, Any]] = None
    op: Optional[str] = Field(None, description="and | or | not (for composed type)")
    children: List["SpatialReferenceSpec"] = Field(default_factory=list)
    intervention_id: Optional[str] = None
    target_id: str = ""
    spec_id: str = ""
    project_ref: Optional[str] = None
    unresolved_reason: str = ""
    # Preserve target materialization semantics across the PARSE -> GROUND
    # boundary.  Spatial resolution is geometry-only, but GROUND must not
    # turn a protection/functional overlay into a land-use assignment merely
    # because both happen to use polygon candidates.
    materialization_role: Literal[
        "land_use_assignment",
        "functional_overlay",
        "protection_overlay",
        "restoration_overlay",
        "site_footprint",
    ] | None = None

    model_config = {"extra": "forbid"}

    @field_validator("topo")
    @classmethod
    def topo_must_be_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _VALID_TOPO:
            raise ValueError(f"topo must be one of {_VALID_TOPO}, got '{v}'")
        return v


class GeometryRef(BaseModel):
    """Explicit source-backed geometry reference.

    A target may be backed by more than one source feature (for example a
    retained set of bus stops or a set of existing road segments).  Each
    member stays separate here; callers must not union the records into an
    executable geometry.  ``source_ref`` is the stable feature/entity
    lineage, while ``source_bsms`` is optional parcel evidence associated with
    that feature.
    """
    wkt: str = ""
    crs: str = ""
    bbox: tuple[float, float, float, float] | None = None
    source_ref: str = ""
    source_refs: list[str] = Field(default_factory=list)
    source_bsms: list[str] = Field(default_factory=list)
    feature_kind: str = ""

    model_config = {"extra": "forbid"}

    @field_validator("source_refs", "source_bsms")
    @classmethod
    def _clean_refs(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(str(item) for item in value if str(item).strip()))


@dataclass
class CandidateSet:
    """KG-side candidate BSM set returned by resolve_candidates."""
    bsms: List[str] = field(default_factory=list)
    ref_bsms: List[str] = field(default_factory=list)
    ref_geometry_wkt: Optional[str] = None
    # Source-backed geometries are deliberately a list of independent
    # records.  ``ref_geometry_wkt`` remains for backwards compatibility
    # with adapters that can only return one feature.
    ref_geometries: List[GeometryRef] = field(default_factory=list)


@dataclass
class ResolvedSpatialRef:
    """spatial_ops-side resolved spatial reference (final precise BSMs)."""
    final_bsms: List[str] = field(default_factory=list)
    bbox: Optional[List[float]] = None
    reference_geometry_wkt: Optional[str] = None
    reference_geometries: List[GeometryRef] = field(default_factory=list)
    confidence: float = 0.0
    uncertainty_radius_m: float = 0.0
    uncertainty_reason: str = ""
    provenance: Dict[str, Any] = field(default_factory=dict)


__all__ = ["RefObject", "SpatialReferenceSpec", "GeometryRef", "CandidateSet", "ResolvedSpatialRef"]
