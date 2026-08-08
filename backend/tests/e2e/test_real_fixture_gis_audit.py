"""Read-only audit of the real MVP GIS fixture before any spatial operation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.e2e


def test_mvp_fixture_invalid_geometry_is_recorded_not_crashing():
    from app.api.session_routes import _audit_geojson_geometry

    fixture_dir = Path(__file__).parents[1] / "fixtures" / "mvp_village" / "gis"
    files = sorted(fixture_dir.glob("*.geojson"))
    assert files
    audits = []
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        audit = _audit_geojson_geometry(payload)
        assert audit["status"] == "ok", path.name
        assert audit["feature_count"] == len(payload.get("features") or [])
        assert audit["invalid_count"] >= 0
        assert len(audit["samples"]) <= 10
        audits.append(audit)

    # The fixture intentionally contains a small number of invalid rings.
    # They must remain visible in the audit and be repaired/filtered only at
    # the spatial adapter boundary, never crash the upload process.
    assert sum(item["invalid_count"] for item in audits) == 6
