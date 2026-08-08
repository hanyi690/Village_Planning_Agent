from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from pydantic import Field

from app.modules.schema.contracts.contract_meta import ContractMeta


class ArtifactRef(ContractMeta):
    """Reference to a stored artifact.

    Carries the full envelope metadata so list operations round-trip
    ``context_version`` / ``context_fingerprint`` / ``artifact_type`` /
    ``revision`` / ``checksum`` faithfully.
    """

    module: str
    run_id: str
    artifact_type: str = ""
    revision: str = "v1"
    checksum: str = ""
    stored_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"ArtifactRef({self.run_id}/{self.module}/{self.artifact_id}@{self.revision})"


class ArtifactStorePort(Protocol):
    """Dependency-inversion port for persisting pipeline artifacts.

    Implementations must:
    - persist a full envelope (manifest) + payload per artifact revision;
    - be atomic per write (no partial file on failure);
    - constrain path identifiers (run_id/module/artifact_id) to safe tokens;
    - preserve ``context_version``, ``context_fingerprint``, ``artifact_type``,
      ``revision`` and ``checksum`` on list.
    """

    def store(self, ref: ArtifactRef, payload: dict[str, Any]) -> ArtifactRef: ...
    def retrieve(self, ref: ArtifactRef) -> dict[str, Any]: ...
    def list_by_run(self, run_id: str) -> list[ArtifactRef]: ...
    def list_by_module(self, module: str, run_id: str | None = None) -> list[ArtifactRef]: ...
    def delete(self, ref: ArtifactRef) -> None: ...
