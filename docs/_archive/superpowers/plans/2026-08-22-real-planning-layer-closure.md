# Real Planning Layer Closure Implementation Plan

> Status: SUPERSEDED. Do not use this historical task breakdown as the current
> input contract. Session startup no longer aliases/scans repository
> `project_doc` files; the current L1/L3 dual-channel contract is maintained in
> [`2026-08-24-l1-l3-planning-structured-output.md`](2026-08-24-l1-l3-planning-structured-output.md),
> [`docs/design/01_CONTRACTS_AND_INVARIANTS.md`](../../design/01_CONTRACTS_AND_INVARIANTS.md),
> and [`docs/architecture/CURRENT_RUNTIME.md`](../../architecture/CURRENT_RUNTIME.md).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one newly-created JinTian session consume the original current-status report, complete the canonical planning chain, materialize an approved and validated planning state, and expose non-empty same-run planning layers that Playwright verifies in the frontend.

**Architecture:** Preserve the canonical `L1 → L2 → L3 → TARGET_PROJECTION → GROUND → ScenarioSet → ApprovedExecutionInput → Atomic EXECUTE → ValidationCertificate → RECONCILE → DELIVER` chain. Tighten each boundary so declarative claims do not become executable targets, incomplete grounding cannot become feasible, and execution cannot run without an immutable approval. Use LLMs for typed proposal generation and explanation while deterministic contracts, spatial evaluators, and gates decide executability.

**Tech Stack:** Python 3.12, Pydantic v2, LangGraph, FastAPI, pytest, TypeScript/React, Jest, Playwright.

## Global Constraints

- Preserve unrelated changes in the existing dirty worktree.
- RAG remains disabled for the real acceptance run; session text, project documents, KG, bundle, artifacts, and history remain available.
- `MinerU_markdown_*现状报告*.md` is an input source, never a generated report.
- Formal EXECUTE consumes only `ApprovedExecutionInput`; diagnostic previews must not create a formal `PlannedState` or commit ID.
- Incomplete or human-required grounding may produce diagnostic rows, but never feasible, Pareto, recommended, approved, or formal execution results.
- Source layers are current-state reference data; only delivery projection may be presented as planned layers.
- The shared `.git` directory is read-only in this environment, so each task ends with a recorded test checkpoint instead of a git commit.

---

### Task 1: Bind the original current-status document to L1

**Files:**
- Modify: `backend/app/infrastructure/context/planning_context.py`
- Modify: `backend/app/domain/assessment/analysis_node.py`
- Test: `backend/tests/contracts/test_planning_context_inputs.py`
- Test: `backend/tests/core/test_l1_current_status_prompt_input.py`

**Interfaces:**
- Consumes: `PlanningContext.input_documents`, including `source="project_doc"` and `type="current_status"`.
- Produces: `PlanningContext.input_texts() -> dict[str, str]` with stable document-type keys and a deduplicated current-status corpus used by L1.

- [ ] **Step 1: Write a failing context test**

```python
def test_input_texts_indexes_and_merges_project_documents_by_type():
    context = _context_with_documents(
        {"source": "project_doc", "type": "current_status", "content": "现状甲"},
        {"source": "project_doc", "type": "current_status", "content": "现状乙"},
        {"source": "project_doc", "type": "planning_approach", "content": "规划设想"},
    )
    texts = context.input_texts()
    assert texts["current_status"] == "现状甲\n\n现状乙"
    assert texts["planning_approach"] == "规划设想"
```

- [ ] **Step 2: Run the context test and confirm the current first-document-only behavior fails**

Run: `D:\python\python.exe -m pytest -q -o addopts='' backend/tests/contracts/test_planning_context_inputs.py`

- [ ] **Step 3: Aggregate distinct document bodies by canonical source and document type**

```python
def input_texts(self) -> dict[str, str]:
    buckets: dict[str, list[str]] = {}
    for document in self.input_documents:
        keys = [str(document.get("source") or "")]
        if document.get("source") == "project_doc":
            keys.append(str(document.get("type") or ""))
        for key in filter(None, keys):
            if content and content not in buckets.setdefault(key, []):
                buckets[key].append(content)
    return {key: "\n\n".join(values) for key, values in buckets.items()}
```

