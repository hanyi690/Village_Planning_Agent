# E-validation — M7 bounded auto-repair executor (round-1 audit)

## Files created
- `backend/app/domain/validation/adjustment_executor.py` — `BoundedAdjustmentExecutor`
  (implements `app.contracts.ports.adjustment.ValidationAdjustmentExecutor`) + `AdjustmentBudget`.
- `backend/app/domain/validation/report_service.py` — `build_validation_report(session_id, checks, responsible_stage)`.
- `backend/app/domain/validation/__init__.py` — exports `AdjustmentBudget`, `BoundedAdjustmentExecutor`.

Reuses existing contracts; nothing redefined (`ValidationReport`, `ValidationAdjustment`,
`AdjustmentExecutionResult`, `IterationRecord`, `AdjustmentFailure`). Pure Python, no
FastAPI/LangGraph/LLM — returns typed decisions the stage/workflow caller executes.

## AdjustmentBudget rules
- `max_rounds = 2`; `exhausted(consumed) = consumed >= max_rounds`.
- Loop shape: `EXECUTE -> VALIDATE -> apply() -> earliest-affected-stage recompute -> VALIDATE`.
- Caller keeps a ledger in `state["validation_adjustment_log"]`; each applied/reverted round is one entry.
- Verdicts: `applied` (caller recomputes `iteration.affected_target_refs` at
  `chosen.responsible_stage`), `noop` (report passed), `rejected` (no report),
  `human_required` (`budget_exceeded` | repeated fingerprint | oscillation | nothing adjustable).

## Fingerprint scheme
- `issue_fingerprint(responsible_stage, target_refs, bounded_params)` =
  `sha256(json({responsible_stage, sorted(set(target_refs)), sorted(bounded_params)}, sort_keys, ensure_ascii=False))`.
- `bounded_params` built per failed check: check_id, adjustment_type, expected/actual value, reason.
- `idempotency_key = "adj:" + fingerprint`; `adjustment_id = adj-{round}-{fp[:12]}`.
- Fingerprint order-independent (target refs and params are canonicalized); verified by hand.

## Dedup / parent-digest / oscillation
- Dedup: candidate whose fingerprint already appears in the ledger is skipped; if all repeat -> HUMAN.
- Parent digest: each input ref's `parent_digests` compared against `state["parent_digests"]`
  (plus `artifact_refs[].digest`); mismatch -> candidate excluded (stale ref).
- Oscillation: fingerprint whose latest ledger status is `reverted` -> rollback + `human_required`
  (code `unresolved`, message flags rollback). Checked before repeat/budget verdicts.
- Candidate order: stage priority EXECUTE < SELECT < GROUND < L3 < TARGET_PROJECTION, then fingerprint.

## Import verification
- `python -c "import app.domain.validation.adjustment_executor; import app.domain.validation.report_service; print('OK')"` -> `OK`.
- Note: pre-existing order-dependent cycle `app.contracts.workflow.repair` <-> `app.evidence.model`
  (relation_evidence re-imports repair while repair imports evidence). Worked around in-scope by
  preloading `app.evidence.model.base` before the repair import.
- Hand-test confirmed: deterministic fingerprint, applied -> oscillation rollback -> repeated-fingerprint
  HUMAN -> noop, budget_exceeded at 2 rounds.
