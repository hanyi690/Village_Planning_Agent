"""Configuration resolution must be independent of the process cwd."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.e2e


def test_backend_cwd_loads_root_env_without_overwriting_process_env():
    backend_dir = Path(__file__).parents[2]
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = "process-key"
    env["OPENAI_API_BASE"] = "https://process.example/v1"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from app.core import settings; "
                "print(settings.OPENAI_API_KEY); "
                "print(settings.OPENAI_API_BASE)"
            ),
        ],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.splitlines() == [
        "process-key",
        "https://process.example/v1",
    ]
