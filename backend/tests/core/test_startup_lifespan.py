import sys
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_import_is_model_lazy():
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import app.main; print('torch' in sys.modules, 'transformers' in sys.modules)"],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert "False False" in result.stdout


def test_lifespan_and_health(monkeypatch):
    import app.main as main

    async def init_db():
        return True

    async def init_runtime():
        return None

    monkeypatch.setattr("app.database.init_async_db", init_db)
    monkeypatch.setattr("app.services.runtime.PlanningRuntimeService.initialize", init_runtime)
    with TestClient(main.app) as client:
        assert client.get("/health").json()["status"] == "alive"
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"


def test_startup_failure_is_fail_fast(monkeypatch):
    import app.main as main

    async def fail_db():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr("app.database.init_async_db", fail_db)
    with pytest.raises(RuntimeError, match="db unavailable"):
        with TestClient(main.app):
            pass
