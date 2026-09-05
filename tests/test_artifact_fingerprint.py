from app.infrastructure.artifacts.fingerprint import (
    semantic_checksum,
    semantic_checksum_json,
)
from app.infrastructure.artifacts.repository import ContentAddressedArtifactRepository


def test_json_safe_checksum_fast_path_preserves_stable_payload_identity() -> None:
    payload = {
        "snapshot_id": "snapshot-1",
        "features": [
            {"source_feature_ref": "1", "geometry_kind": "polygon"},
            {"source_feature_ref": "2", "geometry_kind": "line"},
        ],
    }

    assert semantic_checksum_json(payload) == semantic_checksum(payload)


def test_json_safe_checksum_still_filters_semantic_volatile_fields() -> None:
    first = {
        "schema_version": "3",
        "artifact_id": "runtime-id-1",
        "created_at": "2026-09-04T00:00:00Z",
        "value": {"name": "金田村"},
    }
    second = {
        **first,
        "artifact_id": "runtime-id-2",
        "created_at": "2026-09-04T00:00:01Z",
    }

    assert semantic_checksum_json(first) == semantic_checksum_json(second)
    assert semantic_checksum_json(first) == semantic_checksum(first)


def test_cas_reuses_verified_descriptor_without_reloading_it(tmp_path) -> None:
    repository = ContentAddressedArtifactRepository(tmp_path)
    descriptor = repository.put_json(
        {"value": "immutable"},
        schema_id="TestArtifact",
        schema_version="1",
        producer_stage="test",
        run_id="run-1",
        branch_id="main",
    )

    def fail_if_reloaded(_path):
        raise AssertionError("descriptor should come from the immutable cache")

    repository._read_json = fail_if_reloaded
    assert repository.get_descriptor(descriptor.descriptor_digest) is descriptor
