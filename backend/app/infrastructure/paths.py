"""Canonical filesystem locations for one backend run."""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

_run_root_cache: dict[int, Path] = {}
_run_root_lock = threading.Lock()


def run_tmp_root() -> Path:
    """Return the configured, process-wide root for run artifacts.

    The result is cached per process after the first successful probe so that
    concurrent workers (parallel L1/L2/L3 dimension workers, TaskSupervisor
    background tasks) always resolve to the same base directory.  Without the
    cache a concurrent ``.write-probe`` probe can transiently raise and fall
    back to the temp directory, silently splitting the CAS store between two
    roots and causing ``load_artifact`` to miss blobs.
    """
    pid = os.getpid()
    with _run_root_lock:
        cached = _run_root_cache.get(pid)
        if cached is not None:
            return cached
        root = _resolve_run_root()
        _run_root_cache[pid] = root
        return root


def _resolve_run_root() -> Path:
    configured = os.getenv("BACKEND_RUN_TMP_DIR", ".run-tmp").strip()
    root = Path(configured or ".run-tmp").resolve()
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".write-probe"
        probe.touch(exist_ok=True)
        probe.unlink(missing_ok=True)
        return root
    except (OSError, PermissionError):
        # A stale checkout or a locked workspace must not make recovery tests
        # silently write into a shared directory. Preserve the configured
        # leaf name so per-test isolation remains visible in the fallback.
        fallback = (
            Path(tempfile.gettempdir())
            / "village-planning-agent"
            / f"{root.name}-{os.getpid()}"
        )
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def reset_run_tmp_root_cache() -> None:
    """Clear the per-process cache (tests that rebind the run root)."""
    pid = os.getpid()
    with _run_root_lock:
        _run_root_cache.pop(pid, None)


def session_run_dir(session_id: str) -> Path:
    """Return a session-scoped directory under the canonical run root."""
    if not session_id or Path(session_id).name != session_id:
        raise ValueError("session_id must be a single safe path component")
    return run_tmp_root() / session_id


__all__ = ["reset_run_tmp_root_cache", "run_tmp_root", "session_run_dir"]
