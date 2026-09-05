from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile

from app.contracts.data.admission_contracts import DataAdmissionRequest
from app.data.admission import plan_catalog_invalidation
from app.data.coordinate_contract import normalize_to_wgs84
from app.data.resource_catalog import DataResourceCatalog
from app.infrastructure.paths import reset_run_tmp_root_cache, run_tmp_root
from app.modules.data.application import DataAdmissionFacade


def _geojson_payload() -> dict:
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": [{
            "type": "Feature",
            "id": "one",
            "geometry": {"type": "Point", "coordinates": [116.0, 24.0]},
            "properties": {"name": "one"},
        }],
    }


@pytest.mark.asyncio
async def test_facade_persists_lightweight_catalog_pointer_and_replays(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(tmp_path))
    reset_run_tmp_root_cache()
    request = DataAdmissionRequest(
        session_id="mvp-session",
        source_ref="upload:mvp-session:sha256:fixture",
        content_digest="sha256:fixture",
        normalized_input=_geojson_payload(),
        source_kind="upload",
        declared_media_type="application/geo+json",
        declared_crs="EPSG:4326",
        adapter_hint="file_vector",
        expected_role="current_evidence",
        policy_context={"artifact_root": str(run_tmp_root())},
    )

    facade = DataAdmissionFacade()
    first = await facade.admit(request)
    replay = await facade.admit(request)

    assert first.receipt.state == "ADMITTED"
    assert first.receipt.lifecycle == (
        "DISCOVERED", "CLASSIFIED", "PARSING", "NORMALIZED",
        "REPRESENTATION_BUILT", "CAPABILITY_INDEXED", "ADMITTED",
    )
    assert first.data_run.catalog_ref.schema_id == "DataResourceCatalogIndexSnapshot"
    assert first.data_run.source_snapshot_ref.schema_id == "SourceSnapshotArtifact"
    assert first.data_run.normalized_resource_ref.schema_id == "NormalizedResourceArtifact"
    assert first.data_run.representation_snapshot_ref.schema_id == "RepresentationSnapshotArtifact"
    assert first.data_run.capability_index_ref.schema_id == "CapabilityIndexArtifact"
    assert replay.data_run.catalog_ref.digest == first.data_run.catalog_ref.digest


@pytest.mark.asyncio
async def test_facade_rejects_unsupported_input_and_stale_parent(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(tmp_path))
    reset_run_tmp_root_cache()
    base = {
        "session_id": "stale-session",
        "declared_crs": "EPSG:4326",
        "adapter_hint": "file_vector",
        "expected_role": "current_evidence",
        "policy_context": {"artifact_root": str(run_tmp_root())},
    }
    facade = DataAdmissionFacade()
    first = await facade.admit(DataAdmissionRequest(
        **base,
        source_ref="source:first",
        content_digest="sha256:first",
        normalized_input=_geojson_payload(),
        declared_media_type="application/geo+json",
    ))
    second = await facade.admit(DataAdmissionRequest(
        **base,
        source_ref="source:second",
        content_digest="sha256:second",
        normalized_input={
            **_geojson_payload(),
            "features": [{
                **_geojson_payload()["features"][0],
                "geometry": {"type": "Point", "coordinates": [117.0, 24.0]},
            }],
        },
        declared_media_type="application/geo+json",
        parent_catalog_ref=first.catalog_ref.model_dump(mode="json"),
    ))
    stale = await facade.admit(DataAdmissionRequest(
        **base,
        source_ref="source:stale",
        content_digest="sha256:stale",
        normalized_input=_geojson_payload(),
        declared_media_type="application/geo+json",
        parent_catalog_ref=first.catalog_ref.model_dump(mode="json"),
    ))
    unsupported = await facade.admit(DataAdmissionRequest(
        **base,
        source_ref="source:unsupported",
        content_digest="sha256:unsupported",
        normalized_input="anything",
        declared_media_type="application/x-unknown",
    ))

    assert second.receipt.state == "ADMITTED"
    assert stale.receipt.reason_code == "stale_parent_catalog"
    assert unsupported.receipt.state == "UNSUPPORTED"


