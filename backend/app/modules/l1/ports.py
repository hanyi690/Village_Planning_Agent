"""Ports owned by the L1 stage.

The workflow passes a control-plane mapping into the application facade.  The
facade owns the typed result; the port keeps the current aggregate adapter
replaceable while the old implementation is moved into this module.
"""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from typing import Any, Protocol


class L1AggregatePort(Protocol):
    """Produce and persist one L1 artifact from a frozen workflow state."""

    async def aggregate(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return a state patch containing typed L1 artifact references."""


class L1ObservationSnapshotLoaderPort(Protocol):
    """Reload an L1 artifact by its workflow reference."""

    def load(self, state: Mapping[str, Any]) -> Any:
        """Return a validated ``L1ObservationSnapshot`` or ``None``."""


__all__ = ["L1AggregatePort", "L1ObservationSnapshotLoaderPort"]
