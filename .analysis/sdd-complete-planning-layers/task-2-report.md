# Task 2 Report — Compile pending spatial intent into typed GROUND requirements

## Status

DONE

## Files changed

- `backend/app/contracts/workflow/parse_result_contracts.py`
  - Added the typed `ClaimDispositionAudit` target-projection snapshot and
    additive `pending_grounding_claims` / `claim_dispositions` fields on
    `IntentCompilationResult`.
- `backend/app/evidence/retrieval/requirements.py`
  - Projects pending L3 spatial claims as exact, source-routed spatial
    requirements with claim ID, pending status, and canonical missing
    requirement metadata.
  - Compiles explicit typed grounding requirements and relation templates, and
    applies only the allowed typed-field fallback for place/candidate,
    parcel/polygon, line/road/axis, and topology inputs.
  - Emits auditable package-identity and source-lineage requirements when
    those admission prerequisites are missing.
- `backend/app/domain/program/target_projection/compile.py`
  - Copies pending claim audit data onto target projection and adds the pending
    requirement subset alongside existing target-projection requirements.
- `backend/tests/contracts/test_l3_executable_target_admission.py`
  - Covers exact pending facility requirements, explicit place/candidate/
    parcel/network/topology/demand roles, package/source gaps, and the
    non-executable target-projection boundary.

## Focused verification

From `F:\project\Village_Planning_Agent\backend`:

```text
pytest tests/contracts/test_l3_executable_target_admission.py tests/contracts/test_artifact_requirement_producers.py tests/core/test_target_projection_semantic_contract.py -q -o addopts=''
..........................                                               [100%]
26 passed in 3.36s
```

```text
python -m compileall -q app/contracts/workflow/parse_result_contracts.py app/evidence/retrieval/requirements.py app/domain/program/target_projection/compile.py
```

```text
git diff --check
```

The repository default pytest configuration selects e2e tests, so the focused
pytest command explicitly disables configured addopts.

## Review fix loop

The Task 2 review found that TARGET_PROJECTION was independently compiling
pending claims' `spatial_requirements`, creating unaudited duplicate
requirements in the projection artifact. `requirements_from_target_projection`
now excludes IDs listed in `pending_grounding_claims`; pending requirements are
therefore present exactly once, are owned by the L3 producer, and retain their
pending disposition metadata.

The review also found that the typed place hints were only present on the base
claim requirement. Pending place-binding and candidate-geometry requirements
now include normalized `location_hints` in their scope and `place_hints`
metadata, together with the typed pending relation context. The added
regression assertions verify both the one-producer boundary and locator
context preservation.

## Self-review

- Pending claim requirements use only typed `PlanningSpatialRequirements`,
  relation-template, category, and output-kind data. No prose/regex parsing,
  geometry, coordinates, WKT, GeoJSON, BSM identities, candidates, or
  compatibility paths were introduced.
- Existing admitted intervention projection remains the sole producer of
  `spatial_reference_specs`; the strict admission recomputation is unchanged.
- TARGET_PROJECTION carries both its existing admitted-spec requirements and
  the pending L3 requirement subset. GROUND and SELECT code was not changed.
- No unrelated dirty-worktree changes were reset, reverted, or committed.

## Non-executable boundary

`pending_grounding_claims` are copied for audit and evidence retrieval only.
They produce no `SpatialReferenceSpec`, no executable target, no candidate
geometry, and no solver input in this task. Task 3 remains responsible for
having candidate producers consume these typed requirements after GROUND has
resolved authoritative source support.
