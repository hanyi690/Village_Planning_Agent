# Task 1 — Classification generator stability

## Goal

Fix the L3 aggregate classification path that currently sends 25 records plus long rationale/catalog context into an ambiguous `list | str` Instructor model and fails with trailing JSON characters.

## Allowed files

- `backend/app/domain/program/classification_generator.py`
- `backend/tests/core/test_l3_classification_generator.py`

## Required behavior

- Use a strict Pydantic list response contract; do not accept nested string output.
- Split classification into small bounded batches (choose a sensible size such as 4–8) and keep closed-set Appendix 5 validation.
- Keep bounded retry behavior and useful failure diagnostics; do not reintroduce unbounded loops.
- Keep output compact: code/index/short reason only if reason is needed.
- Do not alter `development_goals=36` semantics.
- Add regression tests for batch splitting, trailing-character/invalid response handling, and closed-set behavior.

## Verification

Run the focused classification test file with `-o addopts=`. Do not run real network calls.

## Report

Write a short report in this task directory and stage/commit only the allowed source/test files if committing is safe in the dirty worktree. Never stage unrelated files.
