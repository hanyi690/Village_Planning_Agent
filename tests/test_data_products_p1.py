from __future__ import annotations

import pytest

from app.contracts.data.admission_contracts import DataAdmissionRequest
from app.contracts.data.product_contracts import (
    CapabilityIndexArtifact,
    NormalizedResourceArtifact,
    RepresentationSnapshotArtifact,
    SourceSnapshotArtifact,
)
from app.contracts.data.source_contracts import DataResourceCatalogIndexSnapshot
from app.infrastructure.artifacts.runtime import load_artifact
from app.infrastructure.paths import reset_run_tmp_root_cache, run_tmp_root
from app.modules.data.application import DataAdmissionFacade, DataApplication


def _request() -> DataAdmissionRequest:
    return DataAdmissionRequest(
        session_id="products-session",
        source_ref="upload:products-session:geojson",
        content_digest="sha256:products",
        normalized_input={
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "id": "f-1",
                "geometry": {"type": "Point", "coordinates": [116.0, 24.0]},
                "properties": {"name": "one"},
            }],
        },
        declared_media_type="application/geo+json",
        declared_crs="EPSG:4326",
        adapter_hint="file_vector",
        expected_role="current_evidence",
        policy_context={"artifact_root": str(run_tmp_root())},
    )


@pytest.mark.asyncio
async def test_catalog_is_published_as_four_products_and_reloaded_from_them(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(tmp_path))
    reset_run_tmp_root_cache()
    result = await DataAdmissionFacade().admit(_request())
    state = {
        "run_id": result.data_run.request.run_id,
        "session_id": result.data_run.request.session_id,
        "branch_id": result.data_run.request.branch_id,
        **result.to_state_patch(),
    }
    refs = state["artifact_refs"]

    assert set(("source_snapshot", "normalized_resource", "representation_snapshot", "capability_index")) <= set(refs)
    assert "data_catalog_payload" not in refs
    index = load_artifact(state, "data_catalog", DataResourceCatalogIndexSnapshot)
    assert index is not None
    assert result.data_run.catalog_ref.schema_id == "DataResourceCatalogIndexSnapshot"
    assert result.data_run.catalog_ref.digest == refs["data_catalog"]["digest"]

    source = load_artifact(state, "source_snapshot", SourceSnapshotArtifact)
    normalized = load_artifact(state, "normalized_resource", NormalizedResourceArtifact)
    representations = load_artifact(state, "representation_snapshot", RepresentationSnapshotArtifact)
    capabilities = load_artifact(state, "capability_index", CapabilityIndexArtifact)
    assert source is not None
    assert normalized is not None
    assert representations is not None
    assert capabilities is not None
    assert source.features[0].geometry is not None
    assert "normalized_geometry" in normalized.model_dump()["features"][0]
    assert "geometry" not in index.model_dump()
    reloaded = DataApplication.load_catalog(state)
    assert reloaded is not None
    assert reloaded.digest == result.data_run.catalog.digest


@pytest.mark.asyncio
async def test_payload_only_state_is_not_a_catalog_compatibility_path(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(tmp_path))
    reset_run_tmp_root_cache()
    result = await DataAdmissionFacade().admit(_request())
    state = {
        "run_id": result.data_run.request.run_id,
        "session_id": result.data_run.request.session_id,
        "branch_id": result.data_run.request.branch_id,
        **result.to_state_patch(),
    }
    state["artifact_refs"].pop("source_snapshot")
    state["artifact_refs"].pop("normalized_resource")
    state["artifact_refs"].pop("representation_snapshot")
    state["artifact_refs"].pop("capability_index")

    with pytest.raises((RuntimeError, ValueError)):
        DataApplication.load_catalog(state)
