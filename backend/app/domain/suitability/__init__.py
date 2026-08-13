"""Suitability contracts and grounding-to-suitability projection."""

from .model import SuitabilityCandidate, SuitabilitySurface
from .candidate_features import (
    CandidateSuitabilityFeatures,
    EvidenceAvailabilityDiagnostic,
    SuitabilityEvidenceAvailability,
    TerrainCandidateFeatures,
)
from .policy import (
    FactorAvailabilityPolicy,
    SuitabilityFactorPolicies,
    VersionedSuitabilityPolicy,
    load_suitability_policy,
)
from .service import build_suitability_surface
from .terrain import assess_terrain_suitability
from .terrain_adapter import (
    TerrainCandidateFeatureAdapter,
    audit_suitability_evidence_availability,
)

__all__ = [
    "SuitabilityCandidate",
    "SuitabilitySurface",
    "CandidateSuitabilityFeatures",
    "EvidenceAvailabilityDiagnostic",
    "FactorAvailabilityPolicy",
    "SuitabilityEvidenceAvailability",
    "SuitabilityFactorPolicies",
    "TerrainCandidateFeatureAdapter",
    "TerrainCandidateFeatures",
    "VersionedSuitabilityPolicy",
    "load_suitability_policy",
    "assess_terrain_suitability",
    "audit_suitability_evidence_availability",
    "build_suitability_surface",
]
