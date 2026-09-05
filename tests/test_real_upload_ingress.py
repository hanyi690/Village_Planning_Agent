from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from fastapi import UploadFile

from app.contracts.data.temporal_role_contracts import SourceTemporalRoleDecision
from app.data.ingestion.source_admission import (
    assess_uploaded_source_admission,
)


def _decision(*, status: str = "ambiguous", selected_role: str = "ambiguous"):
    return SourceTemporalRoleDecision(
        decision_ref="temporal-decision:test",
        source_ref="upload:sha256:fixture",
        profile_ref="temporal-profile:test",
        declared_channel="current_evidence",
        selected_role=selected_role,
        reason_code=(
            "observed_current_state"
            if selected_role == "current_evidence"
            else "insufficient_evidence"
        ),
        status=status,
        confidence=0.0 if status != "accepted" else 0.9,
        input_digest="sha256:input",
        raw_output_digest="sha256:output",
        prompt_version="test",
        model_id="test-model",
        provider_pass_count=2,
    )


@pytest.mark.asyncio
async def test_explicit_current_upload_is_not_blocked_by_temporal_advisory(
    monkeypatch: pytest.MonkeyPatch,
):
    classifier = AsyncMock(return_value=_decision())
    monkeypatch.setattr(
        "app.data.ingestion.temporal_role_classifier.classify_temporal_role_async",
        classifier,
    )

    result = await assess_uploaded_source_admission(
        input_role="current_evidence",
        category="village_data",
        filename="source.geojson",
        source_digest="sha256:fixture",
        gis_data={"type": "FeatureCollection", "features": []},
        gis_data_type="geojson",
        parse_status="success",
        temporal_llm_enabled=True,
    )

    assert result.status == "admitted"
    assert result.input_role == "current_evidence"
    assert result.decision_basis == "explicit_typed_channel_temporal_advisory"
    assert "temporal_role_advisory_only" in result.signals
    classifier.assert_awaited_once()
    assert classifier.await_args.args[0].source_ref == "upload:sha256:fixture"


@pytest.mark.asyncio
async def test_process_uploaded_file_reaches_facade_after_temporal_advisory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    from app.data.ingestion import upload
    from app.infrastructure.paths import reset_run_tmp_root_cache

    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(tmp_path))
    reset_run_tmp_root_cache()
    classifier = AsyncMock(return_value=_decision())
    monkeypatch.setattr(
        "app.data.ingestion.temporal_role_classifier.classify_temporal_role_async",
        classifier,
    )
    persisted: dict[str, object] = {}

    async def persist_upload(**kwargs: object) -> int:
        persisted.update(kwargs)
        return 101

    monkeypatch.setattr(upload, "create_uploaded_file_async", persist_upload)
    result = await upload.process_uploaded_file(
        UploadFile(
            BytesIO(json.dumps({
                "type": "FeatureCollection",
                "crs": {
                    "type": "name",
                    "properties": {"name": "EPSG:4326"},
                },
                "features": [{
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [116.0, 24.0]},
                    "properties": {"name": "fixture"},
                }],
            }).encode("utf-8")),
            filename="boundary.geojson",
            headers={"content-type": "application/geo+json"},
        ),
        "real-upload",
        "village_data",
        input_role="current_evidence",
    )

    assert result["id"] == 101
    assert result["admission_status"] == "admitted"
    assert result["admission_receipt_ref"]["schema_id"] == "DataAdmissionReceipt"
    assert result["admission_lifecycle"][-1] == "ADMITTED"
    assert persisted["admission_status"] == "admitted"
    classifier.assert_awaited_once()


@pytest.mark.asyncio
async def test_unclassified_upload_remains_quarantined_without_classifier_upgrade():
    result = await assess_uploaded_source_admission(
        input_role="",
        category="village_data",
        filename="source.geojson",
        source_digest="sha256:fixture",
        gis_data={"type": "FeatureCollection", "features": []},
        gis_data_type="geojson",
        parse_status="success",
        temporal_llm_enabled=True,
    )

    assert result.status == "quarantined"
    assert result.input_role == "unclassified"
    assert result.reason == "source_input_role_unclassified"


@pytest.mark.asyncio
async def test_explicit_planned_output_is_rejected_before_temporal_advisory():
    result = await assess_uploaded_source_admission(
        input_role="planned_output",
        category="village_data",
        filename="source.geojson",
        source_digest="sha256:fixture",
        gis_data={"type": "FeatureCollection", "features": []},
        gis_data_type="geojson",
        parse_status="success",
        temporal_llm_enabled=True,
    )

    assert result.status == "excluded"
    assert result.input_role == "planned_output"
