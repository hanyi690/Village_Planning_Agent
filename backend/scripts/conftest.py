"""Pytest collection guards for backend/scripts.

External-map-provider probe scripts (coord system validation, Tianditu WFS
queries) are run manually with real API keys — `python scripts/test_*.py`.
They are not pytest tests: no assertions, they print results. Excluded from
collection to keep the full-suite run hermetic.
"""

collect_ignore = [
    "test_coord_system_validation.py",
    "test_tianditu_vector_query.py",
]
