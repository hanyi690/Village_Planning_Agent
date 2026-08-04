"""Tests for the top-level PARSE compile node (deterministic extraction)."""
from __future__ import annotations

from app.agent.parse.compile_node import compile_program_deterministic
from app.modules.schema.contracts.parse_result_contracts import (
    CompilationStatus,
    ParseMode,
)


def test_compile_program_deterministic_full_program(planning_program):
    result, specs, diagnostics = compile_program_deterministic(
        planning_program,
        run_id="run-1",
        context_version="cv1",
        program_ref="l3-xxx-v1",
    )

    assert result.compilation_status == CompilationStatus.DRAFT
    assert len(result.typed_intent.project_targets) == 1
    assert len(result.typed_intent.facilities) == 1
    assert len(result.typed_intent.road_targets) == 1
    assert result.typed_intent is result.intent
    assert len(result.spatial_reference_specs) >= 1
    assert len(result.project_requirements) == 1
    assert result.trace.mode == ParseMode.COMPILE
    assert result.provenance.source == "parse"


def test_compile_program_deterministic_empty_program(empty_program):
    result, specs, diagnostics = compile_program_deterministic(empty_program)

    assert any(d.code == "EMPTY_PROGRAM" for d in result.diagnostics)
    assert len(result.typed_intent.project_targets) == 0


def test_compile_program_spec_mapping_sanity(planning_program):
    result, specs, diagnostics = compile_program_deterministic(planning_program)

    spec_types = {s.type for s in result.spatial_reference_specs}
    assert "composed" in spec_types or "topological" in spec_types
