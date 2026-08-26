# Task 1 review — Preserve pending spatial intent during L3 admission

## Scope reviewed

- Brief: `.analysis/sdd-complete-planning-layers/task-1-brief.md`
- Implementation report: `.analysis/sdd-complete-planning-layers/task-1-report.md`
- Diff package against `c8a3c0688900570c5302bf1f237c8d72c26b97da`

## Verdicts

- **Spec compliance: PASS.** The implementation adds typed, auditable claim
  accounting while leaving `interventions_from_claims()` as the strict
  admission boundary. A spatial claim whose only gaps are package identity,
  locator/candidate/source-feature support, and/or evidence lineage is placed
  in `pending_grounding_claims`, gets a `pending_grounding` disposition, and
  emits warning `claim_grounding_pending`. Semantic incompleteness continues
  through the strict helper as error `claim_admission_incomplete`.
- **Implementation quality: PASS WITH ONE MINOR FOLLOW-UP.** The code is
  compact, uses typed contracts, preserves claim audit data, and does not touch
  GROUND, SELECT, geometry, regex parsing, or compatibility adapters. The
  `merged_duplicate` vocabulary is presently declarative only; current
  compaction does not update dispositions for claims merged into a canonical
  intervention. This does not violate the stated Task 1 behavior, because
  every claim is still accounted for as admitted/pending/deferred/invalid, but
  it should be resolved when compaction-level audit semantics are expanded.

## Findings

### Minor

1. `merged_duplicate` cannot yet be observed in an assembled program.
   `ClaimDisposition` exposes the status at
   `backend/app/contracts/domain/l3_contracts.py:167`, but
   `merge_program_fragments()` records the classifier output unchanged after
   `compact_interventions()` at
   `backend/app/domain/program/aggregate.py:219` and
   `backend/app/domain/program/aggregate.py:247`. Thus a claim whose admitted
   intervention is compacted into another is still labelled `admitted`.
   This is safe for Task 1's strict/non-executable boundary, but an eventual
   audit contract that promises merge outcomes should either set
   `merged_duplicate` deterministically or remove that unused status until the
   compaction slice implements it.

## Evidence checked

- `ClaimDisposition` contains the required stable identity, dimension, status,
  reason, and explicit missing requirements
  (`backend/app/contracts/domain/l3_contracts.py:162`).
- The classifier sends only the three declared readiness gaps to the pending
  path (`backend/app/domain/program/claim_adapter.py:222` and `:272`); action
  output, typed-parameter/completion, and materialization failures remain
  invalid through the strict helper (`:298`).
- Non-spatial claims retain their strict helper informational issue and receive
  an explicit `deferred` disposition (`:249`).
- The aggregate retains all original claims and separately persists both
  pending claims and dispositions (`backend/app/domain/program/aggregate.py:237`).
- The focused tests cover ready, pending, invalid, every-claim disposition,
  and existing strict-helper behavior
  (`backend/tests/contracts/test_l3_executable_target_admission.py:62`).

## Review conclusion

No Critical or Important findings. Task 1 is ready to proceed to Task 2. The
minor compaction-status follow-up should be placed in the accounting/compaction
backlog rather than block pending-intent-to-GROUND wiring.
