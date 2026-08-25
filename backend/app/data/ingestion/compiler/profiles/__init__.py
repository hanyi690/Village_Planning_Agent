"""L1 report projection profile.

L2 and L3 workers persist typed objects directly; neither stage has a prose
semantic compiler.
"""
from __future__ import annotations

from .l1_observation import compile_l1_observation

__all__ = [
    "compile_l1_observation",
]
