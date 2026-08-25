# Task 3 Report — P0-C Role-Aware Suitability Hard-Constraint Policy

Date: 2026-08-25

## Scope

Implemented the P0-C typed materialization-role policy in the suitability layer only, without adding legacy compatibility shims. The change is scoped to the new explicit role contract and preserves the user-owned dirty files called out in the brief.

## What Changed

### 1. Typed role policy in `SpatialFactorIndex`

Updated `backend/app/domain/suitability/spatial_factors.py` to make hard-constraint evaluation role-aware:

- Added a typed role-policy model for:
  - `site_footprint`
  - `land_use_assignment`
  - `functional_overlay`
  - `protection_overlay`
  - `restoration_overlay`
- Added explicit policy classes per factor:
  - `site_hard_exclusion`
  - `overlay_constraint`
  - `advisory`
- Added fail-closed handling:
  - missing or unknown role returns `MATERIALIZATION_ROLE_POLICY_UNAVAILABLE`
  - hard feasibility becomes `False`
- Kept site behavior hard:
  - farmland overlap
  - ecological overlap
  - hazard buffer
  - prohibited constraint-index overlaps
- Relaxed overlay behavior:
  - overlay roles still record protected/restoration/prohibited overlaps
  - those overlaps are not converted into hard exclusions
- Left road/facility proximity as explicit advisory factors

### 2. Suitability artifact now records role/policy/trace

Updated:

- `backend/app/domain/suitability/model.py`
- `backend/app/domain/suitability/service.py`

Each `SuitabilityCandidate` now carries:

- `materialization_role`
- `role_policy_key`
- `materialization_role_policy`
- `hard_constraint_factors`
- `evaluation_trace`

The suitability surface provenance now records:

- `materialization_role_policy_version`
- `evaluated_materialization_roles`

### 3. Suitability service now passes role explicitly

`build_suitability_surface(...)` now resolves the materialization role from the typed target/candidate contract and passes it into `SpatialFactorIndex.evaluate(...)`.

This applies to:

- context-backed parcel-level suitability evaluation
- context-free suitability projection from grounding artifacts

Unknown or missing role now fails closed in both paths instead of implicitly relaxing behavior.

### 4. Targeted regression updates

Added or updated focused regressions for:

- site footprint vs protection overlay on the same geometry
- missing/unknown role fail-closed
- explicit confidence fixtures in tests that are now governed by the new typed confidence contract rather than legacy implicit behavior

## Files Changed

- `backend/app/domain/suitability/spatial_factors.py`
- `backend/app/domain/suitability/model.py`
- `backend/app/domain/suitability/service.py`
- `backend/tests/core/test_spatial_factors_overlap.py`
- `backend/tests/core/test_service_coverage_not_existing_facility_proximity.py`
- `backend/tests/core/test_planning_subgeometry_service.py`
- `backend/tests/contracts/test_planning_domain_boundaries.py`
- `backend/tests/core/test_scenario_hard_relation_feasibility.py`

## Verification

Ran:

```bash
python -m compileall backend/app/domain/suitability
pytest -c backend/pytest.ini -o addopts='' backend/tests/core/test_spatial_factors_overlap.py backend/tests/core/test_service_coverage_not_existing_facility_proximity.py backend/tests/core/test_planning_subgeometry_service.py backend/tests/contracts/test_planning_domain_boundaries.py backend/tests/integration/test_candidate_validation_boundary.py backend/tests/core/test_scenario_hard_relation_feasibility.py
```

Result:

- `compileall` passed
- targeted pytest slice passed: `34 passed`

## Dirty Files Preserved

Left untouched as requested:

- `.codex/config.toml`
- `.analysis/`
- `backend/tests/acceptance/test_recorded_real_root_graph_replay.py`
- `backend/tests/support/recorded_planning_provider.py`

Also did not modify unrelated user-owned worktree entries.

## Notes

- No legacy compatibility shim was added for implicit/older suitability behavior.
- The fixture updates in `test_scenario_hard_relation_feasibility.py` and the facility refinement test keep the new explicit confidence contract authoritative instead of relying on deprecated implicit executability.

## Fix Round 1

- Finalized the scoped P0-C role-aware suitability diff without touching unrelated dirty files.
- Added centralized typed role aliases, context-free role-aware hard-feasibility handling, policy provenance, and fail-closed parcel diagnostics/traces.
- Bounded verification was started with `python -m pytest -c backend/pytest.ini -o addopts='' --maxfail=1 backend/tests/core/test_planning_subgeometry_service.py backend/tests/core/test_spatial_factors_overlap.py`; it stopped after one focused assertion failure in the newly added matrix test (`test_role_policy_matrix_classifies_spatial_factors`).
- Fix Round 1 corrected the chained boolean assertion while preserving the `result.hard_feasible` assertion; the same bounded command then passed: `43 passed`.
