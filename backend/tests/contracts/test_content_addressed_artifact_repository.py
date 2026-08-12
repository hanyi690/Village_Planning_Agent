from __future__ import annotations

import pytest

from app.infrastructure.artifacts import ContentAddressedArtifactRepository, NamedRefConflict


pytestmark = pytest.mark.contracts


def _put(repository: ContentAddressedArtifactRepository, *, branch_id: str = 'main', parents=None):
    return repository.put_json(
        {'projects': [{'id': 'project-1', 'area_m2': 1200}]},
        schema_id='PlanningProgram',
        schema_version='1.0',
        producer_stage='program',
        run_id='run-1',
        branch_id=branch_id,
        parent_digests=parents,
        provenance={'source': 'contract-test'},
    )


def test_identical_payload_reuses_blob_but_not_cross_branch_descriptor(tmp_path) -> None:
    repository = ContentAddressedArtifactRepository(tmp_path)

    main = _put(repository)
    replay = _put(repository)
    fork = _put(repository, branch_id='fork-checkpoint-a')

    assert replay.descriptor_digest == main.descriptor_digest
    assert fork.digest == main.digest
    assert fork.descriptor_digest != main.descriptor_digest
    assert repository.get_json(fork) == {'projects': [{'id': 'project-1', 'area_m2': 1200}]}


def test_named_ref_requires_expected_descriptor_and_preserves_old_descriptor(tmp_path) -> None:
    repository = ContentAddressedArtifactRepository(tmp_path)
    first = _put(repository)
    second = repository.put_json(
        {'projects': [{'id': 'project-2', 'area_m2': 2400}]},
        schema_id='PlanningProgram',
        schema_version='1.0',
        producer_stage='program',
        run_id='run-1',
        branch_id='main',
    )

    repository.compare_and_set_named_ref(
        'run-1', 'main', 'planning_program', first, expected_descriptor_digest=None,
    )
    with pytest.raises(NamedRefConflict, match='stale named ref'):
        repository.compare_and_set_named_ref(
            'run-1', 'main', 'planning_program', second, expected_descriptor_digest=None,
        )

    assert repository.get_named_ref('run-1', 'main', 'planning_program') == first
    assert repository.get_json(first)['projects'][0]['id'] == 'project-1'


def test_parent_digest_changes_descriptor_identity_without_mutating_blob(tmp_path) -> None:
    repository = ContentAddressedArtifactRepository(tmp_path)

    before = _put(repository, parents={'assessment': 'sha256:' + 'a' * 64})
    after = _put(repository, parents={'assessment': 'sha256:' + 'b' * 64})

    assert before.digest == after.digest
    assert before.descriptor_digest != after.descriptor_digest
