from __future__ import annotations

import json
from io import BytesIO

import pytest
from fastapi import UploadFile

from app.contracts.data.admission_contracts import DataAdmissionRequest
from app.infrastructure.paths import reset_run_tmp_root_cache, run_tmp_root
from app.modules.data.application import DataAdmissionFacade


def _geojson(count: int = 1) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [116.0 + index, 24.0]},
                "properties": {},
            }
            for index in range(count)
        ],
    }


@pytest.mark.asyncio
async def test_facade_rejects_feature_budget_before_materialization(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.settings.DATA_MAX_FEATURES", 1)
    reset_run_tmp_root_cache()
    result = await DataAdmissionFacade().admit(DataAdmissionRequest(
        session_id="feature-budget",
        source_ref="upload:feature-budget:geojson",
        content_digest="sha256:feature-budget",
        normalized_input=_geojson(2),
        declared_media_type="application/geo+json",
        declared_crs="EPSG:4326",
        adapter_hint="file_vector",
        expected_role="current_evidence",
        policy_context={"artifact_root": str(run_tmp_root())},
    ))

    assert result.receipt.state == "POLICY_REJECTED"
    assert result.receipt.reason_code == "feature_count_exceeded"
    assert result.catalog_ref is None


@pytest.mark.asyncio
async def test_facade_rejects_text_and_table_budgets(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.settings.DATA_MAX_TEXT_CHARS", 3)
    monkeypatch.setattr("app.core.settings.DATA_MAX_TABLE_ROWS", 1)
    reset_run_tmp_root_cache()
    facade = DataAdmissionFacade()
    text_result = await facade.admit(DataAdmissionRequest(
        session_id="text-budget",
        source_ref="upload:text-budget:md",
        content_digest="sha256:text-budget",
        normalized_input="abcd",
        declared_media_type="text/markdown",
        declared_crs="non-spatial",
        adapter_hint="document",
        expected_role="current_evidence",
        policy_context={"artifact_root": str(run_tmp_root())},
    ))
    table_result = await facade.admit(DataAdmissionRequest(
        session_id="table-budget",
        source_ref="upload:table-budget:csv",
        content_digest="sha256:table-budget",
        normalized_input={
            "type": "TableResource",
            "tables": [{"name": "default", "rows": [{"id": 1}, {"id": 2}]}],
        },
        declared_media_type="text/csv",
        declared_crs="non-spatial",
        adapter_hint="table",
        expected_role="current_evidence",
        policy_context={"artifact_root": str(run_tmp_root())},
    ))

    assert text_result.receipt.reason_code == "text_length_exceeded"
    assert table_result.receipt.reason_code == "table_row_count_exceeded"


@pytest.mark.asyncio
async def test_upload_size_budget_is_persisted_without_classifier_or_decoder(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.settings.DATA_MAX_UPLOAD_BYTES", 4)
    reset_run_tmp_root_cache()
    from app.data.ingestion import upload

    seen: dict[str, object] = {}

    async def fake_create(**kwargs):
        seen["db"] = kwargs
        return 9

    monkeypatch.setattr(upload, "create_uploaded_file_async", fake_create)
    body = json.dumps(_geojson()).encode("utf-8")
    result = await upload.process_uploaded_file(
        UploadFile(BytesIO(body), filename="boundary.geojson", headers={"content-type": "application/geo+json"}),
        "budget-upload",
        "village_data",
        input_role="current_evidence",
    )

    assert result["admission_status"] == "quarantined"
    assert result["admission_reason"] == "upload_size_exceeded"
    assert seen["db"]["file_size"] == len(body)
    assert seen["db"]["admission_gap_ref"]["schema_id"] == "DataAdmissionGap"
