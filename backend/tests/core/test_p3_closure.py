"""Behavioral P3 golden benchmark, accounting, and replay acceptance tests."""

import hashlib
import json
from pathlib import Path

from app.acceptance.p3_benchmark import (
    build_accounting,
    canonical_fingerprint,
    recorded_replay_acceptance_matrix,
    run_golden_benchmark,
)


MANIFEST = Path(__file__).parents[1] / "fixtures" / "p3_golden_manifest.json"
RECORDED_FIXTURE = Path(__file__).parents[1] / "fixtures" / "p3_recorded_replay"


def _complete_chain(suffix: str) -> dict[str, list[dict[str, object]]]:
    return {
        "L1_fact": [{"ref": f"fact:{suffix}"}],
        "L2_dimension": [{"ref": f"dimension:{suffix}", "parent_refs": f"fact:{suffix}"}],
        "L3_claim": [{"ref": f"claim:{suffix}", "parent_refs": [f"dimension:{suffix}"]}],
        "target_project": [{"ref": f"target:{suffix}", "parent_refs": [f"claim:{suffix}"]}],
        "candidate": [{"ref": f"candidate:{suffix}", "parent_refs": [f"target:{suffix}"]}],
        "scenario": [{"ref": f"scenario:{suffix}", "parent_refs": [f"candidate:{suffix}"]}],
        "intervention_output": [{"ref": f"output:{suffix}", "parent_refs": [f"scenario:{suffix}"]}],
    }


def test_golden_benchmark_is_content_driven_and_byte_stable() -> None:
    first = run_golden_benchmark(MANIFEST)
    second = run_golden_benchmark(MANIFEST)

    assert first == second
    assert first["status"] == "passed"
    assert first["manifest_bytes_fingerprint"] == "sha256:" + hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    assert first["fingerprint"] == canonical_fingerprint({key: value for key, value in first.items() if key != "fingerprint"})
    assert {case["scope"] for case in first["cases"]} == {
        "exact_parcel",
        "multi_parcel",
        "coarse_search",
        "overlay",
        "network_coverage",
        "human",
        "not_groundable",
        "solver_deferred",
    }
    assert all(case["passed"] for case in first["cases"])
    assert all(case["fixture_bytes"] > 0 for case in first["cases"])
    assert first["metrics"]["source_binding"]["coverage"] == 0.875
    assert first["metrics"]["human_escalation"]["count"] == 4
    assert first["output_accounting"]["status"] == "ok"


def test_accounting_deduplicates_numeric_values_and_checks_parent_conservation() -> None:
    layers = _complete_chain("demo")
    layers["L1_fact"] = [
        {"ref": "fact:demo", "area": 10, "amount": 100},
        {"ref": "fact:demo", "area": 10, "amount": 100},
        {"ref": "fact:deferred", "status": "deferred"},
    ]
    report = build_accounting(layers)
    l1 = report["layers"]["L1_fact"]

    assert report["status"] == "ok"
    assert report["conservation"]["overall_ok"] is True
    assert l1["refs"] == ["fact:deferred", "fact:demo"]
    assert l1["deduped_refs"] == ["fact:demo"]
    assert l1["counts"] == {"admitted": 1, "deferred": 1, "rejected": 0, "deduped": 1}
    assert l1["source_count"] == 3
    assert l1["unique_count"] == 2
    assert l1["area"] == 10.0
    assert l1["amount"] == 100.0
    assert any(issue["kind"] == "duplicate" for issue in report["issues"])

    broken = _complete_chain("broken")
    broken["L2_dimension"][0]["parent_refs"] = "fact:missing"
    broken_report = build_accounting(broken)
    drops = [issue for issue in broken_report["issues"] if issue["kind"] == "drop"]
    assert broken_report["status"] == "incomplete"
    assert drops and drops[0]["refs"] == ["fact:missing"]
    assert set(drops[0]["refs"]) != set("fact:missing")
    assert build_accounting({})["status"] == "incomplete"


def test_recorded_replay_matrix_verifies_route_artifacts_gates_and_certificates(tmp_path: Path) -> None:
    matrix = recorded_replay_acceptance_matrix(recorded_session=RECORDED_FIXTURE)
    assert matrix["status"] == "passed"
    assert matrix["live_provider"] == "not_run"
    assert {row["outcome"] for row in matrix["rows"]} == {
        "success",
        "human_required",
        "not_groundable",
        "solver_deferred",
    }
    assert all(row["replay_passed"] for row in matrix["rows"])
    assert all(all(row["checks"].values()) for row in matrix["rows"])
    assert all(row["artifacts"]["artifact"]["refs"] for row in matrix["rows"])
    assert all(row["artifacts"]["certificate"]["present"] for row in matrix["rows"])

    absent = recorded_replay_acceptance_matrix(recorded_session=MANIFEST.parent)
    assert absent["status"] == "unavailable"
    assert all(not row["replay_passed"] for row in absent["rows"])
    assert all(row["status"] == "unavailable" for row in absent["rows"])

    tampered_root = tmp_path / "tampered"
    tampered_root.mkdir()
    payload = json.loads((RECORDED_FIXTURE / "p3_replay_manifest.json").read_text(encoding="utf-8"))
    payload["routes"][0]["artifact_refs"]["delivery_manifest"] = "sha256:tampered"
    (tampered_root / "p3_replay_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tampered = recorded_replay_acceptance_matrix(recorded_session=tampered_root)
    assert tampered["status"] == "failed"
    success = next(row for row in tampered["rows"] if row["id"] == "success")
    assert success["replay_passed"] is False
    assert success["checks"]["artifact"] is False
