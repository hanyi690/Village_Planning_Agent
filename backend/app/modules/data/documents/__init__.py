"""Documents subpackage - non-spatial document loading and intent caching.

Provides high-level loaders for planning markdown and L3 reports, plus
intent caching with parse-factor-aware invalidation. Complements the
document DataSourceDriver (low-level file access via Catalog) with
parsed/structured output.

LLM/intent parsing logic remains in gis.data.loader (and tools/gis.parse)
pending full migration; this module bridges to it via legacy helpers.
"""

from __future__ import annotations

from .intent_cache import (
    INTENT_CACHE_DIR,
    PARSE_VERSION,
    get_cached_intent,
    list_cached_intents,
    resolve_gen_intent_cached,
    resolve_intent_live,
    resolve_plan_intent_cached,
    save_cached_intent,
)
from .loader import (
    L3_BASELINE_PATH,
    L3_REPORT_PATH,
    list_available_documents,
    load_l3_reports,
    load_planning_text,
)

__all__ = [
    # Loaders
    "load_l3_reports",
    "load_planning_text",
    "list_available_documents",
    "L3_REPORT_PATH",
    "L3_BASELINE_PATH",
    # Intent cache
    "INTENT_CACHE_DIR",
    "PARSE_VERSION",
    "get_cached_intent",
    "save_cached_intent",
    "list_cached_intents",
    "resolve_gen_intent_cached",
    "resolve_plan_intent_cached",
    "resolve_intent_live",
]
