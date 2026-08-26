# Task 2 independent review — historical initial pass

> **Superseded by the current fix-round review:**
> [task-2-rereview.md](task-2-rereview.md) records one remaining Important
> relation-binding JSON Pointer defect and the still-missing real SELECT
> checkpoint.  The original Critical findings below were corrected in the
> fix round.

**Reviewer scope:** only the seven implementation/test files named in
`task-2-review-package.md`, inspected in the shared dirty worktree at review
time.  No business-code changes were made by this review.

## Verification performed

- Read the task brief, implementer report, and review package.
- Inspected the task-owned lifecycle contract, compiler, GROUND executor,
  artifact/runtime and stage wiring, and focused test module.
- Ran:

  ```powershell
  pytest -o addopts='' -o pythonpath=backend backend/tests/contracts/test_planning_task_graph.py backend/tests/core/test_planning_task_graph_ground_execution.py -q
  ```

  Result: **17 passed in 3.91s**.

- Performed two deterministic in-process contract probes against the executor:
  1. A source binding without a `GroundedCandidateDomain` still produced a
     `resolved` candidate task and a synthetic
     `ground-task-output:c:candidate_domain:x` output.
  2. A standalone validation task requiring `event:complete` was returned as
     `resolved` with reason `ground_binding_complete` when no event evidence
     existed.

## Findings

### Critical — five explicitly required relation templates are omitted and silently dropped

- **Files:** `backend/app/domain/program/target_projection/planning_task_graph_compiler.py:32-46`, `backend/app/domain/program/target_projection/planning_task_graph_compiler.py:645-647`
- **Evidence:** `_RELATION_TEMPLATES` includes the newer parameterized
  templates, but not the mandatory existing templates `contains`,
  `located_in`, `adjacent_to`, `intersects`, or `overlaps`.  The compilation
  loop then uses `continue`, so any such current intent-graph relation is
  silently absent from the executable DAG rather than retained as a typed
  task with a blocked/deferred lifecycle.
- **Why this blocks acceptance:** Task 2 explicitly requires all current
  `PlanningIntentGraph` relation templates and names these five as the minimum
  existing coverage.  Silently discarding a planning constraint directly
  violates both relation completeness and the requirement not to hide missing
  work.
- **Required correction:** add typed compilation/prerequisites for all five;
  retain any genuinely unsupported relation as an explicit diagnostic task,
  never omit it.  Add contract cases for all five.

### Critical — executor fabricates candidate-domain completion without a grounded candidate binding

- **Files:** `backend/app/domain/ground/task_graph_executor.py:85-86`, `backend/app/domain/ground/task_graph_executor.py:151-174`
- **Evidence:** after an evidence task is resolved, line 174 adds its symbolic
  `produced_artifact_refs` to `available`.  A `candidate_producer` requires
  that symbolic evidence label, so it proceeds through `running` to
  `resolved` and line 86 emits a made-up
  `ground-task-output:<task-id>:candidate_domain:<target>` reference.  There
  is no check that `GroundedPlanningProblem.candidate_domains` contains a
  matching, resolved domain with candidate ids/geometry before claiming that
  output.  The probe described above reproduced this with zero candidate
  domains.
- **Why this blocks acceptance:** GROUND may bind a source-backed candidate
  domain, but it must not manufacture one.  This marks a candidate prerequisite
  as resolved without a source-backed candidate artifact and can make SELECT
  appear ready for a solver subproblem whose candidate set does not exist.
- **Required correction:** distinguish task declarations from bound outputs.
  Resolve a candidate producer only when the matching typed GROUND candidate
  domain is actually present and valid; otherwise block it with a typed
  missing-candidate reason.  Bind a stable real artifact/geometry reference
  rather than inventing a `ground-task-output` label.

### Important — `precedes` ignores its required event and can resolve with no event evidence

- **Files:** `backend/app/domain/program/target_projection/planning_task_graph_compiler.py:600-601`, `backend/app/domain/ground/task_graph_executor.py:89-96`
- **Evidence:** the compiler correctly emits
  `event:<required_event>` for `PrecedesParameters`, but `_missing_inputs`
  deliberately skips every `event:` label.  `_ground_available_inputs` never
  adds event evidence.  The direct probe therefore resolved a task requiring
  `event:complete` despite an empty `GroundedPlanningProblem`.
