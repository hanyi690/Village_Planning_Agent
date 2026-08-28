# EXECUTE

`backend/app/modules/execute/` owns execution of an approved plan. It checks
the approval boundary, builds and schedules an immutable execution plan,
runs the typed workers, reconciles worker results, materializes staged
changes, and publishes `ExecutionResult`/`PlannedState` artifacts.

## Public boundary

- `application.ExecuteApplication.run(state) -> ExecuteRunResult`
- `application.run_execute(state) -> ExecuteRunResult`
- `approval_boundary.py` validates that execution is still bound to the
  approved scenario and target set.
- `plan_builder.py`, `task_scheduler.py`, `workers/`,
  `result_reconciliation.py`, and `materialize.py` own execution internals.
- `ports` defines worker and persistence ports.

EXECUTE requires canonical `approved_execution_input` and `execution_plan`
references. It cannot run from a free-form request, a SELECT summary, or a
newly invented candidate. Every task retains its approved target lineage;
failure, partial execution, deferred work, and insufficient evidence remain
distinct statuses.

## Runtime boundary

`stage.py` contains the production execution orchestration, while workflow
keeps only routing and shared checkpoint helpers. Workers are deterministic
where geometry and changesets are concerned. The stage persists staged
changes, planned state, execution evidence, and the final execution result
through the CAS runtime so VALIDATE can reload them independently.

## Verification

Use compile/import and the current-session runtime probes. Do not reintroduce
the removed test tree or use historical checkpoints. An execution probe is
only successful when an actual `ApprovedExecutionInput` is loaded and the
result can be reloaded from its artifact reference.
