"""Provider-neutral protocols for evidence and validation adapters."""

from .adjustment import AdjustmentExecutionResult, ValidationAdjustmentExecutor
from .context import PlanningContextProvider
from .external_search import ExternalSearchPort
from .media_evidence import MediaEvidencePort, VisualEvidencePort
from .place_evidence import PlaceEvidenceIndex
from .spatial import SpatialQueryPort
from .workers import WorkerInput, WorkerResult

__all__ = [
    "AdjustmentExecutionResult",
    "ExternalSearchPort",
    "MediaEvidencePort",
    "PlaceEvidenceIndex",
    "PlanningContextProvider",
    "SpatialQueryPort",
    "ValidationAdjustmentExecutor",
    "VisualEvidencePort",
    "WorkerInput",
    "WorkerResult",
]
