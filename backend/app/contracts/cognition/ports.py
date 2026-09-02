"""Cognition-facing port aliases.

Only bounded current-world reads and explicit write capabilities are exposed
from this module. The generic RDF adapter remains an infrastructure detail
for deferred identity/network operations and is not a cognition capability.
"""

from app.contracts.ports.world_model import (
    CognitionCommitPort,
    CurrentWorldQueryPort,
    WorldModelCommitPort,
)

__all__ = [
    "CognitionCommitPort",
    "CurrentWorldQueryPort",
    "WorldModelCommitPort",
]
