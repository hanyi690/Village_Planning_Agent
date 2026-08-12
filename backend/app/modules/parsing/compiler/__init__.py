"""Shared report compiler - text report -> typed stage fragments.

The compiler serves only L1/L2 report projection. L3 claims are produced by
the L3 worker and target projection consumes the resulting PlanningProgram.
"""
from __future__ import annotations

from app.modules.schema.contracts.parsing_contracts import CompilationProfile

from .core import compile_dimension_report

__all__ = ["CompilationProfile", "compile_dimension_report"]
