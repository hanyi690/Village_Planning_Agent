"""Validated World Model change-set contracts."""

from __future__ import annotations

from typing import Literal

from app.contracts.base import StrictContractModel


class WorldModelChange(StrictContractModel):
    operation: Literal["assert", "upsert_entity", "upsert_part", "upsert_representation", "planned"]
    subject_ref: str
    predicate: str = ""
    object_ref: str = ""
    value: str = ""
    source_refs: tuple[str, ...] = ()
    representation_ref: str = ""


class WorldModelChangeSet(StrictContractModel):
    changeset_ref: str
    parent_snapshot_ref: str = ""
    source_snapshot_ref: str = ""
    changes: tuple[WorldModelChange, ...] = ()

    @property
    def change_count(self) -> int:
        return len(self.changes)


__all__ = ["WorldModelChange", "WorldModelChangeSet"]
