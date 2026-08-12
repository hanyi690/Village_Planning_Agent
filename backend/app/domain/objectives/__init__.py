"""L2 STRATEGIZE subgraph - independent worker.

L2 strategy analysis has its own worker (analyze_l2_dimension), its own
L2_STRATEGY compilation profile, aggregate, G2 gate, and review package.
It shares infrastructure (app.infrastructure.llm.dimension_runtime) with L1 but does
NOT import app.domain.assessment.analysis_node.
"""
from .worker import analyze_l2_dimension

__all__ = ["analyze_l2_dimension"]
