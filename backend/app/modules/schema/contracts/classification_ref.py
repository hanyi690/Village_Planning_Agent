from __future__ import annotations

from pydantic import BaseModel, field_validator


class ClassificationRef(BaseModel):
    system: str  # e.g. "gbt21010" | "ghytbm" | "vne" | "planning_zones" | "unknown"
    code: str
    canonical_name: str
    source: str  # "ingested" | "user_provided" | "preserve" | "derived"

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        allowed = {"ingested", "user_provided", "preserve", "derived"}
        if v not in allowed:
            raise ValueError(f"source must be one of {allowed}, got {v}")
        return v
