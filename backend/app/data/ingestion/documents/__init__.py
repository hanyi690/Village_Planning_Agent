"""Documents subpackage for explicitly configured legacy report fixtures.

Session-owned raw inputs are resolved by the session catalog; this package
does not scan repository planning documents.
"""

from __future__ import annotations

from .loader import (
    L3_BASELINE_PATH,
    L3_REPORT_PATH,
    load_l3_reports,
)

__all__ = [
    "load_l3_reports",
    "L3_REPORT_PATH",
    "L3_BASELINE_PATH",
]
