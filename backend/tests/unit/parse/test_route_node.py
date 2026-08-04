"""PARSE route node tests - route_compilation (Hybrid routing skeleton)."""
from __future__ import annotations

from app.agent.parse.route_node import route_compilation
from app.modules.schema.contracts.parse_result_contracts import (
    IntentCompilationResult,
    ParseDiagnostic,
)


def _diag(code: str, severity: str = "warning") -> ParseDiagnostic:
    return ParseDiagnostic(severity=severity, code=code)


def test_route_no_diagnostics_merge():
    result = IntentCompilationResult()
    assert route_compilation(result, []) == "merge"


def test_route_error_diagnostic_human_review():
    result = IntentCompilationResult()
    diags = [_diag("AMBIGUOUS_REFERENCE"), _diag("TABLE_CORRUPT", "error")]
    assert route_compilation(result, diags) == "human_review"


def test_route_three_ambiguous_llm_patch():
    result = IntentCompilationResult()
    diags = [_diag("AMBIGUOUS_REFERENCE") for _ in range(3)]
    assert route_compilation(result, diags) == "llm_patch"


def test_route_two_ambiguous_merge():
    result = IntentCompilationResult()
    diags = [_diag("AMBIGUOUS_REFERENCE") for _ in range(2)]
    assert route_compilation(result, diags) == "merge"
