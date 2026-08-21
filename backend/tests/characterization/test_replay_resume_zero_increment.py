"""Bounded resume evidence without starting the full real graph.

The real source-aware replay is intentionally expensive.  These checks pin
the part that can be proven deterministically at the contract boundary:
completed scenario/validation artifacts retain their semantic fingerprints,
and a completed checkpoint produces no rerun plan.  A live provider/worker
counter remains an acceptance item for the clone replay.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.application.recovery.resume_service import ResumeService
from app.contracts.planning.scenario import PlanningScenario, ScenarioFeature, ScenarioTargetSelection
from app.domain.validation.relation_validation import FinalScenarioValidation


_REPLAY28_REPORT = (
    Path(__file__).resolve().parents[3]
    / ".run-tmp"
    / "sdd"
    / "2026-08-17-relation-aware-spatial-planning-gap-closure-v2"
    / "reconcile-retry-replay28-report.json"
)


def _zero_increment_observation(first: dict, second: dict) -> dict:
    """Compare two persisted observations at the no-op resume boundary.

    This is deliberately a test-side acceptance projection.  Runtime replay
    instrumentation must provide these fields; a missing field is a failed
    acceptance rather than an implicit zero.  In particular, unchanged
    artifact refs alone do not prove that a worker or provider was not called.
    """
    required = {
        "scenario_fingerprint",
        "final_validation_fingerprint",
        "artifact_digests",
        "llm_calls",
        "worker_calls",
        "feature_ids",
    }
    missing = sorted(required - set(first) - set(second))
    if missing:
        raise AssertionError(f"resume observation missing fields: {missing}")
    for key in ("scenario_fingerprint", "final_validation_fingerprint"):
        if not first[key] or not second[key]:
            raise AssertionError(f"resume observation has empty {key}")
        if first[key] != second[key]:
            raise AssertionError(f"{key} changed across no-op resume")
    if first["artifact_digests"] != second["artifact_digests"]:
        raise AssertionError("completed artifact refs changed across no-op resume")
    if first["feature_ids"] != second["feature_ids"]:
        raise AssertionError("materialized feature IDs changed across no-op resume")
    return {
        "scenario_fingerprint": second["scenario_fingerprint"],
        "final_validation_fingerprint": second["final_validation_fingerprint"],
        "artifact_digests_unchanged": True,
        "feature_ids_unchanged": True,
        "llm_call_delta": second["llm_calls"] - first["llm_calls"],
        "worker_call_delta": second["worker_calls"] - first["worker_calls"],
    }


def _replay28_final_artifact_digests() -> dict[str, str]:
    """Read final artifact digests from the checked-in bounded replay report."""
    if not _REPLAY28_REPORT.is_file():
        pytest.skip("bounded replay28 report is not present in this checkout")
    payload = json.loads(_REPLAY28_REPORT.read_text(encoding="utf-8"))
    refs = ((payload.get("replay") or {}).get("summary") or {}).get("after", {}).get(
        "artifact_refs", {}
    )
    keys = {
        "planning_scenario",
        "final_relation_validation",
        "planned_state",
        "execution_result",
        "delivery_manifest",
        "delivery_spatial_snapshot",
        "render_layers",
    }
    result = {
        key: str(value.get("digest") or "")
        for key, value in refs.items()
        if key in keys and isinstance(value, dict)
    }
    if not result or any(not value.startswith("sha256:") for value in result.values()):
        raise AssertionError("replay28 report has no complete final artifact digest set")
    return result


def _scenario() -> PlanningScenario:
    feature = ScenarioFeature(
        feature_id="feature:facility",
        scenario_id="scenario:resume",
        target_id="target:facility",
        candidate_id="candidate:facility",
        geometry_kind="point",
        geometry_wkt="POINT (1 2)",
        crs="EPSG:4326",
        generation_operation="scenario_candidate_projection",
        source_refs=["source:facility"],
        relation_ids=["selection:target:facility:candidate:facility"],
    )
    return PlanningScenario(
        scenario_id="scenario:resume",
        baseline_ref="baseline:resume",
        problem_fingerprint="problem:resume",
        target_selections=[ScenarioTargetSelection(
            target_id="target:facility",
            selection_mode="choose_one",
            candidate_ids=["candidate:facility"],
        )],
        feature_intents=[feature],
        status="partial",
    )


def test_completed_checkpoint_has_no_rerun_and_fingerprints_are_stable() -> None:
    scenario = _scenario()
    validation = FinalScenarioValidation(
        scenario_id=scenario.scenario_id,
        problem_fingerprint=scenario.problem_fingerprint,
        final_fingerprint="final:resume",
        evaluator_version="relation-evaluator-v1",
        passed=True,
        status="passed",
        final_features=list(scenario.feature_intents),
    )

    scenario_roundtrip = PlanningScenario.model_validate(
        scenario.model_dump(mode="json")
    )
    validation_roundtrip = FinalScenarioValidation.model_validate(
        validation.model_dump(mode="json")
    )
    assert scenario_roundtrip.fingerprint == scenario.fingerprint
    assert validation_roundtrip.final_fingerprint == validation.final_fingerprint

    snapshot = SimpleNamespace(
        values={
            "phase": "completed",
            "planning_scenario_fingerprint": scenario.fingerprint,
            "final_validation_fingerprint": validation.final_fingerprint,
            "artifact_refs": {},
        },
        next=(),
        config={"configurable": {"checkpoint_id": "resume-complete"}},
        tasks=(),
    )
    stable, kind, plan = ResumeService.plan_for_snapshot("session:resume", snapshot)

    assert stable is True
    assert kind == "completed"
    assert str(plan.mode) == "completed"
    assert plan.rerun == []
