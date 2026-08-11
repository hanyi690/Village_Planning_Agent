from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ClassificationSystem(str, Enum):
    """Independent code-system namespaces used by planning outputs."""

    GBT21010 = "gbt21010"
    GHYTBM = "ghytbm"
    VNE = "vne"
    GHFLBM = "ghflbm"
    YDYHFLDM = "ydyhfldm"
    TDYTFQDM = "tdytfqdm"
    TDKJGZFQDM = "tdkjgzfqdm"
    PLANNING_ZONE = "planning_zone"
    SPACE_CONTROL = "space_control"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


class ClassificationStatus(str, Enum):
    RESOLVED = "resolved"


class ClassificationRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system: ClassificationSystem
    code: str
    canonical_name: str
    source: str  # "ingested" | "user_provided" | "preserve" | "derived"
    evidence_refs: list[str] = Field(default_factory=list)
    decision_ref: str = ""
    status: ClassificationStatus = ClassificationStatus.RESOLVED

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        allowed = {"ingested", "user_provided", "preserve", "derived"}
        if v not in allowed:
            raise ValueError(f"source must be one of {allowed}, got {v}")
        return v

    @model_validator(mode="after")
    def validate_resolved_namespace(self) -> "ClassificationRef":
        """Validate only within the declared namespace; never crosswalk codes."""
        system = self.system.value if isinstance(self.system, ClassificationSystem) else str(self.system)
        if system in {ClassificationSystem.UNKNOWN.value, ""}:
            raise ValueError("resolved classification cannot use unknown code system")
        names = _same_system_code_names(system)
        if names is None:
            raise ValueError(f"no authoritative dictionary for resolved system: {system}")
        expected = names.get(str(self.code).strip())
        if expected is None:
            raise ValueError(f"code {self.code!r} is not valid in system {system!r}")
        if expected != str(self.canonical_name).strip():
            raise ValueError(
                f"code/name mismatch within system {system!r}: "
                f"{self.code!r} != {self.canonical_name!r}"
            )
        if not self.evidence_refs and self.source not in {"ingested", "preserve"}:
            raise ValueError("resolved non-ingested classification requires evidence_refs")
        return self


def _same_system_code_names(system: str) -> dict[str, str] | None:
    """Return one system's own code→name table, without cross-system mappings."""
    from app.modules.schema.encodings import code_sets

    tables = {
        "gbt21010": code_sets.DLBM_TO_DLMC,
        "ghytbm": code_sets.GHYTBM_TO_GHYTMC,
        "vne": code_sets.VNE_CODE_TO_NAME,
        "ghflbm": code_sets.GHFLBM_MEANING,
        "ydyhfldm": code_sets.YDYHFLDM_TO_NAME,
        "space_control": code_sets.SPACE_CONTROL_ZONE_CODES,
        "planning_zone": {str(code): str(code) for code in code_sets.PLANNING_ZONES},
    }
    if system == "custom":
        return None
    return tables.get(system)


class ClassificationDecision(BaseModel):
    """A decision in exactly one code-system namespace."""

    model_config = ConfigDict(extra="forbid", strict=True)

    target_id: str
    code_system: ClassificationSystem
    candidate_codes: list[str] = []
    selected_code: str = ""
    decision_mode: str = "human"
    evidence_refs: list[str] = []
    rationale: str = ""
    status: str = "unresolved"

    @model_validator(mode="after")
    def validate_closed_set(self) -> "ClassificationDecision":
        if self.status == "resolved":
            if self.code_system == ClassificationSystem.UNKNOWN:
                raise ValueError("resolved decision cannot use unknown code system")
            if self.selected_code not in set(self.candidate_codes):
                raise ValueError("selected_code must be one of candidate_codes")
            if not self.evidence_refs:
                raise ValueError("resolved classification decision requires evidence_refs")
        return self


__all__ = [
    "ClassificationSystem",
    "ClassificationStatus",
    "ClassificationRef",
    "ClassificationDecision",
]
