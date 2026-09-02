from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from app.data.catalog.provider_run_lease import (
    ProviderFenceViolation,
    ProviderLeaseConflict,
    ProviderObservationWriter,
    ProviderRunLeaseStore,
)


def test_active_lease_is_exclusive_and_reclaim_increments_fence(tmp_path):
    store_a = ProviderRunLeaseStore(tmp_path)
    store_b = ProviderRunLeaseStore(tmp_path)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    lease = store_a.acquire("run-1", "amap", "worker-a", ttl_seconds=10, now=start)

    with pytest.raises(ProviderLeaseConflict):
        store_b.acquire("run-1", "amap", "worker-b", ttl_seconds=10, now=start + timedelta(seconds=1))

    reclaimed = store_b.acquire("run-1", "amap", "worker-b", ttl_seconds=10, now=start + timedelta(seconds=11))
    assert reclaimed.fencing_token == lease.fencing_token + 1
    with pytest.raises(ProviderFenceViolation):
        store_a.assert_writer(lease, now=start + timedelta(seconds=11))


def test_writer_publishes_atomic_manifest_and_rejects_stale_writer(tmp_path):
    start = datetime.now(timezone.utc)
    store = ProviderRunLeaseStore(tmp_path)
    lease = store.acquire("run-2", "tianditu", "worker-a", ttl_seconds=10, now=start)
    writer = ProviderObservationWriter(tmp_path, "tianditu", "run-2")
    path = writer.publish(
        lease,
        [{"observation_id": "o1", "location_wgs84": [116.0, 24.0]}],
        boundary_digest="sha256:boundary",
        query_geometry_digest="sha256:query",
        crs_contract="source=WGS84; target=WGS84; transform=identity",
        coverage={"coverage_status": "COMPLETE", "expected": 1, "completed": 1},
    )
    assert (path / "manifest.json").is_file()
    assert (path / "normalized_all.jsonl").read_text(encoding="utf-8").count("\n") == 1
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "success_nonempty"
    assert manifest["published"] is True
    assert manifest["fencing_token"] == lease.fencing_token

    store.release(lease, now=start + timedelta(seconds=1))
    with pytest.raises(ProviderFenceViolation):
        writer.publish(
            lease,
            [],
            boundary_digest="sha256:boundary",
            query_geometry_digest="sha256:query",
            crs_contract="source=WGS84; target=WGS84; transform=identity",
            coverage={"coverage_status": "PARTIAL"},
        )


def test_expired_run_recovery_marks_staging_abandoned(tmp_path):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store = ProviderRunLeaseStore(tmp_path)
    lease = store.acquire("run-3", "tencent", "worker-a", ttl_seconds=1, now=start)
    staging = tmp_path / "tencent" / "runs" / "run-3"
    staging.mkdir(parents=True)
    recovery = store.recover("run-3", "tencent", now=start + timedelta(seconds=2))
    assert recovery.status == "RECOVERED"
    assert recovery.previous_fencing_token == lease.fencing_token
    assert '"ABANDONED"' in (staging / "recovery.json").read_text(encoding="utf-8")
