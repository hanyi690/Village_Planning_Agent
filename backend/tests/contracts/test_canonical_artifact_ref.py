from __future__ import annotations

from typing import get_type_hints

import pytest
from pydantic import ValidationError

from app.contracts.artifacts import ArtifactRef
from app.infrastructure.artifacts import ContentAddressedArtifactRepository
from app.contracts.artifacts.ref import ArtifactRef as ArtifactDescriptor
from app.contracts.workflow.execution_plan_contracts import ExecutionResult
from app.workflow.stage_adapter import StageCommand, StageCompletion
from app.workflow.state import WorkflowState, project_workflow_state


pytestmark = pytest.mark.contracts


def _ref_data(*, schema_id: str = "PlanningProgram") -> dict[str, object]:
    return {
        "digest": "sha256:" + "a" * 64,
        "descriptor_digest": "sha256:" + "b" * 64,
        "media_type": "application/json",
        "size_bytes": 42,
        "schema_id": schema_id,
        "schema_version": "3",
        "semantic_digest": "sha256:" + "c" * 64,
        "parent_digests": {"context": "sha256:" + "d" * 64},
        "producer_stage": "execute",
        "run_id": "run-1",
        "branch_id": "main",
        "provenance": {"artifact_key": "planning_program"},
    }


def test_artifact_ref_is_frozen_canonical_descriptor_and_round_trips() -> None:
    ref = ArtifactRef.model_validate(_ref_data())

    assert ArtifactDescriptor is ArtifactRef
    assert ArtifactRef.model_validate_json(ref.model_dump_json()) == ref
    with pytest.raises(ValidationError, match="frozen"):
        ref.run_id = "other-run"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("path", "C:/tmp/artifact.json"),
        ("revision", "v2"),
        ("latest", True),
    ],
)
def test_artifact_ref_rejects_legacy_locator_fields(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ArtifactRef.model_validate({**_ref_data(), field: value})


def test_artifact_ref_rejects_invalid_digest_and_missing_identity() -> None:
    with pytest.raises(ValidationError):
        ArtifactRef.model_validate({**_ref_data(), "digest": "artifact-1"})
    with pytest.raises(ValidationError):
        ArtifactRef.model_validate({**_ref_data(), "run_id": ""})


def test_execution_result_rejects_incomplete_child_ref_and_accepts_valid_refs() -> None:
    refs = {
        "approved_input_ref": _ref_data(schema_id="ApprovedExecutionInput"),
        "execution_plan_ref": _ref_data(schema_id="ExecutionPlan"),
        "parcel_changeset_ref": _ref_data(schema_id="ParcelChangeSet"),
        "planned_state_ref": _ref_data(schema_id="PlannedState"),
        "layout_configs_ref": _ref_data(schema_id="LayoutConfigs"),
        "atomic_commit_id": "commit:canonical",
        "atomic_commit_status": "committed",
    }

    with pytest.raises(ValidationError):
        ExecutionResult(**{**refs, "planned_state_ref": {"descriptor_digest": "planned"}})

    result = ExecutionResult(**refs)

    assert isinstance(result.execution_plan_ref, ArtifactRef)
    assert isinstance(result.parcel_changeset_ref, ArtifactRef)
    assert isinstance(result.planned_state_ref, ArtifactRef)
    assert isinstance(result.layout_configs_ref, ArtifactRef)
    assert result.deferral_ledger_ref is None


def test_stage_boundaries_validate_artifact_refs_and_reject_invalid_gate() -> None:
    command = StageCommand(
        run_id="run-1",
        branch_id="main",
        context_ref={"session_id": "run-1", "version": "ctx-1"},
        input_refs={"planning_program": _ref_data()},
    )

    assert isinstance(command.input_refs["planning_program"], ArtifactRef)
    with pytest.raises(ValidationError):
        StageCompletion(
            stage="validate",
            output_refs={},
            gate_ref={"descriptor_digest": "gate"},
        )


def test_workflow_state_annotations_and_projection_preserve_canonical_refs() -> None:
    annotations = get_type_hints(WorkflowState)
    ref = ArtifactRef.model_validate(_ref_data())

    assert annotations["artifact_refs"] == dict[str, ArtifactRef]
    assert annotations["gate_ref"] == ArtifactRef | None
    assert annotations["interrupt_ref"] == ArtifactRef | None
    assert annotations["terminal_ref"] == ArtifactRef | None

    projected = project_workflow_state(
        {
            "artifact_refs": {"planning_program": ref},
            "gate_ref": ref,
            "interrupt_ref": ref,
            "terminal_ref": ref,
        }
    )

    assert projected["artifact_refs"]["planning_program"] is ref
    assert projected["gate_ref"] is ref
    assert projected["interrupt_ref"] is ref
    assert projected["terminal_ref"] is ref


def test_cas_repository_stores_and_reloads_canonical_ref(tmp_path) -> None:
    repository = ContentAddressedArtifactRepository(tmp_path)
    stored = repository.put_json(
        {"projects": [{"id": "project-1"}]},
        schema_id="PlanningProgram",
        schema_version="3",
        producer_stage="program",
        run_id="run-1",
        branch_id="main",
    )

    reloaded = repository.get_descriptor(stored.descriptor_digest)

    assert isinstance(stored, ArtifactRef)
    assert isinstance(reloaded, ArtifactRef)
    assert reloaded == stored
    assert repository.get_json(reloaded) == {"projects": [{"id": "project-1"}]}
