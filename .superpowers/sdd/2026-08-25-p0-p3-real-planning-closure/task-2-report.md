Task 2 report

Changed files

- `backend/app/contracts/spatial/candidate_geometry.py`
- `backend/app/contracts/spatial/grounding_contracts.py`
- `backend/app/domain/ground/aggregate.py`
- `backend/app/domain/allocation/refined_candidate_catalog.py`
- `backend/app/domain/allocation/scenario_solver.py`
- `backend/tests/test_ground_parcel_alternatives.py`
- `backend/tests/core/test_artifact_runtime.py`

Implemented behavior

- Added explicit `identity_confidence`, `geometry_confidence`, and `suitability_score` accounting to typed candidate geometry/site contracts.
- Kept legacy `confidence` as a compatibility field, but normalized it to mirror `geometry_confidence` for new/loaded models.
- Added backward-compatible parsing for legacy artifacts:
  - legacy `confidence` values inside `[0, 1]` backfill identity/geometry confidence.
  - overloaded legacy `confidence` values above `1` are treated as suitability-only, do not raise geometry confidence, and record a compatibility diagnostic.
  - records with no confidence fields keep a compatibility diagnostic so older test fixtures/manual constructors do not fail closed unnecessarily.
- Updated GROUND candidate creation so new writes populate explicit grounding confidence fields from resolver evidence.
- Updated refined candidate catalog so SELECT refinement:
  - preserves grounding confidence from source evidence,
  - stores evaluator output in `suitability_score`,
  - never overwrites grounding confidence with suitability score.
- Updated scenario suitability scoring to read `suitability_score` first, then suitability components, and to stop falling back to geometry confidence.
- Preserved existing exact/search-scope behavior by keeping the gating surface narrow:
  - executable geometry now requires grounding readiness,
  - legacy overloaded confidence artifacts remain non-executable and therefore stay diagnostic/human-review only.

Tests added

- `backend/tests/test_ground_parcel_alternatives.py::test_select_refinement_does_not_promote_score_into_geometry_confidence`
- `backend/tests/test_ground_parcel_alternatives.py::test_high_suitability_does_not_close_incomplete_grounding`
- `backend/tests/core/test_artifact_runtime.py::test_load_artifact_roundtrip_preserves_legacy_confidence_compatibility`

Verification run

- `pytest -o addopts='' backend/tests/test_ground_parcel_alternatives.py::test_select_refinement_does_not_promote_score_into_geometry_confidence backend/tests/test_ground_parcel_alternatives.py::test_high_suitability_does_not_close_incomplete_grounding backend/tests/core/test_artifact_runtime.py::test_load_artifact_roundtrip_preserves_legacy_confidence_compatibility backend/tests/core/test_grounding_fail_closed.py::test_build_candidate_site_carries_confidence_and_uncertainty -q`
- `pytest -o addopts='' backend/tests/core/test_scenario_optimizer.py::test_optimizer_preserves_alternatives_pareto_and_recommendation backend/tests/core/test_scenario_optimizer.py::test_objective_definition_order_is_authoritative_and_missing_results_fail_closed -q`
- `python -m py_compile backend/app/contracts/spatial/candidate_geometry.py backend/app/contracts/spatial/grounding_contracts.py backend/app/domain/ground/aggregate.py backend/app/domain/allocation/refined_candidate_catalog.py backend/app/domain/allocation/scenario_solver.py backend/tests/test_ground_parcel_alternatives.py backend/tests/core/test_artifact_runtime.py`

Behavior decisions

- I did not widen availability semantics for parcel refinements beyond this brief. The score/confidence split was kept orthogonal to parcel-availability promotion.
- I did not touch the user-owned dirty files called out in the task (`.codex/config.toml`, `.analysis/`, `backend/tests/acceptance/test_recorded_real_root_graph_replay.py`, `backend/tests/support/recorded_planning_provider.py`).
- I left legacy `metrics["confidence"]` in place for compatibility, but new writes also include explicit grounding confidence fields alongside it.

Concerns

- A dormant non-default test, `backend/tests/test_ground_parcel_alternatives.py::test_select_refinement_only_promotes_hard_feasible_parcel_and_keeps_lineage`, still expects a hard-feasible parcel refinement with `availability_status="unknown"` to be executable. That behavior is outside this brief’s accounting boundary, and widening it would change parcel-availability semantics. I left it unchanged and did not include it in the bounded verification set.
- Targeted pytest runs emit a cache warning because `backend/.pytest_cache` is not writable in this environment, but the selected tests still ran and passed.
