from __future__ import annotations

from typing import Any, Protocol

from app.modules.schema.contracts.contract_meta import ContractMeta


class ArtifactRef(ContractMeta):
    module: str
    run_id: str
    artifact_type: str


class ArtifactStorePort(Protocol):
    def store(self, ref: ArtifactRef, payload: dict[str, Any]) -> None: ...
    def retrieve(self, ref: ArtifactRef) -> dict[str, Any]: ...
    def list_by_run(self, run_id: str) -> list[ArtifactRef]: ...
    def list_by_module(self, module: str, run_id: str | None = None) -> list[ArtifactRef]: ...
