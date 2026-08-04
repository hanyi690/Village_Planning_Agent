"""PARSE merge node tests - apply_patches (deterministic patch merger)."""
from __future__ import annotations

from app.agent.parse.compile_node import compile_program_deterministic
from app.agent.parse.merge_node import apply_patches
from app.modules.schema.contracts.parse_contracts import FacilityTarget
from app.modules.schema.contracts.parse_result_contracts import (
    CompilationPatch,
    CompilationStatus,
    PatchOperation,
)


def test_merge_update_patch(planning_program):
    result, _, _ = compile_program_deterministic(
        planning_program, run_id="r", context_version="cv"
    )
    patch = CompilationPatch(
        field_path="typed_intent.project_targets.0.name",
        operation=PatchOperation.UPDATE,
        after="新名称",
        actor="user",
    )
    merged = apply_patches(result, [patch], run_id="r")
    assert merged.typed_intent.project_targets[0].name == "新名称"
    assert merged.compilation_status == CompilationStatus.VALIDATED


def test_merge_add_patch(planning_program):
    result, _, _ = compile_program_deterministic(
        planning_program, run_id="r", context_version="cv"
    )
    before = len(result.typed_intent.facilities)
    patch = CompilationPatch(
        field_path="typed_intent.facilities",
        operation=PatchOperation.ADD,
        after=FacilityTarget(type="公厕", status="planned_new"),
        actor="user",
    )
    merged = apply_patches(result, [patch], run_id="r")
    assert len(merged.typed_intent.facilities) == before + 1
    assert merged.compilation_status == CompilationStatus.VALIDATED


def test_merge_invalid_path(planning_program):
    result, _, _ = compile_program_deterministic(
        planning_program, run_id="r", context_version="cv"
    )
    patch = CompilationPatch(
        field_path="bogus.path",
        operation=PatchOperation.UPDATE,
        after=1,
    )
    merged = apply_patches(result, [patch], run_id="r")
    assert any(d.code == "SCHEMA_MISMATCH" for d in merged.diagnostics)
    assert merged.compilation_status == CompilationStatus.NEEDS_REPAIR


def test_merge_original_unchanged(planning_program):
    result, _, _ = compile_program_deterministic(
        planning_program, run_id="r", context_version="cv"
    )
    original_name = result.typed_intent.project_targets[0].name
    patch = CompilationPatch(
        field_path="typed_intent.project_targets.0.name",
        operation=PatchOperation.UPDATE,
        after="新名称",
    )
    merged = apply_patches(result, [patch], run_id="r")
    assert result.typed_intent.project_targets[0].name == original_name
    assert merged.typed_intent.project_targets[0].name == "新名称"
