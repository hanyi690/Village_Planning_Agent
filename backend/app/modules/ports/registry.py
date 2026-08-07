"""Neutral dependency registry for module defaults.

The composition root registers concrete adapters here at boot. Modules read
the registered default through this lightweight registry instead of importing
``app.services`` directly, preserving the ``modules -> services`` dependency
direction while still allowing explicit per-call overrides.
"""

from __future__ import annotations

from typing import Any, Optional

_report_store_default: Optional[Any] = None
_context_reader_default: Optional[Any] = None


def set_report_store_default(store: Any) -> None:
    global _report_store_default
    _report_store_default = store


def get_report_store_default() -> Optional[Any]:
    return _report_store_default


def set_context_reader_default(reader: Any) -> None:
    global _context_reader_default
    _context_reader_default = reader


def get_context_reader_default() -> Optional[Any]:
    return _context_reader_default


__all__ = [
    "set_report_store_default",
    "get_report_store_default",
    "set_context_reader_default",
    "get_context_reader_default",
]