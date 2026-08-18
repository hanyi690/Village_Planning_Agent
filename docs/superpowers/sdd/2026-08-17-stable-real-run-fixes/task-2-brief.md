# Task 2 — Semantic issue partition

## Goal

The prior run reported 25 source semantic errors, but all were `classification_decision_required`. Separate classification decisions from true semantic source errors so classification runs before any L3 return decision.

## Allowed files

- `backend/app/domain/program/semantic_repair.py`
- `backend/app/domain/program/aggregate.py`
- `backend/tests/core/test_program_semantic_repair.py`

## Required behavior

- Preserve true semantic-error routing back to L3.
- Do not classify `classification_decision_required` as an automatic source semantic failure.
- Ensure classification issues are visible to the classification stage and are not silently dropped.
- Keep existing warning/info diagnostics meaningful.
- Add focused regression tests for mixed issue sets and classification-only issue sets.

## Verification

Run the focused semantic-repair tests with `-o addopts=`. Do not run real network calls.

## Report

Write a short report in this task directory and stage/commit only the allowed source/test files if committing is safe. Never stage unrelated files.