- [ ] **Step 4: Write a failing L1 input test**

Assert that `get_layer1_prompt(..., raw_data=...)` receives both session `village_data` and the `current_status` corpus, but not `planning_approach` or `detailed_plan` text.

- [ ] **Step 5: Build the L1 factual corpus explicitly**

```python
village_data = "\n\n".join(
    value for value in (
        input_texts.get("village_data", ""),
        input_texts.get("current_status", ""),
    ) if value.strip()
)
```

- [ ] **Step 6: Run the two focused tests and record the checkpoint**

Run: `D:\python\python.exe -m pytest -q -o addopts='' backend/tests/contracts/test_planning_context_inputs.py backend/tests/core/test_l1_current_status_prompt_input.py`

### Task 2: Turn typed L1 output failure into a recoverable, observable breakpoint

**Files:**
- Modify: `backend/app/domain/assessment/analysis_node.py`
- Modify: `backend/app/workflow/conversation/edges.py`
- Modify: `backend/app/infrastructure/runtime/planning_runtime_service.py`
- Test: `backend/tests/core/test_gate_route_policy.py`
- Test: `backend/tests/core/test_l1_typed_output_recovery.py`
- Test: `backend/tests/core/test_runtime_terminal_projection.py`

**Interfaces:**
- Consumes: provider content, typed-output exceptions, `dimension_retry_counts`.
- Produces: parsed typed L1 output, a bounded same-dimension retry/HUMAN interrupt, or an explicit failed diagnostic terminal.

- [ ] **Step 1: Add failing tests for content-JSON fallback and malformed observations**

Use a provider response containing JSON in `message.content` without tool calls and assert that a schema-valid body is recovered when possible; malformed JSON must return the exact dimension and code without marking it complete.

- [ ] **Step 2: Add `llm_typed_output_error` to the bounded transient/HUMAN route**

The first typed-output failure must preserve the failed dimension in the checkpoint and route to `human_review`, not `END`.

- [ ] **Step 3: Add terminal persistence after retry exhaustion**

Persist `fatal_error`, `diagnostic_terminal`, `delivery_status="diagnostic_only"`, `phase="completed"`, and the database task status `failed` when the retry budget is exhausted.

- [ ] **Step 4: Assert the public projection cannot remain running after background completion**

The state projection must be `paused` for a recoverable typed-output failure or `failed` for an exhausted one.

- [ ] **Step 5: Run the focused routing and runtime tests**

Run: `D:\python\python.exe -m pytest -q -o addopts='' backend/tests/core/test_gate_route_policy.py backend/tests/core/test_l1_typed_output_recovery.py backend/tests/core/test_runtime_terminal_projection.py`

### Task 3: Separate planning claims from executable spatial targets

**Files:**
- Modify: `backend/app/contracts/program.py`
- Modify: `backend/app/domain/program/claim_adapter.py`
- Modify: `backend/app/domain/program/assembler.py`
- Modify: `backend/app/domain/program/gate.py`
- Modify: L3 structured-output prompt/schema producer under `backend/app/domain/program/`
- Test: `backend/tests/contracts/test_l3_executable_target_admission.py`
- Test: `backend/tests/core/test_l3_program_target_compaction.py`

**Interfaces:**
- Consumes: `PlanningClaim` records from each L3 dimension.
- Produces: claims partitioned into evidence statements, indicators, constraints, objectives, non-spatial actions, project packages, and executable spatial interventions.

- [ ] **Step 1: Add an explicit `planning_role` to `PlanningClaim`**

```python
planning_role: Literal[
    "evidence_statement",
    "indicator",
    "constraint",
    "objective",
    "non_spatial_action",
    "project_package",
    "spatial_intervention",
] = "evidence_statement"
```

- [ ] **Step 2: Write admission tests**

Assert that indicators such as population/land-scale control, qualitative structure slogans, preserve-only observations, and digital governance actions remain claims; only `spatial_intervention` records with executable geometry contracts become `PlanningIntervention`.

- [ ] **Step 3: Enforce deterministic executable-target readiness**

Require a non-action output kind, compatible category parameters, explicit materialization role where applicable, a spatial locator or source feature ref, and at least one evidence/source fact ref. Missing requirements produce typed `ProgramIssue` records instead of targets.

