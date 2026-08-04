"""PARSE gate node tests - evaluate_parse_gate (4-route gate)."""
from __future__ import annotations

from app.agent.parse.compile_node import compile_program_deterministic
from app.agent.parse.gate_node import evaluate_parse_gate
from app.modules.schema.contracts.parse_result_contracts import (
    CompilationPatch,
    CompilationStatus,
)


def test_gate_pass(planning_program):
    result, _, _ = compile_program_deterministic(
        planning_program, run_id="r", context_version="cv"
    )
    result.compilation_status = CompilationStatus.VALIDATED
    d = evaluate_parse_gate(result, context_version="cv")
    assert d.passed is True
    assert d.feedback_route is None
    assert d.stage == "parse"


def test_gate_repair(planning_program):
    result, _, _ = compile_program_deterministic(
        planning_program, run_id="r", context_version="cv"
    )
    result.compilation_status = CompilationStatus.NEEDS_REPAIR
    result.patches = [CompilationPatch(patch_id=f"p{i}") for i in range(2)]
    d = evaluate_parse_gate(result, context_version="cv")
    assert d.passed is False
    assert d.feedback_route == "REPAIR"
    assert any(r.request_id == "pr-parse-repair" for r in d.pending_requests)


def test_gate_revise(planning_program):
    result, _, _ = compile_program_deterministic(
        planning_program, run_id="r", context_version="cv"
    )
    result.compilation_status = CompilationStatus.NEEDS_REPAIR
    result.patches = [CompilationPatch(patch_id=f"p{i}") for i in range(7)]
    d = evaluate_parse_gate(result, context_version="cv")
    assert d.passed is False
    assert d.feedback_route == "REVISE"
    assert any(r.request_id == "pr-parse-revise" for r in d.pending_requests)


def test_gate_human_needs_review(planning_program):
    result, _, _ = compile_program_deterministic(
        planning_program, run_id="r", context_version="cv"
    )
    result.compilation_status = CompilationStatus.NEEDS_REVIEW
    d = evaluate_parse_gate(result, context_version="cv")
    assert d.passed is False
    assert d.feedback_route == "HUMAN"


def test_gate_human_empty(empty_program):
    result, _, _ = compile_program_deterministic(
        empty_program, run_id="r", context_version="cv"
    )
    result.compilation_status = CompilationStatus.VALIDATED
    d = evaluate_parse_gate(result, context_version="cv")
    assert d.passed is False
    assert d.feedback_route == "HUMAN"
