"""Candidate-only selection boundary used by simulated/real LLM adapters."""

from __future__ import annotations

from dataclasses import dataclass

from app.contracts.evidence.evidence_packet_contracts import EvidencePacket
from app.contracts.evidence.feature_identity_contracts import FeatureEvidenceRef


class CandidateSelectionError(ValueError):
    """Raised when a model selects an identity outside the evidence packet."""


def select_packet_candidate(
    packet: EvidencePacket,
    candidate_ref: str,
) -> FeatureEvidenceRef:
    """Return one supplied candidate; never parse or manufacture a BSM."""
    requested = str(candidate_ref or "").strip()
    for candidate in packet.candidate_refs:
        refs = {
            str(candidate.identity.source_feature_id),
            str(candidate.resource_ref),
            str(candidate.geometry_ref or ""),
            *[str(ref) for ref in candidate.entity_refs],
        }
        if requested in refs:
            return candidate
    raise CandidateSelectionError(
        f"candidate '{requested}' is not present in the EvidencePacket"
    )


@dataclass(frozen=True)
class SimulatedEvidenceLLM:
    """Small deterministic adapter for vertical-slice tests."""

    selected_ref: str

    def choose(self, packet: EvidencePacket) -> FeatureEvidenceRef:
        return select_packet_candidate(packet, self.selected_ref)


__all__ = [
    "CandidateSelectionError",
    "SimulatedEvidenceLLM",
    "select_packet_candidate",
]
