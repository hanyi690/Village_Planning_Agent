# Current Runtime

> Status: CURRENT
> Authority: Evidence-backed map of behavior present in this worktree. Target architecture belongs in `../design/00_SYSTEM_DESIGN.md` through `05_MIGRATION.md`.

## 1. Runtime composition observed in code

FastAPI is created in [`backend/app/main.py`](../../backend/app/main.py), with lifespan wiring in [`backend/app/bootstrap/lifespan.py`](../../backend/app/bootstrap/lifespan.py) and dependency composition in [`backend/app/bootstrap/composition.py`](../../backend/app/bootstrap/composition.py). The API runtime entry is [`PlanningRuntimeService`](../../backend/app/infrastructure/runtime/planning_runtime_service.py).

The root workflow is built in [`backend/app/workflow/root_graph.py`](../../backend/app/workflow/root_graph.py) and segmented in [`backend/app/workflow/segments.py`](../../backend/app/workflow/segments.py) into:

- `intent_loop`
- `cognitive`
- `spatial_chain`
- `hitl`

The current spatial sequence compiled into the graph is:

```text
TARGET_PROJECTION → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER
```

Repair routing is also present in code: SELECT can return to GROUND, and VALIDATE can route back toward EXECUTE, SELECT, GROUND, TARGET_PROJECTION, or L3 depending on the failure artifact carried by the state.

## 2. Current L1, retrieval, and context boundaries

Observed implementation anchors:

- [`backend/app/domain/assessment/source_index.py`](../../backend/app/domain/assessment/source_index.py) builds the L1 source index from session-owned `village_data` and explicit uploads.
- [`backend/app/domain/assessment/l1_extraction_loop.py`](../../backend/app/domain/assessment/l1_extraction_loop.py) runs bounded observe/validate/report passes per L1 dimension.
- [`backend/app/infrastructure/context/project_cognition.py`](../../backend/app/infrastructure/context/project_cognition.py) builds `ProjectCognitionSnapshot` and prompt-safe evidence projections.
- [`backend/app/evidence/retrieval/evidence_service.py`](../../backend/app/evidence/retrieval/evidence_service.py) and [`backend/app/evidence/retrieval/router.py`](../../backend/app/evidence/retrieval/router.py) route retrieval across `LOCAL_TEXT`, `REPORT`, `RAG`, `KG`, `BUNDLE`, `ARTIFACT`, `HISTORY`, `INTEGRITY`, and `EXTERNAL`.
- [`backend/app/workflow/conversation/edges.py`](../../backend/app/workflow/conversation/edges.py) still contains gate-scoped evidence retrieval wiring, including `retrieve_evidence_for_gate`.

What this proves today:

- the code has real cognition-digest and bounded-evidence projection hooks;
- the code has multiple typed requirement producers and a shared retrieval service;
- dense RAG is optional rather than required for all evidence calls.

What it does not prove:

- every production evidence call in every stage is already routed through one unified admission path;
- every prompt in every stage already carries the same named projection contract;
- every retriever and call site has fresh runtime verification in the current worktree.

Those limits remain `PARTIAL` and are tracked only in [`../design/05_MIGRATION.md`](../design/05_MIGRATION.md).

### 2.1 Current L1/L2/L3 model-call shape

The current worktree separates semantic and report calls, but the semantic transaction size differs substantially by layer:

| Layer | Current semantic call | Current post-call behavior |
|---|---|---|
| L1 | `l1.observe` processes a bounded source page and returns an observation array through `L1ObservationProviderOutput`. | Local code validates source quotes, compiles typed observations/facts, then makes a separate structured `l1.report` call. Observe pages and report share the dimension call cursor/budget. |
| L2 | One `l2.decision` call returns a complete strict `L2DecisionSet` containing objectives, metrics, strategies, priorities, spatial structures, conflicts, evidence gaps and their cross-references. | Closed-set errors can trigger one complete decision-set reask, followed by a separate structured `l2.report` call. Same-layer decision context accumulates along the four L2 wave dimensions. |
| L3 | One `l3.claims` call returns a small provider envelope of rough, non-executable intent claims: family, statement, role, closed refs, location hints, grounding requirements and uncertainty. | Local code closes refs against the YAML vocabulary and L1 fact catalog, converts claims deterministically, records an empty/pending evidence state when needed, and optionally calls `l3.intent_summary` from a separate rough-claim table. Detailed planning remains downstream of `ScenarioSet`. |

The dependency renderer removes raw/report/audit keys and has consumer-specific decision/claim table projections with cross-dependency merge. L3 receives one canonical typed L1 fact table plus a bounded evidence projection; packet candidate/relation rows stay in the retrieval/grounding plane. `context_manager.py` centralizes Markdown table rendering, while projection identity/digest auditing remains a follow-up gap.

`LLMManager` admits calls using the initial message character count and records safe call metadata. Explicit schema retry counts now pass through unchanged; worker-level semantic reasks and workflow-level dimension retries remain separate additional retry layers and still need item-level amplification accounting.

### 2.2 Latest L2/L3 live-call evidence

The last complete pre-convergence run, session `24492153-07c9-464a-83a6-b79e1db0df88` in `output/runtime-logs/planning.log`, is retained as a historical baseline:

- L2 prompt lengths were 8638, 16686, 25245 and 35579 characters. The `same_layer_decision_context` component grew from 0 to 28455 characters; five `l2.decision` calls completed for four dimensions because one dimension performed a complete reask.
- The pre-convergence L3 wave produced prompt lengths from 73559 to 91885 characters. Across the initial and workflow-retry waves, 20 `l3.claims` calls were admitted and recorded as completed by the structured runner.
- After those completed provider calls, the L3 worker recorded 16 `SCHEMA_INVALID (ValidationError)` failures at its structured/domain quality boundary. Four dimensions reached the old `l3.report` path; the graph terminated with seven L3 dimensions exhausted after retry. This is a baseline for the migration, not evidence of the current narrow contract's live acceptance rate.

