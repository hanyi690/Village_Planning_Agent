# Task 2 report — semantic issue partition

## Changes

- `semantic_repair.py` now excludes `classification_decision_required` from the source semantic-error set. A classification-only program can therefore reach the classification stage, while a real source semantic error still returns immediately to the L3 repair route.
- `aggregate.py` now runs pending classification decisions before the L3 gate evaluates real source semantic errors. Classification issues remain available to the classification stage; non-classification errors still produce the L3 route after that stage.
- Warning and info diagnostics remain in the program with their original severity. The semantic-repair audit info issue is still appended only when a repair candidate is applied.
- Added focused regression coverage for classification-only and mixed classification/semantic-error issue sets, including warning/info preservation.

## Verification

Command run from `backend`:

```text
python -m pytest -o addopts= tests/core/test_program_semantic_repair.py
```

Result: **10 passed**. No real network calls were run.

## Worktree note

The repository already contained unrelated user/agent changes. They were preserved; no reset, checkout, staging, or commit was performed.
