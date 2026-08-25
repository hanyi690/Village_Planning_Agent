"""Bounded P3 golden benchmark, accounting, and replay acceptance tests."""

from pathlib import Path

from app.acceptance.p3_benchmark import (
    build_accounting,
    recorded_replay_acceptance_matrix,
    run_golden_benchmark,
)


MANIFEST = Path(__file__).parents[1] / "fixtures" / "p3_golden_manifest.json"


def test_golden_benchmark_is_byte_stable_and_declares_required_cases() -> None:
    first = run_golden_benchmark(MANIFEST)
    second = run_golden_benchmark(MANIFEST)
    assert first == second
    assert {case["scope"] for case in first["cases"]} == {
        "exact_parcel", "multi_parcel", "coarse_search", "overlay",
        "network_coverage", "human", "not_groundable", "solver_deferred",
    }
    assert first["metrics"]["human_escalation"]["count"] == 4


def test_incomplete_fixture_is_human_required_and_accounting_detects_drop_duplicate() -> None:
    report = run_golden_benchmark(MANIFEST)
    assert any(case["expected"] == "incomplete" for case in report["cases"])
    accounting = build_accounting({
        "L1_fact": [{"ref": "fact:1", "area": 10}],
        "L2_dimension": [{"ref": "dim:1", "parent_refs": ["fact:1"]}],
        "L3_claim": [{"ref": "claim:1", "parent_refs": ["missing:fact"]}, {"ref": "claim:1", "parent_refs": ["fact:1"]}],
    })
    assert accounting["status"] == "incomplete"
    assert {issue["kind"] for issue in accounting["issues"]} == {"drop", "duplicate"}


def test_recorded_replay_matrix_is_read_only_and_separates_live_provider() -> None:
    matrix = recorded_replay_acceptance_matrix(recorded_session=MANIFEST.parent)
    assert {row["outcome"] for row in matrix["rows"]} == {
        "success", "human_required", "not_groundable", "solver_deferred",
    }
    assert all(row["replay_passed"] for row in matrix["rows"])
    assert all(not row["live_provider_passed"] for row in matrix["rows"])
    assert all(set(row["artifacts"]) == {"route", "artifact", "gate", "certificate", "output_accounting"} for row in matrix["rows"])
