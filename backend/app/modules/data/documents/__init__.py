"""Documents subpackage - non-spatial document loading.

Provides loaders for planning markdown and L3 reports. Complements the
document DataSourceDriver (low-level file access via Catalog) with
parsed/structured output.
"""

from __future__ import annotations

from .loader import (
    L3_BASELINE_PATH,
    L3_REPORT_PATH,
    list_available_documents,
    load_l3_reports,
    load_planning_text,
)

__all__ = [
    "load_l3_reports",
    "load_planning_text",
    "list_available_documents",
    "L3_REPORT_PATH",
    "L3_BASELINE_PATH",
]
