"""E2E tests — full pipeline on real Jin Tian data, no mocking.

23 tests covering:
  - Pipeline API (11): 8-step pipeline via /api/dev/gis/jintian/pipeline
  - Constraint Values (5): 3 hard constraints + area + conflict detection
  - Layout Validate API (2): /layout-validate endpoint
  - Constraint Validator API (1): /constraint-validator endpoint
  - Spatial Layout API (1): /spatial-layout endpoint
  - Jin Tian Data API (2): /jintian/files + /jintian/data endpoints
  - Landuse Change API (1): /landuse-change endpoint

NOTE: Pipeline API tests use engine fallback when endpoint returns
non-JSON-serializable floats (inf/nan from MIP solver).

Run: pytest tests/e2e/ -v
"""
