# A — program assembler typed boundary

Date: 2026-08-12
Scope: `backend/app/domain/program/` only.

## Files

Created:
- `backend/app/domain/program/intent_spec.py` — typed per-task intent spec
  (`TaskIntentSpec` with `{intent, site_selection_ref, geometry_expectation,
  deps, parent_refs, expected_output_kind}`), `PlanningHumanDecision`, and
  `PlanningIntentSpecSet`. `ConfigDict(extra="forbid")` everywhere; reuses
  `WorkerType` from `execution_plan_contracts`.

Changed:
- `backend/app/domain/program/assembler.py` — added typed entry point and
  module-level imports; removed the legacy function's redundant inner
  `classification_program_issues` import; extended `__all__`.

## New assembler entry-point signature

```python
def assemble_program_from_decisions(
    demand_portfolio: DemandPortfolio,
    portfolio_decision: PortfolioDecision,
    classification_decisions: list[ClassificationDecision],
    *,
    human_decisions: list[PlanningHumanDecision] | None = None,
    intent_specs: list[TaskIntentSpec] | None = None,
    dependencies: list[InterventionDependency] | None = None,
    claims: list[PlanningClaim] | None = None,
    omissions: list[str] | None = None,
    evidence_gaps: list[EvidenceGap] | None = None,
    program_issues: list[ProgramIssue] | None = None,
    dimension_provenance: list[Provenance] | None = None,
) -> PlanningProgram
```

## What was removed / gated

- No LLM-text/report-text inference path existed inside `assembler.py`
  (proposal text never became kind/classification/geometry there; text
  inference lives in `claim_adapter.proposals_from_claims`, out of scope).
- The legacy `assemble_planning_program(proposals, ...)` API is preserved
  unchanged so `app.agent.l3_plan.aggregate` and tests keep importing it.
- New path is typed-input-only: object kind from `DemandItem.kind`,
  geometry expectation from `DemandItem.geometry_kind` (canonicalized per
  kind with a `geometry_kind_normalized` warning), classification only from
  resolved `ClassificationDecision`, names only from explicit
  `PlanningHumanDecision`. Unallocated/rejected demands become
  `demand_not_allocated` / `human_rejected_target` issues, never guesses.
- `TaskIntentSpec.deps` translate to `InterventionDependency`; unknown
  intent targets raise `intent_spec_unknown_target`.

## Verification

- `python -c "import app.domain.program.intent_spec; import
  app.domain.program.assembler; print('OK')"` → `OK`
- Import of `app.agent.l3_plan.aggregate` and all sibling program modules → OK.
- Smoke run of `assemble_program_from_decisions` (assigned/action/unplaced
  demands, resolved GHYTBM decision, human name, intent deps) → expected
  interventions, deps, issues; legacy `assemble_planning_program` → OK.
- `tests/core/test_target_projection_location.py::...` → 1 passed
  (run with `-o addopts=""` because project default marker filter
  `-m "e2e and not slow"` otherwise deselects core tests).
