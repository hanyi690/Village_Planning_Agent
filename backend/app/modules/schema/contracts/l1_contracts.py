"""L1 stage contracts - baseline snapshot of facts, constraints, and gaps."""

from __future__ import annotations

from pydantic import BaseModel

from .classification_ref import ClassificationRef
from .contract_meta import ContractMeta, StageIssue
from .evidence_contracts import EvidenceSource
from .parse_result_contracts import ParseDiagnostic
from .parsing_contracts import CompilerTrace
from .provenance import Provenance


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
    diagnostics: list[ParseDiagnostic] = []
    provenance: "Provenance | None" = None
    trace: "CompilerTrace | None" = None


class L1Snapshot(ContractMeta):
    facts: list[str] = []
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
    "EvidenceGap",
]
