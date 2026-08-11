from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ClassificationSystem(str, Enum):
    """Independent code-system namespaces used by planning outputs."""

    GBT21010 = "gbt21010"
    APPENDIX5 = "appendix5"
    TUGUI = "tugui"
    GHYTBM = "ghytbm"
    VNE = "vne"
    GHFLBM = "ghflbm"
    YDYHFLDM = "ydyhfldm"
    THREE_CATEGORIES = "three_categories"
    ZONE_TYPES_APPENDIX5 = "zone_types_appendix5"
    ZONE_TYPES_GBT50137 = "zone_types_gbt50137"
    ZONE_TYPES_TOWN = "zone_types_town"
    ZONE_TYPES_VILLAGE = "zone_types_village"
    TDYTFQDM = "tdytfqdm"
    TDKJGZFQDM = "tdkjgzfqdm"
    PLANNING_ZONE = "planning_zone"
    PRIMARY_ZONE = "primary_zone"
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
    from app.modules.schema.encodings.dicts.loader import get_center

    # These names are deliberately direct dictionary lookups.  Do not add a
    # mapping-table fallback here: a code is valid only in the namespace that
    # declared it, even when another namespace happens to contain the same
    # string.
    tables = {
        "gbt21010": code_sets.DLBM_TO_DLMC,
        "appendix5": code_sets.GHYTBM_TO_GHYTMC,
        "tugui": get_center().encoding("tugui").to_dict("code", "name"),
        "ghytbm": code_sets.GHYTBM_TO_GHYTMC,
        "vne": code_sets.VNE_CODE_TO_NAME,
        "ghflbm": code_sets.GHFLBM_MEANING,
        "ydyhfldm": code_sets.YDYHFLDM_TO_NAME,
        "three_categories": get_center().encoding("three_categories").to_dict("code", "name"),
        "zone_types_appendix5": get_center().encoding("zone_types_appendix5").to_dict("code", "name"),
        "zone_types_gbt50137": get_center().encoding("zone_types_gbt50137").to_dict("code", "name"),
        "zone_types_town": get_center().encoding("zone_types_town").to_dict("code", "name"),
        "zone_types_village": get_center().encoding("zone_types_village").to_dict("code", "name"),
        "space_control": code_sets.SPACE_CONTROL_ZONE_CODES,
        "tdkjgzfqdm": code_sets.SPACE_CONTROL_ZONE_CODES,
        "planning_zone": get_center().encoding("planning_zones").to_dict("code", "name"),
        "primary_zone": get_center().encoding("primary_zones").to_dict("code", "name"),
    }
    if system == "custom":
        return None
    return tables.get(system)


def classification_code_names(system: ClassificationSystem | str) -> dict[str, str] | None:
    """Return the authoritative closed set for one declared system."""
    value = system.value if isinstance(system, ClassificationSystem) else str(system)
    return _same_system_code_names(value)


class ClassificationDecision(BaseModel):
    """A decision in exactly one code-system namespace."""

    model_config = ConfigDict(extra="forbid")

    target_id: str
    code_system: ClassificationSystem
    candidate_codes: list[str] = Field(default_factory=list)
    selected_code: str = ""
    decision_mode: str = "human"
    evidence_refs: list[str] = []
    rationale: str = ""
    status: Literal["unresolved", "resolved"] = "unresolved"

    @model_validator(mode="after")
    def validate_closed_set(self) -> "ClassificationDecision":
        system = self.code_system.value
        names = _same_system_code_names(system)
        if names is None:
            raise ValueError(f"no authoritative dictionary for classification system: {system}")
        invalid = sorted(set(self.candidate_codes) - set(names))
        if invalid:
            raise ValueError(
                f"candidate_codes are not valid in system {system!r}: {invalid}"
            )
        if self.status == "resolved":
            if self.code_system == ClassificationSystem.UNKNOWN:
                raise ValueError("resolved decision cannot use unknown code system")
            if not self.candidate_codes:
                raise ValueError("resolved classification decision requires candidate_codes")
            if self.selected_code not in set(self.candidate_codes):
                raise ValueError("selected_code must be one of candidate_codes")
            if not self.evidence_refs:
                raise ValueError("resolved classification decision requires evidence_refs")
        elif self.selected_code:
            raise ValueError("unresolved classification decision cannot select a code")
        return self


__all__ = [
    "ClassificationSystem",
    "ClassificationStatus",
    "ClassificationRef",
    "ClassificationDecision",
    "classification_code_names",
]
