# Phase P3 Report — Golden benchmark, output accounting, and replay acceptance

Date: 2026-08-25

## STATUS

Implemented the bounded P3-A/P3-B observational slice in one change. The
implementation does not alter solver semantics and does not modify the
user-owned recorded replay test or provider support files.

## IMPLEMENTED

- Added versioned manifest `backend/tests/fixtures/p3_golden_manifest.json`
  (`p3-golden-1`) covering exact parcel, multi-parcel ambiguity, coarse
  search, overlay, network/coverage, HUMAN, not-groundable, and deferred
  solver routes.
- Added `backend/app/acceptance/p3_benchmark.py` with deterministic canonical
  JSON/fingerprint output and metrics for source binding, candidate
  completeness, relation readiness, solver readiness, feasibility, HUMAN
  escalation, and output accounting.
- Added seven-layer accounting (`L1_fact` through `intervention_output`) with
  admitted/deferred/rejected/deduped counts, stable refs, area/amount totals,
  and explicit drop/duplicate issues. Incomplete accounting is reported as
  `incomplete` rather than being promoted to a successful output.
- Added a read-only four-route replay acceptance matrix. Each row records
  route, artifact/gate/certificate/accounting audit scope, `replay_passed`,
  provider capability, and `live_provider_passed`; live provider execution is
  explicitly `not_run`.
- Added focused P3 tests for byte-stable repeated benchmark output,
  incomplete/HUMAN identification, dropped/duplicate reference detection, and
  the four-route replay matrix.

## TESTS

Passed:

```text
python -m pytest -c backend/pytest.ini -o addopts='' backend/tests/core/test_p3_closure.py -q --maxfail=1
3 passed (known pytest cache permission warning)

python -m compileall -q backend/app/acceptance/p3_benchmark.py backend/tests/core/test_p3_closure.py
passed

git diff --check
passed
```

The relevant existing recorded replay tests were executed read-only:

```text
python -m pytest -c backend/pytest.ini -o addopts='' backend/tests/acceptance/test_recorded_real_root_graph_replay.py -q --maxfail=1
FAILED: missing artifact_refs[planning_program]

python -m pytest -c backend/pytest.ini -o addopts='' backend/tests/acceptance/test_recorded_real_root_graph_replay.py::test_recorded_real_closed_scope_delivers_planning_points -q --maxfail=1
FAILED: missing artifact_refs[planning_program]
```

Both failures occur in the pre-existing user test boundary. Captured replay
logs also show recorded-provider source-fact mismatches and structured-output
errors before the assertion. No replay/support file was changed.

## CONCERNS

- The supplied recorded real-session replay is not currently passing in this
  working tree, so the P3 matrix reports replay capability separately from
  live-provider execution and does not claim a live pass.
- The environment emits the known `PytestCacheWarning` because
  `backend/.pytest_cache` is not writable.
- Full repository scanning and full-suite execution were intentionally not
  performed, per the P3 observational/bounded scope.

## COMMIT

Pending final single commit after the staged-file and user-dirty-file checks.