- **Why this matters:** `precedes` is one of the required templates and its
  event prerequisite is not optional.  This bypasses the required
  blocked/deferred lifecycle for absent input, rather than producing an
  evidence request.
- **Required correction:** model a deterministic event/evidence source (or
  defer this relation explicitly to the owning stage) and never ignore the
  label during missing-input evaluation.  Add a missing-event test.

### Important — task transition outputs are symbolic strings, not CAS artifact references

- **Files:** `backend/app/domain/ground/task_graph_executor.py:26-31`, `backend/app/domain/ground/task_graph_executor.py:85-86`, `backend/app/domain/ground/task_graph_executor.py:166-174`
- **Evidence:** input lineage correctly records source descriptors as strings
  of the form `cas:<key>:<digest>`.  In contrast, every resolved task output
  is a non-addressable `ground-task-output:<task-id>:<label>` string.  No
  per-task output descriptor is persisted, and no output digest/descriptor is
  verified on replay.
- **Why this matters:** the top-level `PlanningTaskGraph` is persisted as a
  CAS artifact and, after the latest GROUND wiring update, correctly has the
  new `grounding_result` as a parent (`ground.py:600-609`).  That does not make
  the individual output references actual CAS refs.  The brief requires task
  output bindings and lineage in CAS artifact refs; consumers cannot replay or
  validate the claimed per-task outputs from the strings currently recorded.
- **Required correction:** record descriptor-backed refs for bound outputs
  (or explicitly point each task output to the relevant typed sub-artifact in
  the persisted GroundingResult) and validate/replay them.  Add a repository-
  backed CAS/replay test, including the GroundingResult parent digest.

### Important — focused tests do not satisfy the required full-template or CAS coverage

- **File:** `backend/tests/core/test_planning_task_graph_ground_execution.py:45-88`
- **Evidence:** `test_compiler_includes_each_supported_relation_template`
  covers only the 13 templates in its local dictionary.  It omits the five
  explicitly required templates listed above.  The closest CAS assertion only
  checks the constructed input string
  `cas:grounding_result:ground-digest` (`:115-150`); it does not persist or
  reload an artifact, assert descriptor parent digests, or exercise replay.
  There is likewise no test that a missing event blocks/defer `precedes`, or
  that a missing candidate domain blocks a candidate producer.
- **Why this matters:** the green focused suite does not demonstrate the
  verification contract in the task brief.  It missed the two reproduced
  lifecycle violations and the omitted required relations.
- **Required correction:** extend the suite with every relation template,
  missing input cases for each typed prerequisite class, real CAS persistence
  and replay assertions, and a no-candidate-domain regression test.

## Confirmed positives

- The lifecycle model has the requested deterministic state names and
  transition events with reason/input/output/lineage fields
  (`task_graph.py:25-33`, `:53-69`, `:121-158`).
- Graph construction rejects unknown dependencies and dependency cycles
  (`task_graph.py:174-223`), and the executor processes dependency-ready tasks
  in deterministic sorted order (`task_graph_executor.py:120-188`).
- The current GROUND wiring persists `GroundingResult` first, executes the
  graph afterward, and persists the graph descriptor with the freshly created
  GroundingResult in its artifact-ref parents (`ground.py:586-609`).
- No solver invocation was found in the Task-2 GROUND addition; solver tasks
  are deferred with `solver_owned_by_select`
  (`task_graph_executor.py:143-149`).
- No `CurrentAsset`, `DemandRegisterRow`, or `CoverageDecision` compatibility
  reference was found in the task-owned files.  The compiler is typed and does
  not use a regex/natural-language special-case mapper for relation execution.
- `git diff --check` on the task-owned paths emitted no whitespace error (only
  Git's existing CRLF warning for `stage_adapter.py`).

## Verdicts

**Specification verdict: FAIL / not acceptable yet.**  The omission and
silent dropping of five mandatory relation templates, fabrication of candidate
completion, ignored `precedes` event input, and non-CAS task outputs violate
core Task-2 requirements.  Separately, the implementer report correctly
records that no fresh real checkpoint reached SELECT; the brief requires that
checkpoint before full completion can be claimed.

**Quality verdict: FAIL / revision required.**  The code has useful
deterministic structure and the latest top-level CAS-parent wiring is an
improvement, but its green focused tests leave the key contract breaches
undetected.  Resolve the Critical findings first, then add the missing
contract/replay coverage and obtain the required real SELECT checkpoint before
re-review.
