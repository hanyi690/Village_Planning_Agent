"""Shared parse-compiler - text report -> typed stage fragments.

Wave B delivers core + L1_OBSERVATION profile. L3_PLANNING / REVISION
profiles and the top-level agent/parse stage are Wave F.
"""
from __future__ import annotations

from app.modules.schema.contracts.parsing_contracts import CompilationProfile

from .core import compile_dimension_report

__all__ = ["CompilationProfile", "compile_dimension_report"]
