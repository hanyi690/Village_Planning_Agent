from __future__ import annotations

import json
from copy import deepcopy
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile
from shapely.geometry import shape

from app.contracts.data.admission_contracts import DataAdmissionRequest
from app.data.catalog.external_observation_cache import (
    load_cached_external_observation_snapshot,
)
from app.data.catalog.session_resource_catalog import load_session_boundary_scope
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
from app.infrastructure.paths import reset_run_tmp_root_cache, run_tmp_root
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
    assert external.provider_runs
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
