"""pytest configuration shared across all tests under tests/."""

# Shared DB + pipeline-state fixtures (see tests/fixtures/db.py).
pytest_plugins = ["tests.fixtures.db"]

# Fixtures previously re-exported from tests.fixtures.gis_e2e were removed
# during the V4 audit (schema-promotion refactor made them unused). Active
# tests define their own local fixtures as needed.
