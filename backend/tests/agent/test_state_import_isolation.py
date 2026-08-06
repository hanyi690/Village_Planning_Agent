"""Prove state.py imports standalone (bootstrap<->plan_state circular import fix)."""

import os
import subprocess
import sys

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_state_imports_in_isolation():
    """state.py must import standalone without bootstrap.graph pre-import (circular import fix)."""
    code = "from app.agent.plan_state.state import AgentState, create_initial_state; print('ok')"
    env = dict(os.environ)
    env["PYTHONPATH"] = BACKEND_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=BACKEND_ROOT,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