@pytest.mark.asyncio
async def test_upload_calls_async_classifier_and_facade(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(tmp_path))
    reset_run_tmp_root_cache()
    from app.data.ingestion import source_admission, upload
    from app.data.ingestion.source_admission import SourceAdmissionAssessment

    seen: dict[str, object] = {}

    async def fake_assess(
        *,
        input_role,
        category,
        filename,
        parsed_text,
        gis_data,
        gis_data_type,
        parse_status,
        temporal_llm_enabled,
    ):
        seen["classifier"] = {
            "input_role": input_role,
            "category": category,
            "filename": filename,
            "parsed_text": parsed_text,
            "gis_data": gis_data,
            "gis_data_type": gis_data_type,
            "parse_status": parse_status,
            "temporal_llm_enabled": temporal_llm_enabled,
        }
        return SourceAdmissionAssessment(
            declared_role="current_evidence",
            input_role="current_evidence",
            status="admitted",
            reason="test_temporal_consensus",
            signals=("classifier:test",),
        )

    async def fake_create(**kwargs):
        seen["db"] = kwargs
        return 7

    monkeypatch.setattr(source_admission, "assess_uploaded_source_admission", fake_assess)
    monkeypatch.setattr(upload, "create_uploaded_file_async", fake_create)
    body = json.dumps(_geojson_payload()).encode("utf-8")
    result = await upload.process_uploaded_file(
        UploadFile(BytesIO(body), filename="boundary.geojson", headers={"content-type": "application/geo+json"}),
        "mvp-upload",
        "village_data",
        input_role="current_evidence",
    )

    assert "classifier" in seen
    assert seen["classifier"]["temporal_llm_enabled"] is True
    assert seen["db"]["admission_receipt_ref"]["schema_id"] == "DataAdmissionReceipt"
    assert seen["db"]["admission_lifecycle"][-1] == "ADMITTED"
    assert seen["db"]["gis_data_type"] is None
    assert result["gis_data_type"] is None
    assert result["admission_status"] == "admitted"


@pytest.mark.asyncio
async def test_session_catalog_reloads_persisted_artifact_without_reassessment(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(tmp_path))
    reset_run_tmp_root_cache()
    request = DataAdmissionRequest(
        session_id="reload-session",
        source_ref="upload:reload-session:sha256:fixture",
        content_digest="sha256:fixture",
        normalized_input=_geojson_payload(),
        declared_media_type="application/geo+json",
        declared_crs="EPSG:4326",
        adapter_hint="file_vector",
        expected_role="current_evidence",
        policy_context={"artifact_root": str(run_tmp_root())},
    )
    result = await DataAdmissionFacade().admit(request)
    refs = result.to_state_patch()["artifact_refs"]
    row = {
        "id": 1,
        "filename": "boundary.geojson",
        "original_filename": "boundary.geojson",
        "file_category": "village_data",
        "file_type": "geojson",
        "input_role": "current_evidence",
        "admission_status": "admitted",
        "admission_reason": "test",
        "admission_signals": [],
        "source_digest": "sha256:fixture",
        "gis_data": _geojson_payload(),
        "parse_status": "success",
        "admission_receipt_ref": refs["data_admission_receipt"],
        "admission_artifact_refs": refs,
        "admission_artifact_root": str(run_tmp_root()),
    }
    import app.database.operations as operations
    from app.data.catalog import session_resource_catalog
    from app.data.ingestion import source_admission

    async def get_rows(_session_id):
        return [row]

    monkeypatch.setattr(operations, "get_uploaded_files_by_session_async", get_rows)
    monkeypatch.setattr(
        source_admission,
        "assess_source_admission",
        lambda **_: (_ for _ in ()).throw(AssertionError("session loader reassessed upload")),
    )
    catalog = await session_resource_catalog.load_session_data_catalog("reload-session")

    assert catalog is not None
    assert catalog.snapshot.digest == result.data_run.catalog.digest


def test_external_coordinates_fail_closed():
    with pytest.raises(ValueError):
        normalize_to_wgs84(116.0, 24.0, "bd09")
    with pytest.raises(ValueError):
        normalize_to_wgs84(116.0, 24.0, "unknown")


def test_catalog_invalidation_is_identity_and_digest_based():
    common = {"source_dataset_ref": "dataset:a", "source_feature_ref": "stable"}
    previous = DataResourceCatalog.from_records([
        {**common, "geometry": {"type": "Point", "coordinates": [116.0, 24.0]}, "properties": {"source_crs": "EPSG:4326"}},
    ], dataset_ref="dataset:a")
    current = DataResourceCatalog.from_records([
        {**common, "geometry": {"type": "Point", "coordinates": [116.1, 24.0]}, "properties": {"source_crs": "EPSG:4326"}},
    ], dataset_ref="dataset:a")
    invalidation = plan_catalog_invalidation(previous.snapshot, current.snapshot)

    assert invalidation["features"] == ("dataset:a:stable",)
    assert invalidation["representations"]
    assert invalidation["capabilities"]


def test_real_jintian_p0_inventory_is_present():
    root = Path("data/gis/jintian/current")
    expected = {
        "boundary.geojson",
        "admin_boundary_line.geojson",
        "landuse.geojson",
        "road.geojson",
        "construction_zone.geojson",
        "farmland_protection.geojson",
        "ecological_protection.geojson",
        "historical_protection.geojson",
        "geological_hazard_points.geojson",
        "annotation.geojson",
    }
    assert {path.name for path in root.glob("*.geojson")} == expected
    assert Path("data/gis/jintian/terrain/dem.tif").is_file()
    assert Path("docs/MinerU_markdown_泗水镇金田村现状报告_2056637054755487744.md").is_file()


