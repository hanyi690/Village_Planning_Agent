"""Unit tests — pure logic, no external services, no file I/O beyond temp dirs.

32 tests covering:
  - Planning Zone Mapper (8): forward/reverse mapping, remap, consistency
  - Layout Validator (12): 8 validation checks + report status + retry
  - Data Loader (5): loading, intent computation, params, fallback
  - Intent Cache (4): cache key, roundtrip, corruption handling
  - Metrics Calculator (3): land use metrics, distribution, unit conversion

Run: pytest tests/unit/ -v
"""
