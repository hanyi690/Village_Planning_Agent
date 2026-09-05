from __future__ import annotations

import json
from copy import deepcopy
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile
from rdflib import RDF
from shapely.geometry import shape

from app.contracts.data.admission_contracts import DataAdmissionRequest
from app.data.catalog.external_observation_cache import (
    load_cached_external_observation_snapshot,
)
from app.data.catalog.session_resource_catalog import load_session_boundary_scope
from app.data.boundary_scope import build_boundary_scope_artifact
from app.data.resource_catalog import DataResourceCatalog
from app.infrastructure.context_runtime.manager import (
    build_planning_context,
    invalidate_planning_context,
)
from app.infrastructure.evidence_runtime.retrievers.cached_map_retriever import (
    retrieve_from_cached_map,
)
from app.infrastructure.evidence_runtime.retrievers.data_catalog_retriever import (
    retrieve_from_data_catalog,
)
from app.infrastructure.evidence_runtime.retrievers.kg_retriever import (
    retrieve_from_kg,
)
from app.infrastructure.paths import reset_run_tmp_root_cache, run_tmp_root
from app.infrastructure.kg.ontology import PLN
from app.modules.data.application import DataAdmissionFacade, DataApplication


@pytest.mark.asyncio
async def test_real_jintian_upload_to_evidence_replay_and_read_only_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Exercise the DATA-owned Jintian chain without network calls or writes."""

    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("COGNITION_WORLD_MODEL_MODE", "v2_only")
    monkeypatch.setenv("DATA_LEGACY_BOUNDARY_FILE_FALLBACK", "0")
    reset_run_tmp_root_cache()

    from app.data.ingestion import source_admission, upload
    from app.data.ingestion.source_admission import SourceAdmissionAssessment

    captured: dict[str, object] = {}

    async def admit_current_evidence(**_: object) -> SourceAdmissionAssessment:
        return SourceAdmissionAssessment(
            declared_role="current_evidence",
            input_role="current_evidence",
            status="admitted",
            reason="acceptance_temporal_consensus",
            signals=("test:real-jintian",),
        )

    async def persist_upload(**kwargs: object) -> int:
        captured.update(kwargs)
        return 1001

    monkeypatch.setattr(
        source_admission,
        "assess_uploaded_source_admission",
        admit_current_evidence,
    )
    monkeypatch.setattr(upload, "create_uploaded_file_async", persist_upload)

    boundary_path = Path("data/gis/jintian/current/boundary.geojson")
    boundary_bytes = boundary_path.read_bytes()
    uploaded = await upload.process_uploaded_file(
        UploadFile(
            BytesIO(boundary_bytes),
            filename="boundary.geojson",
            headers={"content-type": "application/geo+json"},
        ),
        "jintian-data-e2e",
        "village_data",
        input_role="current_evidence",
        layer_ref="boundary",
        boundary_scope_mode="admitted_boundary",
    )

    assert uploaded["admission_status"] == "admitted"
    refs = uploaded["admission_artifact_refs"]
    assert isinstance(refs, dict)
    assert refs["boundary_scope"]["schema_id"] == "BoundaryScopeArtifact"
    assert uploaded["admission_lifecycle"][-1] == "ADMITTED"
    assert uploaded["admission_receipt_ref"]["descriptor_digest"]
    assert captured["admission_artifact_refs"] == refs

    state = {
        "run_id": uploaded["admission_attempt_ref"],
        "session_id": "jintian-data-e2e",
        "branch_id": "main",
        "artifact_root": str(run_tmp_root()),
        "artifact_refs": refs,
    }
    catalog = DataApplication.load_catalog(state)
    scope = DataApplication.load_boundary_scope(state)
    receipt = DataAdmissionFacade.load_receipt(state)
    assert catalog is not None
    assert scope is not None
    assert receipt is not None
    assert receipt.boundary_scope_ref == refs["boundary_scope"]["digest"]
    source_digest_before = catalog.digest
    scope_digest_before = scope.boundary_digest

    import app.database.operations as operations

    async def reload_upload_rows(_session_id: str) -> list[dict[str, object]]:
        return [{
            "admission_status": "admitted",
            "admission_artifact_refs": refs,
            "admission_artifact_root": str(run_tmp_root()),
        }]

    monkeypatch.setattr(operations, "get_uploaded_files_by_session_async", reload_upload_rows)
    bootstrapped_scope = await load_session_boundary_scope("jintian-data-e2e")
    assert bootstrapped_scope is not None
    assert bootstrapped_scope.scope_ref == scope.scope_ref

    # The three provider plans are compiled solely from the admitted scope.
    from scripts.collect_amap_jintian_validation import load_admin_boundary_context

    provider_context = load_admin_boundary_context(boundary_scope=scope)
    plans = provider_context["provider_acquisition_plans"]
    assert set(plans) == {"amap", "tencent", "tianditu"}
    assert all(plan["boundary_ref"] == scope.scope_ref for plan in plans.values())
    assert all(plan["boundary_digest"] == scope.boundary_digest for plan in plans.values())
    assert all(plan["normalized_crs"] == "EPSG:4326" for plan in plans.values())

    context = await build_planning_context(
        "jintian-data-e2e",
        village_name="金田村",
        include_reports=False,
        refresh=True,
        data_catalog=DataResourceCatalog(catalog),
        boundary_scope_artifact=bootstrapped_scope,
        artifact_root=str(run_tmp_root()),
    )
    assert context.boundary_scope_artifact.scope_ref == scope.scope_ref
    assert context.world_model_mode == "v2_only"
    assert context.world_model is not None

    # Evidence reads the local cache and does not replace local DATA geometry.
    external = load_cached_external_observation_snapshot(
        "金田村",
        administrative_scope={"city": "梅州市", "county": "平远县", "township": "泗水镇", "village": "金田村"},
        project_bbox_wgs84=tuple(float(value) for value in shape(scope.geometry).bounds),
    )
    context.external_observation_snapshot = external
    facts, sources, trace = retrieve_from_cached_map(context, limit=8)
    assert external.provider_attempts
    assert trace["cache_only"] is True
    assert len(facts) == len(sources)
    assert trace["status"] in {"returned", "empty"}
    data_facts, data_sources = await retrieve_from_data_catalog(
        "jintian-data-e2e", query="boundary"
    )
    assert len(data_facts) == len(data_sources)
    assert all(source.reference.startswith("data:") for source in data_sources)
    assert all(fact.fields["geometry_authority"] == "data_resource_catalog" for fact in data_facts)
    assert getattr(context, "data_resource_catalog", None) is not None
    assert getattr(context.data_resource_catalog, "data_dependency_graph_digest", "")
    assert catalog.digest == source_digest_before
    assert scope.boundary_digest == scope_digest_before

    # Same upload content and policy reuses the immutable admission products.
    replay_request = DataAdmissionRequest(
        session_id="jintian-data-e2e",
        source_ref=f"upload:jintian-data-e2e:{uploaded['source_digest']}",
        content_digest=uploaded["source_digest"],
        normalized_input=json.loads(boundary_bytes.decode("utf-8")),
        declared_media_type="application/geo+json",
        declared_crs="EPSG:4326",
        adapter_hint="file_vector",
        expected_role="current_evidence",
        policy_context={
            "artifact_root": str(run_tmp_root()),
            "layer_ref": "boundary",
            "boundary_scope_mode": "admitted_boundary",
        },
    )
    replay = await DataAdmissionFacade().admit(replay_request)
    assert replay.receipt.state == "ADMITTED"
    assert replay.boundary_scope_artifact_ref.digest == refs["boundary_scope"]["digest"]

    changed_payload = deepcopy(replay_request.normalized_input)
    changed_request = replay_request.model_copy(update={
        "source_ref": "upload:jintian-data-e2e:boundary-revision",
        "content_digest": "sha256:boundary-revision",
        "normalized_input": changed_payload,
        "parent_catalog_ref": refs["data_catalog"],
    })
    changed = await DataAdmissionFacade().admit(changed_request)
    assert changed.receipt.state == "ADMITTED"
    stale = await DataAdmissionFacade().admit(changed_request)
    assert stale.receipt.reason_code == "stale_parent_catalog"

    invalidate_planning_context("jintian-data-e2e")


@pytest.mark.asyncio
async def test_real_jintian_repaired_surface_catalog_is_consumable_by_wm_and_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Admit real boundary/landuse data, then consume one immutable catalog."""

    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("COGNITION_WORLD_MODEL_MODE", "v2_only")
    reset_run_tmp_root_cache()

    def request_for(filename: str, layer_ref: str) -> DataAdmissionRequest:
        payload = json.loads(
            Path("data/gis/jintian/current", filename).read_text(encoding="utf-8")
        )
        return DataAdmissionRequest(
            session_id="jintian-surface-consumer-e2e",
            source_ref=f"upload:jintian:{layer_ref}",
            content_digest=f"sha256:{layer_ref}-real-fixture",
            normalized_input=payload,
            declared_media_type="application/geo+json",
            declared_crs="EPSG:4326",
            adapter_hint="file_vector",
            expected_role="current_evidence",
            policy_context={
                "artifact_root": str(run_tmp_root()),
                "layer_ref": layer_ref,
                "config": {"village_name": "金田村"},
                **(
                    {
                        "boundary_scope_mode": "admitted_boundary",
                        "boundary_dataset_ref": f"upload:jintian:{layer_ref}",
                    }
                    if layer_ref == "boundary"
                    else {}
                ),
            },
        )

    facade = DataAdmissionFacade()
    boundary = await facade.admit(request_for("boundary.geojson", "boundary"))
    landuse = await facade.admit(request_for("landuse.geojson", "landuse"))

    assert boundary.receipt.state == "ADMITTED"
    assert landuse.receipt.state == "ADMITTED"
    assert boundary.data_run is not None
    assert landuse.data_run is not None

    landuse_features = tuple(landuse.data_run.catalog.features)
    landuse_digest_before = landuse.data_run.catalog.digest
    assert len(landuse_features) == 660
    assert all(feature.validity_status == "valid" for feature in landuse_features)
    repaired = next(
        feature for feature in landuse_features
        if feature.source_feature_ref.endswith(":343")
    )
    assert repaired.normalized_geometry is not None
    assert repaired.topology_repair_audit["source_geometry_type"] == "MultiPolygon"
    assert repaired.topology_repair_audit["repaired_geometry_type"] == "MultiPolygon"
    assert repaired.topology_repair_audit["review_required"] is True

    boundary_catalog = DataResourceCatalog(boundary.data_run.catalog)
    landuse_catalog = DataResourceCatalog(landuse.data_run.catalog)
    catalog = boundary_catalog.merge(
        landuse_catalog,
        snapshot_id="jintian-surface-consumer-catalog",
    )
    scope = build_boundary_scope_artifact(
        boundary.data_run.catalog,
        mode="admitted_boundary",
        source_dataset_ref="upload:jintian:boundary",
        source_layer_ref="boundary",
    )
    assert scope is not None

    context = await build_planning_context(
        "jintian-surface-consumer-e2e",
        village_name="金田村",
        include_reports=False,
        refresh=True,
        data_catalog=catalog,
        boundary_scope_artifact=scope,
        artifact_root=str(run_tmp_root()),
    )
    assert context.world_model is not None
    assert context.data_resource_catalog is not None
    assert len(context.data_resource_catalog.snapshot.features) == 661

    facts, sources = await retrieve_from_data_catalog(
        "jintian-surface-consumer-e2e",
        query="landuse",
    )
    assert facts
    assert len(facts) == len(sources)
    assert all(fact.fields["layer_ref"] == "landuse" for fact in facts)
    assert all(fact.fields["geometry_authority"] == "data_resource_catalog" for fact in facts)
    assert all(source.reference.startswith("data:") for source in sources)

    # Retrieval and WM bootstrap must not mutate the admitted source geometry.
    assert landuse.data_run.catalog.digest == landuse_digest_before
    assert repaired.normalized_geometry is not None
    invalidate_planning_context("jintian-surface-consumer-e2e")


