"""Canonical filesystem locations for one backend run."""

from __future__ import annotations

import os
from pathlib import Path


def run_tmp_root() -> Path:
    """Return the configured, process-wide root for run artifacts."""
    configured = os.getenv("BACKEND_RUN_TMP_DIR", ".run-tmp").strip()
    return Path(configured or ".run-tmp").resolve()


def session_run_dir(session_id: str) -> Path:
    """Return a session-scoped directory under the canonical run root."""
    if not session_id or Path(session_id).name != session_id:
        raise ValueError("session_id must be a single safe path component")
    return run_tmp_root() / session_id


__all__ = ["run_tmp_root", "session_run_dir"]
