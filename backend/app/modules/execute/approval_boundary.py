"""Approval and candidate-lineage boundary entry points."""

from .execution_boundaries import (
    candidate_geometry_drift_diagnostics,
    classification_boundary_diagnostics,
)

__all__ = ["candidate_geometry_drift_diagnostics", "classification_boundary_diagnostics"]
