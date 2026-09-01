"""Compatibility import for the DATA-owned dead-letter contracts."""

from app.contracts.data.dlq import DlqCategory, DlqEntry, DlqReport

__all__ = ["DlqCategory", "DlqEntry", "DlqReport"]
