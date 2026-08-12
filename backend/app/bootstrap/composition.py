"""Composition root for the village planning backend.

The canonical implementation currently lives in ``app.services.composition``;
this module is the blueprint-level ``bootstrap/`` home and re-exports the same
singleton so ``app.main`` and tests can import a stable, single entry point.
"""

from __future__ import annotations

from app.services.composition import CompositionRoot

__all__ = ["CompositionRoot"]
