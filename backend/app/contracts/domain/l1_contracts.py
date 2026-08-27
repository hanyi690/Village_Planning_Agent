"""L1 stage contracts - baseline snapshot of facts, constraints, and gaps."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.contracts.artifacts.classification_ref import ClassificationRef
from app.contracts.artifacts.contract_meta import ContractMeta, StageIssue
from app.contracts.evidence.evidence_contracts import EvidenceSource
from app.contracts.evidence.requirement_contracts import EvidenceRequirement
from app.contracts.workflow.parse_result_contracts import ParseDiagnostic
from app.contracts.workflow.parsing_contracts import CompilerTrace
from app.contracts.artifacts.provenance import Provenance


class L1SpatialProvenance(BaseModel):
    """Source lineage for one semantic-to-spatial projection."""

    source_refs: list[str] = Field(default_factory=list)
    source_segment_ids: list[str] = Field(default_factory=list)
    source_quote: str = ""
    observation_id: str = ""


class L1SpatialMention(BaseModel):
    """A named spatial work item emitted by the L1 observe pass.

    This is deliberately semantic only: it carries no coordinate, WKT, BSM,
    or geometry authority.  GROUND resolves it through EvidenceGraph.
    """

    mention_kind: Literal["target", "place", "anchor_request"] = "target"
    mention: str = ""
    normalized_name: str = ""
    target_name: str = ""
    role: str = "unknown"
    village_scopes: list[str] = Field(default_factory=list)
    place_scopes: list[str] = Field(default_factory=list)
    relation: str = ""
    instance_label: str = ""
    instance_count: str = ""
    resolution_state: Literal[
        "resolved",
        "needs_retrieval",
        "conflict",
        "source_exhausted",
        "unknown",
    ] = "needs_retrieval"
    aliases: list[str] = Field(default_factory=list)
    source_feature_ids: list[str] = Field(default_factory=list)
    provenance: L1SpatialProvenance = Field(default_factory=L1SpatialProvenance)


class L1LocationFact(BaseModel):
    """A traceable place mention extracted from an L1 observation report.

    ``target_name`` and the scope/instance fields form a grounding work-item
    identity.  They do not claim that the target has already been located.
    """

    mention: str
    normalized_name: str
    role: str = "unknown"
    target_name: str = ""
    aliases: list[str] = Field(default_factory=list)
    spatial_hint: str = ""
    related_mentions: list[str] = Field(default_factory=list)
    village_scopes: list[str] = Field(default_factory=list)
    place_scopes: list[str] = Field(default_factory=list)
    instance_label: str = ""
    instance_count: str = ""
    resolution_state: Literal[
        "resolved",
        "needs_retrieval",
        "conflict",
        "source_exhausted",
        "unknown",
    ] = "needs_retrieval"
    provenance: L1SpatialProvenance = Field(default_factory=L1SpatialProvenance)
    source_report_ref: str = ""
    dimension_key: str = ""
    source_span: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    source_feature_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class L1Fact(BaseModel):
    """Authoritative, provenance-rich fact consumed by later stages.

    ``facts`` remains a deterministic human-readable projection for old
    reports.  Retrieval, L2/L3 citation and spatial grounding should consume
    this record instead, so source kind, counting basis and source span cannot
    be lost in a display string.
    """

    fact_id: str
    statement: str
    confidence: float = 0.0
    fact_kind: Literal[
        "document_observation",
        "spatial_observation",
        "gis_observation",
        "kg_canonical_fact",
        "derived_metric",
    ]
    dimension_key: str = ""
    subject_scope: str = ""
    semantic_type: str = ""
    attributes: dict[str, str] = Field(default_factory=dict)
    value: str | int | float | None = None
    unit: str = ""
    counting_basis: str = ""
    source_refs: list[str] = Field(default_factory=list, min_length=1)
    source_span: str = ""
    source_snapshot_ref: str = ""
    source_feature_ids: list[str] = Field(default_factory=list)
    derivation: str = ""


class EvidenceGap(BaseModel):
    """Structured evidence gap emitted by L1, resolvable by EXPLORE.

    ``gap_id`` links to ``EvidenceGapResolution.gap_id`` so the L1 Evidence
    Gate can track which gaps EXPLORE has resolved.
    """

    gap_id: str
    dimension: str
    description: str
    required_fact: str = ""
    severity: str = "warning"  # "info" | "warning" | "error"


class L1SourceSegment(BaseModel):
    """Addressable raw-input segment exposed to the L1 extraction model.

    Segments are structural transport units only.  They deliberately do not
    assume that the source is a table, Markdown, HTML, PDF text, or a known
    ledger.  The L1 model decides what the segment means for its dimension;
    the application only preserves offsets and verifies returned evidence.
    """

    segment_id: str
    source_key: str
    source_ref: str
    content_digest: str = ""
    start_char: int = 0
    end_char: int = 0
    start_line: int = 1
    end_line: int = 1
    text: str
    section_path: list[str] = Field(default_factory=list)


class L1SourceIndex(ContractMeta):
    """Addressable source segments supplied to L1 extraction.

    This transport artifact does not interpret source material or carry a
    second asset/demand ledger. Semantic facts and their evidence references
    live only in the typed L1 observation output.
    """

    source_documents: list[str] = Field(default_factory=list)
    source_digest: str = ""
    source_segments: list[L1SourceSegment] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class L1DimensionPassState(BaseModel):
    """Durable cursor for one bounded L1 extraction loop."""

    dimension_key: str
    source_digest: str = ""
    pass_name: Literal[
        "observe",
        "report",
        "complete",
        "diagnostic",
    ] = "observe"
    attempt: int = 0
    max_attempts: int = 2
    diagnostics: list[str] = Field(default_factory=list)
    calls_used: int = 0
    max_calls: int = 4
    source_page_index: int = Field(default=0, ge=0)
    source_page_count: int = Field(default=1, ge=1)
    status: Literal["running", "complete", "diagnostic"] = "running"


class L1Snapshot(ContractMeta):
    # Authoritative typed records.  ``facts`` below is a deterministic
    # display projection generated from these records.
    fact_records: list[L1Fact] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    # Dimension-scoped facts are the auditable source for downstream strategy
    # prompts; ``facts`` remains the flattened view used by summaries.
    facts_by_dimension: dict[str, list[str]] = Field(default_factory=dict)
    location_facts: list[L1LocationFact] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    issues: list[StageIssue] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    evidence_gaps: list[EvidenceGap] = Field(default_factory=list)
    sources: list[EvidenceSource] = Field(default_factory=list)
    classification_refs: list[ClassificationRef] = Field(default_factory=list)
    dimension_provenance: list[Provenance] = Field(default_factory=list)
    spatial_facts_by_dimension: dict[str, list[str]] = Field(default_factory=dict)
    diagnostics_by_dimension: dict[str, list[ParseDiagnostic]] = Field(default_factory=dict)
    traces_by_dimension: dict[str, CompilerTrace] = Field(default_factory=dict)
    provenance: "Provenance | None" = None
    evidence_requirements: list[EvidenceRequirement] = Field(default_factory=list)


__all__ = [
    "L1Snapshot",
    "L1LocationFact",
    "L1SpatialMention",
    "L1SpatialProvenance",
    "L1Fact",
    "EvidenceGap",
    "L1SourceSegment",
    "L1SourceIndex",
    "L1DimensionPassState",
]
