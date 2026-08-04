"""Shared parse-compiler contracts - profile enum + compiler trace."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class CompilationProfile(str, Enum):
    """Stage-specific compilation profile for the shared parse-compiler.

    Wave B delivers L1_OBSERVATION. L3_PLANNING and REVISION are Wave F.
    """

    L1_OBSERVATION = "l1_observation"
    L3_PLANNING = "l3_planning"
    REVISION = "revision"


class CompilerTrace(BaseModel):
    """Execution trace of one compile_dimension_report call."""

    profile: CompilationProfile = CompilationProfile.L1_OBSERVATION
    steps: list[str] = Field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""


__all__ = ["CompilationProfile", "CompilerTrace"]
