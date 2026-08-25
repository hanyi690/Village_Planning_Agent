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

## Fix Round 1 — 2026-08-25

### STATUS

Implemented the production wiring findings from the independent P1 review.

### FIXES

- TARGET formal admission now retains only `GroundingRequest.status=ready`
  requests; GROUND rechecks request status and all source snapshot/binding
  authority fields before resolution. If no request is formally admitted,
  GROUND does not call `ground_aggregate`, so pending requests cannot create
  candidates.
- Snapshot digest and source-feature digest are carried from the typed spatial
  spec into the request. The previous `l1_snapshot_ref`-as-digest fallback was
  removed; missing authority remains fail-closed. SELECT refined candidates
  now preserve `physical_project_ref`, `component_claim_refs`, and
  `component_fact_refs`.
- Solver subproblem compilation now coalesces targets sharing one physical
  project into one project coordination boundary while retaining target-keyed
  candidate alternatives and relation evaluation references.
- `build_solver_readiness` invokes `build_relation_readiness` for every factor;
  hard satisfied relations without evidence block and soft issues remain
  advisory.
- Typed `HumanDecisionRecord`/`DecisionFingerprint` payloads are validated at
  `apply_human_review_decision`; stale or malformed records produce a fresh
  HUMAN pending result and cannot pass the generic approval gate.

### REGRESSION TESTS

- Added focused coverage for refined-candidate lineage preservation, hard
  evidence-less relation blocking at the production readiness boundary, same
  physical-project two-target solver coordination, and stale HUMAN resume.
- Updated the target projection fixture to distinguish complete authority from
  a pending request; the latter remains out of formal specs.

### TESTS

Passed:

```text
python -m pytest -c backend/pytest.ini -o addopts='' \
  backend/tests/core/test_p1_closure_contracts.py \
  backend/tests/core/test_l3_program_target_compaction.py \
  backend/tests/core/test_solver_readiness.py \
  backend/tests/core/test_relation_geometry_evaluators.py \
  backend/tests/core/test_select_gate_deferred_targets.py -q --maxfail=1
52 passed, 1 existing pytest cache permission warning
```

Changed-boundary `compileall` and `git diff --check` are recorded in the
handoff. Full backend compile remains affected by the pre-existing invalid
recorded scripts under `backend/.run-tmp/logs/` and the unwritable pytest
cache directory.

## Fix Round 2 — 2026-08-25

### STATUS

Added the two narrow P2 coverage regressions from the review. Production
logic was not changed in this round.

### COVERAGE ADDED

- `test_p1_closure_contracts.py` now invokes the production `ground_node` with
  a pending request and an authority-mismatched request. Both cases monkeypatch
  `ground_aggregate`, assert it is not called, and assert the persisted
  `GroundingResult` has no candidates.
- The same file now covers a typed HUMAN review context with a missing
  `decision_record`; generic `approve` remains pending, returns
  `HUMAN_DECISION_STALE`, and does not consume the HUMAN resume.

### TESTS

Passed:

```text
P1 focused + HUMAN/HITL/resume focused set: 139 passed, 1 existing pytest
cache permission warning
```

The broader command including `test_e2e_stabilization.py` remains blocked by
the pre-existing test `test_auto_defer_blocked_targets_builds_ledger_and_passes`,
which calls the removed `validate_stage._auto_defer_blocked_targets` helper.
That failure is outside this test-only round and no production workaround was
added.
