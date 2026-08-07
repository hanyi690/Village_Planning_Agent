"""
FilesystemArtifactStore - file-backed storage for pipeline artifacts.

Layout (per review: artifacts and reviews are separated under one run):
    {base_dir}/{run_id}/artifacts/{module}/{artifact_id}/{revision}/manifest.json
    {base_dir}/{run_id}/artifacts/{module}/{artifact_id}/{revision}/payload.json

- ``manifest.json`` holds the full envelope: artifact_id, module, run_id,
  artifact_type, context_version, revision, created_at, checksum, byte size.
- ``payload.json`` holds the business payload.
- Writes are atomic: payload is written to a temp file, fsynced, then renamed;
  the manifest is written last as the commit point.
- Path identifiers (run_id/module/artifact_id/revision) are constrained to
  ``[A-Za-z0-9._-]`` to prevent traversal.
- ``list_by_run`` / ``list_by_module`` reconstruct ``ArtifactRef`` with full
  envelope metadata (context_version / artifact_type / revision preserved).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from app.modules.ports.artifact_store import ArtifactRef
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MANIFEST = "manifest.json"
_PAYLOAD = "payload.json"
_REVISION_FILE = "revision.json"


def _validate_id(value: str, label: str) -> str:
    # must start with an alnum char and contain only safe chars -> no "..",
    # no leading ".", no empty, no "/" or "\".
    if not value or not _SAFE_ID.match(value) or ".." in value:
        raise ValueError(f"unsafe {label} identifier: {value!r}")
    return value


def _sha256(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class FilesystemArtifactStore:
    """Store/retrieve versioned pipeline artifacts as JSON files under a base dir."""

    def __init__(self, base_dir: str | Path = ".run-tmp"):
        self.base_dir = Path(base_dir)

    # ── paths ──────────────────────────────────────────────────────────

    def _artifact_dir(self, ref: ArtifactRef) -> Path:
        _validate_id(ref.run_id, "run_id")
        _validate_id(ref.module, "module")
        _validate_id(ref.artifact_id, "artifact_id")
        _validate_id(ref.revision, "revision")
        return (
            self.base_dir
            / ref.run_id
            / "artifacts"
            / ref.module
            / ref.artifact_id
            / ref.revision
        )

    def _revision_index_path(self, ref: ArtifactRef) -> Path:
        _validate_id(ref.run_id, "run_id")
        _validate_id(ref.module, "module")
        _validate_id(ref.artifact_id, "artifact_id")
        return (
            self.base_dir / ref.run_id / "artifacts" / ref.module / ref.artifact_id / _REVISION_FILE
        )

    # ── write ─────────────────────────────────────────────────────────

    def store(self, ref: ArtifactRef, payload: dict[str, Any]) -> ArtifactRef:
        d = self._artifact_dir(ref)
        d.mkdir(parents=True, exist_ok=True)
        # Canonical serialization makes replay checksum validation stable
        # across process/order differences.
        payload_bytes = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        checksum = hashlib.sha256(payload_bytes).hexdigest()

        # atomic payload write: temp file in same dir -> rename
        fd, tmp = tempfile.mkstemp(dir=str(d), suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload_bytes)
            os.replace(tmp, d / _PAYLOAD)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

        manifest = {
            "artifact_id": ref.artifact_id,
            "module": ref.module,
            "run_id": ref.run_id,
            "artifact_type": ref.artifact_type,
            "context_version": ref.context_version,
            "revision": ref.revision,
            "created_at": ref.stored_at.isoformat(),
            "checksum": checksum,
            "payload_bytes": len(payload_bytes),
        }
        self._atomic_write_json(d / _MANIFEST, manifest)

        # update revision index (latest revision pointer)
        self._atomic_write_json(
            self._revision_index_path(ref),
            {"artifact_id": ref.artifact_id, "latest_revision": ref.revision},
        )
        logger.debug(
            "[ArtifactStore] Stored %s/%s/%s@%s",
            ref.run_id, ref.module, ref.artifact_id, ref.revision,
        )
        return ref

    def _atomic_write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    # ── read ──────────────────────────────────────────────────────────

    def retrieve(self, ref: ArtifactRef) -> dict[str, Any]:
        d = self._artifact_dir(ref)
        payload = d / _PAYLOAD
        if not payload.exists():
            raise FileNotFoundError(f"artifact not found: {payload}")
        with payload.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def read_manifest(self, ref: ArtifactRef) -> dict[str, Any]:
        d = self._artifact_dir(ref)
        manifest = d / _MANIFEST
        if not manifest.exists():
            raise FileNotFoundError(f"manifest not found: {manifest}")
        with manifest.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def delete(self, ref: ArtifactRef) -> None:
        d = self._artifact_dir(ref)
        if d.exists():
            import shutil

            shutil.rmtree(d)

    # ── list ──────────────────────────────────────────────────────────

    def _ref_from_manifest(self, manifest: dict[str, Any], run_id: str, module: str) -> ArtifactRef:
        return ArtifactRef(
            context_version=str(manifest.get("context_version", "")),
            artifact_id=str(manifest.get("artifact_id", "")),
            module=module,
            run_id=run_id,
            artifact_type=str(manifest.get("artifact_type", "")),
            revision=str(manifest.get("revision", "v1")),
        )

    def list_by_run(self, run_id: str) -> list[ArtifactRef]:
        _validate_id(run_id, "run_id")
        refs: list[ArtifactRef] = []
        artifacts_dir = self.base_dir / run_id / "artifacts"
        if not artifacts_dir.exists():
            return refs
        for module_dir in sorted(artifacts_dir.iterdir()):
            if not module_dir.is_dir():
                continue
            for artifact_dir in sorted(module_dir.iterdir()):
                if not artifact_dir.is_dir():
                    continue
                ref = self._latest_in(module_dir, artifact_dir, run_id, module_dir.name)
                if ref:
                    refs.append(ref)
        return refs

    def list_by_module(self, module: str, run_id: str | None = None) -> list[ArtifactRef]:
        _validate_id(module, "module")
        refs: list[ArtifactRef] = []
        runs = [run_id] if run_id is not None else self._runs()
        for rid in runs:
            if not rid:
                continue
            module_dir = self.base_dir / rid / "artifacts" / module
            if not module_dir.exists():
                continue
            for artifact_dir in sorted(module_dir.iterdir()):
                if not artifact_dir.is_dir():
                    continue
                ref = self._latest_in(module_dir, artifact_dir, rid, module)
                if ref:
                    refs.append(ref)
        return refs

    def _latest_in(
        self, module_dir: Path, artifact_dir: Path, run_id: str, module: str
    ) -> ArtifactRef | None:
        revs = [d for d in artifact_dir.iterdir() if d.is_dir() and d.name != "__pycache__"]
        if not revs:
            return None
        revs.sort(key=lambda p: p.name)
        latest = revs[-1]
        manifest_path = latest / _MANIFEST
        if manifest_path.exists():
            try:
                with manifest_path.open("r", encoding="utf-8") as fh:
                    manifest = json.load(fh)
                return self._ref_from_manifest(manifest, run_id, module)
            except (json.JSONDecodeError, KeyError):
                pass
        return ArtifactRef(
            context_version="",
            artifact_id=artifact_dir.name,
            module=module,
            run_id=run_id,
            artifact_type="",
            revision=latest.name,
        )

    def _runs(self) -> list[str]:
        if not self.base_dir.exists():
            return []
        return [d.name for d in sorted(self.base_dir.iterdir()) if d.is_dir()]


__all__ = ["FilesystemArtifactStore"]
