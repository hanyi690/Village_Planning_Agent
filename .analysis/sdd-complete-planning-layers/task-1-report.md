# Task 1 Report — Preserve Pending Spatial Intent During L3 Admission

## Status

DONE

## Files Changed

- `backend/app/contracts/domain/l3_contracts.py`
  - Added `ClaimDisposition` with stable `claim_id`, `dimension_key`, status,
    reason, and `missing_requirements`.
  - Added `pending_grounding_claims` and `claim_dispositions` to
    `PlanningProgram`; the original `claims` field remains unchanged.
- `backend/app/domain/program/claim_adapter.py`
  - Added `classify_claims()` returning, in order, admitted interventions,
    pending claims, dispositions, and program issues.
  - Restricted pending classification to spatial claims whose only failures are
    `project_package_ref`, locator/candidate/source-feature reference, and/or
    evidence/source lineage.
  - Pending items produce warning `claim_grounding_pending` issues whose detail
    includes canonical missing requirement names. Typed parameter/completion,
    materialization, output, and other semantic defects still use strict
    `claim_admission_incomplete` errors.
  - Left `interventions_from_claims()` behavior unchanged.
- `backend/app/domain/program/aggregate.py`
  - Switched `merge_program_fragments()` to `classify_claims()` and persists
    pending claims and dispositions on the assembled program.
- `backend/tests/contracts/test_l3_executable_target_admission.py`
  - Added ready/pending/invalid/every-claim-disposition coverage while keeping
    the existing strict helper tests.
- `docs/superpowers/plans/2026-08-24-l3-claim-accounting.md`
  - Recorded the required implementation plan before edits.

## Tests Run

From `F:\project\Village_Planning_Agent\backend`:

```text
pytest tests/contracts/test_l3_executable_target_admission.py -q -o addopts=''
..........                                                               [100%]
10 passed in 3.43s
```

```text
pytest tests/contracts/test_l3_executable_target_admission.py tests/core/test_l3_program_target_compaction.py tests/core/test_l3_planning_output_contract.py -q -o addopts=''
.......................                                                  [100%]
23 passed in 3.33s
```

```text
python -m compileall -q app/contracts/domain/l3_contracts.py app/domain/program/claim_adapter.py app/domain/program/aggregate.py
```

The repository default pytest configuration selects e2e tests only, so the
focused commands explicitly use `-o addopts=''`.

## Self-Review

- `git diff --check` passed.
- The classifier calls the existing strict helper for admitted, invalid, and
  deferred paths, keeping direct-caller behavior and diagnostic wording stable.
- No GROUND or SELECT code changed. No parsing, geometry, coordinates, BSMs,
  WKT, candidate geometry, or compatibility aliases were added.
- `merged_duplicate` is represented in the new contract status vocabulary but
  is not assigned by this admission slice; existing intervention compaction
  still performs merge behavior after claim classification.

## Task 2 Consumption Note

Task 2 should consume `PlanningProgram.pending_grounding_claims` together with
each matching `ClaimDisposition.missing_requirements` to build typed grounding
and evidence requirements. It must keep `PlanningProgram.interventions` as the
strict executable set and must not promote pending claims until GROUND supplies
the required support.
