"""Cognition-facing port aliases.

Only the bounded current-world read port and the write boundary are exposed
from this module. The legacy whole-graph protocol remains an infrastructure
internal for deferred projection/identity work and is deliberately not
re-exported as a cognition capability.
"""

from app.contracts.ports.world_model import (
    CurrentWorldQueryPort,
    WorldModelCommitPort,
)

__all__ = ["CurrentWorldQueryPort", "WorldModelCommitPort"]
