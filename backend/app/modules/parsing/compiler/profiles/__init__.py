"""Stage-specific compilation profiles for the shared parse-compiler.

Wave B: l1_observation. Wave F: l3_planning, revision.
"""
from __future__ import annotations

from .l1_observation import compile_l1_observation

__all__ = ["compile_l1_observation"]
