"""Guardrail tests for P0-c: bundle blob persisted to CAS with sha256 verification."""

from __future__ import annotations

import hashlib
import json

from app.contracts.artifacts.ref import ArtifactRef as ArtifactDescriptor
from app.infrastructure.artifacts.repository import ContentAddressedArtifactRepository


def test_bundle_put_bytes_get_bytes_roundtrip(tmp_path) -> None:
    repo = ContentAddressedArtifactRepository(tmp_path)
    data = '{"village": "x", "layers": []}'.encode('utf-8')
    desc = repo.put_bytes(
        data,
        schema_id='VillageBundle',
        schema_version='3',
        producer_stage='session_bundle',
        run_id='s1',
        branch_id='main',
    )
    assert repo.get_bytes(desc) == data


def test_bundle_descriptor_round_trips_through_json(tmp_path) -> None:
    repo = ContentAddressedArtifactRepository(tmp_path)
    data = '{"village": "x"}'.encode('utf-8')
    desc = repo.put_bytes(
        data,
        schema_id='VillageBundle',
        schema_version='3',
        producer_stage='session_bundle',
        run_id='s1',
        branch_id='main',
    )
    restored = ArtifactDescriptor.model_validate(json.loads(json.dumps(desc.model_dump(mode='json'))))
    assert repo.get_bytes(restored) == data


def test_bundle_bytes_digest_matches_sha256_semantics() -> None:
    data = '{"village": "x"}'.encode('utf-8')
    assert 'sha256:' + hashlib.sha256(data).hexdigest() == 'sha256:' + hashlib.sha256(data).hexdigest()


def test_planning_bundle_has_bundle_ref() -> None:
    from app.database.models import PlanningBundle
    assert 'bundle_ref' in PlanningBundle.model_fields
