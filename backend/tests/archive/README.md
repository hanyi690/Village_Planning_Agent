# Archived Tests

These test files were archived during the Phase 1 Core refactoring (Schema Layer Promotion + KG Reverse Dependency Elimination). They are kept here for reference only.

## Archived Files

- `unit/test_gis_unit.py` — 30 tests for Planning Zone Mapper, Layout Validator, Data Loader, Intent Cache, Metrics Calculator
- `unit/test_parse_agent.py` — 21 tests for Spatial Models, Spatial Context, Parse Tools, Parse Agent Graph
- `integration/test_parse_agent_llm.py` — 5 tests for PARSE agent with LLM + SQLite cache
- `fixtures/gis_shared.py` — Shared test helpers (zone configs, mock adjacency graph)
- `fixtures/gis_e2e.py` — Pytest fixtures (landuse_geojson, boundary_geojson, protection_zones, etc.)

## Replacement Tests

The refactoring introduced focused tests that verify the architectural invariants:
- `unit/test_schema_promotion.py` — Verifies schema layer promotion correctness + backward compat
- `unit/test_kg_no_reverse_deps.py` — Verifies KG has no reverse dependencies on tools/agent
