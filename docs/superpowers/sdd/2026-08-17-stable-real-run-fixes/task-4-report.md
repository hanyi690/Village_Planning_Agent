# Task 4 report — equivalent Grounding fact grouping

## Implemented

- Added a stable Grounding work key covering fallback kind, role, mention/name,
  spatial hint, and the ordered candidate fingerprint.
- Equivalent ambiguous facts share one candidate-selection call, while each
  fact receives its own `GroundedAnchor` built from its own fact metadata.
- Orientation rebinding uses the same representative-call/fan-out pattern;
  each fact is rebound independently so `location_fact_ref`, source span,
  BSM ownership, geometry, and trace metadata remain fact-specific.
- Candidate fingerprints include entity references, type/role, canonical name,
  geometry, BSMs, relations, score, membership, and order. Same-name facts
  with different roles or candidate sets therefore do not share work.
- Preserved the existing independent grounding budget, bounded concurrency,
  KG/upload-derived geometry and BSMs, coordinate deduplication, and
  deterministic first-candidate/best-effort behavior after budget exhaustion.
- Tightened name-backfill mention aggregation to include role and location,
  preventing same-name facts from crossing those boundaries.

## Review follow-up fixes

- Empty village/water/road fallback results no longer create an anchor with no
  BSM, geometry, or entity reference. Such facts are skipped after their
  deterministic/LLM paths finish, with a `skip_no_spatial_evidence` trace
  retained in the per-fact working item and logged for diagnosis.
- Village spatial fallback is now split into read-only candidate planning,
  bounded/equivalence-grouped LLM selection, and ordered commit. The LLM wave
  never mutates `_grounding_used_cluster_bsms`; commit rechecks currently
  available clusters and updates ownership one fact at a time, preserving
  deterministic allocation when an earlier fact consumed the representative's
  selected cluster.

## Tests

Command:

```text
pytest -q -o addopts= backend/tests/core/test_grounding_equivalent_fact_grouping.py backend/tests/core/test_timeout_boundaries.py backend/tests/core/test_unified_grounding_core.py backend/tests/core/test_grounding_llm_reason_alignment.py
```

Result: `23 passed`.

The tests run with fake in-memory indexes and an async fake LLM; no real
network/provider call was made. Coverage includes equivalent facts sharing one
call, distinct roles not sharing, distinct candidate fingerprints not sharing,
per-fact identity/BSM/geometry fan-out, empty village/water/road candidates
being skipped, bounded village fallback concurrency with ordered BSM ownership,
budget exhaustion with deterministic continuation, and existing Grounding
timeout/alignment regressions.

## Scope

Changed implementation: `backend/app/domain/ground/anchors.py`.

Changed focused test: `backend/tests/core/test_grounding_equivalent_fact_grouping.py`.

No changes were made to `backend/app/infrastructure/llm/call_budget.py`.
