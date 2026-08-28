"""Shared report compiler - text report -> typed stage snapshots.

The compiler serves only L1/L2 report projection. L3 claims are produced by
the L3 worker and target projection consumes the resulting PlanningProgram.
"""
from __future__ import annotations

from app.contracts.target_projection.parsing_contracts import CompilationProfile

from .core import compile_dimension_report

__all__ = ["CompilationProfile", "compile_dimension_report"]
