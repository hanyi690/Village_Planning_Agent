from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from .contract_meta import ContractMeta


class ParseMode(str, Enum):
    COMPILE = "compile"
    REPAIR = "repair"
    REVISE = "revise"


class CompilationStatus(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    NEEDS_REPAIR = "needs_repair"
    NEEDS_REVIEW = "needs_review"
    COMMITTED = "committed"
    REJECTED = "rejected"


class PatchOperation(str, Enum):
    ADD = "add"
    UPDATE = "update"
    REMOVE = "remove"
    MERGE = "merge"


class CompilationError(BaseModel):
    field: str = ""
    error: str = ""
    source_text: str = ""
    suggestion: str = ""


class ProjectRequirement(BaseModel):
    project_ref: str
    area_range: tuple[float, float] | None = None
    functions: list[str] = Field(default_factory=list)
    spatial_requirements: dict = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)


class CompilationPatch(BaseModel):
    patch_id: str = ""
    field_path: str = ""  # dotted path e.g. "project_requirements.0.functions"
    operation: PatchOperation = PatchOperation.UPDATE
    before: Any = None
    after: Any = None
    source_text_loc: str = ""  # 来源文本位置 (e.g. "L3-report.md:line42")
    actor: Literal["deterministic", "llm", "user"] = "deterministic"
    confidence: float = 0.0
    base_revision: str = ""  # 基于的 artifact revision
    rationale: str = ""  # 简要判断依据，不保存模型内部推理链


class ParseDiagnostic(BaseModel):
    diagnostic_id: str = ""
    severity: Literal["info", "warning", "error"] = "warning"
    code: str = ""  # e.g. "AMBIGUOUS_REFERENCE" | "TABLE_CORRUPT" | "SCHEMA_MISMATCH"
    message: str = ""
    field_path: str = ""
    source_text_loc: str = ""
    target_id: str = ""
    spec_id: str = ""


class ParseTrace(BaseModel):
    mode: ParseMode = ParseMode.COMPILE
    steps: list[dict] = Field(default_factory=list)  # deterministic step log
    started_at: str = ""
    finished_at: str = ""


class ParseRevisionRequest(BaseModel):
    request_id: str = ""
    mode: ParseMode = ParseMode.COMPILE
    program_ref: str = ""  # L3 PlanningProgram artifact_id
    base_revision_ref: str = ""  # 已有编译结果的 revision (for REPAIR/REVISE)
    user_revisions: dict = Field(default_factory=dict)  # 用户局部纠正
    patch_ids: list[str] = Field(default_factory=list)


class IntentCompilationResult(ContractMeta):
    schema_version: Literal["2.0"] = "2.0"
    # 正式字段（不再用 Any intent 承载）
    program_ref: str = ""
    base_revision_ref: str = ""
    typed_intent: Any = None  # SpatialPlanningIntent (lazy ref, keep Any to avoid circular)
    project_requirements: list[ProjectRequirement] = Field(default_factory=list)
    spatial_reference_specs: list[Any] = Field(default_factory=list)  # SpatialReferenceSpec[]
    constraint_set: Any = None  # ConstraintSet (lazy ref)
    diagnostics: list[ParseDiagnostic] = Field(default_factory=list)
    patches: list[CompilationPatch] = Field(default_factory=list)
    target_binding_table: Any = None  # TargetBindingTable (lazy ref)
    compilation_status: CompilationStatus = CompilationStatus.DRAFT
    confidence: float = 0.0
    provenance: Any = None  # Provenance
    # 兼容字段（保留 name 供现有消费者）
    intent: Any = None
    compilation_errors: list[CompilationError] = Field(default_factory=list)
    trace: ParseTrace = Field(default_factory=ParseTrace)


__all__ = [
    "ParseMode",
    "CompilationStatus",
    "PatchOperation",
    "CompilationError",
    "ProjectRequirement",
    "CompilationPatch",
    "ParseDiagnostic",
    "ParseTrace",
    "ParseRevisionRequest",
    "IntentCompilationResult",
]
