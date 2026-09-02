from __future__ import annotations

import pytest

from app.contracts.data.admission_contracts import DataAdmissionRequest
from app.data.admission import check_local_admission_boundary
from app.infrastructure.paths import reset_run_tmp_root_cache, run_tmp_root
from app.modules.data.application import DataAdmissionFacade


@pytest.mark.parametrize(
    ("media", "adapter"),
    [
        ("application/geo+json", "file_vector"),
        ("application/x-esri-shapefile", "file_vector"),
        ("application/geopackage+sqlite3", "file_vector"),
        ("application/vnd.google-earth.kml+xml", "file_vector"),
        ("text/csv", "table"),
        ("text/tab-separated-values", "table"),
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "table"),
    ],
)
def test_local_capability_matrix_accepts_supported_local_formats(media, adapter):
    decision = check_local_admission_boundary(
        declared_media_type=media,
        adapter_hint=adapter,
        declared_crs="non-spatial" if adapter == "table" else "EPSG:4326",
        declared_encoding="UTF-8",
        expected_role="current_evidence",
    )

    assert decision.accepted is True
    assert decision.state == "ADMITTED"


@pytest.mark.parametrize(
    ("media", "adapter", "crs", "encoding", "role", "state"),
    [
        ("application/x-esri-shapefile", "api_vector", "EPSG:4326", "UTF-8", "current_evidence", "UNSUPPORTED"),
        ("text/csv", "table", "EPSG:4326", "UTF-8", "current_evidence", "CRS_UNRESOLVED"),
        ("application/geo+json", "file_vector", "", "UTF-8", "current_evidence", "CRS_UNRESOLVED"),
        ("application/geo+json", "file_vector", "EPSG:4326", "GBK", "current_evidence", "ENCODING_UNRESOLVED"),
        ("application/geo+json", "file_vector", "EPSG:4326", "UTF-8", "planned_output", "POLICY_REJECTED"),
        ("application/x-unknown", "file_vector", "EPSG:4326", "UTF-8", "current_evidence", "UNSUPPORTED"),
    ],
)
def test_local_capability_matrix_fails_closed(media, adapter, crs, encoding, role, state):
    decision = check_local_admission_boundary(
        declared_media_type=media,
        adapter_hint=adapter,
        declared_crs=crs,
        declared_encoding=encoding,
        expected_role=role,
    )

    assert decision.accepted is False
    assert decision.state == state


def _table_payload() -> dict:
    return {
        "type": "TableResource",
        "filename": "inventory.csv",
        "tables": [{
            "name": "default",
            "columns": ["name", "count"],
            "rows": [{"name": "a", "count": 1}],
        }],
        "row_count": 1,
    }


@pytest.mark.asyncio
async def test_facade_admits_materialized_table_without_spatial_crs(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(tmp_path))
    reset_run_tmp_root_cache()
    result = await DataAdmissionFacade().admit(DataAdmissionRequest(
        session_id="table-session",
        source_ref="upload:table-session:csv",
        content_digest="sha256:table",
        normalized_input=_table_payload(),
        declared_media_type="text/csv",
        declared_crs="non-spatial",
        adapter_hint="table",
        expected_role="current_evidence",
        policy_context={"artifact_root": str(run_tmp_root()), "layer_ref": "inventory"},
    ))

    assert result.receipt.state == "ADMITTED"
    assert result.data_run.catalog.features[0].raw_attributes["sheet_name"] == "default"
    assert result.data_run.catalog.features[0].raw_attributes["row_ordinal"] == 0


@pytest.mark.asyncio
async def test_recovery_creates_new_attempt_and_preserves_gap_parent(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(tmp_path))
    reset_run_tmp_root_cache()
    base = {
        "session_id": "recovery-session",
        "source_ref": "upload:recovery-session:geojson",
        "content_digest": "sha256:recovery",
        "normalized_input": {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [116.0, 24.0]},
                "properties": {},
            }],
        },
        "declared_media_type": "application/geo+json",
        "declared_crs": "EPSG:4326",
        "adapter_hint": "file_vector",
        "expected_role": "current_evidence",
        "policy_context": {"artifact_root": str(run_tmp_root())},
    }
    failed = await DataAdmissionFacade().admit(DataAdmissionRequest(
        **base,
        declared_encoding="GBK",
    ))
    assert failed.receipt.state == "ENCODING_UNRESOLVED"
    assert failed.receipt.lifecycle == ("DISCOVERED", "CLASSIFIED", "ENCODING_UNRESOLVED")
    assert failed.gap_artifact_ref is not None

    recovered = await DataAdmissionFacade().resume(DataAdmissionRequest(
        **base,
        declared_encoding="UTF-8",
        recovery_gap_ref=failed.gap_artifact_ref.model_dump(mode="json"),
    ))
    assert recovered.receipt.state == "ADMITTED"
    assert recovered.receipt.attempt_ref != failed.receipt.attempt_ref
    assert failed.receipt.attempt_ref in recovered.receipt.input_refs or failed.gap_artifact_ref.digest in recovered.receipt.input_refs


@pytest.mark.asyncio
async def test_non_retryable_recovery_gap_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(tmp_path))
    reset_run_tmp_root_cache()
    request = DataAdmissionRequest(
        session_id="nonretry-session",
        source_ref="upload:nonretry-session:geojson",
        content_digest="sha256:nonretry",
        normalized_input={"type": "FeatureCollection", "features": []},
        declared_media_type="application/geo+json",
        declared_crs="EPSG:4326",
        adapter_hint="file_vector",
        expected_role="planning_instruction",
        policy_context={"artifact_root": str(run_tmp_root())},
    )
    failed = await DataAdmissionFacade().admit(request)
    assert failed.gap_artifact_ref is not None
    resumed = await DataAdmissionFacade().resume(request.model_copy(update={
        "expected_role": "current_evidence",
        "recovery_gap_ref": failed.gap_artifact_ref.model_dump(mode="json"),
    }))
    assert resumed.receipt.state == "POLICY_REJECTED"
    assert resumed.receipt.reason_code == "recovery_gap_not_retryable"
