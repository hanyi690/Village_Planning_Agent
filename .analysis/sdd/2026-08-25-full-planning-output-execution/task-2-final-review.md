# Task 2 final review — executable planning task graph

## Verdict: PASS for the code-review boundary

Reviewed the current worktree, not the earlier implementation/review reports.
No Critical or Important defect was found in the Task 2 change set.

## Required-behaviour checks

- **Lifecycle and lineage:** `PlanningTask` has deterministic terminal and
  transient states (`planned`, `ready`, `running`, `resolved`, `blocked`,
  `deferred`, `failed`); transitions are closed, ordered, and carry reasons,
  input/output artifact references, lineage, and binding ids. The graph
  rejects unknown bindings/dependencies, cycles, and stale fingerprints.
- **CAS binding boundary:** `PlanningTaskBinding.artifact_ref` is the strict
  immutable `ArtifactRef` contract, and each binding has an explicit JSON
  pointer. The executor writes resolved output references as
  `cas:<sha256>#<json-pointer>`. It does not invent an output domain:
  a candidate producer resolves only when its requested candidate-domain label
  is bound to an existing `GroundingResult` fragment.
- **Relation coverage:** the compiler retains all 18 templates in
  `PlanningIntentGraph`, including the five legacy topology relations
  (`contains`, `located_in`, `adjacent_to`, `intersects`, `overlaps`) and the
  required newer relations (`serve`, `provide_access`, `connect_network`,
  `follow_alignment`, `preserve_existing`, `upgrade_existing`, `near`,
  `precedes`). Parameter-specific demand/network/alignment/entity/area/
  constraint/event prerequisites are represented as typed input labels.
- **GROUND ownership:** the executor schedules topologically. Missing
  source-backed inputs become `blocked`; a missing demand or execution event
  is expressly `deferred` to SELECT; solver subproblems are expressly
  `deferred` to SELECT. Candidate domains are never selected or fabricated in
  GROUND.
- **GROUND → SELECT:** GROUND persists the executed `PlanningTaskGraph` as a
  `PlanningTaskGraph` CAS artifact. SELECT reloads and forwards it, logs its
  status counts, and the select gate fails closed when a task is `blocked` or
  `failed`, including its target in the human deferral scope.
- **Evidence requests:** TARGET_PROJECTION emits typed evidence requirements
  for every compiled task, including required input labels and graph
  fingerprint. A GROUND block therefore preserves both a lifecycle reason and
  an actionable pre-existing typed retrieval requirement rather than silently
  dropping the task.
- **Frontend visibility:** `planning_task_graph` is in the backend artifact
  registry and the frontend's actual artifact list, “目标与落地” group, and
  Chinese label (`空间任务执行图`). The existing generic structured-artifact
  panel renders its lifecycle/binding payload; it does not synthesize an
  outcome when the artifact is absent.

## Re-run verification

Command:

```text
pytest -o addopts='' -o pythonpath=backend \
  backend/tests/contracts/test_planning_task_graph.py \
  backend/tests/core/test_planning_task_graph_ground_execution.py \
  backend/tests/core/test_select_gate_deferred_targets.py -q
```

Result: **31 passed in 4.35s**.

The focused coverage includes all relation templates, transition validity,
deterministic graph checks, source-backed candidate binding, missing-source
blocking, missing-event deferral, SELECT gate consumption, and stale CAS
reference rejection for downstream deferral.

## Runtime limitation (not a code-review defect)

This review cannot substitute for the brief's required fresh provider-backed
session. No post-fix fresh session has yet reached SELECT in this review pass,
so there is no runtime session id, persisted task-graph digest, or observed
task-state count to certify. The next checkpoint must run a new real session
through SELECT and inspect the persisted `planning_task_graph` artifact; the
earlier L3-provider timeouts are not evidence that this Task 2 runtime gate
has passed.
