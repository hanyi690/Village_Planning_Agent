# Task 3 Independent Review — PlanningTaskGraph

**Reviewer:** independent review agent  
**Scope:** `task_graph.py`, `planning_task_graph_compiler.py`, TARGET_PROJECTION attachment, requirement production, and GROUND consumption path.  
**Initial result:** **CHANGES REQUIRED**  
**Repair re-review result:** **PASS (Task 3 scope)**

## Important finding — task graph does not enter the actual GROUND work path

Task 3's purpose is to expand typed intent into evidence prerequisites and candidate-producer work which GROUND can consume.  The implementation creates an internally consistent graph, but it is not connected to the production GROUND path:

1. `compile_program_deterministic()` compiles the intent graph exclusively from `admitted_program` (`backend/app/domain/program/target_projection/compile.py:519-535`).  A `pending_grounding_claim` is deliberately absent from `program.interventions`, so it produces neither an intent node nor a PlanningTask.  The existing regression test actually proves this current behavior: `test_pending_claim_is_audited_on_projection_without_target_specs` asserts `specs == []` and has no task-graph/GROUND assertion.
2. GROUND creates evidence packet work exclusively by iterating `spatial_reference_specs` (`backend/app/workflow/stages/ground.py:211-218`), then `ground_aggregate()` resolves exclusively those specs (`backend/app/domain/ground/aggregate.py:820-830`).  A task-only target therefore has no retrieval request, candidate domain, query evidence row, or unresolved/deferred ground result.
3. `requirements_from_target_projection()` serializes every task as a generic `EvidenceRequirement` (`backend/app/evidence/retrieval/requirements.py:814-862`), but no task-capability executor consumes `planning_task_evidence`, `planning_task_candidate_producer`, or `planning_task_solver_subproblem`.  Passing an arbitrary graph requirement to retrieval cannot prove that a candidate producer or solver ran; the evidence coverage implementation matches source claims/text (`backend/app/evidence/retrieval/coverage.py:192-276`) and does not materialize `produced_artifact_refs`.

This is material because the user-facing requirement is specifically to allow L3 spatial intent with incomplete locators/lineage to receive more spatial information downstream, not merely to save a second descriptive graph.  The current patch leaves the behavior shown by the fresh run unchanged: pending claims remain outside GROUND.

### Required repair

Introduce a typed GROUND work-item/adapter boundary, rather than turning task labels into text retrieval requests.  It should:

- compile a `pending_grounding_claim` into an explicitly typed target/task using its existing typed category/output/parameters and claim ID, without parsing claim prose or inventing a locator;
- make GROUND enumerate executable **evidence** and **candidate-producer** tasks in dependency order, with capabilities routed to the existing Bundle/KG/evidence/candidate modules;
- record a typed task result (produced artifact refs, source evidence refs, or an explicit blocked/deferred reason) in the GROUND artifact;
- create a `GroundedTargetDomain` or explicit unresolved/deferred domain for every spatial task target, so it cannot silently vanish before SELECT;
- leave solver/validation authority at SELECT/VALIDATE.  They must not be marked satisfied merely because retrieval returned a text claim.

Add an end-to-end regression that begins with a `pending_grounding_claim` with no `SpatialReferenceSpec`, invokes the actual `ground_node` / aggregate path on a fixture context, and proves: a task was consumed, an evidence query or explicit blocked result is recorded, and the target appears in GroundedPlanningProblem as candidate/resolved or deferred/unresolved.  A second test should prove an admitted spec-backed target does not execute the same requirement twice.

## Important finding — arbitrary supplied graph fingerprints are accepted unchanged

`PlanningTaskGraph.validate_and_canonicalize()` derives `fingerprint` only when the field is empty (`task_graph.py:127-136`).  It accepts a caller-supplied fingerprint even if it represents different tasks.  A direct current-code probe constructed two different one-task graphs with the same provided fingerprint and printed `True` for fingerprint equality.

The graph fingerprint is subsequently used as the sole `source_artifact_ref` for every task requirement (`requirements.py:851,859`).  This makes provenance / deduplication ambiguous for loaded or replayed artifacts, contrary to the requested deterministic canonicalization and audit boundary.

### Required repair

Always calculate the canonical payload hash, then either overwrite the field with it or reject a non-empty mismatch.  Add a contract test for reordered equivalent tasks (same hash) and for a stale or forged supplied fingerprint (validation error or canonical replacement).

## What is correct in the current patch

