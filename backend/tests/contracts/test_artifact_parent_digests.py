from __future__ import annotations

import pytest

from app.infrastructure.artifacts.runtime import store_artifact
from app.infrastructure.artifacts import ContentAddressedArtifactRepository


pytestmark = pytest.mark.contracts


def test_runtime_records_parent_blob_digests_and_excludes_current_key(tmp_path) -> None:
    state = {
        'run_id': 'run-1',
        'session_id': 'session-1',
        'context_version': 'ctx-1',
        'context_fingerprint': 'fp-1',
        'artifact_refs': {},
    }
    l1 = store_artifact(state, 'l1_snapshot', 'l1_observe', 'L1Snapshot', {'facts': ['a']}, base_dir=tmp_path)
    l2 = store_artifact(
        {**state, 'artifact_refs': {'l1_snapshot': l1}},
        'l2_strategy', 'l2_strategize', 'L2Strategy', {'goals': ['b']}, base_dir=tmp_path,
    )
    program = store_artifact(
        {**state, 'artifact_refs': {'l1_snapshot': l1, 'l2_strategy': l2}},
        'planning_program', 'l3_plan', 'PlanningProgram', {'steps': ['draft']}, base_dir=tmp_path,
    )

    assert program['parent_digests'] == {
        'l1_snapshot': l1['digest'],
        'l2_strategy': l2['digest'],
    }
    assert 'planning_program' not in program['parent_digests']

    repository = ContentAddressedArtifactRepository(tmp_path)
    descriptor = repository.get_descriptor(program['descriptor_digest'])
    assert descriptor.parent_digests == program['parent_digests']
