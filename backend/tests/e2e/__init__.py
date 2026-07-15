"""E2E tests — full pipeline on real Jin Tian data, no mocking.

23 tests covering:
  - Pipeline API (11): 8-step pipeline via /api/dev/gis/layout
  - Constraint Values (5): 3 hard constraints + area + conflict detection
  - Layout Validate API (2): /validate (validation_type=layout)
  - Constraint Validator API (1): /validate (validation_type=constraint)
  - Spatial Layout API (1): /layout endpoint
  - Jin Tian Data API (2): /files + /files/{path} endpoints
  - Landuse Change API (1): /layout (include_landuse_change=true)

NOTE: Pipeline API tests use engine fallback when endpoint returns
non-JSON-serializable floats (inf/nan from MIP solver).

Run: pytest tests/e2e/ -v
"""
