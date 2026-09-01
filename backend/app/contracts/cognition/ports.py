"""Port aliases for cognition infrastructure.

The application imports the stable ports from ``contracts.ports.world_model``;
these aliases keep cognition contracts discoverable without introducing a
second protocol definition.
"""

from app.contracts.ports.world_model import WorldModelCommitPort, WorldModelPort

__all__ = ["WorldModelCommitPort", "WorldModelPort"]
