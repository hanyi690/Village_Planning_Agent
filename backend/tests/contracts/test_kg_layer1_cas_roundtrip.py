"""Guardrail: KG Layer-1 turtle persists to CAS and round-trips by ref."""

from __future__ import annotations


def test_kg_layer1_cas_roundtrip(tmp_path):
    from app.infrastructure.artifacts.repository import ContentAddressedArtifactRepository

    repo = ContentAddressedArtifactRepository(tmp_path)
    desc = repo.put_json(
        "village turtle payload",
        schema_id="KGLayer1Turtle",
        schema_version="3",
        producer_stage="session_kg",
        run_id="s1",
        branch_id="main",
        parent_digests={"bundle": "digest-abc"},
    )
    repo.compare_and_set_named_ref(
        "s1", "main", "kg_layer1", desc, expected_descriptor_digest=None
    )
    ref = repo.get_named_ref("s1", "main", "kg_layer1")
    assert ref is not None
    assert ref.parent_digests.get("bundle") == "digest-abc"
    assert repo.get_json(ref) == "village turtle payload"


def test_kg_layer1_key_registered():
    from app.infrastructure.artifacts.runtime import ARTIFACT_KEYS

    assert "kg_layer1" in ARTIFACT_KEYS
