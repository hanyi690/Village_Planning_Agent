from scripts.collect_three_provider_validation import (
    ValidationCollector,
    classify_response,
    normalize_point_record,
    request_key,
)


def test_successful_empty_is_missing_not_failed():
    event = classify_response(
        provider="tencent",
        attempted=True,
        http_status=200,
        payload={"status": 0, "data": [], "count": 0},
    )
    assert event["status"] == "missing"
    assert event["failure"] is None


def test_transport_error_is_failed_and_retryable():
    event = classify_response(
        provider="amap",
        attempted=True,
        http_status=None,
        payload={},
        error="Timeout",
    )
    assert event["status"] == "failed"
    assert event["retryable"] is True


def test_amap_point_is_converted_once_for_local_spatial_checks():
    row = normalize_point_record({"location": "116.044146,24.818629"}, "amap")
    assert row["location_crs"] == "GCJ-02"
    assert row["location_wgs84"] != row["location_gcj02"]


def test_tencent_lat_lng_is_normalized_to_lon_lat():
    row = normalize_point_record({"location": {"lat": 24.818629, "lng": 116.044146}}, "tencent")
    assert row["location_wgs84"] == [116.044146, 24.818629]


def test_success_cache_key_excludes_credentials():
    assert request_key("https://example.test", {"key": "secret", "a": "1"}) == request_key(
        "https://example.test", {"a": "1"}
    )


def test_collector_exposes_provider_specific_cache_path(tmp_path):
    collector = ValidationCollector("tencent", "01_admin_scope", False, 0,)
    assert collector.stage_dir.name == "01_admin_scope"
    assert collector.provider == "tencent"
