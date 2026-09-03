"""Shared trace contract for typed parsing and projection stages."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CompilerTrace(BaseModel):
    """Execution trace for a typed stage projection."""

    profile: str = ""
    steps: list[str] = Field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""


__all__ = ["CompilerTrace"]