- [ ] **Step 4: Cluster cross-dimension claims into project packages**

Claims that refer to the same canonical asset/project support one target rather than creating parallel targets in ecological, land-use, spatial-structure, and project-bank dimensions.

- [ ] **Step 5: Fail the L3 gate when target admission is unresolved**

`compilation_status="needs_review"` or error diagnostics must route to HUMAN before GROUND.

- [ ] **Step 6: Run L3 admission and compaction tests**

Run: `D:\python\python.exe -m pytest -q -o addopts='' backend/tests/contracts/test_l3_executable_target_admission.py backend/tests/core/test_l3_program_target_compaction.py`

### Task 4: Make grounding completeness authoritative in ScenarioOptimizer

**Files:**
- Modify: `backend/app/domain/allocation/scenario_optimizer.py`
- Modify: `backend/app/contracts/planning/scenario.py`
- Test: `backend/tests/core/test_scenario_optimizer.py`
- Test: `backend/tests/contracts/test_grounded_problem_completeness.py`

**Interfaces:**
- Consumes: `GroundedPlanningProblem.candidate_completeness` and objective definitions compiled upstream.
- Produces: diagnostic provisional rows for incomplete problems, or feasible/Pareto/recommended scenarios only for `candidate_complete` problems.

- [ ] **Step 1: Add the degraded-geometry regression test**

Construct a problem with a valid candidate geometry and `geometry_uncertainty_reasons`; assert `can_solve is False`, all rows are provisional, and feasible/Pareto/recommended are empty.

- [ ] **Step 2: Pass the completeness gate into scenario construction**

```python
status = "complete" if problem.can_solve and local_checks_pass else "partial"
```

- [ ] **Step 3: Make objective direction authoritative**

Use `ObjectiveDefinition.direction` when testing Pareto dominance; reject objective vectors missing a declared evaluator result.

- [ ] **Step 4: Run scenario and grounding contract tests**

Run: `D:\python\python.exe -m pytest -q -o addopts='' backend/tests/core/test_scenario_optimizer.py backend/tests/contracts/test_grounded_problem_completeness.py`

### Task 5: Remove formal execution without approval and remove partial-commit compatibility

**Files:**
- Modify: `backend/app/domain/materialization/atomic_commit.py`
- Modify: `backend/app/workflow/stages/execute.py`
- Modify: `backend/app/contracts/artifacts/validation_certificate_contracts.py`
- Modify: `backend/app/workflow/stages/validate.py`
- Test: `backend/tests/core/test_atomic_execution_commit.py`
- Test: `backend/tests/core/test_execute_approval_boundary.py`
- Test: `backend/tests/contracts/test_approval_and_validation_certificates.py`

**Interfaces:**
- Consumes: executable `ApprovedExecutionInput` and its derived `ExecutionPlan`.
- Produces: committed or aborted `ExecutionResult`; no formal `partial` atomic state.

- [ ] **Step 1: Add tests that missing approval always aborts before workers**

- [ ] **Step 2: Require non-null executable approval inside `commit_execution_batch`**

```python
if batch.approved_input is None:
    diagnostics.append("approved execution input is missing")
elif not batch.approved_input.can_execute:
    diagnostics.append("approved execution input is not executable")
```

- [ ] **Step 3: Remove the provisional formal EXECUTE branch**

Diagnostic previews may persist diagnostic artifacts but may not invoke the formal worker graph, create a commit ID, promote staged refs, or claim atomic execution.

- [ ] **Step 4: Remove `partial` from formal atomic and certificate acceptance semantics**

`ValidationCertificate.can_reconcile` requires a passed certificate and committed atomic execution; explicitly scoped/approved partial delivery is represented by a reduced approved problem, not a partial transaction.

- [ ] **Step 5: Run approval, atomic, and certificate tests**

Run: `D:\python\python.exe -m pytest -q -o addopts='' backend/tests/core/test_atomic_execution_commit.py backend/tests/core/test_execute_approval_boundary.py backend/tests/contracts/test_approval_and_validation_certificates.py`

### Task 6: Remove remaining legacy selection authority

