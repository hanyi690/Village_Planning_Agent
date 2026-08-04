"""GROUND subgraph package - thin orchestrator over SpatialResolver."""

from .aggregate import build_candidate_site, ground_aggregate

__all__ = ["ground_aggregate", "build_candidate_site"]
