"""Integration tests — multi-module interactions with real data, no LLM.

24 tests covering:
  - Knowledge Graph (4): build, constraints, SPARQL, serialization
  - Conflict Detection (1): detect + resolve on real data
  - Zone Allocation (2): greedy + MIP parameterized
  - Layout Generation (1): multi-layer output
  - Layout Validation (1): 8-check validation on generated layout
  - GIS Data Priority (1): GIS overrides regex
  - Tool Layer (1): build_knowledge_graph + query_knowledge_graph
  - EXPORT step (6): 12-layer output + land balance + field coverage + layout.json
  - RENDER step (3): GISLayerConfig format + base layers
  - Conflict Detailed (4): 3 conflict types + KG→Allocator data flow

Run: pytest tests/integration/ -v
"""
