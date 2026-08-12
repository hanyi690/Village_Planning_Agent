"""L1 stage contracts - baseline snapshot of facts, constraints, and gaps."""

from __future__ import annotations

from pydantic import BaseModel

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


class L1DimensionFragment(BaseModel):
    """Per-dimension compiled output of the L1 Observation profile.

    Produced in parallel by the shared parse-compiler for each L1 dimension;
    consumed by l1_aggregate which merges fragments into L1Snapshot.
    """

    dimension_key: str
    facts: list[str] = []
    constraints: list[str] = []
    issues: list[StageIssue] = []
    opportunities: list[str] = []
    evidence_gaps: list[EvidenceGap] = []
    classification_refs: list[ClassificationRef] = []
    spatial_facts: list[str] = []
    location_facts: list[L1LocationFact] = []
    diagnostics: list[ParseDiagnostic] = []
    provenance: "Provenance | None" = None
    trace: "CompilerTrace | None" = None


class L1Snapshot(ContractMeta):
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
    provenance: "Provenance | None" = None


__all__ = [
    "L1Snapshot",
    "L1DimensionFragment",
    "L1LocationFact",
    "EvidenceGap",
]
