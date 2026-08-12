"""Provider-neutral protocols for evidence and validation adapters."""

from .adjustment import AdjustmentExecutionResult, ValidationAdjustmentExecutor
from .external_search import ExternalSearchPort
from .media_evidence import MediaEvidencePort, VisualEvidencePort

__all__ = [
    "AdjustmentExecutionResult",
    "ExternalSearchPort",
    "MediaEvidencePort",
    "ValidationAdjustmentExecutor",
    "VisualEvidencePort",
]
