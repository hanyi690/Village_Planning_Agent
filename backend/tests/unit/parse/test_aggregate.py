"""Tests for the top-level PARSE aggregate (orchestrator + public API)."""
from __future__ import annotations

import pytest

from app.agent.parse.aggregate import compile_program, parse_aggregate
from app.modules.schema.contracts.parse_result_contracts import (
    CompilationPatch,
    CompilationStatus,
    ParseMode,
    PatchOperation,
)


def test_compile_program_compile_mode(planning_program):
    result, specs, gate_decision = compile_program(
        planning_program, run_id="r", context_version="cv"
    )

    assert gate_decision.stage == "parse"
    assert result.compilation_status in (
        CompilationStatus.DRAFT,
        CompilationStatus.VALIDATED,
    )
    assert len(specs) >= 1
    assert len(result.spatial_reference_specs) >= 1


def test_compile_program_empty_program_routes_human(empty_program):
    result, specs, gate_decision = compile_program(
        empty_program, run_id="r", context_version="cv"
    )

    assert gate_decision.feedback_route == "HUMAN"
    assert gate_decision.passed is False


def test_compile_program_repair_mode_applies_patch(planning_program):
    result, specs, gate_decision = compile_program(
        planning_program,
        run_id="r",
        context_version="cv",
        mode=ParseMode.REPAIR,
        patches=[
            CompilationPatch(
                field_path="typed_intent.project_targets.0.name",
                operation=PatchOperation.UPDATE,
                after="新名称",
                actor="user",
            )
        ],
    )

    assert len(result.patches) == 1
    assert result.typed_intent.project_targets[0].name == "新名称"


@pytest.mark.asyncio
async def test_parse_aggregate_persists_artifact_and_review(tmp_path, planning_program):
    result = await parse_aggregate(
        {"planning_program": planning_program, "run_id": "r", "context_version": "cv"},
        base_dir=str(tmp_path),
    )

    assert result["parse_result_ref"]["artifact_type"] == "IntentCompilationResult"
    assert result["parse_review_id"]
    assert result["parse_gate_decision"]["stage"] == "parse"

    payload = tmp_path / "r" / "artifacts" / "parse" / "parse-r-v1" / "v1" / "payload.json"
    assert payload.exists()
