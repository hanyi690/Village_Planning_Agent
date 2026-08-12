"""Immutable artifact descriptor contracts.

Descriptors identify a content-addressed blob and the stage provenance that
made that blob part of a planning run.  They deliberately contain no revision
number and no filesystem path.

The canonical implementation is ``ArtifactRef`` in
``app.contracts.artifacts.ref``; this module keeps the historical import path
as a compatibility alias so persisted CAS payloads and existing runtime
callers validate through the single canonical class.
"""

from __future__ import annotations

from app.contracts.artifacts.ref import ArtifactRef as ArtifactDescriptor

__all__ = ["ArtifactDescriptor"]