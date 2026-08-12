from __future__ import annotations

import pytest

from app.infrastructure.artifacts.runtime import (
    fork_artifact_refs,
    load_artifact,
    store_artifact,
)
from app.infrastructure.artifacts import ContentAddressedArtifactRepository


pytestmark = pytest.mark.contracts


def _state(tmp_path, *, branch_id: str = 'main', refs=None) -> dict:
    return {
        'run_id': 'run-runtime',
        'session_id': 'session-runtime',
        'branch_id': branch_id,
        'context_version': 'ctx-1',
        'context_fingerprint': 'context-fingerprint',
        'artifact_schema_version': '3',
        'artifact_refs': refs or {},
        'artifact_base_dir': str(tmp_path),
    }


def test_runtime_stores_descriptor_and_replays_from_same_descriptor(tmp_path) -> None:
    state = _state(tmp_path)
    payload = {'decisions': [{'id': 'site-1'}]}

    first = store_artifact(state, 'site_selection', 'allocation', 'SiteSelectionDecision', payload, base_dir=tmp_path)
    replay = store_artifact({**state, 'artifact_refs': {'site_selection': first}}, 'site_selection', 'allocation', 'SiteSelectionDecision', payload, base_dir=tmp_path)

    assert set(('digest', 'descriptor_digest', 'parent_digests')).issubset(first)
    assert 'revision' not in first
    assert replay['descriptor_digest'] == first['descriptor_digest']
    assert load_artifact({**state, 'artifact_refs': {'site_selection': first}}, 'site_selection', base_dir=tmp_path) == payload


def test_runtime_fork_reuses_blob_but_has_branch_descriptor(tmp_path) -> None:
    payload = {'decisions': [{'id': 'site-1'}]}
    main = store_artifact(_state(tmp_path), 'site_selection', 'allocation', 'SiteSelectionDecision', payload, base_dir=tmp_path)
    fork = store_artifact(_state(tmp_path, branch_id='fork-cp-1'), 'site_selection', 'allocation', 'SiteSelectionDecision', payload, base_dir=tmp_path)

    assert fork['digest'] == main['digest']
    assert fork['descriptor_digest'] != main['descriptor_digest']
    assert fork['branch_id'] == 'fork-cp-1'


def test_runtime_rejects_old_revision_reference(tmp_path) -> None:
    with pytest.raises(ValueError, match='ArtifactDescriptor'):
        load_artifact({**_state(tmp_path), 'artifact_refs': {'site_selection': {'revision': 'v1'}}}, 'site_selection', base_dir=tmp_path)


def test_checkpoint_fork_clones_refs_and_reuses_payload_bytes(tmp_path) -> None:
    state = _state(tmp_path)
    original = store_artifact(
        state,
        'site_selection',
        'allocation',
        'SiteSelectionDecision',
        {'decisions': [{'id': 'site-1'}]},
        base_dir=tmp_path,
    )
    forked_refs = fork_artifact_refs(
        {**state, 'artifact_refs': {'site_selection': original}},
        'fork-checkpoint-1',
        base_dir=tmp_path,
    )
    forked = forked_refs['site_selection']

    assert forked['digest'] == original['digest']
    assert forked['descriptor_digest'] != original['descriptor_digest']
    assert forked['branch_id'] == 'fork-checkpoint-1'
    assert load_artifact(
        {
            **state,
            'branch_id': 'fork-checkpoint-1',
            'artifact_refs': forked_refs,
        },
        'site_selection',
        base_dir=tmp_path,
    ) == {'decisions': [{'id': 'site-1'}]}