This evidence distinguishes provider transport completion from downstream domain normalization success. It does not identify every invalid item field because the safe production call record deliberately omits response bodies and currently has no item-level error-path histogram.

## 3. Current planning and execution artifacts observed in code

Current typed artifacts are present and wired into workflow state by ref:

- `PlanningProgram` / L3 contracts in [`backend/app/contracts/domain/l3_contracts.py`](../../backend/app/contracts/domain/l3_contracts.py)
- `IntentCompilationResult` in TARGET_PROJECTION under [`backend/app/workflow/stages/target_projection.py`](../../backend/app/workflow/stages/target_projection.py)
- [`GroundedPlanningProblem`](../../backend/app/contracts/spatial/grounded_problem.py)
- [`ScenarioSet`](../../backend/app/contracts/planning/scenario.py)
- [`ApprovedExecutionInput`](../../backend/app/contracts/planning/approval.py)
- `ExecutionPlan` and execution result contracts in [`backend/app/contracts/workflow/execution_plan_contracts.py`](../../backend/app/contracts/workflow/execution_plan_contracts.py)
- [`ValidationCertificate`](../../backend/app/contracts/artifacts/validation_certificate_contracts.py)

Observed stage boundaries:

- GROUND persists typed grounding/problem artifacts and carries unresolved/deferred findings forward.
- SELECT persists a `ScenarioSet`, can persist an approval-bound `ExecutionPlan`, and derives [`ApprovedExecutionInput`](../../backend/app/contracts/planning/approval.py) for executable paths.
- EXECUTE refuses to proceed when approval, scenario lineage, or plan digest does not match.
- VALIDATE and RECONCILE read typed artifacts back by ref instead of recomputing authority from free-form state.
- DELIVER publishes `delivery_status` and `statutory_complete` from the final manifest path.

The current code is stricter than the older compatibility paths, but the end-to-end surface is still only partially verified for all target types and solver backends.

## 4. State and delivery behavior observed in code

[`backend/app/workflow/state.py`](../../backend/app/workflow/state.py) keeps `WorkflowState` as a control-plane object with stage, routing, diagnostics, lightweight runtime fields, and artifact refs. Typed runtime products such as `scoped_grounding_problem`, `ScenarioSet`, [`ApprovedExecutionInput`](../../backend/app/contracts/planning/approval.py), and [`ValidationCertificate`](../../backend/app/contracts/artifacts/validation_certificate_contracts.py) are persisted separately and referenced from state.

Current delivery-facing status fields are visible in:

- [`backend/app/api/v1/contracts.py`](../../backend/app/api/v1/contracts.py)
- [`backend/app/workflow/terminal.py`](../../backend/app/workflow/terminal.py)
- [`backend/app/workflow/runtime_adapter.py`](../../backend/app/workflow/runtime_adapter.py)
- [`backend/app/domain/delivery/aggregate.py`](../../backend/app/domain/delivery/aggregate.py)

The runtime currently distinguishes `complete`, `partial`, and `diagnostic_only` delivery outcomes. `statutory_complete` is carried explicitly and is not inferred from stage completion alone.

## 5. Real-run evidence kept as evidence, not as target claims

The repository contains repeatable audit notes for several real sessions. Two current evidence points still matter:

| Date | Session | Observed result | What it proves | What it does not prove |
|---|---|---|---|---|
| 2026-08-23 | `2e4095c8-1691-4b5b-8c7d-b9f820c75eaf` | same-session run reached DELIVER with `delivery_status=partial` and `statutory_complete=false` | approval, execution, validation, reconcile, and deliver can close a real run without pretending statutory completion | not all planned land-use, road, coverage, or topology paths are complete |
| 2026-08-24 | `efb707cd-a052-411b-8860-9fdd27051621` | same-session run reached `completed / active_stage=deliver / progress=100 / delivery_status=complete` with one formal planned change and visible front-end planning layers | current UI, delivery projection, and typed artifact hydration can present a completed example run | not every target type, retrieval path, or later tightened admission path has fresh live verification |

These sessions remain evidence snapshots, not general completion claims. They are kept because they show both a truthful `partial` path and a completed example path.

## 6. Explicit current partial boundaries

The current worktree still has evidence-backed limits:

- dense recall depends on configured embedding infrastructure and can be unavailable without disabling the whole workflow;
- cognition and prompt-boundary hooks exist, but not every retrieval or LLM call path has fresh proof of uniform enforcement;
- current grounding and solver paths are stronger for parcel-style bounded scenarios than for all road, coverage, topology, and mixed-worker cases;
- approval-bound execution is enforced in code, but full execution-surface verification remains narrower than the target design;
- delivery can truthfully emit `partial`, so successful stage progression must not be read as whole-village completion.

The status words for those limits belong in [`../design/05_MIGRATION.md`](../design/05_MIGRATION.md), not here.

## 7. Historical residue still worth naming

Some older names remain useful only as audit residue:

- the old `solve_scenario(max_scenarios=1)` path is gone from the production call graph, but `max_scenarios=1` remains a useful historical marker when reading older reports and tests;
- legacy anchor-style names still appear in some compatibility or internal code paths, but they are not the active documentation authority;
- the `staging ChangeSet` boundary still matters because EXECUTE now treats duplicates, omissions, and unexpected outputs as commit blockers instead of converting them into a partial formal result.

For target rules and normative boundaries, use the canonical design set in `docs/design/`. This file stays intentionally limited to code evidence and real-run evidence.
