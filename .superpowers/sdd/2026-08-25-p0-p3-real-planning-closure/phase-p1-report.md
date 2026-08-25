# Phase P1 Report — Minimal Project, Grounding, Relation, and HUMAN Closure

Date: 2026-08-25

## STATUS

Implemented the minimal P1-A/B/C contract slice. The change adds typed,
deterministic contracts and connects only the existing TARGET_PROJECTION,
GROUND, relation-readiness, and HUMAN decision boundaries needed to carry the
new lineage.

## Implemented

- Added `PhysicalProject` and `PhysicalProjectAssembly` with canonical
  package/variant/materialization-role identity, component claim/fact refs,
  target/intervention refs, stable project IDs, and assembly fingerprints.
- Added `GroundingRequest` with typed spatial spec, retrieval scopes, source
  collection/snapshot/binding refs, binding fingerprint, physical-project
  refs, request fingerprint, and fail-closed pending reasons.
- Target projection now assembles physical projects and carries project and
  component refs into `SpatialReferenceSpec` and `GroundingRequest`.
- Unsupported named-village spatial specs are removed from formal target
  specs, recorded as pending requests, and excluded from formal GROUND
  resolution; therefore they cannot create candidates.
- Grounding artifacts retain formal and pending request lineage.
- Added `DecisionFingerprint` and `HumanDecisionRecord`; current-context
  validation rejects changed source snapshot, constraint, or evaluator
  identity as stale.
- Extended relation contracts with evaluator version, required refs, source
  snapshot refs, semantic/input status, and solver support. Added deterministic
  relation readiness that blocks hard missing/unsupported/not-evaluable or
  evidence-less results while retaining soft issues as advisory.
- Existing relation evaluation and SELECT readiness consume the new fields
  without changing legacy factors that do not opt into the P1 metadata.

## COMMIT

Phase-level commit created with message `feat: close minimal P1 planning lineage contracts`; final hash is reported in the handoff.

## TESTS

Passed:

```text
python -m pytest -c backend/pytest.ini -o addopts='' \
  backend/tests/core/test_p1_closure_contracts.py \
  backend/tests/core/test_l3_program_target_compaction.py \
  backend/tests/core/test_solver_readiness.py \
  backend/tests/core/test_relation_geometry_evaluators.py \
  backend/tests/core/test_select_gate_deferred_targets.py -q --maxfail=1
48 passed, 1 existing pytest cache permission warning

python -m compileall -q backend/app backend/tests
passed

git diff --check
passed
```

## CONCERNS

- Full `compileall backend` remains red because existing files under
  `.run-tmp/logs/` contain syntax-invalid recorded scripts; the changed
  source/test boundary compiles successfully. `.pytest_cache` is also not
  writable in this environment.
- The broader relation solver fixture
  `backend/tests/core/test_relation_aware_scenario_solver.py::test_hard_relation_changes_feasible_set_and_soft_relation_changes_objective`
  still constructs `CandidateGeometry` without explicit P0 grounding
  confidence and is rejected by the existing P0-D fail-closed schema. It was
  not changed because it is outside this P1 contract slice.
- An unrelated suitability-domain fixture still supplies the removed legacy
  `metrics["confidence"]` field and remains outside this phase.
- User-owned dirty files were preserved and not staged: `.codex/config.toml`,
  `.analysis/`, recorded replay/support files, and the planning document.
