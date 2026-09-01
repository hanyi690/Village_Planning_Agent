"""Legacy identity adapters isolated from the GROUND business module.

These imports are intentionally confined to the compatibility infrastructure;
the generic World Model path never calls them.
"""

from app.infrastructure.evidence_runtime.evidence_graph import (
    EvidenceGraph,
    _kg_relations,
    feature_ref_from_candidate,
    geometry_refs_from_evidence_packet,
)
from app.infrastructure.evidence_runtime.identity.binding_store import BindingStore
from app.infrastructure.evidence_runtime.identity.observation_store import ObservationStore

__all__ = [
    "BindingStore",
    "EvidenceGraph",
    "ObservationStore",
    "_kg_relations",
    "feature_ref_from_candidate",
    "geometry_refs_from_evidence_packet",
]
