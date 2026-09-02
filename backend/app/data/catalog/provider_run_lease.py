"""Cross-process provider-run lease, fencing and publication primitives.

The implementation uses only atomic file creation/replacement so it works in
the Windows development environment as well as POSIX workers.  A lease is
not a lock around a whole provider process: the fencing token is checked
before each write and at publish time, which makes an old worker harmless
after a crash/reclaim.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Iterator, Mapping

from app.contracts.data.provider_run_contracts import ProviderRunLease, ProviderRunRecovery


class ProviderLeaseConflict(RuntimeError):
    """An active lease is owned by another writer."""


class ProviderFenceViolation(RuntimeError):
    """A writer tried to use an expired or superseded fencing token."""


def _now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _safe(value: str) -> str:
    value = str(value or "").strip()
    if not value or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in value):
        raise ValueError("provider lease identity contains unsafe characters")
    return value


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


class ProviderRunLeaseStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.lease_root = self.root / ".leases"
        self.recovery_root = self.root / ".recovery"

    def _path(self, run_ref: str, provider: str) -> Path:
        return self.lease_root / f"{_safe(run_ref)}__{_safe(provider)}.json"

    @contextmanager
    def _locked(self, path: Path) -> Iterator[None]:
        lock = path.with_suffix(path.suffix + ".lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + 5.0
        while True:
            try:
                fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                break
            except FileExistsError:
                try:
                    if time.time() - lock.stat().st_mtime > 30:
                        lock.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise ProviderLeaseConflict(f"lease record is being updated: {path.name}")
                time.sleep(0.01)
        try:
            yield
        finally:
            lock.unlink(missing_ok=True)

    @staticmethod
    def _read(path: Path) -> ProviderRunLease | None:
        if not path.is_file():
            return None
        return ProviderRunLease.model_validate(json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _replace(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(_json_bytes(payload))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
        finally:
            Path(temp_name).unlink(missing_ok=True)

    def acquire(
        self,
        run_ref: str,
        provider: str,
        owner_id: str,
        *,
        ttl_seconds: int = 120,
        now: datetime | None = None,
    ) -> ProviderRunLease:
        if ttl_seconds < 1 or ttl_seconds > 86400:
            raise ValueError("ttl_seconds must be between 1 and 86400")
        path = self._path(run_ref, provider)
        current_time = _now(now)
        with self._locked(path):
            previous = self._read(path)
            if previous is not None and previous.status == "ACTIVE" and previous.expires_at > current_time:
                raise ProviderLeaseConflict(f"active provider lease exists for {run_ref}/{provider}")
            previous_token = previous.fencing_token if previous is not None else 0
            if previous is not None and previous.status == "ACTIVE":
                self._write_recovery(
                    run_ref,
                    provider,
                    {"status": "ABANDONED", "previous_fencing_token": previous_token, "reason": "lease_expired", "at": current_time.isoformat()},
                )
            lease = ProviderRunLease(
                run_ref=_safe(run_ref),
                provider=_safe(provider),
                owner_id=_safe(owner_id),
                fencing_token=previous_token + 1,
                acquired_at=current_time,
                expires_at=current_time + timedelta(seconds=ttl_seconds),
                status="ACTIVE",
            )
            self._replace(path, lease.model_dump(mode="json"))
            return lease

    def renew(self, lease: ProviderRunLease, *, ttl_seconds: int = 120, now: datetime | None = None) -> ProviderRunLease:
        path = self._path(lease.run_ref, lease.provider)
        current_time = _now(now)
        with self._locked(path):
            current = self._read(path)
            self._assert_current(current, lease, current_time)
            renewed = lease.model_copy(update={"expires_at": current_time + timedelta(seconds=ttl_seconds)})
            self._replace(path, renewed.model_dump(mode="json"))
            return renewed

    def release(self, lease: ProviderRunLease, *, now: datetime | None = None) -> None:
        path = self._path(lease.run_ref, lease.provider)
        current_time = _now(now)
        with self._locked(path):
            current = self._read(path)
            self._assert_current(current, lease, current_time, permit_expired=True)
            released = lease.model_copy(update={"status": "RELEASED", "expires_at": current_time})
            self._replace(path, released.model_dump(mode="json"))

    def assert_writer(self, lease: ProviderRunLease, *, now: datetime | None = None) -> None:
        current = self._read(self._path(lease.run_ref, lease.provider))
        self._assert_current(current, lease, _now(now))

    def recover(self, run_ref: str, provider: str, *, now: datetime | None = None) -> ProviderRunRecovery:
        path = self._path(run_ref, provider)
        current_time = _now(now)
        lease = self._read(path)
        if lease is None:
            return ProviderRunRecovery(run_ref=run_ref, provider=provider, status="NOT_FOUND", reason="lease_not_found")
        if lease.status == "ACTIVE" and lease.expires_at > current_time:
            return ProviderRunRecovery(run_ref=run_ref, provider=provider, status="ACTIVE", previous_fencing_token=lease.fencing_token, reason="lease_active")
        staging = self.root / _safe(provider) / "runs" / _safe(run_ref)
        marker = staging / "recovery.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        self._replace(marker, {"status": "ABANDONED", "fencing_token": lease.fencing_token, "reason": "expired_lease", "recovered_at": current_time.isoformat()})
        return ProviderRunRecovery(
            run_ref=run_ref,
            provider=provider,
            previous_fencing_token=lease.fencing_token,
            status="RECOVERED" if staging.exists() else "ABANDONED",
            staging_path=str(staging),
            reason="expired_lease",
        )

    def _write_recovery(self, run_ref: str, provider: str, payload: Mapping[str, Any]) -> None:
        key = hashlib.sha256(f"{run_ref}:{provider}".encode()).hexdigest()[:32]
        self._replace(self.recovery_root / f"{key}.json", dict(payload, run_ref=run_ref, provider=provider))

    @staticmethod
    def _assert_current(
        current: ProviderRunLease | None,
        expected: ProviderRunLease,
        now: datetime,
        *,
        permit_expired: bool = False,
    ) -> None:
        if current is None or current.fencing_token != expected.fencing_token or current.owner_id != expected.owner_id or current.status != "ACTIVE":
            raise ProviderFenceViolation("provider writer fencing token is not current")
        if not permit_expired and current.expires_at <= now:
            raise ProviderFenceViolation("provider writer lease has expired")


class ProviderObservationWriter:
    """Publish provider records only while holding the current fence."""

    def __init__(self, root: str | Path, provider: str, run_ref: str, *, stage: str = ""):
        self.root = Path(root).resolve()
        self.provider = _safe(provider)
        self.run_ref = _safe(run_ref)
        self.stage = _safe(stage) if stage else ""
        self.staging_dir = self.root / self.provider / self.stage / "runs" / self.run_ref
        self.lease_store = ProviderRunLeaseStore(self.root)

    def publish(
        self,
        lease: ProviderRunLease,
        rows: list[Mapping[str, Any]],
        *,
        boundary_digest: str,
        query_geometry_digest: str,
        crs_contract: str,
        coverage: Mapping[str, Any],
        manifest_extra: Mapping[str, Any] | None = None,
    ) -> Path:
        self.lease_store.assert_writer(lease)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        normalized = "".join(json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str) + "\n" for row in rows).encode("utf-8")
        normalized_path = self.staging_dir / "normalized_all.jsonl"
        self._atomic_bytes(normalized_path, normalized)
        self.lease_store.assert_writer(lease)
        coverage_status = str(coverage.get("coverage_status") or "PARTIAL").upper()
        if coverage_status not in {"COMPLETE", "PARTIAL", "FAILED", "ABANDONED"}:
            raise ValueError("invalid provider coverage_status")
        run_status = {
            "COMPLETE": "success_nonempty" if rows else "success_empty",
            "PARTIAL": "partial",
            "FAILED": "failed",
            "ABANDONED": "abandoned",
        }[coverage_status]
        manifest = {
            "run_id": self.run_ref,
            "provider": self.provider,
            "fencing_token": lease.fencing_token,
            "boundary_digest": boundary_digest,
            "query_geometry_digest": query_geometry_digest,
            "crs_contract": crs_contract,
            "coverage_status": coverage_status,
            "status": run_status,
            "published": coverage_status in {"COMPLETE", "PARTIAL"},
            "normalized_record_count": len(rows),
            "normalized_sha256": "sha256:" + hashlib.sha256(normalized).hexdigest(),
            "coverage": dict(coverage),
        }
        manifest.update(dict(manifest_extra or {}))
        self._atomic_bytes(self.staging_dir / "manifest.json", _json_bytes(manifest))
        return self.staging_dir

    def recover(self, run_ref: str | None = None, provider: str | None = None, *, now: Any = None) -> ProviderRunRecovery:
        """Recover an expired run without publishing any partial rows."""

        return self.lease_store.recover(
            run_ref or self.run_ref,
            provider or self.provider,
            now=now,
        )

    @staticmethod
    def _atomic_bytes(path: Path, data: bytes) -> None:
        handle, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
        finally:
            Path(temp_name).unlink(missing_ok=True)


__all__ = ["ProviderFenceViolation", "ProviderLeaseConflict", "ProviderObservationWriter", "ProviderRunLeaseStore"]
