"""Unit tests for artifact + render query endpoints.

Builds a minimal FastAPI app from the two routers (no DB / runtime needed);
the artifact store is redirected to a tmp_path via monkeypatch.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.artifact_routes import router as artifact_router
from app.api.render_routes import router as render_router
from app.modules.ports.artifact_store import ArtifactRef
from app.services.artifact_store import FilesystemArtifactStore

SESSION_ID = "sess-test-001"


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(artifact_router)
    app.include_router(render_router)
    return app


def _write_artifacts(tmp_path, session_id: str = SESSION_ID) -> None:
    store = FilesystemArtifactStore(base_dir=str(tmp_path))
    store.store(
        ArtifactRef(
            context_version="cv-1",
            artifact_id=f"ground-{session_id}-v1",
            module="ground",
            run_id=session_id,
            artifact_type="GroundingResult",
            revision="v1",
        ),
        {"candidates": [], "grounded": True, "note": "ground-pass"},
    )
    store.store(
        ArtifactRef(
            context_version="cv-1",
            artifact_id=f"execute-{session_id}-v1",
            module="execute",
            run_id=session_id,
            artifact_type="PlannedState",
            revision="v1",
        ),
        {
            "parcels": [
                {
                    "bsm": "P001",
                    "planning_land_use": "0101",
                    "zone_type": "农村宅基地",
                    "area_ha": 0.12,
                    "geometry": "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))",
                    "operation": "reclassify",
                }
            ],
            "zones": [],
            "facilities": [
                {"name": "卫生室", "facility_type": "health", "lon": 1.5, "lat": 1.5}
            ],
            "roads": [{"name": "村道", "road_level": "村道", "width_m": 4.5}],
            "axes": [],
        },
    )


async def _no_layout_configs(session_id: str):
    return []


@pytest.fixture
def client(tmp_path, monkeypatch):
    _write_artifacts(tmp_path)
    monkeypatch.setattr(
        "app.api.artifact_routes.FilesystemArtifactStore",
        lambda base_dir=".run-tmp": FilesystemArtifactStore(base_dir=str(tmp_path)),
    )
    monkeypatch.setattr(
        "app.api.render_routes.FilesystemArtifactStore",
        lambda base_dir=".run-tmp": FilesystemArtifactStore(base_dir=str(tmp_path)),
    )
    monkeypatch.setattr(
        "app.api.render_routes._get_layout_configs", _no_layout_configs
    )
    return TestClient(_make_app())


# ── list ────────────────────────────────────────────────────────────


def test_list_artifacts(client):
    resp = client.get(f"/api/sessions/{SESSION_ID}/artifacts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == SESSION_ID
    assert body["count"] == 2
    types = {a["artifact_type"] for a in body["artifacts"]}
    assert types == {"GroundingResult", "PlannedState"}


def test_list_artifacts_empty_session_returns_empty_list(client, monkeypatch):
    async def _exists(session_id):
        return True

    monkeypatch.setattr("app.api.artifact_routes._session_exists", _exists)
    resp = client.get("/api/sessions/empty-session/artifacts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["artifacts"] == []


def test_list_artifacts_missing_session_404(client, monkeypatch):
    async def _missing(session_id):
        return False

    monkeypatch.setattr("app.api.artifact_routes._session_exists", _missing)
    resp = client.get("/api/sessions/ghost-session/artifacts")
    assert resp.status_code == 404


# ── get by type ─────────────────────────────────────────────────────


def test_get_artifact_by_type(client):
    resp = client.get(f"/api/sessions/{SESSION_ID}/artifacts/GroundingResult")
    assert resp.status_code == 200
    body = resp.json()
    assert body["artifact_type"] == "GroundingResult"
    assert body["revision"] == "v1"
    assert body["payload"]["grounded"] is True
    assert body["manifest"]["artifact_type"] == "GroundingResult"
    assert body["artifact_ref"]["artifact_type"] == "GroundingResult"


def test_get_artifact_version_one(client):
    resp = client.get(f"/api/sessions/{SESSION_ID}/artifacts/GroundingResult?version=1")
    assert resp.status_code == 200
    assert resp.json()["artifact_ref"]["revision"] == "v1"


def test_get_artifact_unsupported_version_404(client):
    resp = client.get(f"/api/sessions/{SESSION_ID}/artifacts/GroundingResult?version=9")
    assert resp.status_code == 404
    assert "supported versions" in resp.json()["detail"]


def test_get_artifact_missing_type_404(client):
    resp = client.get(f"/api/sessions/{SESSION_ID}/artifacts/NoSuchType")
    assert resp.status_code == 404


# ── ref ─────────────────────────────────────────────────────────────


def test_get_artifact_ref(client):
    resp = client.get(f"/api/sessions/{SESSION_ID}/artifacts/GroundingResult/ref")
    assert resp.status_code == 200
    body = resp.json()
    assert body["artifact_ref"]["artifact_type"] == "GroundingResult"
    assert body["manifest"]["revision"] == "v1"


def test_get_artifact_ref_missing_type_404(client):
    resp = client.get(f"/api/sessions/{SESSION_ID}/artifacts/NoSuchType/ref")
    assert resp.status_code == 404


# ── render layers ───────────────────────────────────────────────────


def test_render_layers(client):
    resp = client.get(f"/api/sessions/{SESSION_ID}/render-layers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == SESSION_ID
    by_type = {layer["layerType"]: layer for layer in body["layers"]}
    assert set(by_type) == {"function_zone", "facility_point", "planned_road"}

    fz = by_type["function_zone"]["data"]["features"][0]
    assert fz["properties"]["planning_land_use"] == "0101"
    assert fz["geometry"]["type"] == "Polygon"

    fp = by_type["facility_point"]["data"]["features"][0]
    assert fp["geometry"]["type"] == "Point"
    assert fp["geometry"]["coordinates"] == [1.5, 1.5]

    pr = by_type["planned_road"]["data"]["features"][0]
    assert pr["properties"]["road_level"] == "村道"
    assert pr["geometry"] is None


def test_render_layers_no_planned_state_404(client):
    resp = client.get("/api/sessions/no-plan-state/render-layers")
    assert resp.status_code == 404
