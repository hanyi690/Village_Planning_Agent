# Task 1 brief: Preserve pending spatial intent during L3 admission

This is the first implementation slice for the complete planning-layer goal.
The current `interventions_from_claims()` path drops spatial claims when a
typed parameter block is present but locator/evidence/package identity is not
yet available. That prevents GROUND from doing its intended evidence work.

Implement an additive, typed claim-accounting boundary:

1. Add a `ClaimDisposition` contract to the L3 domain contracts with a stable
   `claim_id`, `dimension_key`, a status from `admitted`, `pending_grounding`,
   `merged_duplicate`, `deferred`, or `invalid`, a reason, and explicit
   `missing_requirements`.
2. Add `pending_grounding_claims` and `claim_dispositions` to
   `PlanningProgram`. Keep the original `claims` list unchanged so the source
   claim remains available for audit.
3. Add a new `classify_claims()` helper in `claim_adapter.py` that returns
   admitted interventions, pending claims, dispositions, and program issues.
   A claim is pending when it is a `spatial_intervention`, has a valid typed
   parameter/completion/materialization contract, and its only readiness gaps
   are package identity, locator/candidate/source-feature reference, or
   evidence/source lineage. Missing typed parameters, invalid category/output,
   action output, and malformed semantics remain invalid and must not become
   pending spatial work.
4. Preserve the existing `interventions_from_claims()` strict behavior for
   direct callers and existing tests; the new classifier is the new accounting
   API. Change `merge_program_fragments()` to use the classifier and persist
   pending claims/dispositions on the assembled `PlanningProgram`.
5. Pending issues must be warnings with code `claim_grounding_pending` and
   include the missing requirement names. Invalid readiness issues keep the
   existing `claim_admission_incomplete` code/severity.
6. Add focused tests covering: a valid ready facility intervention; a facility
   spatial intent missing locator/evidence becomes pending and remains in the
   program; a missing typed parameter remains invalid; all claims receive a
   disposition; existing strict helper tests still pass.

Do not add regex parsing, coordinates, BSMs, WKT, candidate geometry, or a
compatibility alias. Do not change GROUND or SELECT in this task. Use the
existing Pydantic v2 style and preserve unrelated dirty-worktree changes.

Report contract: write `.analysis/sdd-complete-planning-layers/task-1-report.md`
with status DONE/DONE_WITH_CONCERNS/NEEDS_CONTEXT/BLOCKED, files changed, tests
run and exact output, self-review concerns, and a short note on how the new
classifier will be consumed by Task 2.
