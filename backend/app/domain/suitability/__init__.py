"""Suitability contracts and grounding-to-suitability projection."""

from .model import SuitabilityCandidate, SuitabilitySurface
from .service import build_suitability_surface

__all__ = ["SuitabilityCandidate", "SuitabilitySurface", "build_suitability_surface"]
