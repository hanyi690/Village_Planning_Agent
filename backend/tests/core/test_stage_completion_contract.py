from __future__ import annotations

import ast
from pathlib import Path

from app.infrastructure.artifacts.repository import ContentAddressedArtifactRepository
from app.modules.schema.contracts.workflow_contracts import GateDecision
from app.modules.schema.contracts.artifact_descriptor import ArtifactDescriptor
from app.workflow.stage_adapter import StageCompletion, persist_gate_decision
from app.workflow.stages.support import stage_completion_patch


ROOT = Path(__file__).parents[2] / "app" / "workflow" / "stages"


def test_target_projection_ground_and_select_use_one_shared_completion_helper() -> None:
    for name in ("target_projection.py", "ground.py", "select.py"):
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "stage_completion_patch"
        ]
        assert len(calls) == 1, name
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = {
                key.value
                for key in node.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            assert "artifact_refs" not in keys, name
            assert not {"target_projection_gate", "ground_gate", "select_gate"}.intersection(keys), name


def test_stage_completion_patch_has_typed_immutable_gate_descriptor(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.infrastructure.paths.run_tmp_root", lambda: tmp_path)
    state = {
        "run_id": "run-stage-completion",
        "session_id": "run-stage-completion",
        "branch_id": "main",
        "context_ref": {"session_id": "run-stage-completion", "version": "ctx-1"},
    }
    gate = GateDecision(stage="ground", passed=True)

    patch = stage_completion_patch(
        state,
        "ground",
        output_refs={},
        gate=gate,
        context_patch={"context_fingerprint": "sha256:ctx"},
    )

    completion = StageCompletion.model_validate({
        "stage": "ground",
        "output_refs": {},
        "gate_ref": patch["gate_ref"],
    })
    assert isinstance(completion.gate_ref, ArtifactDescriptor)
    assert completion.gate_ref.schema_id == "GateDecision"
    assert completion.gate_ref.producer_stage == "ground"
    assert completion.gate_ref.digest.startswith("sha256:")
    assert "path" not in completion.gate_ref.model_dump()

    repository = ContentAddressedArtifactRepository(tmp_path)
    payload = repository.get_json(completion.gate_ref)
    assert GateDecision.model_validate(payload).stage == "ground"
    same_ref = persist_gate_decision(state, "ground", gate)
    assert same_ref.descriptor_digest == completion.gate_ref.descriptor_digest
