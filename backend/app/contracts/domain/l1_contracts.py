"""L1 stage contracts - baseline snapshot of facts, constraints, and gaps."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.contracts.artifacts.classification_ref import ClassificationRef
from app.contracts.artifacts.contract_meta import ContractMeta, StageIssue
from app.contracts.evidence.evidence_contracts import EvidenceSource
from app.contracts.workflow.parse_result_contracts import ParseDiagnostic
from app.contracts.workflow.parsing_contracts import CompilerTrace
from app.contracts.artifacts.provenance import Provenance


class L1LocationFact(BaseModel):
    """A traceable place mention extracted from an L1 observation report."""

    mention: str
    normalized_name: str
    role: str = "unknown"
    aliases: list[str] = []
    spatial_hint: str = ""
    related_mentions: list[str] = []
    source_report_ref: str = ""
    dimension_key: str = ""
    source_span: str = ""
    evidence_refs: list[str] = []
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


class L1Snapshot(ContractMeta):
    # Authoritative typed records.  ``facts`` below is a deterministic
    # compatibility/display projection generated from these records.
    fact_records: list[L1Fact] = Field(default_factory=list)
    facts: list[str] = []
    # Dimension-scoped facts are the auditable source for downstream strategy
    # prompts; ``facts`` remains the backward-compatible flattened view.
    facts_by_dimension: dict[str, list[str]] = {}
    location_facts: list[L1LocationFact] = []
    constraints: list[str] = []
    issues: list[StageIssue] = []
    opportunities: list[str] = []
    evidence_gaps: list[EvidenceGap] = []
    sources: list[EvidenceSource] = []
    classification_refs: list[ClassificationRef] = []
    dimension_provenance: list[Provenance] = []
    spatial_facts_by_dimension: dict[str, list[str]] = {}
    diagnostics_by_dimension: dict[str, list[ParseDiagnostic]] = {}
    traces_by_dimension: dict[str, CompilerTrace] = {}
    provenance: "Provenance | None" = None


__all__ = [
    "L1Snapshot",
    "L1LocationFact",
    "L1Fact",
    "EvidenceGap",
]
