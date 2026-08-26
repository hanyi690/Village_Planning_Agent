# Task 1 Report — Stabilize the global L1 union

## Status

Implementation completed for the code/test scope. Fresh runtime checkpoint evidence is currently blocked because the workspace has no live provider configuration, so a new real session cannot be started from this environment on August 25, 2026.

## Files changed

- `backend/app/domain/assessment/observation_draft.py`
- `backend/app/domain/assessment/l1_extraction_loop.py`
- `backend/app/domain/assessment/observation_quality.py`
- `backend/app/data/ingestion/compiler/profiles/l1_observation.py`
- `backend/tests/core/test_l1_typed_output_contract.py`
- `backend/tests/core/test_l1_observe_report_contract.py`

## What changed

- Kept the L1 observe pass on the global typed fact union instead of returning a dimension-narrowed response model.
- Added provider-container normalization at the L1 observation boundary so stringified list containers are decoded before validation.
- Isolated malformed observation records: valid records are preserved and invalid ones are downgraded to bounded diagnostics instead of rejecting the entire dimension.
- Added soft dimension-mismatch diagnostics (`l1_dimension_fact_type_mismatch:*`) so globally legal facts emitted under a non-preferred dimension are accepted rather than treated as hard failures.
- Updated L1 observation quality so dimension preference mismatches are reported separately (`dimension_mismatch`) and do not fail the dimension by themselves.
- Carried instruction-side L1 diagnostics into the compiled `L1Snapshot` diagnostics stream.

## Tests and commands

### Failing-first focused test runs

Command:

```powershell
pytest -o addopts='' -o pythonpath=backend backend/tests/core/test_l1_typed_output_contract.py -q
```

Initial result:

- `2 failed, 3 passed`
- failures proved:
  - stringified `observations` container was rejected as a plain string
  - a valid `demand` fact under `location` failed because the response model was still dimension-narrowed

Command:

```powershell
pytest -o addopts='' -o pythonpath=backend backend/tests/core/test_l1_observe_report_contract.py -q
```

Initial result:

- `1 failed, 5 passed`
- failure proved `validate_observations(..., dimension_key='location')` still hard-failed a globally valid `demand` fact

### Verification after implementation

Command:

```powershell
pytest -o addopts='' -o pythonpath=backend backend/tests/core/test_l1_typed_output_contract.py backend/tests/core/test_l1_observe_report_contract.py backend/tests/core/test_l1_planning_observation_contract.py backend/tests/core/test_l1_typed_fact_contract.py backend/tests/core/test_l1_typed_output_recovery.py backend/tests/core/test_structured_output_runner.py -q
```

Result:

- `67 passed in 5.23s`

Additional focused green runs executed during development:

- `backend/tests/core/test_l1_planning_observation_contract.py` → `3 passed`
- `backend/tests/core/test_l1_typed_fact_contract.py` → `3 passed`
- `backend/tests/core/test_l1_typed_output_recovery.py` → `8 passed`
- `backend/tests/core/test_structured_output_runner.py` → `42 passed`

## Fresh runtime checkpoint

### Requirement

Task 1 requires a fresh real session that completes all 12 L1 dimensions and reaches L2/L3.

### Current blocker

Environment check in this workspace returned all live-provider switches unset:

```text
LLM_PROVIDER=UNSET
MINIMAX_API_KEY=UNSET
OPENCODE_GO_API_KEY=UNSET
DASHSCOPE_API_KEY=UNSET
OPENAI_API_KEY=UNSET
RUN_REAL_GRAPH_RESUME=UNSET
REAL_CLASSIFICATION_DECISIONS_JSON=UNSET
REAL_CLASSIFICATION_DECISIONS_PATH=UNSET
```

Because no provider credentials are configured, I could not run either of the repo’s real-session harnesses:

- `backend/tests/acceptance/test_real_graph_resume_delivery.py`
- `scripts/run_pipeline_real_jintian.py`

No fresh runtime checkpoint was produced from this environment.

## Commit attempt

No commit was created.

Reason:

- the worktree is heavily dirty in overlapping backend areas already modified by other in-scope tasks
- several files touched for Task 1 were already modified before my changes, so a selective commit would risk bundling unrelated edits

## Self-review

- The acceptance behavior is covered at three layers:
  - provider-facing typed contract recovery
  - L1 loop acceptance plus soft mismatch diagnostics
  - downstream quality validation no longer rejecting mismatch-only cases
- Single-record isolation is intentionally bounded and non-lossy for valid records, with no provider/body leak in diagnostics.
- The compiler now preserves the soft mismatch signal into snapshot diagnostics, which should help later runtime inspection and human review.
- I did not modify retired register/current-asset/coverage paths back into production behavior.

## Concerns

- Fresh runtime evidence is still missing and remains the main outstanding acceptance gap.
- `backend/tests/core/test_l1_observe_report_contract.py` is currently untracked in the worktree state shown by `git status`; I edited the file in place, but because the branch is already messy, downstream commit/branch hygiene needs an owner decision before publishing.

## Round 1 Follow-up Fixes

### Review findings addressed

1. Restored legacy persisted observation compatibility for compiler consumers:
   - `observation_to_compiler_payload()` now accepts legacy dict rows without `fact_type` and normalizes them into the compiler payload shape.
   - `_instruction_payload()` again accepts raw JSON lists and wraps them as `{"observations": ...}` for compiler-only legacy reads.
2. Switched `validate_observations()` defect accounting from per-bucket max to row-level defective counting, so mixed bad rows in different categories no longer undercount.

### Additional files changed in round 1

- `backend/tests/core/test_l1_planning_observation_contract.py`

### Failing-first follow-up regressions

Command:

```powershell
pytest -o addopts='' -o pythonpath=backend backend/tests/core/test_l1_planning_observation_contract.py -k legacy_raw_observation_list_still_enriches_location_relation_facts -q
```

Initial result:

- `1 failed, 3 deselected`
- failure: `StopIteration` while reading `snapshot.location_facts`, confirming legacy raw-list observations no longer compiled into location facts

Command:

```powershell
pytest -o addopts='' -o pythonpath=backend backend/tests/core/test_l1_observe_report_contract.py -k counts_distinct_defective_rows_across_buckets -q
```

Initial result:

- `1 failed, 6 deselected`
- failure: `defect_ratio` returned `0.5` instead of `1.0`, confirming mixed defective rows were undercounted

### Verification after round 1 fixes

Command:

```powershell
pytest -o addopts='' -o pythonpath=backend backend/tests/acceptance/test_l1_village_cluster_resolution.py -k l1_observation_relation_enriches_location_facts -q
```

Result:

- `1 passed, 10 deselected in 3.87s`

Command:

```powershell
pytest -o addopts='' -o pythonpath=backend backend/tests/core/test_l1_observe_report_contract.py -q
```

Result:

- `7 passed in 3.95s`

Command:

```powershell
pytest -o addopts='' -o pythonpath=backend backend/tests/core/test_l1_planning_observation_contract.py backend/tests/core/test_l1_typed_output_contract.py backend/tests/core/test_l1_typed_fact_contract.py backend/tests/core/test_l1_typed_output_recovery.py backend/tests/core/test_structured_output_runner.py -q
```

Result:

- `62 passed in 5.71s`

### Commit attempt after round 1

No commit was created.

Reason:

- the worktree is still heavily dirty in overlapping backend areas
- `backend/tests/core/test_l1_observe_report_contract.py` still appears as untracked in `git status`, so I did not try to package a partial commit with uncertain surrounding worktree state
