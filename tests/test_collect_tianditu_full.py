from pathlib import Path

from shapely.geometry import Polygon

from scripts.collect_tianditu_full import (
    TiandituCollectorConfig,
    TiandituRequestJob,
    TiandituTransport,
    build_admin_jobs,
    classify_tianditu_response,
    normalize_tianditu_record,
    paginate_offsets,
    polygon_chunks,
    request_key,
)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = payload if isinstance(payload, str) else ""

    def json(self):
        if isinstance(self._payload, str):
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def test_admin_category_jobs_use_village_scope_bbox_and_show_two():
    context = {
        "bbox_wgs84": [116.02, 24.80, 116.10, 24.86],
        "boundary_geometry_wgs84": Polygon(
            [(116.02, 24.80), (116.10, 24.80), (116.10, 24.86), (116.02, 24.86)]
        ),
        "expanded_geometry_wgs84": Polygon(
            [(116.01, 24.79), (116.11, 24.79), (116.11, 24.87), (116.01, 24.87)]
        ),
    }
    config = TiandituCollectorConfig(
        scope_codes={"project": "金田村", "township": "泗水镇", "county": "平远县", "city": "梅州市"},
        categories=("学校",),
    )

    jobs = build_admin_jobs(context, config)
    category_jobs = [job for job in jobs if job.operation == "td_search_category"]
    all_jobs = [job for job in jobs if job.operation == "td_search_category_all"]

    assert category_jobs
    assert len(all_jobs) == 2
    assert all("dataTypes" not in job.params for job in all_jobs)
    assert all(job.params["mapBound"] for job in all_jobs)
    assert all(job.params["queryType"] == 13 for job in category_jobs)
    assert all(
        job.params["mapBound"] == "116.02,24.8,116.1,24.86"
        for job in category_jobs
        if job.scope == "project" and job.partition == "project_bbox"
    )
    assert all(job.params["show"] == 2 for job in category_jobs)
    assert any(job.params["specify"] == "金田村" for job in category_jobs)


def test_polygon_chunks_have_at_most_twenty_vertices_and_close_ring():
    points = [(116.0 + index * 0.001, 24.8 + (index % 3) * 0.001) for index in range(45)]
    geometry = Polygon(points + [points[0]])

    chunks = polygon_chunks(geometry, max_vertices=20)

    assert len(chunks) > 1
    for chunk in chunks:
        coordinates = [float(value) for value in chunk.split(",")]
        pairs = list(zip(coordinates[::2], coordinates[1::2]))
        assert len(pairs) <= 20
        assert pairs[0] == pairs[-1]


def test_pagination_stops_before_provider_start_limit_and_shards_over_500():
    assert paginate_offsets(0) == [0]
    assert paginate_offsets(500) == [0, 300]
    assert paginate_offsets(501, shard_size=250) == [0, 250, 500]


def test_empty_success_is_not_missing_provider_failure():
    result = classify_tianditu_response(200, {"status": {"infocode": 1000}, "count": 0, "pois": []})

    assert result["status"] == "success_empty"
    assert result["retryable"] is False


def test_transient_error_is_retryable_but_parameter_error_is_not():
    transient = classify_tianditu_response(503, {"status": {"infocode": 3000}})
    invalid = classify_tianditu_response(200, {"status": {"infocode": 2003}})

    assert transient["status"] == "failed"
    assert transient["retryable"] is True
    assert invalid["status"] == "failed"
    assert invalid["retryable"] is False


def test_wfs_service_exception_is_failed_not_success_empty():
    result = classify_tianditu_response(
        200,
        {"_raw_text": "<ServiceExceptionReport><ServiceException>denied</ServiceException></ServiceExceptionReport>"},
    )

    assert result["status"] == "failed"
    assert result["failure_class"] == "malformed_or_service_exception"
    assert result["retryable"] is False


def test_wfs_capabilities_xml_is_nonempty_success():
    result = classify_tianditu_response(200, {"_raw_text": "<WFS_Capabilities><FeatureTypeList /></WFS_Capabilities>"})

    assert result["status"] == "success_nonempty"


def test_tianditu_coordinates_are_wgs84_without_gcj_conversion():
    row = normalize_tianditu_record(
        {"name": "金田村", "lonlat": "116.044146,24.818629"},
        raw_response="output/raw.json",
        operation="td_search_category",
    )

    assert row["location_wgs84"] == [116.044146, 24.818629]
    assert row["coordinate_contract"] == "Tianditu documented lon/lat; WGS84-compatible"


def test_wfs_feature_keeps_geometry_and_derives_wgs84_centroid():
    row = normalize_tianditu_record(
        {
            "type": "Feature",
            "properties": {"NAME": "道路"},
            "geometry": {"type": "LineString", "coordinates": [[116.0, 24.0], [116.2, 24.0]]},
        },
        raw_response="output/raw.json",
        operation="td_wfs_feature",
    )

    assert row["NAME"] == "道路"
    assert row["source_geometry"]["type"] == "LineString"
    assert row["location_wgs84"] == [116.1, 24.0]


def test_request_key_excludes_secret_and_is_stable(tmp_path: Path):
    left = request_key("https://api.tianditu.gov.cn/v2/search", {"tk": "secret", "queryType": 13})
    right = request_key("https://api.tianditu.gov.cn/v2/search", {"queryType": 13})

    assert left == right
    assert tmp_path.exists()


def test_transport_retries_transient_failure_and_persists_attempts(tmp_path, monkeypatch):
    import scripts.collect_tianditu_full as module

    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    session = FakeSession(
        [
            FakeResponse(503, {"status": {"infocode": 3000}}),
            FakeResponse(200, {"status": {"infocode": 1000}, "pois": [{"name": "学校", "lonlat": "116,24"}]}),
        ]
    )
    config = TiandituCollectorConfig(output_root=tmp_path, min_interval=0, max_retries=3)
    stage_dir = tmp_path / "01_admin_scope"
    transport = TiandituTransport(config, stage_dir, api_key="test-key", session=session)
    job = TiandituRequestJob("td_search_category", "https://example.test", {"queryType": 13})

    result = transport.request(job, stage_dir / "runs" / "test")

    assert result.status == "success_nonempty"
    assert result.attempts == 2
    assert session.calls == 2
    assert (stage_dir / "runs" / "test" / "attempts.jsonl").read_text(encoding="utf-8").count("attempt") == 2


def test_transport_reuses_cached_raw_response_without_network(tmp_path, monkeypatch):
    import scripts.collect_tianditu_full as module

    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    config = TiandituCollectorConfig(output_root=tmp_path, min_interval=0, max_retries=1)
    stage_dir = tmp_path / "01_admin_scope"
    job = TiandituRequestJob("td_search_category", "https://example.test", {"queryType": 13})
    first = TiandituTransport(config, stage_dir, api_key="test-key", session=FakeSession([FakeResponse(200, {"pois": [{"name": "学校", "lonlat": "116,24"}]} )]))
    first_result = first.request(job, stage_dir / "runs" / "first")
    second_session = FakeSession([])
    second = TiandituTransport(config, stage_dir, api_key="test-key", session=second_session)
    second_result = second.request(job, stage_dir / "runs" / "second")

    assert first_result.status == "success_nonempty"
    assert second_result.cache_hit is True
    assert second_result.raw_response == first_result.raw_response
    assert second_session.calls == 0
