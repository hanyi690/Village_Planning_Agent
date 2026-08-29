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
        ExternalObservation(observation_id="a", provider="amap", stage="l1", location_wgs84=(116.0, 24.0)),
        ExternalObservation(observation_id="t", provider="tianditu", stage="l1", location_wgs84=(116.0001, 24.0001)),
        ExternalObservation(observation_id="far", provider="tencent", stage="l1", location_wgs84=(116.01, 24.01)),
    ]
    clusters = cluster_external_observations(observations, tolerance_m=30)
    assert clusters["a"] == clusters["t"]
    assert clusters["a"] != clusters["far"]
    assert len(clusters) == 3


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
