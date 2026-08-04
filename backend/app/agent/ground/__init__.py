"""GROUND subgraph package - thin orchestrator over SpatialResolver."""

from .aggregate import build_candidate_site, ground_aggregate
from .gate import evaluate_ground_gate, ground_gate_route

__all__ = [
    "ground_aggregate",
    "build_candidate_site",
    "evaluate_ground_gate",
    "ground_gate_route",
]
