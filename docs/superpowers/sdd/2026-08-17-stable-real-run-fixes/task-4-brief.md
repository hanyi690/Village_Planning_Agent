# Task 4 — Group equivalent Grounding facts

## Goal

Reduce redundant per-fact LLM fallback calls without merging semantically different facts. The prior run had 121 anchors and 71 deterministic best-effort anchors; repeated role/name groups were common.

## Allowed files

- `backend/app/domain/ground/anchors.py`
- `backend/app/infrastructure/llm/call_budget.py` only if required
- focused Grounding/timeout tests under `backend/tests/core/`

## Required behavior

- Group only equivalent facts using role/name/hint/candidate fingerprint (or a stronger equivalent key); same name alone must not merge.
- Resolve a representative once, then fan out result metadata without losing per-fact identity.
- Preserve KG/upload geometry and BSM ownership, independent fallback budgets, bounded concurrency, and deterministic best-effort after budget exhaustion.
- Add tests proving equivalent facts share work while different roles/candidates do not.

## Verification

Run focused Grounding/timeout tests with `-o addopts=`. Do not run real network calls.

## Report

Write a short report in this task directory and stage/commit only allowed files if committing is safe. Never stage unrelated files.
