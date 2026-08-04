"""Context reference contracts — dataset snapshot refs and run context."""

from __future__ import annotations

from pydantic import BaseModel

from .contract_meta import ContractMeta


class DatasetRef(BaseModel):
    dataset_id: str
    source: str
    version: str
    layer_type: str = ""


class ContextVersion(BaseModel):
    version: str
    snapshot_artifact_id: str
    parent_version: str | None = None


class PlanningContextRef(ContractMeta):
    run_id: str
    village_name: str
    dataset_refs: list[DatasetRef] = []
    context_version: str = ""


__all__ = [
    "DatasetRef",
    "ContextVersion",
    "PlanningContextRef",
]
