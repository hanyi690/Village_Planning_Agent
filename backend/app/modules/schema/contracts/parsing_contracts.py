"""Shared parse-compiler contracts - profile enum + compiler trace."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class CompilationProfile(str, Enum):
    """Stage-specific compilation profile for the shared parse-compiler.

    L1_OBSERVATION and L2_STRATEGY are the only report projection profiles.
    """

    L1_OBSERVATION = "l1_observation"
    L2_STRATEGY = "l2_strategy"


class CompilerTrace(BaseModel):
    """Execution trace of one compile_dimension_report call."""

    profile: CompilationProfile = CompilationProfile.L1_OBSERVATION
    steps: list[str] = Field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""


__all__ = ["CompilationProfile", "CompilerTrace"]