@pytest.mark.asyncio
async def test_real_jintian_complete_p0_catalog_is_consumable_by_wm_and_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Consume every local Jintian P0 input through one generic catalog."""

    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("COGNITION_WORLD_MODEL_MODE", "v2_only")
    reset_run_tmp_root_cache()

    vector_layers = (
        "boundary",
        "admin_boundary_line",
        "landuse",
        "road",
        "construction_zone",
        "farmland_protection",
        "ecological_protection",
        "historical_protection",
        "geological_hazard_points",
        "annotation",
    )
    facade = DataAdmissionFacade()
    admitted_catalogs: list[DataResourceCatalog] = []
    boundary_catalog = None
    boundary_scope = None

    vector_requests: list[DataAdmissionRequest] = []
    vector_payloads: list[tuple[str, dict[str, object]]] = []
    for layer_ref in vector_layers:
        payload = json.loads(
            Path("data/gis/jintian/current", f"{layer_ref}.geojson").read_text(
                encoding="utf-8"
            )
        )
        vector_payloads.append((layer_ref, payload))
        vector_requests.append(DataAdmissionRequest(
            session_id="jintian-complete-p0-e2e",
            source_ref=f"upload:jintian:p0:{layer_ref}",
            content_digest=f"sha256:jintian-p0-{layer_ref}",
            normalized_input=payload,
            declared_media_type="application/geo+json",
            declared_crs="EPSG:4326",
            adapter_hint="file_vector",
            expected_role="current_evidence",
            policy_context={
                "artifact_root": str(run_tmp_root()),
                "layer_ref": layer_ref,
                "config": {"village_name": "金田村"},
                **(
                    {
                        "boundary_scope_mode": "admitted_boundary",
                        "boundary_dataset_ref": f"upload:jintian:p0:{layer_ref}",
                    }
                    if layer_ref == "boundary"
                    else {}
                ),
            },
        ))
    vector_results = await facade.admit_many(vector_requests, max_concurrency=2)
    for (layer_ref, _payload), result in zip(
        vector_payloads,
        vector_results,
        strict=True,
    ):
        assert result.receipt.state == "ADMITTED"
        assert result.data_run is not None
        catalog = DataResourceCatalog(result.data_run.catalog)
        admitted_catalogs.append(catalog)
        if layer_ref == "boundary":
            boundary_catalog = catalog
            boundary_scope = build_boundary_scope_artifact(
                result.data_run.catalog,
                mode="admitted_boundary",
                source_dataset_ref=f"upload:jintian:p0:{layer_ref}",
                source_layer_ref=layer_ref,
            )

    raster_request = DataAdmissionRequest(
        session_id="jintian-complete-p0-e2e",
        source_ref="upload:jintian:p0:dem",
        content_digest="sha256:jintian-p0-dem",
        content=Path("data/gis/jintian/terrain/dem.tif"),
        declared_media_type="image/tiff",
        declared_crs="EPSG:4326",
        adapter_hint="local_raster",
        expected_role="current_evidence",
        policy_context={
            "artifact_root": str(run_tmp_root()),
            "layer_ref": "dem",
            "config": {"village_name": "金田村"},
        },
    )
    report_request = DataAdmissionRequest(
        session_id="jintian-complete-p0-e2e",
        source_ref="upload:jintian:p0:current-report",
        content_digest="sha256:jintian-p0-current-report",
        content=Path(
            "docs/MinerU_markdown_泗水镇金田村现状报告_2056637054755487744.md"
        ),
        declared_media_type="text/markdown",
        declared_crs="non-spatial",
        adapter_hint="document",
        expected_role="current_evidence",
        policy_context={
            "artifact_root": str(run_tmp_root()),
            "layer_ref": "current-report",
            "config": {"village_name": "金田村"},
        },
    )
    raster_result, report_result = await facade.admit_many(
        [raster_request, report_request],
        max_concurrency=2,
    )
    assert raster_result.receipt.state == "ADMITTED"
    assert report_result.receipt.state == "ADMITTED"
    assert raster_result.data_run is not None
    assert report_result.data_run is not None
    admitted_catalogs.extend((
        DataResourceCatalog(raster_result.data_run.catalog),
        DataResourceCatalog(report_result.data_run.catalog),
    ))

    assert boundary_catalog is not None
    assert boundary_scope is not None
    catalog = admitted_catalogs[0].merge(
        *admitted_catalogs[1:],
        snapshot_id="jintian-complete-p0-catalog",
    )

    expected_feature_count = sum(
        len(item.snapshot.features) for item in admitted_catalogs
    )
    assert len(catalog.snapshot.features) == expected_feature_count

    context = await build_planning_context(
        "jintian-complete-p0-e2e",
        village_name="金田村",
        include_reports=False,
        refresh=True,
        data_catalog=catalog,
        boundary_scope_artifact=boundary_scope,
        artifact_root=str(run_tmp_root()),
    )
    assert context.world_model is not None
    assert context.data_resource_catalog is not None
    assert context.data_resource_catalog.data_dependency_graph_digest
    kg_facts, kg_cognition = await retrieve_from_kg(
        "jintian-complete-p0-e2e",
        "金田村",
        "current",
        "L1",
    )
    assert kg_facts
    assert kg_cognition.kg_confidence > 0
    assert all(fact.fields["geometry_authority"] == "data_resource_catalog" for fact in kg_facts)
    source_records = set(
        context.world_model.source_graph.subjects(RDF.type, PLN.SourceRecord)
    )
    assert len(source_records) == len(catalog.snapshot.features)
    source_layers = {
        str(value)
        for source_record in source_records
        for value in context.world_model.source_graph.objects(
            source_record,
            PLN.sourceLayerRef,
        )
    }
    assert set(vector_layers) | {"dem", "current-report"} <= source_layers

    landuse_facts, landuse_sources = await retrieve_from_data_catalog(
        "jintian-complete-p0-e2e",
        query="landuse",
    )
    report_facts, report_sources = await retrieve_from_data_catalog(
        "jintian-complete-p0-e2e",
        query="current-report",
    )
    assert landuse_facts and len(landuse_facts) == len(landuse_sources)
    assert report_facts and len(report_facts) == len(report_sources)
    assert all(
        fact.fields["geometry_authority"] == "data_resource_catalog"
        for fact in landuse_facts
    )
    assert all(
        fact.fields["layer_ref"] == "current-report"
        for fact in report_facts
    )
    assert all(source.reference.startswith("data:") for source in (
        *landuse_sources,
        *report_sources,
    ))
    for layer_ref in (*vector_layers, "dem", "current-report"):
        layer_facts, layer_sources = await retrieve_from_data_catalog(
            "jintian-complete-p0-e2e",
            query=layer_ref,
        )
        assert layer_facts and len(layer_facts) == len(layer_sources)
        assert any(
            fact.fields["layer_ref"] == layer_ref
            for fact in layer_facts
        )
    invalidate_planning_context("jintian-complete-p0-e2e")


@pytest.mark.asyncio
async def test_complete_geometry_collection_is_consumed_read_only_by_wm_and_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Preserve mixed-dimensional normalized output without polygon coercion."""

    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("COGNITION_WORLD_MODEL_MODE", "v2_only")
    reset_run_tmp_root_cache()
    payload = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {
                "type": "GeometryCollection",
                "geometries": [
                    {
                        "type": "Polygon",
                        "coordinates": [[
                            [116.0, 24.0],
                            [116.001, 24.0],
                            [116.001, 24.001],
                            [116.0, 24.0],
                        ]],
                    },
                    {
                        "type": "LineString",
                        "coordinates": [[116.0, 24.0], [116.001, 24.001]],
                    },
                ],
            },
            "properties": {"name": "collection-demo"},
        }],
    }
    result = await DataAdmissionFacade().admit(DataAdmissionRequest(
        session_id="collection-consumer-e2e",
        source_ref="upload:collection-consumer-e2e:fixture",
        content_digest="sha256:collection-consumer-e2e",
        normalized_input=payload,
        declared_media_type="application/geo+json",
        declared_crs="EPSG:4326",
        adapter_hint="file_vector",
        expected_role="current_evidence",
        policy_context={
            "artifact_root": str(run_tmp_root()),
            "layer_ref": "collection-demo",
        },
    ))
    assert result.receipt.state == "ADMITTED"
    assert result.data_run is not None
    catalog = DataResourceCatalog(result.data_run.catalog)
    feature = catalog.snapshot.features[0]
    assert feature.geometry_kind == "collection"
    assert feature.normalized_geometry_kind == "collection"
    assert {item.operation for item in catalog.snapshot.capabilities} == {"read"}

    context = await build_planning_context(
        "collection-consumer-e2e",
        village_name="collection-demo",
        include_reports=False,
        refresh=True,
        data_catalog=catalog,
        artifact_root=str(run_tmp_root()),
    )
    assert context.world_model is not None
    assert context.world_model.find_entities(
        source_feature_ref=feature.source_feature_ref,
        limit=1,
    )
    assert not context.workspace.polygons.get("collection-demo")
    assert context.workspace.query_resources(
        geometry_kind="collection",
        layer_ref="collection-demo",
    ) == [feature]
    facts, sources = await retrieve_from_data_catalog(
        "collection-consumer-e2e",
        query="collection-demo",
    )
    assert facts and len(facts) == len(sources)
    assert facts[0].fields["normalized_geometry_kind"] == "collection"
    invalidate_planning_context("collection-consumer-e2e")
