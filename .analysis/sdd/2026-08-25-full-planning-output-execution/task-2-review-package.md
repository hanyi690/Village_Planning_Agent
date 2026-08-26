# Task 2 review — PlanningTaskGraph / GROUND executor

Reviewer: fresh independent review

Verdict: **changes requested**.  The contract/compile surface is a useful
start, but the runtime executor does not yet provide truthful, consumable
GROUND bindings.  Do not use it as the Task-2 checkpoint until the P1 items
below are resolved and a fresh session reaches SELECT.

## Evidence inspected

- Task brief: `task-2-brief.md`.
- Implementer report: `task-2-report.md` (which itself records no fresh
  SELECT checkpoint).
- Current implementation: `backend/app/contracts/planning/task_graph.py`,
  `backend/app/domain/ground/task_graph_executor.py`,
  `backend/app/domain/program/target_projection/planning_task_graph_compiler.py`,
  `backend/app/workflow/stages/ground.py`, and `backend/app/workflow/stages/select.py`.
- Tests run:

  ```text
  pytest -o addopts='' -o pythonpath=backend \
    backend/tests/contracts/test_planning_task_graph.py \
    backend/tests/core/test_planning_task_graph_ground_execution.py \
    backend/tests/contracts/test_artifact_requirement_producers.py \
    backend/tests/core/test_stage_completion_contract.py \
    backend/tests/core/test_select_gate_deferred_targets.py -q
  ```

  Initial review found one immutable-completion-contract failure.  The
  implementer corrected the AST-visible dictionary construction during this
  review; the final independent re-run is **34 passed in 4.13s**.

- Direct typed reproductions (not mock LLMs):
  - A new facility with a resolved target domain, evidence ref, candidate ID,
    and candidate geometry is still `blocked` at
    `task:facility-1:evidence:demand` because the executor cannot derive
    `demand:facility-1` from any GROUND evidence.
  - A road with two endpoint refs, a resolved candidate domain, and
    `network:road` is still `blocked` at endpoint binding because it cannot
    derive `endpoint_refs:road-1` or either `endpoint:*` input.
  - A compiled `precedes` relation with two external endpoints and the typed
    `PrecedesParameters(required_event='complete')` is incorrectly
    `resolved`; its only required inputs are `event:complete` and
    `relation:order`, both of which the executor ignores.

## Findings

### P1 — GROUND cannot bind the prerequisites emitted by its own compiler

**Locations:** `backend/app/domain/ground/task_graph_executor.py:34-82`,
`:89-96`; `backend/app/domain/program/target_projection/planning_task_graph_compiler.py:394-497`.

The compiler emits `demand:<target>`, `endpoint_refs:<target>`, and
`endpoint:<ref>` prerequisites, but `_ground_available_inputs()` only derives
candidate-domain, geometry, target-evidence, binding, network, and parcel-pool
labels.  It does not inspect typed demand/evidence packets, endpoint bindings,
or source references.  Consequently, normal newly proposed facilities and
roads remain blocked even when the `GroundedPlanningProblem` contains the
available candidate/evidence results.  The focused tests only exercise the
special case of `source_identity:<entity>`, which the executor does derive.

**Required fix:** define a typed evidence/binding result contract (or an
explicit mapping from its actual fields to the compiler’s requirement labels)
for demand, endpoint, existing entity, network, allowed area, constraint,
alignment, parent, and event inputs.  Bind the precise source artifact/evidence
refs for each satisfied task.  Add tests that use real `GroundedPlanningProblem`
members for a new facility, road endpoints, and each relation parameter class;
they must resolve only when the corresponding proof is present.

### P1 — Task output refs are synthetic labels, not the claimed artifact bindings

**Locations:** `backend/app/contracts/planning/task_graph.py:83-104`,
`backend/app/domain/ground/task_graph_executor.py:85-86, 159-174`.

`produced_artifact_refs` and `output_artifact_refs` are declared as artifact
refs, but successful execution writes strings such as
`ground-task-output:<task-id>:evidence:demand:<target>`.  These are not CAS
descriptors, evidence IDs, geometry IDs, or typed result references.  Every
resolved task also receives the same broad source-CAS list, so the record
cannot establish which input actually proved which output.  The graph CAS
artifact is persisted, but it merely serializes this unbound symbolic status.

