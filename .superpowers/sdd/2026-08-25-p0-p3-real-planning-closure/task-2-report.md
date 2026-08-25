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

Fix Round 1

Changed files

- `backend/app/contracts/spatial/candidate_geometry.py`
- `backend/app/contracts/spatial/grounded_problem.py`
- `backend/app/contracts/spatial/grounding_contracts.py`
- `backend/app/domain/ground/gate.py`
- `backend/app/domain/suitability/service.py`
- `backend/tests/contracts/test_grounded_problem_completeness.py`
- `backend/tests/contracts/test_planning_domain_boundaries.py`
- `backend/tests/core/test_artifact_runtime.py`
- `backend/tests/core/test_scenario_optimizer.py`
- `backend/tests/core/test_solver_portfolio_slice1.py`
- `backend/tests/core/test_typed_candidate_geometry.py`
- `backend/tests/e2e/test_ground_gate_contract.py`

Behavior changes

- Legacy-only `confidence` is no longer promoted into trusted `identity_confidence` or `geometry_confidence`, regardless of whether the numeric value is in-range.
- Legacy geometries without explicit grounding confidence now fail closed:
  - `grounding_ready` is `False`
  - `is_executable` is `False`
  - compatibility diagnostics preserve the ambiguity instead of inferring trust.
- `GroundedPlanningProblem` now reconciles persisted resolved domains against actual candidate geometry readiness during replay. A replayed candidate geometry that is resolved-by-status but missing trusted grounding confidence downgrades completeness and keeps `can_solve == False`.
- GROUND gate ambiguity routing now uses typed grounding readiness/confidence instead of `metrics["confidence"]`, and legacy/untrusted replayed candidates route conservatively to `HUMAN`.
- Context-free suitability no longer synthesizes candidate score from grounding confidence. It returns a neutral score unless an explicit `suitability_score` is already present, and records `no_suitability_evaluator` in diagnostics.

Fix Round 1 tests

- `backend/tests/contracts/test_grounded_problem_completeness.py::test_resolved_domains_are_downgraded_when_replayed_geometry_has_only_legacy_confidence`
- `backend/tests/core/test_artifact_runtime.py::test_load_artifact_roundtrip_preserves_legacy_confidence_compatibility`
- `backend/tests/core/test_typed_candidate_geometry.py::test_legacy_geometry_without_explicit_grounding_confidence_is_not_ready`
- `backend/tests/e2e/test_ground_gate_contract.py::test_legacy_multi_parcel_confidence_routes_to_human_conservatively`
- `backend/tests/contracts/test_planning_domain_boundaries.py::test_context_free_suitability_does_not_derive_score_from_grounding_confidence`
- `backend/tests/contracts/test_planning_domain_boundaries.py::test_context_free_suitability_respects_explicit_suitability_score`

Fix Round 1 verification

- `pytest -o addopts='' backend/tests/contracts/test_grounded_problem_completeness.py::test_grounded_problem_reports_candidate_complete_only_with_geometry backend/tests/contracts/test_grounded_problem_completeness.py::test_resolved_domains_are_downgraded_when_replayed_geometry_has_only_legacy_confidence backend/tests/core/test_artifact_runtime.py::test_load_artifact_roundtrip_preserves_legacy_confidence_compatibility backend/tests/core/test_typed_candidate_geometry.py::test_legacy_geometry_without_explicit_grounding_confidence_is_not_ready backend/tests/e2e/test_ground_gate_contract.py::test_legacy_multi_parcel_confidence_routes_to_human_conservatively backend/tests/contracts/test_planning_domain_boundaries.py::test_context_free_suitability_does_not_derive_score_from_grounding_confidence backend/tests/contracts/test_planning_domain_boundaries.py::test_context_free_suitability_respects_explicit_suitability_score backend/tests/core/test_scenario_optimizer.py::test_optimizer_preserves_alternatives_pareto_and_recommendation backend/tests/core/test_scenario_optimizer.py::test_objective_definition_order_is_authoritative_and_missing_results_fail_closed -q`
- `pytest -o addopts='' backend/tests/contracts/test_planning_domain_boundaries.py::test_suitability_exposes_grounding_evidence_without_allocating backend/tests/core/test_grounding_fail_closed.py::test_build_candidate_site_carries_confidence_and_uncertainty backend/tests/core/test_solver_portfolio_slice1.py::test_view_derives_typed_single_choice_kind_and_required_refs -q`
- `python -m py_compile backend/app/contracts/spatial/candidate_geometry.py backend/app/contracts/spatial/grounding_contracts.py backend/app/contracts/spatial/grounded_problem.py backend/app/domain/ground/gate.py backend/app/domain/suitability/service.py backend/tests/contracts/test_grounded_problem_completeness.py backend/tests/contracts/test_planning_domain_boundaries.py backend/tests/e2e/test_ground_gate_contract.py backend/tests/core/test_artifact_runtime.py backend/tests/core/test_typed_candidate_geometry.py backend/tests/core/test_scenario_optimizer.py backend/tests/core/test_solver_portfolio_slice1.py`

Fix Round 1 concerns

- The repo still emits a pytest cache permission warning when targeted tests run because `backend/.pytest_cache` is not writable here, but the selected tests completed and passed.
- I kept parcel-availability semantics unchanged, per instruction; the dormant hard-feasible/unknown-availability parcel test remains outside this round’s scope.
