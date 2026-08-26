# Task 2 implementer report — executable PlanningTaskGraph in GROUND

## Status

DONE_WITH_CONCERNS

## Implemented boundary

- Extended the task lifecycle contract with deterministic `planned`, `ready`,
  `running`, `resolved`, `blocked`, `deferred`, and `failed` states.  Every
  transition captures a reason, source/produced artifact refs, and lineage.
- Expanded the task compiler from five topology-only templates to the complete
  current `PlanningIntentGraph` relation vocabulary: `within_allowed_area`,
  `avoid_constraint`, `near`, `serve`, `provide_access`, `connect_network`,
  `follow_alignment`, `preserve_existing`, `upgrade_existing`, `part_of`,
  `co_locate`, `mutually_exclusive`, and `precedes`.  Typed relation parameters
  add demand, network, alignment, existing entity, constraint, area, parent,
  and event prerequisites as appropriate.
- Added `app.domain.ground.task_graph_executor`.  It topologically evaluates
  the graph against `GroundedPlanningProblem` bindings, candidate domains,
  geometry refs, parcel pool, and network refs.  It binds CAS source refs and
  symbolic output refs without inventing source facts or geometry.  Missing
  ground prerequisites are `blocked`; downstream tasks become `deferred`;
  solver tasks remain explicitly `deferred` with `solver_owned_by_select`.
- Wired it after `ground_aggregate` in `workflow/stages/ground.py`.  GROUND
  persists its ordinary `GroundingResult`, then persists the executed
  `PlanningTaskGraph` as a CAS artifact under `planning_task_graph`, making the
  state reachable at SELECT/frontend artifact projection without changing
  SELECT ownership of solving.

## Files owned by this task

- `backend/app/contracts/planning/task_graph.py`
- `backend/app/domain/program/target_projection/planning_task_graph_compiler.py`
- `backend/app/domain/ground/task_graph_executor.py`
- `backend/app/infrastructure/artifacts/runtime.py`
- `backend/app/workflow/stage_adapter.py`
- `backend/app/workflow/stages/ground.py`
- `backend/tests/core/test_planning_task_graph_ground_execution.py`

## Verification

- `pytest -o addopts='' -o pythonpath=backend backend/tests/contracts/test_planning_task_graph.py backend/tests/core/test_planning_task_graph_ground_execution.py -q`
  - `17 passed in 4.44s`
- `pytest -o addopts='' -o pythonpath=backend backend/tests/contracts/test_artifact_requirement_producers.py backend/tests/core/test_stage_completion_contract.py -q`
  - `7 passed in 3.79s`
- `python -m compileall -q backend/app/contracts/planning/task_graph.py backend/app/domain/ground/task_graph_executor.py backend/app/domain/program/target_projection/planning_task_graph_compiler.py backend/app/workflow/stages/ground.py`
  - passed
- `pytest -o addopts='' -o pythonpath=backend backend/tests/core/test_planning_task_graph_ground_execution.py backend/tests/contracts/test_planning_task_graph.py backend/tests/core/test_select_gate_deferred_targets.py -q`
  - `27 passed in 4.38s`
- `pytest -o addopts='' -o pythonpath=backend backend/tests/core/test_stage_completion_contract.py backend/tests/core/test_stage_completion_post_l3_contract.py backend/tests/core/test_planning_task_graph_ground_execution.py backend/tests/contracts/test_planning_task_graph.py -q`
  - `21 passed in 3.94s`

## Concerns / runtime checkpoint

No fresh real Task-2 session reached SELECT after these edits.  The only
currently running fresh session reached L1 `12/12`, L2 `4/4`, and L3 `9/12`,
then hit two provider timeouts; it predates this task's GROUND change and is
not used as Task-2 evidence.  Therefore there is no session id, run root,
executed task-state count, or Task-2 CAS digest to report yet.  A fresh run
that reaches SELECT must verify the `planning_task_graph` artifact and show no
tasks left in `planned` before this task is considered fully accepted.

## Scope checks

No retired `CurrentAsset`, `DemandRegisterRow`, or `CoverageDecision` path was
restored.  GROUND does not invoke a solver and does not manufacture final
geometry/candidates.

## Fix round 1 — submitted for re-review

- Added `contains`, `located_in`, `adjacent_to`, `intersects`, and `overlaps`
  to the typed IntentGraph relation catalogue with explicit empty parameters;
  they are compiled rather than silently skipped.
- Replaced synthetic task-output strings with typed `PlanningTaskBinding`
  records. Each binding contains a strict immutable `ArtifactRef` plus a JSON
  Pointer to a source-backed GroundingResult/TargetProjection fragment.
  Candidate producers can resolve only when a matching, resolved
  `GroundedCandidateDomain` contains actual candidates.
- Relation declarations and relation evaluations are separate labels. Missing
  demand and event inputs are explicitly deferred to their later owning stage;
  no prefix is silently ignored.
- SELECT now loads and propagates the graph, and its gate fails with
  `planning_task_prerequisites_incomplete` when any blocked/failed task exists;
  affected target refs enter the typed HUMAN scope. The frontend intermediate
  artifact panel lists `planning_task_graph` in the GROUND group.
- Focused verification after the final fix: `45 passed in 4.40s` across task graph,
  relation compiler, select gate, and stage completion contracts. Fresh real
  SELECT runtime evidence remains unavailable and is still an acceptance
  concern.
