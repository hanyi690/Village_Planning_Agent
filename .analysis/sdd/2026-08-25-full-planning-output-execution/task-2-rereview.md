# Task 2 fix-round independent re-review

## Scope and verification

Reviewed the current worktree only within the files listed in
`task-2-rereview-package.md`, together with the brief, implementer record,
and prior review.  No source code was changed by this review.

Ran the current focused suite with repository addopts disabled:

```powershell
pytest -o addopts='' -o pythonpath=backend backend/tests/contracts/test_planning_task_graph.py backend/tests/core/test_planning_task_graph_ground_execution.py backend/tests/core/test_select_gate_deferred_targets.py backend/tests/core/test_stage_completion_contract.py backend/tests/core/test_stage_completion_post_l3_contract.py -q
```

Result: **35 passed in 4.36s**.

I also checked the relation binding pointer directly with the installed JSON
Pointer implementation.  `/intent_graph/relations/0` resolves a relation
array element; `/intent_graph/relations/relation:foo` raises
`JsonPointerException: 'relation:foo' is not a valid sequence index`.

## Remaining findings

### Important — relation declaration bindings contain invalid JSON Pointers

- **File:** `backend/app/domain/ground/task_graph_executor.py:111-121`
- **Evidence:** `PlanningIntentGraph.relations` is a list
  (`backend/app/contracts/planning/intent_graph.py:146-150`), but the executor
  builds every declaration binding with
  `json_pointer=f"/intent_graph/relations/{relation_ref}"`, where
  `relation_ref` is an opaque relation ID rather than the relation's numeric
  list position.  That string is not an RFC 6901 pointer to an element of the
  persisted `IntentCompilationResult`; it cannot be resolved on replay.
  Relation IDs containing `/` would also need pointer-token escaping.
- **Impact:** The new `PlanningTaskBinding` contract correctly carries a strict
  immutable `ArtifactRef`, but this particular binding fails the package's
  required *valid pointer semantics*.  Relation validation tasks may claim an
  input binding that a downstream consumer cannot dereference.
- **Required correction:** enumerate the persisted intent-graph relations and
  bind the matching relation to `/intent_graph/relations/<numeric-index>`
  (or persist a descriptor whose payload is an ID-keyed mapping).  Add a
  replay test that resolves every emitted `relation:<id>` binding pointer
  against the referenced `target_projection` payload, including an ID with an
  RFC 6901 escaped character.

## Confirmed corrections and positive checks

- All **18** current `RelationTemplate` values are now present in the typed
  intent contract, relation catalog, parameter mapping, and task compiler.
  The five topology templates (`contains`, `located_in`, `adjacent_to`,
  `intersects`, `overlaps`) use typed empty parameters and are compiled rather
  than silently dropped.  The compiler now correctly treats
  `parameter_status='not_required'` as satisfied
  (`planning_task_graph_compiler.py:574-610`).
- `PlanningTaskBinding` uses immutable, fully validated `ArtifactRef` objects
  and tracks binding IDs on tasks.  Candidate producer outputs resolve only
  from a matching resolved `GroundedCandidateDomain` with candidate IDs;
  missing domains block with `missing_ground_output_binding`
  (`task_graph_executor.py:141-159`, `:237-264`).  The focused negative test
  covers this behavior.
- Relation declaration and evaluation are distinct required labels.
  Missing demand/event input is no longer silently accepted; it is explicitly
  deferred to SELECT ownership, while other missing source inputs block
  (`task_graph_executor.py:133-139`, `:220-235`).  The missing-`precedes`
  event test passes.
- The executor schedules deterministically after validated DAG construction,
  records lifecycle transitions/bindings, and does not invoke a solver in
  GROUND.  Solver subproblems remain `solver_owned_by_select`
  (`task_graph_executor.py:189-288`).
- GROUND persists the executed graph after `GroundingResult`; its state copy
  includes the fresh grounding descriptor as a CAS parent
  (`ground.py:586-609`).
- SELECT now loads and re-emits `planning_task_graph`, passes it to the SELECT
  gate, and blocked/failed tasks produce
  `planning_task_prerequisites_incomplete` plus typed target scope
  (`select.py:113-119`, `:190-197`, `:473-482`; `select_gate.py:65-73`,
  `:137-149`).  The focused SELECT gate test passes.
- The frontend artifact key registry and intermediate-artifact panel list
  `planning_task_graph`, so the normal artifact API path can display the
  persisted execution graph (`artifact-keys.ts:14-24`,
  `IntermediateArtifactsPanel.tsx:24-37`, `:84-96`, `:365-375`).
- No `CurrentAsset`, `DemandRegisterRow`, or `CoverageDecision` reference was
  found in the re-review scope.  No solver call was found in the Task-2 GROUND
  code.  `git diff --check` for the scoped paths reported no whitespace error
  (aside from Git's pre-existing CRLF conversion warning for
  `stage_adapter.py`).

## Runtime limitation

The implementer record still contains no fresh real session checkpoint that
reaches SELECT with a persisted `planning_task_graph` digest and task-state
counts.  Per the brief, this does not permit full task acceptance even after
the code-level issue above is fixed.

## Verdicts

**Specification verdict: CHANGES REQUESTED.**  The prior Critical findings
are corrected, but the remaining invalid relation JSON Pointer violates the
descriptor-backed binding/replay contract.  A fresh SELECT checkpoint is also
still required for full acceptance.

**Quality verdict: CHANGES REQUESTED.**  The fix round materially improves
the design and test coverage, and all focused tests pass, but the untested
relation-pointer path is an Important replay defect.  Correct it, add the
pointer round-trip test, rerun the focused suite, then obtain the required
real SELECT evidence.
