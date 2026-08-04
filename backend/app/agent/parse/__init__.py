"""PARSE subgraph - deterministic compile/repair/revise pipeline.

Wave F: PARSE is being refactored into its own independent subgraph under
app.agent.parse. The bridge layer (app.agent.select.parse_agent) is NOT used
here to keep this subgraph isolated.
"""
__all__ = []
