from pathlib import Path

from app.contracts.evidence.external_observation_contracts import ExternalObservation
from app.data.catalog.external_observation_cache import (
    cluster_external_observations,
    load_cached_external_observation_snapshot,
)


def _write_run(root: Path, provider: str, stage: str, rows: list[dict], *, manifest: bool = True) -> None:
    run = root / provider / stage / "runs" / "run-1"
    run.mkdir(parents=True)
    (run / "normalized_all.jsonl").write_text(
        "".join(__import__("json").dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    if manifest:
        (run / "manifest.json").write_text(
            __import__("json").dumps({"run_id": "run-1", "normalized_record_count": len(rows), "retained_candidate_count": len(rows)}),
            encoding="utf-8",
        )


def test_cache_loader_normalizes_provider_coordinates_and_preserves_aliases(tmp_path: Path):
    _write_run(
        tmp_path,
        "amap",
        "02_l1_place_names",
        [{
            "id": "a-1",
            "name": "金田村委会",
            "query_name": "村委会",
            "location": "116.044146,24.818629",
            "location_gcj02": [116.044146, 24.818629],
            "location_wgs84": [116.043, 24.819],
            "location_crs": "GCJ-02",
            "scope_bucket": "project_local",
        }],
    )
    _write_run(
        tmp_path,
        "tianditu",
        "01_admin_scope",
        [{
            "hotPointID": "t-1",
            "name": "金田村",
            "lonlat": "116.043,24.819",
            "location_wgs84": [116.043, 24.819],
            "scope_bucket": "project_local",
        }],
    )
    snapshot = load_cached_external_observation_snapshot("金田村", root=tmp_path)
    assert len(snapshot.observations) == 2
    amap = next(item for item in snapshot.observations if item.provider == "amap")
    assert amap.location_wgs84 == (116.043, 24.819)
    assert "村委会" in amap.aliases
    assert amap.raw_response_ref == ""
    assert snapshot.digest.startswith("sha256:")


def test_same_coordinate_observations_share_cluster_without_collapsing_rows():
    observations = [
        ExternalObservation(observation_id="a", provider="amap", stage="l1", observed_name="金田村委会", location_wgs84=(116.0, 24.0), coordinate_contract="WGS84 direct", coordinate_source_crs="WGS84", coordinate_target_crs="EPSG:4326", coordinate_trust_status="verified_direct", spatial_evidence_role="feature_location"),
        ExternalObservation(observation_id="t", provider="tianditu", stage="l1", observed_name="金田村委会", location_wgs84=(116.0001, 24.0001), coordinate_contract="WGS84 direct", coordinate_source_crs="CRS84", coordinate_target_crs="WGS84", coordinate_trust_status="verified_direct", spatial_evidence_role="feature_location"),
        ExternalObservation(observation_id="far", provider="tencent", stage="l1", observed_name="金田村委会", location_wgs84=(116.01, 24.01), coordinate_contract="WGS84 direct", coordinate_source_crs="WGS84", coordinate_target_crs="WGS84", coordinate_trust_status="verified_direct", spatial_evidence_role="feature_location"),
    ]
    clusters = cluster_external_observations(observations, tolerance_m=30)
    assert clusters["a"] == clusters["t"]
    assert clusters["a"] != clusters["far"]
    assert len(clusters) == 3


def test_co_located_distinct_names_do_not_share_entity_support():
    common = {
        "provider": "amap",
        "stage": "l1",
        "query_name": "金田村",
        "location_wgs84": (116.04, 24.82),
        "coordinate_contract": "WGS84 direct",
        "coordinate_source_crs": "WGS84",
        "coordinate_target_crs": "WGS84",
        "coordinate_trust_status": "verified_direct",
        "spatial_evidence_role": "feature_location",
    }
    observations = [
        ExternalObservation(
            observation_id="committee",
            observed_name="金田村委会",
            aliases=["金田村"],
            **common,
        ),
        ExternalObservation(
            observation_id="service",
            observed_name="退役军人服务站",
            aliases=["金田村"],
            **common,
        ),
    ]
    clusters = cluster_external_observations(observations, tolerance_m=30)
    assert clusters["committee"] != clusters["service"]


def test_tianditu_compatible_contract_is_unverified_and_bad_rows_are_isolated(tmp_path: Path):
    _write_run(
        tmp_path,
        "tianditu",
        "02_l1_place_names",
        [
            {"id": "good", "name": "金田村", "location_wgs84": [116.0, 24.0], "location_crs": "WGS84-compatible", "scope_bucket": "project_local"},
            {"id": "bad-target", "name": "金田村", "location_wgs84": [116.1, 24.1], "coordinate_contract": "WGS84 direct", "coordinate_source_crs": "WGS84", "coordinate_target_crs": "EPSG:3857", "scope_bucket": "project_local"},
            {"id": "bad", "name": "金田村", "location_wgs84": [float("nan"), 24.0], "scope_bucket": "project_local"},
        ],
    )
    snapshot = load_cached_external_observation_snapshot(
        "金田村", root=tmp_path, administrative_scope={"village": "金田村"}
    )
    assert {item.coordinate_trust_status for item in snapshot.observations} == {"unverified"}
    assert snapshot.excluded_counts["invalid_observation"] == 1


def test_interrupted_run_is_read_without_network_and_out_of_scope_is_counted(tmp_path: Path):
    _write_run(
        tmp_path,
        "amap",
        "01_admin_scope",
        [{
            "id": "a-1",
            "name": "梅江区结果",
            "location_wgs84": [116.1, 24.3],
            "scope_bucket": "meizhou_other",
        }],
        manifest=False,
    )
    snapshot = load_cached_external_observation_snapshot("金田村", root=tmp_path)
    assert snapshot.observations == []
    assert snapshot.excluded_counts["meizhou_other"] == 1
    assert snapshot.complete is False


def test_geocode_roles_separate_feature_locations_from_admin_fallbacks(tmp_path: Path):
    admin = {
        "province": "广东省",
        "city": "梅州市",
        "county": "平远县",
        "township": "泗水镇",
        "village": "金田村",
    }
    coordinate = {
        "location_gcj02": [116.045, 24.82],
        "location_wgs84": [116.04, 24.82],
        "coordinate_source_crs": "GCJ-02",
        "coordinate_target_crs": "WGS84",
        "coordinate_transform": "GCJ-02 converted once to WGS84",
        "coordinate_contract": "GCJ-02 converted once to WGS84",
        "scope_bucket": "project_local",
        **admin,
    }
    rows = [
        {
            **coordinate,
            "id": "coarse",
            "operation": "geocodes",
            "query_name": "广东省梅州市平远县泗水镇金田村古茶亭",
            "formatted_address": "广东省梅州市平远县泗水镇金田村",
            "level": "村庄",
        },
        {
            **coordinate,
            "id": "admin",
            "operation": "geocodes",
            "query_name": "广东省梅州市平远县泗水镇",
            "formatted_address": "广东省梅州市平远县泗水镇",
            "level": "乡镇",
        },
        {
            **coordinate,
            "id": "poi",
            "operation": "pois",
            "name": "古茶亭",
            "query_name": "古茶亭",
        },
    ]
    _write_run(tmp_path, "amap", "02_l1_place_names", rows)
    snapshot = load_cached_external_observation_snapshot(
        "金田村", root=tmp_path, administrative_scope=admin
    )
    by_ref = {item.source_record_ref: item for item in snapshot.observations}
    assert by_ref["coarse"].spatial_evidence_role == "coarse_geocode"
    assert by_ref["admin"].spatial_evidence_role == "administrative_anchor"
    assert by_ref["poi"].spatial_evidence_role == "feature_location"
    assert {
        item.coordinate_trust_status for item in by_ref.values()
    } == {"verified_transformed"}


def test_snapshot_identity_ignores_cache_root_but_tracks_content(tmp_path: Path):
    roots = [tmp_path / name for name in ("a", "b", "changed")]
    for root, name in zip(roots, ("古茶亭", "古茶亭", "古驿道")):
        _write_run(
            root,
            "amap",
            "02_l1_place_names",
            [{
                "id": "same-record",
                "operation": "pois",
                "name": name,
                "query_name": name,
                "raw_response_ref": str((root / "raw" / "response.json").resolve()),
                "scope_bucket": "project_local",
            }],
        )
    first = load_cached_external_observation_snapshot(
        root=roots[0], administrative_scope={}
    )
    second = load_cached_external_observation_snapshot(
        root=roots[1], administrative_scope={}
    )
    changed = load_cached_external_observation_snapshot(
        root=roots[2], administrative_scope={}
    )
    assert first.digest == second.digest
    assert first.snapshot_id == second.snapshot_id
    assert first.digest != changed.digest


def test_explicit_admin_values_must_all_match(tmp_path: Path):
    _write_run(
        tmp_path,
        "amap",
        "01_admin_scope",
        [{
            "id": "mixed-county",
            "name": "冲突记录",
            "province": "广东省",
            "city": "梅州市",
            "county": ["平远县", "梅江区"],
            "scope_bucket": "county_local",
        }],
    )
    snapshot = load_cached_external_observation_snapshot(
        root=tmp_path,
        administrative_scope={
            "province": "广东省",
            "city": "梅州市",
            "county": "平远县",
        },
    )
    assert snapshot.observations == []
    assert snapshot.excluded_counts["admin_conflict_county"] == 1
