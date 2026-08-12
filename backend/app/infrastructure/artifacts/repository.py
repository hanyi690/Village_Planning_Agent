"""Filesystem CAS repository for immutable planning artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.modules.schema.contracts.artifact_descriptor import ArtifactDescriptor
from app.services.artifact_fingerprint import semantic_checksum


class NamedRefConflict(RuntimeError):
    """The caller tried to update a named ref from a stale descriptor."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _token(value: str, field: str) -> str:
    if not value or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in value):
        raise ValueError(f"unsafe {field}: {value!r}")
    if ".." in value:
        raise ValueError(f"unsafe {field}: {value!r}")
    return value


class ContentAddressedArtifactRepository:
    """Persist immutable blobs and branch-scoped mutable named refs.

    Blob and descriptor files are create-if-absent.  Only a named ref changes,
    and it changes through an expected-descriptor compare-and-set operation.
    """

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)

    def put_json(
        self,
        payload: Any,
        *,
        schema_id: str,
        schema_version: str,
        producer_stage: str,
        run_id: str,
        branch_id: str,
        parent_digests: dict[str, str] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> ArtifactDescriptor:
        _token(run_id, "run_id")
        _token(branch_id, "branch_id")
        data = _canonical_json(payload)
        blob_digest = _sha256(data)
        self._create_once(self._blob_path(blob_digest), data)
        descriptor_payload = {
            "digest": blob_digest,
            "media_type": "application/json",
            "size_bytes": len(data),
            "schema_id": schema_id,
            "schema_version": schema_version,
            "semantic_digest": f"sha256:{semantic_checksum(payload)}",
            "parent_digests": dict(sorted((parent_digests or {}).items())),
            "producer_stage": producer_stage,
            "run_id": run_id,
            "branch_id": branch_id,
            "provenance": provenance or {},
        }
        descriptor_digest = _sha256(_canonical_json(descriptor_payload))
        descriptor_path = self._descriptor_path(descriptor_digest)
        if descriptor_path.exists():
            return self.get_descriptor(descriptor_digest)
        descriptor = ArtifactDescriptor(
            **descriptor_payload,
            descriptor_digest=descriptor_digest,
            created_at=datetime.now(timezone.utc),
        )
        self._create_once(
            descriptor_path,
            _canonical_json(descriptor.model_dump(mode="json")),
        )
        return self.get_descriptor(descriptor_digest)

    def get_descriptor(self, descriptor_digest: str) -> ArtifactDescriptor:
        data = self._read_json(self._descriptor_path(descriptor_digest))
        descriptor = ArtifactDescriptor.model_validate(data)
        if descriptor.descriptor_digest != descriptor_digest:
            raise ValueError("descriptor digest does not match descriptor identity")
        return descriptor

    def get_json(self, descriptor: ArtifactDescriptor) -> Any:
        data = self._blob_path(descriptor.digest).read_bytes()
        if _sha256(data) != descriptor.digest:
            raise ValueError("artifact blob checksum mismatch")
        return json.loads(data)

    def get_named_ref(self, run_id: str, branch_id: str, artifact_key: str) -> ArtifactDescriptor | None:
        path = self._named_ref_path(run_id, branch_id, artifact_key)
        if not path.exists():
            return None
        return self.get_descriptor(str(self._read_json(path)["descriptor_digest"]))

    def compare_and_set_named_ref(
        self,
        run_id: str,
        branch_id: str,
        artifact_key: str,
        descriptor: ArtifactDescriptor,
        *,
        expected_descriptor_digest: str | None,
    ) -> None:
        if descriptor.run_id != run_id or descriptor.branch_id != branch_id:
            raise ValueError("named ref and descriptor run/branch must match")
        path = self._named_ref_path(run_id, branch_id, artifact_key)
        lock = path.with_suffix(".lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise NamedRefConflict(f"named ref is being updated: {artifact_key}") from exc
        try:
            os.close(handle)
            current = None
            if path.exists():
                current = str(self._read_json(path).get("descriptor_digest") or "")
            if current != expected_descriptor_digest:
                raise NamedRefConflict(
                    f"stale named ref for {artifact_key}: expected {expected_descriptor_digest!r}, got {current!r}"
                )
            self._replace_file(path, _canonical_json({"descriptor_digest": descriptor.descriptor_digest}))
        finally:
            try:
                lock.unlink()
            except FileNotFoundError:
                pass

    def _blob_path(self, digest: str) -> Path:
        return self.base_dir / "blobs" / "sha256" / digest.removeprefix("sha256:")

    def _descriptor_path(self, digest: str) -> Path:
        return self.base_dir / "descriptors" / f"{digest.removeprefix('sha256:')}.json"

    def _named_ref_path(self, run_id: str, branch_id: str, artifact_key: str) -> Path:
        return self.base_dir / "runs" / _token(run_id, "run_id") / "branches" / _token(branch_id, "branch_id") / "refs" / f"{_token(artifact_key, 'artifact_key')}.json"

    @staticmethod
    def _read_json(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _create_once(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError(f"CAS collision for {path.name}")
            return
        try:
            with os.fdopen(handle, "wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _replace_file(path: Path, data: bytes) -> None:
        handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(handle, "wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


__all__ = ["ContentAddressedArtifactRepository", "NamedRefConflict"]
