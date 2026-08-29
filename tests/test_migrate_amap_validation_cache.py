from scripts.migrate_amap_validation_cache import (
    extract_records,
    normalize_amap_record,
    status_for,
)


def test_successful_empty_response_is_missing():
    envelope = {
        "http_status": 200,
        "error": None,
        "response_json": {"status": "1", "infocode": "10000", "info": "OK"},
    }
    assert status_for(envelope, len(extract_records(envelope["response_json"]))) == ("missing", None)


def test_provider_error_is_failed_even_when_http_is_200():
    envelope = {
        "http_status": 200,
        "error": None,
        "response_json": {"status": "0", "infocode": "10012", "info": "INSUFFICIENT_PRIVILEGES"},
    }
    assert status_for(envelope, 0) == ("failed", "INSUFFICIENT_PRIVILEGES")


def test_migration_preserves_amap_gcj02_and_converts_once():
    row = normalize_amap_record({"name": "金田村", "location": "116.044146,24.818629"})
    assert row["location_crs"] == "GCJ-02"
    assert row["location_gcj02"] == [116.044146, 24.818629]
    assert row["location_wgs84"] != row["location_gcj02"]


def test_regeo_nested_roads_are_normalized_candidates():
    records = extract_records(
        {
            "status": "1",
            "infocode": "10000",
            "regeocode": {
                "formatted_address": "广东省梅州市平远县泗水镇金田村",
                "roads": [{"id": "road-1", "name": "122乡道", "distance": "5"}],
            },
        }
    )
    assert ("regeo_roads", {"id": "road-1", "name": "122乡道", "distance": "5"}) in records
