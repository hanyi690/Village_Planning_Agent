"""L3 PLAN subgraph - independent worker.

L3 detail planning has its own worker (analyze_l3_dimension), its own
L3_PLANNING compilation profile, aggregate, G3 gate, and review package.
It shares infrastructure (app.agent.common.dimension_runtime) with L1/L2 but
does NOT reference the L1 analysis node implementation.
"""
from .worker import analyze_l3_dimension

__all__ = ["analyze_l3_dimension"]