**Files:**
- Delete or reduce: `backend/app/domain/allocation/select_service.py`
- Modify: `backend/app/domain/allocation/scenario_worker_projection.py`
- Modify: consumers of `SiteSelectionDecision` that still infer planning decisions
- Modify: `backend/app/workflow/stages/select.py`
- Test: `backend/tests/contracts/test_single_scenario_authority.py`
- Update characterization tests that intentionally exercise the retired path.

**Interfaces:**
- Consumes: selected `PlanningScenario` plus `ApprovedExecutionInput`.
- Produces: a worker-only execution projection with no independent selection authority.

- [ ] **Step 1: Add an import/call-boundary test forbidding production `select_aggregate`**

- [ ] **Step 2: Move worker-only shapes out of decision-named contracts**

- [ ] **Step 3: Delete unused legacy selection, revision, and compatibility helpers**

- [ ] **Step 4: Run contract, SELECT, and execution projection tests**

Run: `D:\python\python.exe -m pytest -q -o addopts='' backend/tests/contracts backend/tests/core/test_scenario_projection.py backend/tests/core/test_select_gate_deferred_targets.py`

### Task 7: Make delivery and frontend state reflect the canonical result

**Files:**
- Modify: `backend/app/application/projections/session.py`
- Modify: `backend/app/application/queries/map_layers.py`
- Modify: `frontend/src/features/planning/hooks/useSessionRestore.ts`
- Modify: `frontend/src/features/planning/store/planningStore.ts`
- Modify: planning map/report components under `frontend/src/features/planning/components/`
- Test: backend projection tests, Jest store/hydration tests, Playwright planning-flow test.

**Interfaces:**
- Consumes: terminal workflow state, `DeliveryManifest`, and map-layer delivery projection.
- Produces: unambiguous running/paused/failed/completed UI state and planned layers visually distinct from source layers.

- [ ] **Step 1: Add stale-running projection regression tests**

- [ ] **Step 2: Stop polling nonexistent terminal artifacts and distinguish pending from failed**

- [ ] **Step 3: Label source/current layers separately from planned/delivery layers**

- [ ] **Step 4: Assert non-empty planned layer counts match `/map-layers`**

- [ ] **Step 5: Run frontend typecheck and Jest**

Run: `npm run typecheck` and `npm test -- --runInBand` from `frontend`.

### Task 8: Prove a new real same-run planning-layer delivery

**Files:**
- Create/update: a real-run acceptance script under `backend/scripts/`
- Create/update: a Playwright spec under `frontend/e2e/`
- Produce: runtime artifacts and screenshots under the project test-output directory.
- Update: current design/runtime status only after evidence exists.

**Interfaces:**
- Consumes: original JinTian input documents, RAG-disabled session config, live backend/frontend.
- Produces: one session ID with complete same-run lineage and visible planned layers.

- [ ] **Step 1: Create a brand-new session with the original current-status report and RAG disabled**

- [ ] **Step 2: Verify every canonical artifact exists and references the same run/snapshot**

- [ ] **Step 3: Verify selected-to-materialized coverage, certificate, reconciliation, and delivery gates**

- [ ] **Step 4: Verify `/map-layers` has non-empty planned feature collections**

- [ ] **Step 5: Use Playwright to open the real session, inspect layer counts, and capture the map plus report UI**

- [ ] **Step 6: Run the full focused backend/frontend acceptance suite**

- [ ] **Step 7: Only after all checks pass, update `CURRENT_RUNTIME.md`, migration status, and prepare the requested weekly report from the real screenshots and recent changes**

## Self-Review

- Spec coverage: input truth, L1 breakpoint, target explosion, grounding completeness, solver semantics, approval/atomic execution, compatibility removal, delivery projection, frontend/Playwright, screenshots, and deferred weekly report all have explicit tasks.
- Placeholder scan: no `TBD`, `TODO`, generic error-handling instruction, or unnamed test step remains.
- Type consistency: `PlanningClaim.planning_role`, `GroundedPlanningProblem.candidate_completeness`, `ObjectiveDefinition.direction`, `ApprovedExecutionInput`, `ExecutionResult`, and `ValidationCertificate` are used consistently across producer and consumer tasks.
