from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.artifacts.provenance import Provenance
from app.contracts.program import PlanningClaim
from app.contracts.evidence.requirement_contracts import EvidenceRequirement
from app.contracts.planning.intent_graph import PlanningIntentGraph
from app.contracts.planning.task_graph import PlanningTaskGraph
from app.contracts.spatial.spatial_reference_contracts import SpatialReferenceSpec
from app.contracts.workflow.parse_contracts import SpatialPlanningIntent


class CompilationStatus(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    NEEDS_REVIEW = "needs_review"
    COMMITTED = "committed"
    REJECTED = "rejected"


class ParseDiagnostic(BaseModel):
    diagnostic_id: str = ""
    severity: Literal["info", "warning", "error"] = "warning"
    code: str = ""  # e.g. "AMBIGUOUS_REFERENCE" | "TABLE_CORRUPT" | "SCHEMA_MISMATCH"
    message: str = ""
    field_path: str = ""
    source_text_loc: str = ""
    target_id: str = ""
    spec_id: str = ""


class ClaimDispositionAudit(BaseModel):
    """Stable claim-accounting snapshot copied onto target projection."""

    claim_id: str
    dimension_key: str
    status: Literal[
        "admitted",
        "pending_grounding",
        "merged_duplicate",
        "deferred",
        "invalid",
    ]
    reason: str
    missing_requirements: list[str] = Field(default_factory=list)


class IntentCompilationResult(ContractMeta):
    schema_version: Literal["2.0"] = "2.0"
    program_ref: str = ""
    claims: list[PlanningClaim] = Field(default_factory=list)
    pending_grounding_claims: list[PlanningClaim] = Field(default_factory=list)
    claim_dispositions: list[ClaimDispositionAudit] = Field(default_factory=list)
    typed_intent: SpatialPlanningIntent | None = None
    spatial_reference_specs: list[SpatialReferenceSpec] = Field(default_factory=list)
    # Internal GROUND work items for pending spatial claims.  These are not
    # formal TARGET_PROJECTION outputs or executable interventions.
    pending_grounding_specs: list[SpatialReferenceSpec] = Field(default_factory=list)
    diagnostics: list[ParseDiagnostic] = Field(default_factory=list)
    compilation_status: CompilationStatus = CompilationStatus.DRAFT
    provenance: Provenance | None = None
    intent_graph: PlanningIntentGraph | None = None
    planning_task_graph: PlanningTaskGraph | None = None
    evidence_requirements: list[EvidenceRequirement] = Field(default_factory=list)


__all__ = [
    "CompilationStatus",
    "ParseDiagnostic",
    "ClaimDispositionAudit",
    "IntentCompilationResult",
]
