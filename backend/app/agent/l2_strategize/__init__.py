"""L2 STRATEGIZE subgraph (placeholder).

L2 dimension analysis currently shares the implementation in
app.agent.l1_observe.analysis_node until the L2 subgraph is split per
docs/architecture/agent-graph.md §5. Do not add new L1-specific logic here.
"""
from app.agent.l1_observe.analysis_node import analyze_dimension, DIMENSION_NAMES

__all__ = ["analyze_dimension", "DIMENSION_NAMES"]