**Required fix:** distinguish `required_capability_labels` / planned output
labels from actual `ArtifactRef` (or a typed binding object carrying a CAS
descriptor plus evidence/geometry IDs).  A resolved task must contain exact
source and produced refs that exist in the artifact repository; a task without
such an output stays blocked/deferred.  Add a repository round-trip test that
loads each bound ref and verifies its schema/provenance.

### P1 — SELECT and the frontend projection never consume the executed graph

**Locations:** `backend/app/workflow/stages/ground.py:586-623`; 
`backend/app/workflow/stages/select.py:104-128` and the remaining SELECT
control flow.

GROUND adds `planning_task_graph` to its stage output refs, but SELECT only
loads `grounding_result`, `target_projection`, repair directives, and the
deferral ledger.  There is no load of `PlanningTaskGraph`, no lifecycle-state
gate, no propagation to the scenario/deferral result, and no frontend use of
this artifact key.  This fails the required boundary that SELECT/frontend see
task states beyond `planned`; storing an otherwise orphaned CAS artifact is
not reachability.

**Required fix:** load the executed graph at SELECT, make its blocked/deferred
states drive typed deferrals or solver admission, and project the task graph
or its lifecycle summary through the checkpoint/delivery API consumed by the
frontend.  Cover it with an end-to-end stage test and then a fresh real
session that records the graph digest and status counts at SELECT.

### P1 — Some required inputs are silently ignored, allowing false resolution

**Location:** `backend/app/domain/ground/task_graph_executor.py:89-96`.

`_missing_inputs()` unconditionally skips all `relation:*` and `event:*`
requirements.  A relation whose endpoints are external/missing has no terminal
dependencies; with provided parameters it can therefore be marked `resolved`
without a relation proof.  A `precedes` relation similarly ignores its required
event.  This contradicts the stated rule that missing prerequisites must be
typed blocked/deferred rather than silently completed.

**Required fix:** either introduce typed relation/event evidence bindings or
leave these validation tasks deferred until SELECT owns their evaluation.
Never exempt a requirement merely because its label prefix is inconvenient to
resolve.  Add negative tests for external-endpoint `near`/`serve` and
`precedes`.

### P2 — Relation coverage is syntactic, not a prerequisite expansion

**Location:** `backend/app/domain/program/target_projection/planning_task_graph_compiler.py:553-613`.

All 13 *current* `RelationTemplate` values are recognized (the older
`contains`/`located_in`/`adjacent_to`/`intersects`/`overlaps` names are not in
the current intent contract).  However every relation expands to one
`validation` task.  `serve`, `connect_network`, `follow_alignment`, and
constraint relations only append symbolic required-input labels; they create
no relation-scoped evidence/candidate producer task and have no source-binding
mechanism in GROUND.  The present template test proves label emission only,
not satisfiable relation-grounding behavior.

**Required fix:** make the compiler emit explicit producer nodes where a
relation needs demand/network/alignment/constraint/endpoint evidence, link
them to the validation/solver task, and make the executor resolve those
producer outputs from typed data.  Keep solver execution SELECT-owned.

## Positive checks

- The lifecycle transition set is deterministic and rejects invalid terminal
  transitions (`task_graph.py:72-158`).
- The compiler covers the complete *current* intent-graph relation vocabulary;
  it does not restore the retired register records.  `rg` found no
  `CurrentAsset`, `DemandRegisterRow`, or `CoverageDecision` references in the
  Task-2-owned files.
- The executor does not invoke a solver; it explicitly defers
  `solver_subproblem` tasks to SELECT (`task_graph_executor.py:143-149`).

## Acceptance status

**Not accepted.**  Fix the four P1 runtime/boundary findings first, then run
the complete focused suite and a fresh real session through SELECT.  The
runtime evidence must show the persisted `PlanningTaskGraph` CAS digest,
per-state counts, exact typed bindings for resolved tasks, and how blocked or
deferred tasks affect SELECT/frontend output.
