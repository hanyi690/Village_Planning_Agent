# Task 2 fix-round re-review package

Review the current worktree, with the original brief at `task-2-brief.md`,
the implementer record at `task-2-report.md`, and prior findings at
`task-2-review.md`. The dirty worktree is shared: restrict attribution to the
following Task-2 fix-round files.

- `backend/app/contracts/planning/task_graph.py`
- `backend/app/contracts/planning/intent_graph.py`
- `backend/app/contracts/planning/relation_parameters.py`
- `backend/app/domain/program/target_projection/intent_graph_compiler.py`
- `backend/app/domain/program/target_projection/relation_catalog.py`
- `backend/app/domain/program/target_projection/planning_task_graph_compiler.py`
- `backend/app/domain/ground/task_graph_executor.py`
- `backend/app/domain/allocation/select_gate.py`
- `backend/app/workflow/stages/ground.py`
- `backend/app/workflow/stages/select.py`
- `backend/app/infrastructure/artifacts/runtime.py`
- `backend/app/workflow/stage_adapter.py`
- `backend/tests/core/test_planning_task_graph_ground_execution.py`
- `backend/tests/core/test_select_gate_deferred_targets.py`
- `frontend/src/features/planning/components/artifact-keys.ts`
- `frontend/src/features/planning/components/IntermediateArtifactsPanel.tsx`

Required re-review focus: no silent relation drops; strict descriptor-backed
task bindings with valid pointer semantics; candidate producers cannot invent
domains; relation/event/demand prerequisites are not silently accepted;
blocked tasks gate SELECT with typed target scope; UI can access the artifact.
Check no solver runs in GROUND and no retired compatibility registers return.
No real fresh run has yet reached SELECT, so report that limitation separately.
