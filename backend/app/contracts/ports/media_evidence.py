"""Media storage and typed visual extraction protocols."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.infrastructure.evidence_runtime.model import (
    ImageArtifact,
    ImageEvidence,
    ImageIngestRequest,
    VisualAnalysisRequest,
)


@runtime_checkable
class MediaEvidencePort(Protocol):
    """Store media and return its immutable metadata artifact."""

    async def ingest(self, request: ImageIngestRequest) -> ImageArtifact:
        """Register media without exposing bytes to workflow state."""
        ...


@runtime_checkable
class VisualEvidencePort(Protocol):
    """Extract typed visual evidence from a stored image artifact."""

    async def analyze(
        self,
        artifact_ref: str,
        request: VisualAnalysisRequest,
    ) -> ImageEvidence:
        """Return visual evidence or a typed unresolved ImageEvidence."""
        ...


__all__ = ["MediaEvidencePort", "VisualEvidencePort"]
