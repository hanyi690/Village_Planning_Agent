"""Compatibility import for report-to-KG entity enrichment.

Use ``report_entity_enrichment`` for new imports.  This module remains for
existing integrations that still import the historical path.
"""

from . import report_entity_enrichment as _implementation
from .report_entity_enrichment import *  # noqa: F403

_get_semantic_memory = _implementation._get_semantic_memory


async def extract_bindings(*args, **kwargs):
    """Run the canonical implementation with legacy dependency injection."""
    _implementation._get_semantic_memory = _get_semantic_memory
    return await _implementation.extract_bindings(*args, **kwargs)


async def run_wave(*args, **kwargs):
    """Compatibility wrapper for the report-enrichment wave entry point."""
    _implementation._get_semantic_memory = _get_semantic_memory
    return await _implementation.run_wave(*args, **kwargs)


def __getattr__(name: str):
    """Forward legacy access, including private test and integration helpers."""
    return getattr(_implementation, name)
