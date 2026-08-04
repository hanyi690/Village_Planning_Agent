"""
FilesystemArtifactStore - file-backed storage for pipeline artifacts.

Layout: {base_dir}/{run_id}/{module}/{artifact_id}.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.modules.ports.artifact_store import ArtifactRef
from app.utils.logger import get_logger

logger = get_logger(__name__)


class FilesystemArtifactStore:
    """Store/retrieve pipeline artifacts as JSON files under a base dir."""

    def __init__(self, base_dir: str | Path = ".run-tmp"):
        self.base_dir = Path(base_dir)

    def _path(self, ref: ArtifactRef) -> Path:
        return self.base_dir / ref.run_id / ref.module / f"{ref.artifact_id}.json"

    def store(self, ref: ArtifactRef, payload: dict[str, Any]) -> None:
        path = self._path(ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        logger.debug("[ArtifactStore] Stored %s/%s/%s", ref.run_id, ref.module, ref.artifact_id)

    def retrieve(self, ref: ArtifactRef) -> dict[str, Any]:
        path = self._path(ref)
        if not path.exists():
            raise FileNotFoundError(f"artifact not found: {path}")
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def list_by_run(self, run_id: str) -> list[ArtifactRef]:
        refs: list[ArtifactRef] = []
        run_dir = self.base_dir / run_id
        if not run_dir.exists():
            return refs
        for json_file in sorted(run_dir.glob("*/*.json")):
            refs.append(
                ArtifactRef(
                    context_version="",
                    artifact_id=json_file.stem,
                    module=json_file.parent.name,
                    run_id=run_id,
                    artifact_type="artifact",
                )
            )
        return refs

    def list_by_module(self, module: str, run_id: str | None = None) -> list[ArtifactRef]:
        refs: list[ArtifactRef] = []
        if run_id is not None:
            module_dir = self.base_dir / run_id / module
            if module_dir.exists():
                for json_file in sorted(module_dir.glob("*.json")):
                    refs.append(
                        ArtifactRef(
                            context_version="",
                            artifact_id=json_file.stem,
                            module=module,
                            run_id=run_id,
                            artifact_type="artifact",
                        )
                    )
            return refs
        if not self.base_dir.exists():
            return refs
        for run_dir in sorted(self.base_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            module_dir = run_dir / module
            if not module_dir.is_dir():
                continue
            for json_file in sorted(module_dir.glob("*.json")):
                refs.append(
                    ArtifactRef(
                        context_version="",
                        artifact_id=json_file.stem,
                        module=module,
                        run_id=run_dir.name,
                        artifact_type="artifact",
                    )
                )
        return refs


__all__ = ["FilesystemArtifactStore"]