def test_real_jintian_topology_repairs_keep_surface_family_and_audit_landuse_feature_343():
    payload = json.loads(
        Path("data/gis/jintian/current/landuse.geojson").read_text(encoding="utf-8")
    )
    catalog = DataResourceCatalog.from_records(
        payload,
        dataset_ref="jintian:current:landuse",
        layer_ref="landuse",
    )
    repaired = [
        feature
        for feature in catalog.snapshot.features
        if feature.topology_repair_audit
    ]
    assert len(repaired) == 5
    feature_343 = catalog.snapshot.features[343]
    audit = feature_343.topology_repair_audit
    assert audit["policy"] == "surface_family_compatible"
    assert audit["source_geometry_type"] == "MultiPolygon"
    assert audit["repaired_geometry_type"] == "MultiPolygon"
    assert audit["source_geometry_family"] == "polygon"
    assert audit["repaired_geometry_family"] == "polygon"
    assert audit["source_part_count"] == 67
    assert audit["repaired_part_count"] == 50
    assert audit["part_count_delta"] == -17
    assert audit["review_required"] is True
    assert feature_343.normalized_geometry is not None
    assert feature_343.normalized_geometry["type"] == "MultiPolygon"


def test_real_jintian_ecological_topology_repair_is_surface_family_compatible():
    payload = json.loads(
        Path("data/gis/jintian/current/ecological_protection.geojson").read_text(
            encoding="utf-8"
        )
    )
    catalog = DataResourceCatalog.from_records(
        payload,
        dataset_ref="jintian:current:ecological_protection",
        layer_ref="ecological_protection",
    )
    repaired = [
        feature
        for feature in catalog.snapshot.features
        if feature.topology_repair_audit
    ]
    assert len(repaired) == 1
    audit = repaired[0].topology_repair_audit
    assert audit["policy"] == "surface_family_compatible"
    assert audit["source_geometry_type"] == "MultiPolygon"
    assert audit["repaired_geometry_type"] == "Polygon"
    assert repaired[0].normalized_geometry is not None
    assert repaired[0].normalized_geometry["type"] == "Polygon"
    assert repaired[0].geometry["type"] == "MultiPolygon"
    assert repaired[0].crs_transform[-1].endswith("MultiPolygon->Polygon")


@pytest.mark.asyncio
async def test_real_jintian_p0_inputs_are_admissible_through_facade(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(tmp_path))
    reset_run_tmp_root_cache()
    root = Path("data/gis/jintian/current")
    facade = DataAdmissionFacade()
    names = [
        "boundary.geojson",
        "admin_boundary_line.geojson",
        "landuse.geojson",
        "road.geojson",
        "construction_zone.geojson",
        "farmland_protection.geojson",
        "ecological_protection.geojson",
        "historical_protection.geojson",
        "geological_hazard_points.geojson",
        "annotation.geojson",
    ]
    results = []
    for name in names:
        payload = json.loads((root / name).read_text(encoding="utf-8"))
        results.append(await facade.admit(DataAdmissionRequest(
            session_id="real-jintian-p0",
            source_ref=f"file:{name}",
            content_digest=f"sha256:{name}",
            normalized_input=payload,
            declared_media_type="application/geo+json",
            declared_crs="EPSG:4326",
            adapter_hint="file_vector",
            expected_role="current_evidence",
            policy_context={
                "artifact_root": str(run_tmp_root()),
                "layer_ref": name.removesuffix(".geojson"),
                **(
                    {"boundary_scope_mode": "admitted_boundary"}
                    if name == "boundary.geojson"
                    else {}
                ),
            },
        )))
    dem = await facade.admit(DataAdmissionRequest(
        session_id="real-jintian-p0",
        source_ref="file:dem.tif",
        content_digest="sha256:dem.tif",
        content=Path("data/gis/jintian/terrain/dem.tif"),
        declared_media_type="image/tiff",
        declared_crs="EPSG:4326",
        adapter_hint="local_raster",
        expected_role="current_evidence",
        policy_context={"artifact_root": str(run_tmp_root()), "layer_ref": "dem"},
    ))
    report = await facade.admit(DataAdmissionRequest(
        session_id="real-jintian-p0",
        source_ref="file:current-report.md",
        content_digest="sha256:current-report",
        content=Path("docs/MinerU_markdown_泗水镇金田村现状报告_2056637054755487744.md"),
        declared_media_type="text/markdown",
        declared_crs="non-spatial",
        adapter_hint="document",
        expected_role="current_evidence",
        policy_context={"artifact_root": str(run_tmp_root()), "layer_ref": "report"},
    ))
    assert all(
        item.receipt.state == (
            "ADMITTED"
        )
        for name, item in zip(names, results)
    )
    assert dem.receipt.state == "ADMITTED"
    assert report.receipt.state == "ADMITTED"
    assert results[0].boundary_scope_artifact_ref is not None
