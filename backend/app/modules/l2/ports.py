"""L2 ports for typed upstream facts and downstream planning consumers."""

from __future__ import annotations

from typing import Protocol

from app.contracts.l1.l1_contracts import L1Snapshot
from app.contracts.l2.l2_contracts import L2Strategy


class L1SnapshotPort(Protocol):
    def load(self) -> L1Snapshot | None: ...


class L2DecisionConsumerPort(Protocol):
    def consume(self, decision_set: L2Strategy) -> None: ...


__all__ = ["L1SnapshotPort", "L2DecisionConsumerPort"]
