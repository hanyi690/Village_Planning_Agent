# Task 3 — Preserve delivery refs across diagnostic/reconcile

## Goal

The prior real run successfully wrote delivery manifest, spatial snapshot, and render artifacts, then a no-progress diagnostic state replaced the final artifact refs. Preserve successful refs through reconcile/resume/diagnostic transitions.

## Allowed files

- `backend/app/infrastructure/runtime/planning_runtime_service.py`
- relevant acceptance test under `backend/tests/acceptance/` that asserts final delivery refs
- one focused core/runtime test under `backend/tests/core/` if needed

## Required behavior

- Merge artifact refs monotonically; diagnostic/end-state updates must not replace successful delivery refs with a smaller set.
- Keep state persistence and resume semantics intact.
- Add a deterministic regression test for delivery refs surviving a no-progress diagnostic transition.
- Do not run the real network test in the implementation task.

## Verification

Run focused runtime/acceptance collection or deterministic tests with `-o addopts=`.

## Report

Write a short report in this task directory and stage/commit only allowed files if committing is safe. Never stage unrelated files.
