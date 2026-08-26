# Task 2 review — Compile pending spatial intent into typed GROUND requirements

## Scope reviewed

- Brief: `.analysis/sdd-complete-planning-layers/task-2-brief.md`
- Updated implementation report and review package against
  `c8a3c0688900570c5302bf1f237c8d72c26b97da`
- The two prior Important findings: pending target-stage duplication and
  missing typed place-hint context.

## Verification

```text
cd backend
pytest tests/contracts/test_l3_executable_target_admission.py \
  tests/contracts/test_artifact_requirement_producers.py \
  tests/core/test_target_projection_semantic_contract.py -q -o addopts=''
..........................                                               [100%]
26 passed in 3.63s

git diff --check
passed (no output)
```

## Verdict

- **Specification compliance: PASS.**
- **Task quality: PASS.**

## Resolution of prior findings

1. **Pending requirements no longer leak into TARGET_PROJECTION.**
   `requirements_from_target_projection()` builds `pending_claim_ids` from
   `result.pending_grounding_claims` and skips those claims before projecting
   their `spatial_requirements`
   (`backend/app/evidence/retrieval/requirements.py:763-782`). The compiler
   instead appends the metadata-bearing pending subset from `requirements_from_l3()`
   (`backend/app/domain/program/target_projection/compile.py:610-619`).
   The added projection regression test asserts both that pending requirements
   have `producer_stage == "L3"` and that no TARGET_PROJECTION requirement
   targets the pending claim.

2. **Place hints now remain on typed GROUND-facing requirements.**
   Pending claim projection sends normalized `location_hints` as both
   `scope_context` and `metadata.place_hints`
   (`backend/app/evidence/retrieval/requirements.py:647-660`). The helper
   deterministically combines the claim ID and contextual hints into
   `target_scope` (`requirements.py:254-272`), which is used by the exact
   place-binding and candidate-geometry requirements. The regression test
   asserts scope `(claim_id, "社前村")`, `place_hints`, and the typed
   `relation_context`.

## Boundary and quality checks

- Pending base claim requirements are spatial and exact, carry the claim ID,
  `pending_grounding=True`, and the classified missing-requirement names.
- The closed typed fallback still supplies place binding and candidate
  geometry for all pending spatial claims, parcel membership for parcel/
  polygon outputs, network snapshot for line/road/axis outputs, and topology
  for typed topology relations. It does not parse prose or introduce
  coordinates, geometry, BSM identities, or compatibility aliases.
- Network, demand, and topology relation requirements retain relation IDs and
  templates; their scopes include the pending claim's place context and any
  typed subject/object references.
- No GROUND or SELECT production behavior was changed in this task; pending
  claims remain audit/evidence inputs only and create no spatial reference
  spec, candidate geometry, or solver input.

No Critical, Important, or Minor findings remain for Task 2.
