# H-validate-wiring — M7 executor wired into the VALIDATE stage (round-2 audit)

## What `validate_node` now returns
- Same StageCompletion-style patch as before (`artifact_refs.validation_report`,
  `validate_gate`, `gate_ref`, `upstream_gates`, context/retry patches) **plus**
  a typed top-level `next_action` and, on an applied round, the
  `validation_adjustment_log` ledger.
- `next_action` shapes:
  - `{"type": "recompute", "target_stage", "responsible_stage", "round", "adjustment_id", "issue_fingerprint"}`
    when the executor returned `applied` — the graph recomputes the
    earliest-affected stage named by `responsible_stage`.
  - `{"type": "forward", "target_stage": "reconcile"}` when the report passed (`noop`).
  - `{"type": "human_required", "status", "code", "message"}` for
    `rejected`/`failed`/`human_required`; never a silent approve.
- Gate is always typed: `RETRY_<STAGE>` on applied, `PASS` on noop, `HUMAN` on failure.

## How the executor is invoked
- `BoundedAdjustmentExecutor` (from `app.domain.validation.adjustment_executor`)
  is called with the immutable `WorkflowState` and the deterministic
  `ValidationReport` built by `validate_aggregate`.
- `executor.apply(state, report)` returns the bounded verdict; on `applied`,
  `executor.plan(...)` supplies the priority-ordered candidate whose
  `responsible_stage` picks the earliest-affected recompute target.
- `max_rounds = 2`: each applied iteration is appended to
  `state["validation_adjustment_log"]`, so the next VALIDATE round sees it and
  the executor stops (budget / dedup / oscillation) with `human_required`.
- Stage stays pure: no FastAPI, no LangGraph node calls; routing is done by
  `root_graph.route_after_validate` on the persisted gate + `next_action`.

## next_action contract
- The workflow routes on the typed `next_action` (and the mirroring gate route);
  the stage never jumps to a node itself.
- `target_stage` is the graph node name: `execute`/`select`/`ground`/`l3`/
  `target_projection`; `responsible_stage` is the domain literal
  (EXECUTE/SELECT/GROUND/L3/TARGET_PROJECTION).
- Reuses existing contracts (`ValidationReport`, `ValidationAdjustment`,
  `AdjustmentExecutionResult`); nothing redefined.

## Import verification (run from backend/)
- `python -c "import app.workflow.stages.validate; import app.domain.validation.adjustment_executor; print('OK')"` -> `OK`.
- `python -c "import app.workflow.root_graph; print('ROOT OK')"` -> `ROOT OK`
  (root_graph keeps importing `validate_node as _validate_stage`; signature stable).

## Files changed
- `backend/app/workflow/stages/validate.py` (rewritten stage body; `validate_node` signature preserved).
- No changes outside scope; `root_graph.py` untouched.
