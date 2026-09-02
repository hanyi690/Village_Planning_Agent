from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from app.contracts.data.remote_admission_contracts import (
    RemoteSourceAdmissionRequest,
)
from app.modules.data.application import DataAdmissionFacade


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _request(kind: str = "wfs") -> RemoteSourceAdmissionRequest:
    return RemoteSourceAdmissionRequest(
        source_id="jintian.remote.constraints",
        kind=kind,
        endpoint="https://guangdong.tianditu.gov.cn/service",
        provider="gd_tianditu",
        layer="farmland_protection",
        boundary_ref="boundary-scope:jintian:current",
        boundary_digest=_digest("boundary"),
        query_geometry_digest=_digest("query"),
        crs_contract="source=EPSG:4490; target=EPSG:4326; transform=declared",
        capabilities=("vector", "bbox_query"),
        auth_ref="env://GD_TIANDITU_TOKEN",
    )


def _invalid(**updates: object) -> RemoteSourceAdmissionRequest:
    payload = _request().model_dump(mode="python")
    payload.update(updates)
    return RemoteSourceAdmissionRequest(**payload)


@pytest.mark.parametrize("kind", ["api_vector", "wfs", "mapserver", "wmts", "remote_raster"])
def test_remote_admission_is_declaration_only(kind: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.data.ingestion.connections.ConnectionRegistry.require",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network/provider must not be touched")),
        raising=False,
    )

    receipt = DataAdmissionFacade.admit_declared_remote(_request(kind))

    assert receipt.status == "ADMITTED"
    assert receipt.provider_run_required is True
    assert receipt.provenance["network_contacted"] is False
    assert receipt.boundary_digest == _digest("boundary")


def test_remote_admission_requires_explicit_boundary_query_crs_and_safe_auth():
    with pytest.raises(ValidationError):
        _invalid(boundary_ref="")
    with pytest.raises(ValidationError):
        _invalid(boundary_digest="unknown")
    with pytest.raises(ValidationError):
        _invalid(crs_contract="unknown target")
    with pytest.raises(ValidationError):
        _invalid(auth_ref="token=plain-text-secret")


def test_remote_admission_rejects_non_https_and_unallowlisted_hosts():
    with pytest.raises(ValidationError):
        _invalid(endpoint="http://guangdong.tianditu.gov.cn/service")
    with pytest.raises(ValidationError):
        _invalid(endpoint="https://example.invalid/service")


def test_remote_receipt_can_be_persisted_without_network(tmp_path):
    state = {
        "run_id": "remote-admission-test",
        "session_id": "remote-admission-test",
        "branch_id": "main",
        "artifact_root": str(tmp_path),
        "artifact_refs": {},
    }
    receipt = DataAdmissionFacade.admit_declared_remote(_request(), state=state)
    assert receipt.receipt_id.startswith("data.remote.receipt.")
    assert state["artifact_refs"]["data_remote_admission_receipt"]["schema_id"] == "RemoteSourceAdmissionReceipt"


def test_catalog_declaration_compiles_to_closed_remote_contract():
    request = RemoteSourceAdmissionRequest.from_catalog_declaration(
        "jintian.wmts",
        {
            "driver": "wmts_tile",
            "endpoint": "https://t0.tianditu.gov.cn",
            "connection": "tianditu",
            "layer": "img_c",
            "crs": "EPSG:4326",
            "zoom_range": [3, 16],
        },
        boundary_ref="boundary-scope:jintian:current",
        boundary_digest=_digest("boundary"),
        query_geometry_digest=_digest("query"),
        auth_ref="env://TIANDITU_API_KEY",
    )
    assert request.kind == "wmts"
    assert request.limits.max_zoom == 16
    assert request.request_digest.startswith("sha256:")


def test_remote_drivers_require_the_admitted_receipt_before_fetch():
    from app.data.ingestion.sources.api_vector import ApiVectorDriver
    from app.data.ingestion.sources.remote_raster import RemoteRasterDriver
    from app.data.ingestion.sources.wmts_tile import WmtsTileDriver
    from app.data.model.canonical import BBox

    bbox = BBox(west=116.0, south=24.0, east=116.1, north=24.1)
    api = ApiVectorDriver({
        "connection": "gd_tianditu",
        "service_id": "SQSXWPSJ",
        "protocol": "mapserver",
        "layers": [{"id": 0, "layer_type": "farmland_protection"}],
    })
    wmts = WmtsTileDriver({"connection": "tianditu"})
    raster = RemoteRasterDriver({"provider": "declared", "local_path": "missing.tif"})

    assert api.fetch(bbox=bbox, layer_type="farmland_protection").success is False
    assert wmts.fetch(bbox=bbox).success is False
    assert raster.fetch().success is False

    receipt = DataAdmissionFacade.admit_declared_remote(_request("mapserver"))
    api.bind_remote_admission(receipt, expected_kinds={"api_vector", "mapserver"})
    assert api._admission_receipt == receipt


def test_api_vector_does_not_cross_protocol_or_return_wms_as_vector(monkeypatch: pytest.MonkeyPatch):
    from types import SimpleNamespace

    from app.data.ingestion.sources.api_vector import ApiVectorDriver
    from app.data.model.canonical import BBox

    driver = ApiVectorDriver({
        "connection": "gd_tianditu",
        "service_id": "SQSXWPSJ",
        "protocol": "mapserver_rest",
        "layers": [{"id": 0, "layer_type": "farmland_protection"}],
    })
    receipt = DataAdmissionFacade.admit_declared_remote(_request("mapserver"))
    driver.bind_remote_admission(receipt, expected_kinds={"api_vector", "mapserver_rest", "mapserver"})
    service = SimpleNamespace(
        query_mapserver_layer=lambda *_args: SimpleNamespace(
            success=False,
            data=None,
            error="declared MapServer request failed",
        ),
        fetch_constraint_data=lambda *_args: (_ for _ in ()).throw(
            AssertionError("driver crossed from MapServer to WFS")
        ),
        get_wms_map_url=lambda *_args: (_ for _ in ()).throw(
            AssertionError("driver returned a WMS compatibility result")
        ),
    )
    monkeypatch.setattr(driver, "_get_service", lambda: service)

    result = driver.fetch(
        bbox=BBox(west=116.0, south=24.0, east=116.1, north=24.1),
        layer_type="farmland_protection",
    )

    assert result.success is False
    assert result.error == "declared MapServer request failed"
