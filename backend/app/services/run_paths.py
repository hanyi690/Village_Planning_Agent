"""Canonical filesystem locations for one backend run."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def run_tmp_root() -> Path:
    """Return the configured, process-wide root for run artifacts."""
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


def session_run_dir(session_id: str) -> Path:
    """Return a session-scoped directory under the canonical run root."""
    if not session_id or Path(session_id).name != session_id:
        raise ValueError("session_id must be a single safe path component")
    return run_tmp_root() / session_id


__all__ = ["run_tmp_root", "session_run_dir"]
