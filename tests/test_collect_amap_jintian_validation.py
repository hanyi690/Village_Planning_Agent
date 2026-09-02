from pathlib import Path
from types import SimpleNamespace

from shapely.geometry import box, mapping

from scripts.collect_amap_jintian_validation import (
    ScopeClassifier,
    StageCollector,
    PLACE_TYPE_SHARDS,
    around_params,
    classify_status,
    chunk_ids,
    load_admin_boundary_context,
    max_pages_for_page_size,
    normalize_amap_location,
    split_saturated_scope,
    write_json,
)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


def test_amap_point_keeps_gcj02_and_normalizes_to_wgs84():
    normalized = normalize_amap_location({"location": "116.044146,24.818629"})
    assert normalized["location_gcj02"] == [116.044146, 24.818629]
    assert normalized["location_wgs84"] != normalized["location_gcj02"]


def test_scope_bucket_rejects_outside_meizhou_and_keeps_project_extensions():
    scope = ScopeClassifier(box(116.03, 24.80, 116.06, 24.84))
    outside = scope.classify({"cityname": "河源市", "location": "114.7,23.7"})
    assert outside["scope_bucket"] == "outside_meizhou"
    township = scope.classify(
        {
            "cityname": "梅州市",
            "adname": "平远县",
            "townname": "泗水镇",
            "location": "116.07,24.85",
        }
    )
    assert township["scope_bucket"] == "township_local"
    project = scope.classify(
        {
            "cityname": "梅州市",
            "adname": "平远县",
            "townname": "泗水镇",
            "location": "116.04,24.82",
        }
    )
    assert project["scope_bucket"] == "project_local"


def test_polygon_request_has_explicit_coordinate_contract():
    context = load_admin_boundary_context(boundary_scope=SimpleNamespace(
        geometry=mapping(box(116.03, 24.80, 116.06, 24.84)),
        scope_ref="boundary-scope:test",
        boundary_digest="sha256:test-boundary",
        query_geometry_digest="sha256:test-query",
        normalized_crs="EPSG:4326",
    ))
    assert context["source_crs"] == "EPSG:4326"
    assert context["request_crs"] == "GCJ-02"
    assert context["check_crs"] == "WGS84"
    assert context["polygon_strings_gcj02"]
    assert context["expanded_polygon_strings_gcj02"]
    assert context["sample_points_wgs84"]
    assert set(context["provider_acquisition_plans"]) == {"amap", "tencent", "tianditu"}


def test_identical_sanitized_requests_reuse_one_cache_key(tmp_path: Path):
    collector = StageCollector("test", refresh=False, min_interval=0, root=tmp_path)
    assert collector.request_key(
        "https://example.test", {"key": "secret", "a": "1"}
    ) == collector.request_key("https://example.test", {"a": "1"})


def test_detail_batches_at_most_ten_ids():
    assert list(chunk_ids([str(i) for i in range(21)], 10)) == [
        [str(i) for i in range(10)],
        [str(i) for i in range(10, 20)],
        ["20"],
    ]


def test_amap_page_plan_respects_documented_two_hundred_record_cap():
    assert max_pages_for_page_size(25) == 8


def test_type_plan_contains_top_level_and_known_fine_type_shards():
    assert PLACE_TYPE_SHARDS["type_190000"] == "190000"
    assert PLACE_TYPE_SHARDS["fine_type_141200"] == "141200"


def test_saturated_scope_can_be_split_into_spatial_cells():
    cells = split_saturated_scope(box(116.0, 24.8, 116.1, 24.9), cell_size_m=2500)
    assert len(cells) > 1
    assert all(cell.intersects(box(116.0, 24.8, 116.1, 24.9)) for cell in cells)


def test_around_requests_use_strict_meizhou_scope():
    params = around_params("116.04,24.82", 3000, "141200")
    assert params["region"] == "441400"
    assert params["city_limit"] == "true"


def test_success_empty_is_distinct_from_missing_and_failed():
    assert classify_status(
        attempted=True,
        capability_available=True,
        payload={"status": "1", "pois": []},
        http_status=200,
    ) == "success_empty"
    assert classify_status(
        attempted=False,
        capability_available=False,
        payload={},
    ) == "missing_capability"
    assert classify_status(
        attempted=True,
        capability_available=True,
        payload={},
        http_status=503,
        error="HTTP 503",
    ) == "failed"


def test_transient_failure_retries_and_then_caches_success(monkeypatch, tmp_path):
    collector = StageCollector("test", refresh=False, min_interval=0, root=tmp_path, max_retries=2)
    responses = [
        FakeResponse(503, {"status": "0", "infocode": "10001"}),
        FakeResponse(200, {"status": "1", "pois": []}),
    ]
    monkeypatch.setattr(collector.session, "get", lambda *args, **kwargs: responses.pop(0))
    monkeypatch.setattr("scripts.collect_amap_jintian_validation.time.sleep", lambda _: None)

    _, event = collector.request("poi", "https://example.test", {"keywords": "村"}, "poi")

    assert event["status"] == "success_empty"
    assert event["retry_count"] == 1
    assert len(event["attempts"]) == 2


def test_cached_failed_response_is_retried(monkeypatch, tmp_path):
    collector = StageCollector("test", refresh=False, min_interval=0, root=tmp_path, max_retries=1)
    url = "https://example.test"
    params = {"keywords": "村"}
    request_key = collector.request_key(url, params)
    raw_path = collector.response_dir / f"{request_key}.json"
    write_json(raw_path, {
        "status": "failed",
        "attempted": True,
        "retryable": True,
        "response_json": {},
        "http_status": 503,
        "error": "HTTP 503",
        "retry_count": 0,
        "attempts": [],
    })
    write_json(collector.cache_dir / f"{request_key}.json", {
        "raw_response": str(raw_path),
        "request_key": request_key,
        "status": "failed",
        "retryable": True,
    })
    monkeypatch.setattr(collector.session, "get", lambda *args, **kwargs: FakeResponse(200, {"status": "1", "pois": [{"id": "p1"}]}))

    _, event = collector.request("poi", url, params, "poi")

    assert event["cache_hit"] is False
    assert event["status"] == "success_nonempty"


def test_cached_empty_response_is_success_empty(tmp_path):
    collector = StageCollector("test", refresh=False, min_interval=0, root=tmp_path, max_retries=1)
    url = "https://example.test"
    params = {"keywords": "不存在的名称"}
    request_key = collector.request_key(url, params)
    raw_path = collector.response_dir / f"{request_key}.json"
    write_json(raw_path, {
        "status": "missing",
        "attempted": True,
        "response_json": {"status": "1", "infocode": "10000", "pois": []},
        "http_status": 200,
        "error": None,
    })
    write_json(collector.cache_dir / f"{request_key}.json", {
        "raw_response": str(raw_path),
        "request_key": request_key,
        "status": "missing",
    })

    _, event = collector.request("poi", url, params, "poi")

    assert event["cache_hit"] is True
    assert event["status"] == "success_empty"