- The task graph itself is typed-only: its compiler branches on target kind, operation, endpoint refs, typed relations, and capability enums; it does not inspect target `name` or other natural-language fields (`planning_task_graph_compiler.py:1-7`, `81-321`).
- Task and graph collections are canonicalized, duplicate IDs and unknown dependencies are rejected, and cycle rejection is implemented (`task_graph.py:64-136`).
- Facility, existing-asset, network, parcel/site-area, topology relation and non-spatial action task shapes are covered by focused tests.
- No direct geometry, BSM, candidate selection, or LLM call was added to TARGET_PROJECTION.  This preserves the intended planning/execution boundary.

## Verification run

All commands used current worktree code; results do **not** close the Important issues above:

```text
pytest tests/contracts/test_planning_task_graph.py \
       tests/contracts/test_artifact_requirement_producers.py \
       tests/contracts/test_l3_executable_target_admission.py \
       tests/core/test_target_projection_semantic_contract.py -q -o addopts=''
# 35 passed in 3.10s

pytest tests/contracts/test_l3_executable_target_admission.py::test_pending_claim_is_audited_on_projection_without_target_specs -q -o addopts='' -vv
# 1 passed in 3.27s (and confirms no specs are created for the pending claim)

python -m compileall -q app/contracts/planning/task_graph.py \
  app/domain/program/target_projection/planning_task_graph_compiler.py \
  app/domain/program/target_projection/compile.py \
  app/evidence/retrieval/requirements.py
# passed

git diff --check
# passed
```

No production files were edited by the reviewer.

## Repair re-review (current worktree)

Both Important findings above are now resolved within Task 3's boundary.

1. **Pending typed spatial intent now reaches GROUND.**
   `pending_claim_grounding_specs()` deterministically maps the existing typed
   `PlanningClaim` category, output kind, hint, source refs, and typed
   parameters to a separate internal `SpatialReferenceSpec` work item
   (`planning_task_graph_compiler.py:205-280`).  It does not parse the claim
   statement and cannot manufacture a BSM, coordinate, or geometry.  The
   compiler stores these as `pending_grounding_specs`, separately from formal
   projection specs (`compile.py:536-541,594-615`).  `ground_node` then combines
   formal and pending work specs exactly once for packet retrieval and
   `ground_aggregate()` (`ground.py:420-431,491-512`); pending claim semantics
   are also copied into target metadata (`ground.py:836-862`).

   The added aggregate regression constructs a pending facility claim without a
   formal projection spec and proves the emitted ground query evidence,
   candidate target reference, and `GroundedPlanningProblem` domain are all
   keyed to its claim ID:
   `tests/core/test_grounding_spatial_domains.py:238-287`.

   The PlanningTaskGraph is still a declaration/ordering artifact rather than
   an execution engine, which is correct for Task 3: GROUND consumes the
   parallel typed work spec, while SELECT/VALIDATE remain solver/validation
   authorities.  The claim-to-spec and claim-to-task transformations are
   deterministic and use the same typed source fields.

2. **Task graph fingerprints now have an integrity boundary.**
   `PlanningTaskGraph` always derives the canonical hash and rejects a supplied
   mismatch (`task_graph.py:127-138`).  The stale-fingerprint regression is in
   `tests/contracts/test_planning_task_graph.py:177-182`.

### Fresh verification

```text
pytest tests/contracts/test_planning_task_graph.py \
       tests/contracts/test_l3_executable_target_admission.py \
       tests/contracts/test_artifact_requirement_producers.py \
       tests/core/test_target_projection_semantic_contract.py -q -o addopts=''
# 37 passed in 3.03s

pytest tests/core/test_grounding_spatial_domains.py::test_pending_spatial_claim_is_consumed_by_ground_aggregate -q -o addopts='' -vv
# 1 passed in 3.60s

python -m compileall -q app/contracts/planning/task_graph.py \
  app/contracts/planning/intent_graph.py \
  app/contracts/workflow/parse_result_contracts.py \
  app/domain/program/target_projection/planning_task_graph_compiler.py \
  app/domain/program/target_projection/compile.py \
  app/evidence/retrieval/requirements.py app/workflow/stages/ground.py
# passed

git diff --check
# passed
```

### Non-blocking current-worktree failures observed during broader regression

These do not touch the Task 3 repair source files, but they must be repaired
before a project-wide green claim:

- `tests/core/test_grounding_spatial_domains.py` has one pre-existing/current
  behavior mismatch: the ambiguous parcel-set test expects one combined
  candidate, while current `ground_aggregate()` returns two explicit
  alternatives.  The Task 3 pending-claim regression itself passes.
- `tests/acceptance/test_grounding_anchors_fixture.py::test_real_fixture_ground_anchors_and_render`
  fails because its `_DispatchLLM` fixture does not implement
  `with_structured_output`; the test consequently misses the `122乡道` anchor.
  The Task 3 patch does not change the anchor implementation or fixture.
